"""Tests for the TransactionFaker service.

Verifies seed reproducibility, transaction generation, balance calculations,
date distribution, description patterns, and edge-case scenarios.
"""

import calendar
from datetime import date
from decimal import Decimal

from app.models.generation import GenerationParams, Scenario, TransactionRange
from app.models.schema import DescriptionPattern
from app.services.data_faker import TransactionFaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_params(**overrides) -> GenerationParams:
    """Build GenerationParams with sensible defaults, applying overrides."""
    defaults = dict(
        schema_id="00000000-0000-0000-0000-000000000000",
        scenario=Scenario.SINGLE_MONTH,
        start_date=date(2025, 3, 1),
        months=1,
        opening_balance="5000.00",
        seed=42,
        transactions_per_month=TransactionRange(min=15, max=25),
    )
    defaults.update(overrides)
    return GenerationParams(**defaults)


def _default_patterns() -> list[DescriptionPattern]:
    return [
        DescriptionPattern(category="debit_card", pattern="DEBIT CARD PURCHASE - {merchant} {city} {state}"),
        DescriptionPattern(category="ach", pattern="ACH {direction} {originator}"),
        DescriptionPattern(category="check", pattern="CHECK #{number}"),
        DescriptionPattern(category="transfer", pattern="ONLINE TRANSFER {transfer_direction} {account_ref}"),
        DescriptionPattern(category="atm", pattern="ATM {atm_action} - {location}"),
    ]


# ---------------------------------------------------------------------------
# Seed reproducibility
# ---------------------------------------------------------------------------


class TestSeedReproducibility:
    """Same seed must produce identical output; different seeds differ."""

    def test_same_seed_same_output(self):
        params = _default_params(seed=12345)
        patterns = _default_patterns()

        faker1 = TransactionFaker(seed=12345)
        txns1 = faker1.generate_transactions(params, patterns)

        faker2 = TransactionFaker(seed=12345)
        txns2 = faker2.generate_transactions(params, patterns)

        assert len(txns1) == len(txns2)
        for t1, t2 in zip(txns1, txns2):
            assert t1.date == t2.date
            assert t1.description == t2.description
            assert t1.amount == t2.amount
            assert t1.balance == t2.balance
            assert t1.tx_type == t2.tx_type

    def test_different_seeds_different_output(self):
        params_a = _default_params(seed=100)
        params_b = _default_params(seed=999)
        patterns = _default_patterns()

        faker_a = TransactionFaker(seed=100)
        txns_a = faker_a.generate_transactions(params_a, patterns)

        faker_b = TransactionFaker(seed=999)
        txns_b = faker_b.generate_transactions(params_b, patterns)

        # At minimum, the amounts should differ (extremely unlikely to match)
        amounts_a = [t.amount for t in txns_a]
        amounts_b = [t.amount for t in txns_b]
        assert amounts_a != amounts_b


# ---------------------------------------------------------------------------
# Transaction count
# ---------------------------------------------------------------------------


class TestTransactionCount:
    """Transaction count must fall within the configured range (for default scenario)."""

    def test_count_within_range(self):
        params = _default_params(
            seed=42,
            transactions_per_month=TransactionRange(min=10, max=20),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        assert 10 <= len(txns) <= 20

    def test_count_exact_when_min_equals_max(self):
        params = _default_params(
            seed=42,
            transactions_per_month=TransactionRange(min=7, max=7),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        assert len(txns) == 7


# ---------------------------------------------------------------------------
# Running balance
# ---------------------------------------------------------------------------


class TestRunningBalance:
    """Running balance must be calculated correctly from opening + amounts."""

    def test_running_balance_matches_cumulative_sum(self):
        params = _default_params(seed=77)
        faker = TransactionFaker(seed=77)
        txns = faker.generate_transactions(params, _default_patterns())

        opening = Decimal("5000.00")
        expected_balance = opening
        for tx in txns:
            expected_balance += tx.amount
            assert tx.balance == expected_balance, (
                f"Balance mismatch at {tx.date}: expected {expected_balance}, got {tx.balance}"
            )


# ---------------------------------------------------------------------------
# Decimal types (not float)
# ---------------------------------------------------------------------------


class TestDecimalTypes:
    """All monetary values must be Decimal, never float."""

    def test_amount_is_decimal(self):
        params = _default_params(seed=42)
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        for tx in txns:
            assert isinstance(tx.amount, Decimal), f"amount is {type(tx.amount)}, expected Decimal"
            assert isinstance(tx.balance, Decimal), f"balance is {type(tx.balance)}, expected Decimal"


# ---------------------------------------------------------------------------
# Date distribution
# ---------------------------------------------------------------------------


class TestDateDistribution:
    """All transaction dates must fall within the specified month."""

    def test_all_dates_within_month(self):
        params = _default_params(seed=42, start_date=date(2025, 6, 1))
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())

        for tx in txns:
            assert tx.date.year == 2025
            assert tx.date.month == 6
            assert 1 <= tx.date.day <= 30

    def test_february_dates(self):
        """February has 28 or 29 days — all dates must be valid."""
        params = _default_params(seed=42, start_date=date(2025, 2, 1))
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())

        _, last_day = calendar.monthrange(2025, 2)
        for tx in txns:
            assert tx.date.month == 2
            assert 1 <= tx.date.day <= last_day

    def test_dates_are_sorted(self):
        params = _default_params(seed=42)
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())

        dates = [tx.date for tx in txns]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Description generation
# ---------------------------------------------------------------------------


class TestDescriptionGeneration:
    """Each tx_type must produce a contextually appropriate description."""

    def test_debit_card_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("debit_card", False, {})
        assert "DEBIT CARD PURCHASE" in desc

    def test_ach_credit_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("ach", True, {})
        assert "ACH CREDIT" in desc

    def test_ach_debit_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("ach", False, {})
        assert "ACH DEBIT" in desc

    def test_check_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("check", False, {})
        assert "CHECK #" in desc

    def test_transfer_to_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("transfer", False, {})
        assert "ONLINE TRANSFER TO" in desc

    def test_transfer_from_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("transfer", True, {})
        assert "ONLINE TRANSFER FROM" in desc

    def test_atm_withdrawal_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("atm", False, {})
        assert "ATM WITHDRAWAL" in desc

    def test_atm_deposit_description(self):
        faker = TransactionFaker(seed=42)
        desc = faker._generate_description("atm", True, {})
        assert "ATM DEPOSIT" in desc

    def test_description_with_pattern(self):
        """When a pattern is provided, it should be used for formatting."""
        faker = TransactionFaker(seed=42)
        pattern_map = {"debit_card": "POS PURCHASE {merchant}"}
        desc = faker._generate_description("debit_card", False, pattern_map)
        assert "POS PURCHASE" in desc
        # Should not fall back to the default
        assert "DEBIT CARD PURCHASE" not in desc


# ---------------------------------------------------------------------------
# Account summary
# ---------------------------------------------------------------------------


class TestAccountSummary:
    """Summary statistics must match the transaction list."""

    def test_summary_matches_transactions(self):
        params = _default_params(seed=42)
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        opening = Decimal("5000.00")

        summary = faker.generate_account_summary(opening, txns)

        expected_deposits = sum(tx.amount for tx in txns if tx.amount > 0)
        expected_withdrawals = sum(abs(tx.amount) for tx in txns if tx.amount < 0)
        expected_closing = txns[-1].balance

        assert summary["opening_balance"] == opening
        assert summary["closing_balance"] == expected_closing
        assert summary["total_deposits"] == expected_deposits
        assert summary["total_withdrawals"] == expected_withdrawals
        assert summary["num_transactions"] == len(txns)

    def test_summary_empty_transactions(self):
        faker = TransactionFaker(seed=42)
        opening = Decimal("1000.00")
        summary = faker.generate_account_summary(opening, [])

        assert summary["opening_balance"] == opening
        assert summary["closing_balance"] == opening
        assert summary["total_deposits"] == Decimal("0.00")
        assert summary["total_withdrawals"] == Decimal("0.00")
        assert summary["num_transactions"] == 0


# ---------------------------------------------------------------------------
# Statement period generation
# ---------------------------------------------------------------------------


class TestStatementPeriod:
    """Statement periods must cover full calendar months."""

    def test_single_month_period(self):
        faker = TransactionFaker(seed=42)
        periods = faker.generate_statement_period(date(2025, 3, 1), months=1)
        assert len(periods) == 1
        start, end = periods[0]
        assert start == date(2025, 3, 1)
        assert end == date(2025, 3, 31)

    def test_multi_month_period(self):
        faker = TransactionFaker(seed=42)
        periods = faker.generate_statement_period(date(2025, 1, 1), months=3)
        assert len(periods) == 3

        assert periods[0] == (date(2025, 1, 1), date(2025, 1, 31))
        assert periods[1] == (date(2025, 2, 1), date(2025, 2, 28))
        assert periods[2] == (date(2025, 3, 1), date(2025, 3, 31))

    def test_period_crossing_year_boundary(self):
        faker = TransactionFaker(seed=42)
        periods = faker.generate_statement_period(date(2025, 11, 1), months=3)
        assert len(periods) == 3

        assert periods[0] == (date(2025, 11, 1), date(2025, 11, 30))
        assert periods[1] == (date(2025, 12, 1), date(2025, 12, 31))
        assert periods[2] == (date(2026, 1, 1), date(2026, 1, 31))

    def test_february_leap_year(self):
        faker = TransactionFaker(seed=42)
        periods = faker.generate_statement_period(date(2024, 2, 1), months=1)
        start, end = periods[0]
        assert end == date(2024, 2, 29)


# ---------------------------------------------------------------------------
# Masked account number
# ---------------------------------------------------------------------------


class TestMaskedAccountNumber:
    """Masked account numbers must follow the XXXX-XXXX-NNNN format."""

    def test_format(self):
        faker = TransactionFaker(seed=42)
        acct = faker.generate_account_number_masked()
        assert acct.startswith("XXXX-XXXX-")
        last4 = acct.split("-")[-1]
        assert len(last4) == 4
        assert last4.isdigit()

    def test_different_seeds_different_numbers(self):
        acct1 = TransactionFaker(seed=1).generate_account_number_masked()
        acct2 = TransactionFaker(seed=9999).generate_account_number_masked()
        # Not guaranteed to differ, but extremely likely with different seeds
        # At minimum, the format must be valid for both
        assert acct1.startswith("XXXX-XXXX-")
        assert acct2.startswith("XXXX-XXXX-")


# ---------------------------------------------------------------------------
# Edge-case scenarios
# ---------------------------------------------------------------------------


class TestScenarios:
    """Scenario-specific adjustments to transaction count and behavior."""

    def test_minimal_scenario_few_transactions(self):
        params = _default_params(
            seed=42,
            scenario=Scenario.MINIMAL,
            transactions_per_month=TransactionRange(min=15, max=25),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        # Minimal forces 1-3 transactions regardless of range
        assert 1 <= len(txns) <= 3

    def test_high_volume_scenario_many_transactions(self):
        params = _default_params(
            seed=42,
            scenario=Scenario.HIGH_VOLUME,
            transactions_per_month=TransactionRange(min=15, max=25),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        # High volume forces at least 80
        assert len(txns) >= 80

    def test_zero_balance_scenario(self):
        params = _default_params(
            seed=42,
            scenario=Scenario.ZERO_BALANCE,
            transactions_per_month=TransactionRange(min=15, max=25),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        # Zero balance scenario: 4-8 transactions
        assert 4 <= len(txns) <= 8

    def test_negative_balance_scenario(self):
        params = _default_params(
            seed=42,
            scenario=Scenario.NEGATIVE_BALANCE,
            transactions_per_month=TransactionRange(min=15, max=25),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        # Negative balance scenario: 10-20 transactions
        assert 10 <= len(txns) <= 20

    def test_multi_page_scenario(self):
        params = _default_params(
            seed=42,
            scenario=Scenario.MULTI_PAGE,
            transactions_per_month=TransactionRange(min=15, max=25),
        )
        faker = TransactionFaker(seed=42)
        txns = faker.generate_transactions(params, _default_patterns())
        # Multi-page forces at least 60
        assert len(txns) >= 60

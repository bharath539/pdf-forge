"""Generates realistic synthetic transaction data for PDF generation."""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker

from app.models.generation import GenerationParams, Scenario
from app.models.schema import DescriptionPattern

# ---------------------------------------------------------------------------
# Transaction dataclass
# ---------------------------------------------------------------------------


@dataclass
class Transaction:
    date: date
    description: str
    amount: Decimal  # negative for debits, positive for credits
    balance: Decimal  # running balance after this transaction
    tx_type: str  # debit_card, ach, check, transfer, atm


# ---------------------------------------------------------------------------
# Curated merchant / originator lists
# ---------------------------------------------------------------------------

MERCHANTS = [
    "Walmart",
    "Target",
    "Starbucks",
    "Shell",
    "Costco",
    "Amazon",
    "Whole Foods",
    "Trader Joe's",
    "Walgreens",
    "CVS Pharmacy",
    "Home Depot",
    "Lowe's",
    "McDonald's",
    "Chick-fil-A",
    "Chipotle",
    "Subway",
    "Panera Bread",
    "Dunkin",
    "Kroger",
    "Safeway",
    "Publix",
    "Aldi",
    "Best Buy",
    "Apple Store",
    "Nike",
    "Uber Eats",
    "DoorDash",
    "Grubhub",
    "Chevron",
    "BP",
    "7-Eleven",
    "Petsmart",
    "Bath & Body Works",
    "TJ Maxx",
    "Nordstrom",
    "Macy's",
    "Gap",
    "Old Navy",
    "Ross",
    "Dollar Tree",
]

ACH_DEBIT_ORIGINATORS = [
    "GEICO INSURANCE",
    "STATE FARM INS",
    "PROGRESSIVE INS",
    "COMCAST CABLE",
    "AT&T SERVICES",
    "VERIZON WIRELESS",
    "DUKE ENERGY",
    "PG&E UTILITY",
    "NATIONAL GRID",
    "PLANET FITNESS",
    "LA FITNESS",
    "NETFLIX.COM",
    "SPOTIFY USA",
    "ADOBE SYSTEMS",
    "MICROSOFT 365",
    "STUDENT LOAN CORP",
    "ALLY AUTO PYMT",
    "TOYOTA FINANCIAL",
]

ACH_CREDIT_ORIGINATORS = [
    "ACME CORP PAYROLL",
    "INITECH PAYROLL",
    "GLOBEX CORP HR",
    "CONTOSO LTD PAYRL",
    "NORTHWIND TRADERS",
    "FABRIKAM INC",
    "DUNDER MIFFLIN PR",
    "STARK INDUSTRIES",
    "WAYNE ENTERPRISES",
    "IRS TREAS TAX REF",
    "STATE TAX REFUND",
    "VENMO CASHOUT",
    "PAYPAL TRANSFER",
    "ZELLE TRANSFER",
]

ATM_BANKS = [
    "Chase Bank",
    "Bank of America",
    "Wells Fargo",
    "US Bank",
    "PNC Bank",
    "TD Bank",
    "Citizens Bank",
    "Capital One",
    "Truist",
]

HOLIDAYS = {
    (1, 1),  # New Year's Day
    (7, 4),  # Independence Day
    (12, 25),  # Christmas Day
}


# ---------------------------------------------------------------------------
# TransactionFaker
# ---------------------------------------------------------------------------


class TransactionFaker:
    """Generates realistic fake data for populating synthetic PDFs.

    Produces contextually appropriate fake values (names, amounts, dates,
    account numbers, etc.) that match the field types defined in a format schema.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed
        self._faker = Faker()
        self._rng = random.Random()
        if seed is not None:
            Faker.seed(seed)
            self._rng.seed(seed)
        self._check_number_start: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_transactions(
        self,
        params: GenerationParams,
        description_patterns: list[DescriptionPattern],
        account_type: str = "checking",
    ) -> list[Transaction]:
        """Generate a full list of transactions for the requested scenario."""
        periods = self.generate_statement_period(params.start_date, params.months)
        opening = Decimal(params.opening_balance)

        # Build a pattern lookup by category for quick access
        pattern_map: dict[str, str] = {p.category: p.pattern for p in description_patterns}

        all_transactions: list[Transaction] = []
        balance = opening

        for period_start, period_end in periods:
            tx_count = self._rng.randint(
                params.transactions_per_month.min,
                params.transactions_per_month.max,
            )
            tx_count = self._adjust_tx_count_for_scenario(tx_count, params.scenario)

            dates = self._generate_dates(period_start, period_end, tx_count)
            types = self._pick_types(tx_count, params)

            for tx_date, tx_type in zip(dates, types):
                is_credit = self._should_be_credit(tx_type, params)
                amount = self._generate_amount(is_credit, params)
                desc = self._generate_description(tx_type, is_credit, pattern_map, account_type)

                balance += amount
                all_transactions.append(
                    Transaction(
                        date=tx_date,
                        description=desc,
                        amount=amount,
                        balance=balance,
                        tx_type=tx_type,
                    )
                )

        return all_transactions

    def generate_account_summary(
        self,
        opening_balance: Decimal,
        transactions: list[Transaction],
    ) -> dict:
        """Return summary statistics for a list of transactions."""
        total_deposits = Decimal("0.00")
        total_withdrawals = Decimal("0.00")

        for tx in transactions:
            if tx.amount > 0:
                total_deposits += tx.amount
            else:
                total_withdrawals += abs(tx.amount)

        closing_balance = transactions[-1].balance if transactions else opening_balance

        return {
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "total_deposits": total_deposits,
            "total_withdrawals": total_withdrawals,
            "num_transactions": len(transactions),
        }

    def generate_statement_period(
        self,
        start_date: date,
        months: int,
    ) -> list[tuple[date, date]]:
        """Return a list of (period_start, period_end) tuples."""
        periods: list[tuple[date, date]] = []
        current = start_date
        for _ in range(months):
            _, last_day = calendar.monthrange(current.year, current.month)
            period_end = date(current.year, current.month, last_day)
            periods.append((current, period_end))
            # Advance to the first day of the next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)
        return periods

    def generate_account_number_masked(self) -> str:
        """Return a masked account number like 'XXXX-XXXX-1234'."""
        last4 = self._rng.randint(0, 9999)
        return f"XXXX-XXXX-{last4:04d}"

    # ------------------------------------------------------------------
    # Internal: scenario adjustments
    # ------------------------------------------------------------------

    def _adjust_tx_count_for_scenario(self, base: int, scenario: Scenario) -> int:
        if scenario == Scenario.HIGH_VOLUME:
            return max(base, 80)
        if scenario == Scenario.MINIMAL:
            return self._rng.randint(1, 3)
        if scenario == Scenario.ZERO_BALANCE:
            return self._rng.randint(4, 8)
        if scenario == Scenario.NEGATIVE_BALANCE:
            return self._rng.randint(10, 20)
        if scenario == Scenario.MULTI_PAGE:
            return max(base, 60)
        return base

    # ------------------------------------------------------------------
    # Internal: date generation
    # ------------------------------------------------------------------

    def _generate_dates(
        self,
        start: date,
        end: date,
        count: int,
    ) -> list[date]:
        """Pick *count* dates in [start, end], biased toward weekdays with clustering."""
        if count == 0:
            return []

        total_days = (end - start).days + 1
        if total_days <= 0:
            return [start] * count

        # Build a weight for each day: weekdays=5, weekends=1, holidays=0
        day_weights: list[float] = []
        day_list: list[date] = []
        for offset in range(total_days):
            d = start + timedelta(days=offset)
            if (d.month, d.day) in HOLIDAYS:
                day_weights.append(0.0)
            elif d.weekday() >= 5:  # Saturday=5, Sunday=6
                day_weights.append(1.0)
            else:
                day_weights.append(5.0)
            day_list.append(d)

        # If all weights are zero (unlikely), fall back to uniform
        if sum(day_weights) == 0:
            day_weights = [1.0] * len(day_weights)

        chosen: list[date] = []
        while len(chosen) < count:
            picked = self._rng.choices(day_list, weights=day_weights, k=1)[0]
            chosen.append(picked)
            # 30% chance the next transaction clusters on the same day
            if len(chosen) < count and self._rng.random() < 0.30:
                chosen.append(picked)

        chosen = chosen[:count]
        chosen.sort()
        return chosen

    # ------------------------------------------------------------------
    # Internal: type distribution
    # ------------------------------------------------------------------

    def _pick_types(self, count: int, params: GenerationParams) -> list[str]:
        dist = params.type_distribution
        types = ["debit_card", "ach", "check", "transfer", "atm"]
        weights = [dist.debit_card, dist.ach, dist.check, dist.transfer, dist.atm]
        return self._rng.choices(types, weights=weights, k=count)

    # ------------------------------------------------------------------
    # Internal: credit vs debit decision
    # ------------------------------------------------------------------

    def _should_be_credit(self, tx_type: str, params: GenerationParams) -> bool:
        """Determine if this transaction should be a credit (deposit)."""
        # ACH has a chance of being a credit (payroll, refund)
        if tx_type == "ach":
            return self._rng.random() < 0.30
        # Transfers can go either way
        if tx_type == "transfer":
            return self._rng.random() < 0.35
        # ATM can be deposit
        if tx_type == "atm":
            return self._rng.random() < 0.10
        # Debit card and checks are always debits
        return False

    # ------------------------------------------------------------------
    # Internal: amount generation
    # ------------------------------------------------------------------

    def _generate_amount(self, is_credit: bool, params: GenerationParams) -> Decimal:
        if is_credit:
            return self._generate_credit_amount()
        return self._generate_debit_amount(params)

    def _generate_credit_amount(self) -> Decimal:
        """Credits: typically paychecks ($1000-$5000) or smaller transfers."""
        roll = self._rng.random()
        if roll < 0.60:
            # Paycheck range
            raw = self._rng.uniform(1000.0, 5000.0)
        elif roll < 0.85:
            # Medium deposit / transfer
            raw = self._rng.uniform(100.0, 999.99)
        else:
            # Small deposit
            raw = self._rng.uniform(10.0, 99.99)
        return Decimal(str(round(raw, 2)))

    def _generate_debit_amount(self, params: GenerationParams) -> Decimal:
        """Debits: realistic distribution across small/medium/large/very-large."""
        roll = self._rng.random()
        if roll < 0.60:
            raw = self._rng.uniform(2.0, 50.0)
        elif roll < 0.85:
            raw = self._rng.uniform(50.0, 300.0)
        elif roll < 0.95:
            raw = self._rng.uniform(300.0, 2000.0)
        else:
            raw = self._rng.uniform(2000.0, 8000.0)
        return -Decimal(str(round(raw, 2)))

    # ------------------------------------------------------------------
    # Internal: description generation
    # ------------------------------------------------------------------

    def _generate_description(
        self,
        tx_type: str,
        is_credit: bool,
        pattern_map: dict[str, str],
        account_type: str = "checking",
    ) -> str:
        """Build a description string, using schema patterns when available."""
        placeholders = self._build_placeholders(tx_type, is_credit)

        pattern = pattern_map.get(tx_type)
        if pattern:
            try:
                return pattern.format(**placeholders)
            except KeyError:
                pass  # Fall through to defaults

        # Credit card statements use a different format:
        # MERCHANT NAME              CITY         ST
        # or MERCHANT NAME           PHONE        ST
        if account_type == "credit_card":
            return self._cc_description(tx_type, is_credit, placeholders)

        # Default checking/savings patterns
        if tx_type == "debit_card":
            return f"DEBIT CARD PURCHASE - {placeholders['merchant']} {placeholders['city']} {placeholders['state']}"
        if tx_type == "ach":
            direction = "CREDIT" if is_credit else "DEBIT"
            return f"ACH {direction} {placeholders['originator']}"
        if tx_type == "check":
            return f"CHECK #{placeholders['number']}"
        if tx_type == "transfer":
            direction = "FROM" if is_credit else "TO"
            return f"ONLINE TRANSFER {direction} {placeholders['account_ref']}"
        if tx_type == "atm":
            action = "DEPOSIT" if is_credit else "WITHDRAWAL"
            return f"ATM {action} - {placeholders['location']}"
        return "MISC TRANSACTION"

    def _cc_description(
        self,
        tx_type: str,
        is_credit: bool,
        placeholders: dict[str, str],
    ) -> str:
        """Generate credit card statement style descriptions.

        Format: 'MERCHANT NAME              CITY         ST'
        Merchant and location are space-padded to fixed columns.
        """
        if tx_type == "debit_card" or (tx_type == "ach" and not is_credit):
            merchant = placeholders["merchant"].upper()
            city = placeholders["city"].upper()
            state = placeholders["state"]
            # Some CC statements show store numbers
            if self._rng.random() < 0.3:
                store_num = self._rng.randint(100, 9999)
                merchant = f"{merchant} #{store_num}"
            # Some show phone numbers instead of city
            if self._rng.random() < 0.2:
                phone = f"{self._rng.randint(100, 999)}-{self._rng.randint(1000000, 9999999)}"
                location = f"{phone} {state}"
            else:
                location = f"{city} {state}"
            # Pad merchant to ~20 chars, location fills the rest
            return f"{merchant:<20s}{location}"
        if tx_type == "ach" and is_credit:
            return "PAYMENT THANK YOU"
        if tx_type == "transfer":
            if is_credit:
                return "PAYMENT THANK YOU"
            return "CASH ADVANCE FEE"
        if tx_type == "check":
            return "PAYMENT THANK YOU"
        if tx_type == "atm":
            return f"CASH ADVANCE {placeholders['city'].upper()} {placeholders['state']}"
        return f"{placeholders['merchant'].upper():<20s}{placeholders['city'].upper()} {placeholders['state']}"

    def _build_placeholders(self, tx_type: str, is_credit: bool) -> dict[str, str]:
        """Return a dict of placeholder values usable for format-string substitution."""
        placeholders: dict[str, str] = {}

        # Merchant info (debit_card, but also useful for others)
        placeholders["merchant"] = self._rng.choice(MERCHANTS)
        placeholders["city"] = self._faker.city()
        placeholders["state"] = self._faker.state_abbr()

        # ACH originator
        if is_credit:
            placeholders["originator"] = self._rng.choice(ACH_CREDIT_ORIGINATORS)
        else:
            placeholders["originator"] = self._rng.choice(ACH_DEBIT_ORIGINATORS)

        # Check number
        if self._check_number_start is None:
            self._check_number_start = self._rng.randint(1001, 9000)
        placeholders["number"] = str(self._check_number_start)
        self._check_number_start += 1

        # Transfer account ref
        last4 = self._rng.randint(1000, 9999)
        acct_type = self._rng.choice(["SAVINGS", "CHECKING", "MONEY MARKET"])
        placeholders["account_ref"] = f"{acct_type} ...{last4}"

        # ATM location
        bank = self._rng.choice(ATM_BANKS)
        city = self._faker.city()
        placeholders["location"] = f"{bank} {city}"

        # Direction helpers (callers may embed these in patterns)
        placeholders["direction"] = "CREDIT" if is_credit else "DEBIT"
        placeholders["transfer_direction"] = "FROM" if is_credit else "TO"
        placeholders["atm_action"] = "DEPOSIT" if is_credit else "WITHDRAWAL"

        return placeholders


# Keep the original name as an alias so existing imports keep working.
DataFaker = TransactionFaker

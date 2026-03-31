import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schema import (
    AccountType,
    DescriptionPattern,
    FontRole,
    FontSpec,
    FormatSchema,
    Margins,
    PageBreakRules,
    PageLayout,
    Section,
    SectionElement,
    SectionType,
    SummaryField,
    TableColumn,
    ElementType,
)


@pytest.fixture
def client():
    """Synchronous test client for simple endpoint tests."""
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async test client using httpx for async endpoint tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Minimal valid FormatSchema — usable by generator and sanitizer tests
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_schema() -> FormatSchema:
    """A minimal but complete FormatSchema for testing the generator."""
    return FormatSchema(
        schema_version="1.0",
        bank_name="Test Bank",
        account_type=AccountType.CHECKING,
        display_name="Test Bank Checking",
        page=PageLayout(
            width=612.0,
            height=792.0,
            margins=Margins(top=72, right=54, bottom=72, left=54),
        ),
        fonts=[
            FontSpec(role=FontRole.HEADER, family="Helvetica", size=16, weight="bold", color="#000000"),
            FontSpec(role=FontRole.SUBHEADER, family="Helvetica", size=10, weight="normal", color="#333333"),
            FontSpec(role=FontRole.BODY, family="Helvetica", size=9, weight="normal", color="#000000"),
            FontSpec(role=FontRole.FOOTER, family="Helvetica", size=8, weight="normal", color="#888888"),
            FontSpec(role=FontRole.TABLE_HEADER, family="Helvetica", size=9, weight="bold", color="#000000"),
            FontSpec(role=FontRole.TABLE_BODY, family="Helvetica", size=8, weight="normal", color="#000000"),
        ],
        sections=[
            Section(type=SectionType.HEADER, y_start=0),
            Section(
                type=SectionType.ACCOUNT_SUMMARY,
                y_start=100,
                fields=[
                    SummaryField(role="account_number_masked", label="Account Number:", format="text"),
                    SummaryField(role="opening_balance", label="Opening Balance:", format="$#,##0.00"),
                    SummaryField(role="closing_balance", label="Closing Balance:", format="$#,##0.00"),
                ],
            ),
            Section(
                type=SectionType.TRANSACTION_TABLE,
                y_start=220,
                row_height=14.0,
                header_underline=True,
                columns=[
                    TableColumn(header="Date", x_start=54, x_end=124, format="date", alignment="left"),
                    TableColumn(header="Description", x_start=134, x_end=394, format="text", alignment="left", max_chars=50),
                    TableColumn(header="Amount", x_start=404, x_end=484, format="amount", alignment="right"),
                    TableColumn(header="Balance", x_start=494, x_end=558, format="amount", alignment="right"),
                ],
            ),
            Section(
                type=SectionType.FOOTER,
                y_start=-60,
                elements=[
                    SectionElement(type=ElementType.TEXT_FIELD, role="page_number", format="Page {n} of {total}"),
                ],
            ),
        ],
        page_break_rules=PageBreakRules(min_rows_before_break=3, continuation_header=True),
        description_patterns=[
            DescriptionPattern(category="debit_card", pattern="DEBIT CARD PURCHASE - {merchant} {city} {state}"),
            DescriptionPattern(category="ach", pattern="ACH {direction} {originator}"),
            DescriptionPattern(category="check", pattern="CHECK #{number}"),
            DescriptionPattern(category="transfer", pattern="ONLINE TRANSFER {transfer_direction} {account_ref}"),
            DescriptionPattern(category="atm", pattern="ATM {atm_action} - {location}"),
        ],
    )


@pytest.fixture
def pii_schema(minimal_schema) -> FormatSchema:
    """A FormatSchema with injected PII values for testing the sanitizer."""
    # Start from a valid schema, then inject PII into string fields
    raw = minimal_schema.model_dump()

    # Inject PII into bank_name and display_name
    raw["bank_name"] = "John Doe's Bank at 123 Main St"
    raw["display_name"] = "Account for john.doe@example.com SSN 123-45-6789"

    # Inject PII into font color (should be hex, but let's put PII in family)
    raw["fonts"][0]["family"] = "Call 555-123-4567 for support"

    # Inject a dollar amount into a section element format
    raw["sections"][3]["elements"][0]["format"] = "Balance: $1,234.56"

    return FormatSchema.model_validate(raw)

"""Tests for the SyntheticGenerator service.

Verifies PDF generation, multi-page output, batch zip creation,
and that outputs are in-memory BytesIO objects (not written to disk).
"""

import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.models.generation import GenerationParams, Scenario, TransactionRange
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
    SectionType,
    TableColumn,
)
from app.services.synthetic_generator import SyntheticGenerator, format_date, format_amount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_params(**overrides) -> GenerationParams:
    defaults = dict(
        schema_id="00000000-0000-0000-0000-000000000000",
        scenario=Scenario.SINGLE_MONTH,
        start_date=date(2025, 3, 1),
        months=1,
        opening_balance="5000.00",
        seed=42,
        transactions_per_month=TransactionRange(min=10, max=15),
    )
    defaults.update(overrides)
    return GenerationParams(**defaults)


# ---------------------------------------------------------------------------
# format_date helper
# ---------------------------------------------------------------------------


class TestFormatDate:
    def test_mm_dd_yyyy(self):
        assert format_date(date(2025, 3, 15), "MM/DD/YYYY") == "03/15/2025"

    def test_yyyy_mm_dd(self):
        assert format_date(date(2025, 1, 7), "YYYY-MM-DD") == "2025-01-07"

    def test_mon_dd_yyyy(self):
        result = format_date(date(2025, 12, 25), "Mon DD, YYYY")
        assert result == "Dec 25, 2025"

    def test_strftime_fallback(self):
        result = format_date(date(2025, 3, 1), "%Y/%m/%d")
        assert result == "2025/03/01"

    def test_empty_format(self):
        result = format_date(date(2025, 3, 15), "")
        assert result == "03/15/2025"


# ---------------------------------------------------------------------------
# format_amount helper
# ---------------------------------------------------------------------------


class TestFormatAmount:
    def test_positive_dollar(self):
        assert format_amount(Decimal("1234.56"), "$#,##0.00") == "$1,234.56"

    def test_negative_dollar(self):
        assert format_amount(Decimal("-500.00"), "$#,##0.00") == "-$500.00"

    def test_accounting_style_negative(self):
        result = format_amount(Decimal("-1234.56"), "(#,##0.00)")
        assert result == "(1,234.56)"

    def test_accounting_style_positive(self):
        result = format_amount(Decimal("1234.56"), "(#,##0.00)")
        assert result == "1,234.56"

    def test_no_symbol(self):
        result = format_amount(Decimal("99.99"), "#,##0.00")
        assert result == "99.99"

    def test_zero(self):
        result = format_amount(Decimal("0.00"), "$#,##0.00")
        assert result == "$0.00"

    def test_empty_format_defaults_to_dollar(self):
        result = format_amount(Decimal("42.50"), "")
        assert result == "$42.50"


# ---------------------------------------------------------------------------
# generate() — basic output validation
# ---------------------------------------------------------------------------


class TestGenerate:
    """Test the generate() method produces valid PDF output."""

    def test_returns_bytesio(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        result = gen.generate(minimal_schema, _gen_params())
        assert isinstance(result, io.BytesIO)

    def test_pdf_header(self, minimal_schema: FormatSchema):
        """Output must start with the PDF magic bytes %PDF."""
        gen = SyntheticGenerator()
        result = gen.generate(minimal_schema, _gen_params())
        header = result.read(5)
        assert header == b"%PDF-"

    def test_pdf_nonzero_size(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        result = gen.generate(minimal_schema, _gen_params())
        content = result.read()
        assert len(content) > 100, "PDF output is suspiciously small"

    def test_seeked_to_start(self, minimal_schema: FormatSchema):
        """BytesIO must be seeked to position 0 so callers can read immediately."""
        gen = SyntheticGenerator()
        result = gen.generate(minimal_schema, _gen_params())
        assert result.tell() == 0

    def test_not_written_to_disk(self, minimal_schema: FormatSchema, tmp_path):
        """Ensure generate() returns in-memory BytesIO, not a file path."""
        gen = SyntheticGenerator()
        result = gen.generate(minimal_schema, _gen_params())
        assert isinstance(result, io.BytesIO)
        # tmp_path should still be empty — nothing written to disk
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# generate() — minimal schema
# ---------------------------------------------------------------------------


class TestMinimalSchema:
    """A minimal schema with no optional sections must still produce output."""

    def test_minimal_no_sections(self):
        """Schema with empty sections list should use defaults."""
        schema = FormatSchema(
            schema_version="1.0",
            bank_name="Bare Bones Bank",
            account_type=AccountType.CHECKING,
            display_name="Bare Bones Checking",
            page=PageLayout(
                width=612.0, height=792.0,
                margins=Margins(top=72, right=54, bottom=72, left=54),
            ),
            fonts=[],
            sections=[],
            description_patterns=[],
        )
        gen = SyntheticGenerator()
        result = gen.generate(schema, _gen_params())
        header = result.read(5)
        assert header == b"%PDF-"


# ---------------------------------------------------------------------------
# Multi-page generation
# ---------------------------------------------------------------------------


class TestMultiPage:
    """High transaction counts must produce multi-page PDFs."""

    def test_high_volume_larger_than_single(self, minimal_schema: FormatSchema):
        """A high-volume PDF must be larger than a low-volume one."""
        gen = SyntheticGenerator()

        small_params = _gen_params(
            seed=42,
            transactions_per_month=TransactionRange(min=5, max=5),
        )
        large_params = _gen_params(
            seed=42,
            scenario=Scenario.HIGH_VOLUME,
            transactions_per_month=TransactionRange(min=80, max=100),
        )

        small_pdf = gen.generate(minimal_schema, small_params)
        large_pdf = gen.generate(minimal_schema, large_params)

        small_size = len(small_pdf.read())
        large_size = len(large_pdf.read())

        assert large_size > small_size, (
            f"High-volume PDF ({large_size}B) should be larger than small PDF ({small_size}B)"
        )


# ---------------------------------------------------------------------------
# generate_batch() — zip output
# ---------------------------------------------------------------------------


class TestGenerateBatch:
    """Batch generation must return a valid zip file."""

    def test_returns_bytesio(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        result = gen.generate_batch(
            minimal_schema,
            scenarios=[Scenario.SINGLE_MONTH],
            start_date=date(2025, 1, 1),
            seed=42,
        )
        assert isinstance(result, io.BytesIO)

    def test_valid_zip(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        result = gen.generate_batch(
            minimal_schema,
            scenarios=[Scenario.SINGLE_MONTH, Scenario.MINIMAL],
            start_date=date(2025, 1, 1),
            seed=42,
        )
        assert zipfile.is_zipfile(result)

    def test_zip_contains_correct_count(self, minimal_schema: FormatSchema):
        scenarios = [Scenario.SINGLE_MONTH, Scenario.MINIMAL, Scenario.HIGH_VOLUME]
        gen = SyntheticGenerator()
        result = gen.generate_batch(
            minimal_schema,
            scenarios=scenarios,
            start_date=date(2025, 1, 1),
            seed=42,
        )
        with zipfile.ZipFile(result, "r") as zf:
            assert len(zf.namelist()) == len(scenarios)

    def test_zip_entries_are_pdfs(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        result = gen.generate_batch(
            minimal_schema,
            scenarios=[Scenario.SINGLE_MONTH],
            start_date=date(2025, 1, 1),
            seed=42,
        )
        with zipfile.ZipFile(result, "r") as zf:
            for name in zf.namelist():
                assert name.endswith(".pdf")
                content = zf.read(name)
                assert content[:5] == b"%PDF-"

    def test_zip_filenames_sanitized(self, minimal_schema: FormatSchema):
        """Filenames in the zip must not contain unsafe characters."""
        gen = SyntheticGenerator()
        result = gen.generate_batch(
            minimal_schema,
            scenarios=[Scenario.SINGLE_MONTH],
            start_date=date(2025, 1, 1),
            seed=42,
        )
        with zipfile.ZipFile(result, "r") as zf:
            for name in zf.namelist():
                # Only alphanumeric, underscore, dash, and dot allowed
                for ch in name:
                    assert ch.isalnum() or ch in ("_", "-", "."), (
                        f"Unsafe character '{ch}' in filename '{name}'"
                    )


# ---------------------------------------------------------------------------
# Different scenarios produce different outputs
# ---------------------------------------------------------------------------


class TestScenarioVariation:
    """Different scenarios must produce PDFs of different sizes."""

    def test_minimal_vs_high_volume(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()

        minimal_params = _gen_params(seed=42, scenario=Scenario.MINIMAL)
        high_params = _gen_params(
            seed=42,
            scenario=Scenario.HIGH_VOLUME,
            transactions_per_month=TransactionRange(min=80, max=100),
        )

        minimal_pdf = gen.generate(minimal_schema, minimal_params)
        high_pdf = gen.generate(minimal_schema, high_params)

        minimal_size = len(minimal_pdf.read())
        high_size = len(high_pdf.read())

        assert high_size > minimal_size


# ---------------------------------------------------------------------------
# Multi-month generation
# ---------------------------------------------------------------------------


class TestMultiMonth:
    """Multi-month scenario must generate content spanning multiple months."""

    def test_multi_month_produces_output(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()
        params = _gen_params(
            seed=42,
            scenario=Scenario.MULTI_MONTH,
            months=3,
        )
        result = gen.generate(minimal_schema, params)
        assert isinstance(result, io.BytesIO)
        header = result.read(5)
        assert header == b"%PDF-"

    def test_multi_month_larger_than_single(self, minimal_schema: FormatSchema):
        gen = SyntheticGenerator()

        single_params = _gen_params(seed=42, months=1)
        multi_params = _gen_params(seed=42, scenario=Scenario.MULTI_MONTH, months=3)

        single_pdf = gen.generate(minimal_schema, single_params)
        multi_pdf = gen.generate(minimal_schema, multi_params)

        single_size = len(single_pdf.read())
        multi_size = len(multi_pdf.read())

        assert multi_size > single_size

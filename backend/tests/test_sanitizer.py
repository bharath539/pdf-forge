"""Tests for the SchemaSanitizer service.

Verifies that PII is correctly redacted while safe patterns (format strings,
hex colors, font names, placeholders) survive sanitization.
"""


import pytest

from app.models.schema import FormatSchema
from app.services.schema_sanitizer import SchemaSanitizer


@pytest.fixture
def sanitizer() -> SchemaSanitizer:
    return SchemaSanitizer()


# ---------------------------------------------------------------------------
# PII redaction — values that MUST be replaced with [REDACTED]
# ---------------------------------------------------------------------------


class TestPIIRedaction:
    """Strings containing PII patterns must be fully redacted."""

    def test_ssn_dashed(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("SSN: 123-45-6789", path="test")
        assert result == "[REDACTED]"

    def test_ssn_dashed_standalone(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("123-45-6789", path="test")
        assert result == "[REDACTED]"

    def test_credit_card_with_dashes(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("4111-1111-1111-1111", path="test")
        assert result == "[REDACTED]"

    def test_credit_card_with_spaces(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("4111 1111 1111 1111", path="test")
        assert result == "[REDACTED]"

    def test_credit_card_no_separators(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("4111111111111111", path="test")
        assert result == "[REDACTED]"

    def test_email_address(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("john.doe@example.com", path="test")
        assert result == "[REDACTED]"

    def test_email_in_sentence(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Contact us at support@bank.com", path="test")
        assert result == "[REDACTED]"

    def test_phone_with_parens(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("(555) 123-4567", path="test")
        assert result == "[REDACTED]"

    def test_phone_with_parens_no_space(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("(555)123-4567", path="test")
        assert result == "[REDACTED]"

    def test_phone_dashed(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("555-123-4567", path="test")
        assert result == "[REDACTED]"

    def test_phone_in_context(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Call us: (800) 555-1234", path="test")
        assert result == "[REDACTED]"

    def test_dollar_amount_simple(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("$1,234.56", path="test")
        assert result == "[REDACTED]"

    def test_dollar_amount_large(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Total: $99,999.00", path="test")
        assert result == "[REDACTED]"

    def test_dollar_amount_no_comma(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("$500.00", path="test")
        assert result == "[REDACTED]"

    def test_account_number_8_digits(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Acct: 12345678", path="test")
        assert result == "[REDACTED]"

    def test_account_number_12_digits(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("123456789012", path="test")
        assert result == "[REDACTED]"

    def test_street_address_st(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("123 Main St", path="test")
        assert result == "[REDACTED]"

    def test_street_address_avenue(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("456 Oak Avenue", path="test")
        assert result == "[REDACTED]"

    def test_street_address_blvd(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("789 Sunset Blvd", path="test")
        assert result == "[REDACTED]"

    def test_street_address_drive(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("1000 Park Drive", path="test")
        assert result == "[REDACTED]"


# ---------------------------------------------------------------------------
# Safe patterns — values that MUST NOT be redacted
# ---------------------------------------------------------------------------


class TestSafePatterns:
    """Format strings, hex colors, font names, and placeholders must survive."""

    def test_format_pattern_dollar(self, sanitizer: SchemaSanitizer):
        """Dollar format patterns with # are allowlisted."""
        result = sanitizer._sanitize_string("$#,##0.00", path="test")
        assert result == "$#,##0.00"

    def test_format_pattern_negative(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("-$#,##0.00", path="test")
        assert result == "-$#,##0.00"

    def test_format_pattern_accounting(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("(#,##0.00)", path="test")
        assert result == "(#,##0.00)"

    def test_hex_color_6_digit(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("#003366", path="test")
        assert result == "#003366"

    def test_hex_color_3_digit(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("#FFF", path="test")
        assert result == "#FFF"

    def test_hex_color_8_digit_with_alpha(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("#003366FF", path="test")
        assert result == "#003366FF"

    def test_hex_color_black(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("#000000", path="test")
        assert result == "#000000"

    def test_font_family_helvetica(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Helvetica", path="test")
        assert result == "Helvetica"

    def test_font_family_times_new_roman(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Times New Roman", path="test")
        assert result == "Times New Roman"

    def test_font_family_courier(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Courier", path="test")
        assert result == "Courier"

    def test_font_family_case_insensitive(self, sanitizer: SchemaSanitizer):
        """Font matching should be case-insensitive."""
        result = sanitizer._sanitize_string("helvetica", path="test")
        assert result == "helvetica"

    def test_placeholder_merchant(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("{merchant}", path="test")
        assert result == "{merchant}"

    def test_placeholder_page_number(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("Page {n} of {total}", path="test")
        assert result == "Page {n} of {total}"

    def test_placeholder_mixed(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("DEBIT CARD PURCHASE - {merchant} {city} {state}", path="test")
        assert result == "DEBIT CARD PURCHASE - {merchant} {city} {state}"

    def test_safe_label_date(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("date", path="test")
        assert result == "date"

    def test_safe_label_description(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("description", path="test")
        assert result == "description"

    def test_safe_enum_checking(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("checking", path="test")
        assert result == "checking"

    def test_safe_enum_bold(self, sanitizer: SchemaSanitizer):
        result = sanitizer._sanitize_string("bold", path="test")
        assert result == "bold"


# ---------------------------------------------------------------------------
# String length truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    """Strings over MAX_STRING_LENGTH (80) must be truncated."""

    def test_string_at_limit_not_truncated(self, sanitizer: SchemaSanitizer):
        value = "A" * 80
        result = sanitizer._sanitize_string(value, path="test")
        assert len(result) == 80

    def test_string_over_limit_truncated(self, sanitizer: SchemaSanitizer):
        value = "B" * 100
        result = sanitizer._sanitize_string(value, path="test")
        assert len(result) == 80

    def test_truncation_preserves_prefix(self, sanitizer: SchemaSanitizer):
        value = "X" * 100
        result = sanitizer._sanitize_string(value, path="test")
        assert result == "X" * 80

    def test_string_under_limit_unchanged(self, sanitizer: SchemaSanitizer):
        value = "Hello world"
        result = sanitizer._sanitize_string(value, path="test")
        assert result == "Hello world"


# ---------------------------------------------------------------------------
# is_safe_string() public helper
# ---------------------------------------------------------------------------


class TestIsSafeString:
    """The is_safe_string() public method returns True only for safe strings."""

    def test_safe_plain_text(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("Hello") is True

    def test_unsafe_ssn(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("123-45-6789") is False

    def test_unsafe_email(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("user@example.com") is False

    def test_safe_hex_color(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("#FF0000") is True

    def test_unsafe_over_length(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("Z" * 81) is False

    def test_safe_font(self, sanitizer: SchemaSanitizer):
        assert sanitizer.is_safe_string("Roboto") is True


# ---------------------------------------------------------------------------
# Full sanitize() method with a FormatSchema
# ---------------------------------------------------------------------------


class TestFullSanitize:
    """Test the sanitize() method with complete FormatSchema objects."""

    def test_sanitize_returns_new_object(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """The output must be a new object — the input must not be mutated."""
        original_dump = minimal_schema.model_dump()
        result = sanitizer.sanitize(minimal_schema)

        # Input unchanged
        assert minimal_schema.model_dump() == original_dump
        # Result is a different instance
        assert result is not minimal_schema

    def test_sanitize_clean_schema_unchanged(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """A clean schema with no PII should come through mostly unchanged."""
        result = sanitizer.sanitize(minimal_schema)
        assert result.bank_name == minimal_schema.bank_name
        assert result.account_type == minimal_schema.account_type
        assert result.display_name == minimal_schema.display_name
        # Fonts should keep their family names
        for orig, cleaned in zip(minimal_schema.fonts, result.fonts):
            assert cleaned.family == orig.family

    def test_sanitize_pii_schema_redacts_pii(self, sanitizer: SchemaSanitizer, pii_schema: FormatSchema):
        """A schema with injected PII must have those fields redacted."""
        result = sanitizer.sanitize(pii_schema)

        # bank_name had street address "123 Main St"
        assert result.bank_name == "[REDACTED]"

        # display_name had email and SSN
        assert result.display_name == "[REDACTED]"

        # Font family had phone number
        assert result.fonts[0].family == "[REDACTED]"

        # Footer element format had dollar amount
        footer = result.sections[3]
        assert footer.elements[0].format == "[REDACTED]"

    def test_sanitize_preserves_hex_colors(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """Hex color values in font specs must survive sanitization."""
        result = sanitizer.sanitize(minimal_schema)
        for font in result.fonts:
            assert font.color.startswith("#")

    def test_sanitize_preserves_description_patterns(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """Description patterns with {placeholders} must survive."""
        result = sanitizer.sanitize(minimal_schema)
        for orig, cleaned in zip(minimal_schema.description_patterns, result.description_patterns):
            assert cleaned.pattern == orig.pattern

    def test_sanitize_preserves_page_format(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """Page {n} of {total} format strings must survive."""
        result = sanitizer.sanitize(minimal_schema)
        footer = result.sections[3]
        assert footer.elements[0].format == "Page {n} of {total}"

    def test_sanitize_returns_valid_schema(self, sanitizer: SchemaSanitizer, minimal_schema: FormatSchema):
        """The sanitized output must be a valid FormatSchema."""
        result = sanitizer.sanitize(minimal_schema)
        # If this doesn't raise, the schema is valid
        FormatSchema.model_validate(result.model_dump())

    def test_sanitize_dict_passthrough_numbers(self, sanitizer: SchemaSanitizer):
        """Numbers, bools, and None must pass through unchanged."""
        data = {"count": 42, "enabled": True, "value": None, "ratio": 3.14}
        result = sanitizer.sanitize_dict(data)
        assert result == data

    def test_sanitize_dict_nested_lists(self, sanitizer: SchemaSanitizer):
        """Lists of dicts should be recursively processed."""
        data = {
            "items": [
                {"name": "safe text"},
                {"name": "john.doe@evil.com"},
            ]
        }
        result = sanitizer.sanitize_dict(data)
        assert result["items"][0]["name"] == "safe text"
        assert result["items"][1]["name"] == "[REDACTED]"

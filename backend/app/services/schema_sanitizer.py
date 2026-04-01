"""Strips personally identifiable information (PII) from learned format schemas.

Acts as a safety net to ensure no real names, account numbers, addresses,
or other sensitive data leaks into stored format definitions.
"""

from __future__ import annotations

import logging
import re

from app.models.schema import FormatSchema

logger = logging.getLogger(__name__)


class SchemaSanitizer:
    """Strips personally identifiable information (PII) from learned format schemas.

    Acts as a safety net to ensure no real names, account numbers, addresses,
    or other sensitive data leaks into stored format definitions.
    """

    MAX_STRING_LENGTH: int = 80

    REDACTED: str = "[REDACTED]"

    # Known-safe font family names (case-insensitive matching)
    SAFE_FONT_FAMILIES: set[str] = {
        "Helvetica",
        "Arial",
        "Courier",
        "Times",
        "Times New Roman",
        "Verdana",
        "Georgia",
        "Trebuchet MS",
        "Palatino",
        "Garamond",
        "Bookman",
        "Comic Sans MS",
        "Impact",
        "Lucida Console",
        "Lucida Sans",
        "Tahoma",
        "Calibri",
        "Cambria",
        "Consolas",
        "Segoe UI",
        "Roboto",
        "Open Sans",
        "Lato",
        "Montserrat",
        "Noto Sans",
        "Source Sans Pro",
        "Raleway",
        "PT Sans",
        "Ubuntu",
        "Fira Sans",
        "Inter",
        "Poppins",
        "Nunito",
        "Helvetica Neue",
        "SF Pro",
        "SF Pro Display",
        "SF Pro Text",
        "Menlo",
        "Monaco",
        "Courier New",
        "DejaVu Sans",
        "Liberation Sans",
        "Liberation Serif",
        "Liberation Mono",
        "Avenir",
        "Avenir Next",
        "Futura",
        "Gill Sans",
        "Optima",
        "Didot",
        "Baskerville",
        "Copperplate",
        "American Typewriter",
        "Rockwell",
    }

    # Lowercase lookup for case-insensitive font matching
    _SAFE_FONT_FAMILIES_LOWER: set[str] = {f.lower() for f in SAFE_FONT_FAMILIES}

    # Known-safe column header labels
    _SAFE_LABELS: set[str] = {
        "date",
        "description",
        "amount",
        "balance",
        "credit",
        "debit",
        "withdrawal",
        "deposit",
        "check",
        "check number",
        "reference",
        "transaction",
        "transaction date",
        "posting date",
        "type",
        "category",
        "memo",
        "details",
        "status",
        "fee",
        "interest",
        "principal",
        "payment",
        "total",
        "subtotal",
        "opening balance",
        "closing balance",
        "previous balance",
        "new balance",
        "statement period",
        "account number",
        "account type",
        "page",
        "statement date",
    }

    # Enum values from schema models that should never be redacted
    _SAFE_ENUM_VALUES: set[str] = {
        # AccountType
        "checking",
        "savings",
        "credit_card",
        "investment",
        "loan",
        # FontRole
        "header",
        "subheader",
        "body",
        "footer",
        "table_header",
        "table_body",
        # SectionType
        "account_summary",
        "transaction_table",
        "disclaimer",
        # ElementType
        "logo_placeholder",
        "text_field",
        "line_rule",
        "background_fill",
        # Font weights
        "normal",
        "bold",
        "light",
        # Alignments
        "left",
        "right",
        "center",
        # Description pattern categories
        "debit_card",
        "ach",
        "check",
        "transfer",
        "atm",
        "wire",
        "pos",
        "online",
        "mobile",
        "recurring",
        # Format types
        "text",
        "date",
        "amount",
    }

    # PII detection patterns — order matters, more specific first
    PII_PATTERNS: dict[str, re.Pattern[str]] = {
        "ssn_dashed": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "phone_parens": re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}"),
        "phone_dashed": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
        "street_address": re.compile(
            r"\b\d+\s+\w+\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Pl|Street|Avenue|Boulevard|Drive|Road|Lane|Court|Place)\b",
            re.IGNORECASE,
        ),
        "dollar_amount": re.compile(r"\$[\d,]+\.\d{2}"),
        "ssn_plain": re.compile(r"\b\d{9}\b"),
        "account_number": re.compile(r"\b\d{8,}\b"),
        "phone_plain": re.compile(r"\b\d{10}\b"),
    }

    # Patterns that indicate a string is safe (allowlisted)
    SAFE_PATTERNS: list[re.Pattern[str]] = [
        # Format pattern strings with placeholders
        re.compile(r"[#{}]"),
        # Hex color codes
        re.compile(r"^#[0-9A-Fa-f]{3,8}$"),
    ]

    def sanitize(self, schema: FormatSchema) -> FormatSchema:
        """Sanitize a FormatSchema, returning a new instance with PII stripped.

        Does not mutate the input schema.
        """
        raw = schema.model_dump()
        cleaned = self.sanitize_dict(raw, path="")
        return FormatSchema.model_validate(cleaned)

    def sanitize_dict(self, data: dict | list | object, path: str = "") -> dict | list | object:
        """Recursively walk a dict/list structure, sanitizing string values."""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                child_path = f"{path}.{key}" if path else key
                result[key] = self.sanitize_dict(value, path=child_path)
            return result

        if isinstance(data, list):
            return [self.sanitize_dict(item, path=f"{path}[{i}]") for i, item in enumerate(item for item in data)]

        if isinstance(data, str):
            return self._sanitize_string(data, path)

        # Numbers, bools, None — pass through
        return data

    def _sanitize_string(self, value: str, path: str) -> str:
        """Apply sanitization rules to a single string value."""
        # Length check
        if len(value) > self.MAX_STRING_LENGTH:
            logger.warning(
                "Truncated oversized string at '%s' (length %d > %d, pattern: string_length)",
                path,
                len(value),
                self.MAX_STRING_LENGTH,
            )
            value = value[: self.MAX_STRING_LENGTH]

        # Check allowlist before PII scan
        if self._is_allowlisted(value):
            return value

        # PII pattern scan
        for pattern_name, pattern in self.PII_PATTERNS.items():
            if pattern.search(value):
                logger.warning(
                    "Redacted PII at '%s' (pattern: %s)",
                    path,
                    pattern_name,
                )
                return self.REDACTED

        return value

    def _is_allowlisted(self, value: str) -> bool:
        """Check if a string matches any allowlist rule."""
        # Hex color codes
        if re.match(r"^#[0-9A-Fa-f]{3,8}$", value):
            return True

        # Format patterns containing # { or } (like $#,##0.00 or {merchant})
        if any(ch in value for ch in ("#", "{", "}")):
            return True

        # Known-safe font family names
        if value.lower() in self._SAFE_FONT_FAMILIES_LOWER:
            return True

        # Known-safe enum values
        if value.lower() in self._SAFE_ENUM_VALUES:
            return True

        # Known-safe column header labels
        if value.lower() in self._SAFE_LABELS:
            return True

        return False

    def is_safe_string(self, value: str) -> bool:
        """Return True if the string passes all checks.

        A string is safe if:
        - It is within the length limit (or is allowlisted)
        - It contains no PII patterns (or is allowlisted)
        """
        if len(value) > self.MAX_STRING_LENGTH:
            return False

        if self._is_allowlisted(value):
            return True

        for _pattern_name, pattern in self.PII_PATTERNS.items():
            if pattern.search(value):
                return False

        return True

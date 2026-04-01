"""Template Sanitizer — strips PII from classified templates before storage.

For data placeholder elements: replaces text with typed placeholder strings.
For structural elements: verifies no PII leaked through.
"""

from __future__ import annotations

import logging
import re

from app.models.template import (
    DataType,
    ElementCategory,
    PDFTemplate,
    TextElement,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII detection regexes (for structural elements that might have leaked PII)
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")),
    ("email", re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\(\d{3}\)|\d{3})[\s\-\.]?\d{3}[\s\-\.]?\d{4}\b")),
    ("street", re.compile(
        r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
        r"(?:St|Dr|Ave|Blvd|Ln|Rd|Ct|Way|Pl|Cir|Pkwy|Hwy|Ter)\b",
        re.IGNORECASE,
    )),
]

# Placeholder strings for each data type
_PLACEHOLDERS: dict[DataType, str] = {
    DataType.AMOUNT: "{amount}",
    DataType.DATE: "{date}",
    DataType.NAME: "{name}",
    DataType.ADDRESS: "{address}",
    DataType.ACCOUNT_NUMBER: "{account_number}",
    DataType.DESCRIPTION: "{description}",
    DataType.PHONE: "{phone}",
    DataType.EMAIL: "{email}",
    DataType.REFERENCE: "{reference}",
}

REDACTED = "[REDACTED]"


class TemplateSanitizer:
    """Strips PII from templates, replacing data with typed placeholders."""

    def sanitize(self, template: PDFTemplate) -> PDFTemplate:
        """Replace data element text with placeholders and verify structural safety."""
        logger.info("Sanitizing template: %d text elements", len(template.text_elements))

        data_replaced = 0
        structural_redacted = 0

        for te in template.text_elements:
            if te.element_type == ElementCategory.DATA_PLACEHOLDER:
                # Replace with typed placeholder
                if te.data_type and te.data_type in _PLACEHOLDERS:
                    te.text = _PLACEHOLDERS[te.data_type]
                else:
                    te.text = "{data}"
                data_replaced += 1
            else:
                # Verify structural elements don't contain PII
                if self._contains_pii(te.text):
                    te.text = REDACTED
                    structural_redacted += 1

        logger.info(
            "Sanitization complete: %d data→placeholders, %d structural→redacted",
            data_replaced, structural_redacted,
        )
        return template

    def _contains_pii(self, text: str) -> bool:
        """Check if text matches any PII pattern."""
        for name, pattern in _PII_PATTERNS:
            if pattern.search(text):
                return True
        return False

"""Template Sanitizer — strips PII from classified templates before storage.

For data placeholder elements: replaces text with typed placeholder strings.
For structural elements: promotes detected PII to data placeholders so the
renderer can fill them with fake values (rather than destroying the text).
"""

from __future__ import annotations

import logging
import re

from app.models.template import (
    DataType,
    ElementCategory,
    PDFTemplate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII detection regexes — only truly personal identifiers, NOT bank info
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, DataType, re.Pattern[str]]] = [
    ("ssn", DataType.ACCOUNT_NUMBER, re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "credit_card",
        DataType.ACCOUNT_NUMBER,
        re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"),
    ),
    (
        "street",
        DataType.ADDRESS,
        re.compile(
            r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
            r"(?:St|Dr|Ave|Blvd|Ln|Rd|Ct|Way|Pl|Cir|Pkwy|Hwy|Ter)\b",
            re.IGNORECASE,
        ),
    ),
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


class TemplateSanitizer:
    """Strips PII from templates, replacing data with typed placeholders."""

    def sanitize(self, template: PDFTemplate) -> PDFTemplate:
        """Replace data element text with placeholders.

        Structural elements are left untouched — bank phone numbers,
        legal text, and fixed addresses are part of the format, not user PII.
        Only promote truly personal identifiers (SSN, full CC#, personal
        street addresses that weren't already caught by the classifier).
        """
        logger.info("Sanitizing template: %d text elements", len(template.text_elements))

        data_replaced = 0
        structural_promoted = 0

        for te in template.text_elements:
            if te.element_type == ElementCategory.DATA_PLACEHOLDER:
                # Save original text for format detection during rendering
                te.original_text = te.text
                # Replace with typed placeholder
                if te.data_type and te.data_type in _PLACEHOLDERS:
                    te.text = _PLACEHOLDERS[te.data_type]
                else:
                    te.text = "{data}"
                data_replaced += 1
            else:
                # Only promote clear personal identifiers (SSN, full CC numbers,
                # personal street addresses). Bank phone numbers and legal text
                # are structural and should be preserved.
                pii_type = self._detect_personal_pii(te.text)
                if pii_type is not None:
                    te.original_text = te.text
                    te.element_type = ElementCategory.DATA_PLACEHOLDER
                    te.data_type = pii_type
                    te.text = _PLACEHOLDERS[pii_type]
                    structural_promoted += 1

        logger.info(
            "Sanitization complete: %d data→placeholders, %d structural→promoted",
            data_replaced,
            structural_promoted,
        )
        return template

    def _detect_personal_pii(self, text: str) -> DataType | None:
        """Check if text contains a truly personal identifier.

        Returns the DataType if found, None if the text is safe to keep.
        Phone numbers and emails in structural text are assumed to be the
        bank's contact info, not user PII.
        """
        for _name, data_type, pattern in _PII_PATTERNS:
            if pattern.search(text):
                return data_type
        return None

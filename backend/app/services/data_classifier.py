"""Data Classifier — identifies which text elements in a template are PII/data.

Takes a template where all elements are marked structural, and reclassifies
data elements (amounts, dates, names, addresses, account numbers, descriptions,
etc.) so they can be replaced with fake values during generation.
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
# Regex patterns for data detection
# ---------------------------------------------------------------------------

# Amounts: $1,234.56, -$50.00, ($123.45), 1234.56
_AMOUNT_RE = re.compile(r"^[\$€£]?\s*[\-\(]?\s*\d{1,3}(?:[,]\d{3})*(?:\.\d{1,2})?\s*[\)\-]?$")

# Standalone dollar amounts that are clearly money
_STRICT_AMOUNT_RE = re.compile(r"^\$\s*[\-\(]?\s*\d{1,3}(?:,\d{3})*\.\d{2}\s*[\)]?$")

# Date patterns
_DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),  # MM/DD/YYYY
    re.compile(r"^\d{1,2}/\d{2}/\d{4}$"),  # M/DD/YYYY
    re.compile(r"^\d{2}/\d{2}/\d{2}$"),  # MM/DD/YY
    re.compile(r"^\d{2}/\d{2}$"),  # MM/DD
    re.compile(r"^\d{1,2}/\d{1,2}$"),  # M/D
    re.compile(r"^\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}$"),  # DD Mon YYYY
    re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}$"),  # Mon DD, YYYY
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),  # YYYY-MM-DD
]

# Account numbers: sequences of digits, possibly masked
_ACCT_NUM_RE = re.compile(
    r"^(?:X{2,}|x{2,}|\*{2,})?\d{4,}$"  # XXXX1234, ****2917, 41471814
)
_MASKED_ACCT_RE = re.compile(
    r"^[\dXx\*\s\-]{8,}$"  # Longer masked patterns like XXXX XXXX XXXX 1234
)

# Phone numbers
_PHONE_RE = re.compile(r"^[\(\d][\d\s\(\)\-\.]{8,14}$")

# Email
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Address patterns
_STREET_RE = re.compile(
    r"^\d+\s+.+\b(?:St|Dr|Ave|Blvd|Ln|Rd|Ct|Way|Pl|Cir|Pkwy|Hwy|Ter|Loop)\b",
    re.IGNORECASE,
)
_CITY_STATE_ZIP_RE = re.compile(r"^[A-Z][a-zA-Z\s]+,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?$")
_PO_BOX_RE = re.compile(r"^P\.?O\.?\s+BOX\s+\d+", re.IGNORECASE)

# Reference numbers: alphanumeric strings (8+ chars, mix of letters and digits)
_REF_NUM_RE = re.compile(r"^[A-Z0-9]{8,}$")

# Structural labels that should never be classified as data
_STRUCTURAL_LABELS = {
    "account summary",
    "transaction detail",
    "transactions",
    "account activity",
    "statement summary",
    "payment information",
    "interest charge calculation",
    "fees",
    "interest charged",
    "total",
    "subtotal",
    "total payments",
    "total purchases",
    "total fees",
    "total interest",
    "total credits",
    "total debits",
    "total deposits",
    "total withdrawals",
    "beginning balance",
    "ending balance",
    "previous balance",
    "new balance",
    "minimum payment due",
    "payment due date",
    "credit limit",
    "available credit",
    "cash advance limit",
    "closing date",
    "opening date",
    "statement period",
    "account number",
    "page",
    "of",
    "date",
    "description",
    "amount",
    "balance",
    "credit",
    "debit",
    "check",
    "reference",
    "trans date",
    "post date",
    "posting date",
    "type",
    "category",
    "standard purchases",
    "cardholder summary",
    "account summary",
    "new charges",
    "promo purchase",
    "fees charged",
    "interest charged",
}

# Section header keywords that are structural
_SECTION_KEYWORDS = [
    "statement",
    "summary",
    "detail",
    "activity",
    "information",
    "calculation",
    "warning",
    "notice",
    "important",
    "page",
    "continued",
    "fees charged",
    "interest",
    "payment",
    "rewards",
    "cash back",
]


# ---------------------------------------------------------------------------
# DataClassifier
# ---------------------------------------------------------------------------


class DataClassifier:
    """Classifies text elements in a template as structural or data."""

    def classify(self, template: PDFTemplate) -> PDFTemplate:
        """Classify all text elements and return updated template.

        Modifies element_type and data_type on text elements in-place.
        """
        logger.info("Classifying %d text elements", len(template.text_elements))

        # First pass: classify individual elements by content
        for te in template.text_elements:
            self._classify_element(te)

        # Second pass: detect address blocks (multi-line name+street+city)
        self._classify_address_blocks(template)

        # 2b: detect mailing address at bottom of page 0
        self._classify_bottom_address_block(template)

        # 2c: detect repeated cardholder name across pages
        self._classify_cardholder_names(template)

        # Third pass: detect transaction table rows and classify descriptions
        self._classify_transaction_rows(template)

        # Compute data field summary
        self._compute_summary(template)

        classified = sum(1 for te in template.text_elements if te.element_type == ElementCategory.DATA_PLACEHOLDER)
        logger.info("Classified %d elements as data placeholders", classified)

        return template

    def _classify_element(self, te: TextElement) -> None:
        """Classify a single text element based on its content."""
        text = te.text.strip()
        text_lower = text.lower()

        # Skip empty
        if not text:
            return

        # Check if it's a known structural label
        if text_lower in _STRUCTURAL_LABELS:
            return
        if any(kw in text_lower for kw in _SECTION_KEYWORDS):
            # Longer text containing section keywords is likely structural
            if len(text) < 60:
                return

        # Email
        if _EMAIL_RE.match(text):
            te.element_type = ElementCategory.DATA_PLACEHOLDER
            te.data_type = DataType.EMAIL
            return

        # Phone
        if _PHONE_RE.match(text) and not _is_likely_date(text):
            # Avoid matching dates like 03/15/2026
            digits = sum(1 for c in text if c.isdigit())
            if digits >= 7:
                te.element_type = ElementCategory.DATA_PLACEHOLDER
                te.data_type = DataType.PHONE
                return

        # Strict dollar amounts (with $ sign)
        if _STRICT_AMOUNT_RE.match(text):
            te.element_type = ElementCategory.DATA_PLACEHOLDER
            te.data_type = DataType.AMOUNT
            return

        # General amounts (without $ but looks numeric with decimals)
        if _AMOUNT_RE.match(text) and "." in text:
            # Extra check: must have at least one digit
            if any(c.isdigit() for c in text):
                te.element_type = ElementCategory.DATA_PLACEHOLDER
                te.data_type = DataType.AMOUNT
                return

        # Dates
        if _is_likely_date(text):
            te.element_type = ElementCategory.DATA_PLACEHOLDER
            te.data_type = DataType.DATE
            return

        # Masked account numbers
        if _ACCT_NUM_RE.match(text.replace(" ", "").replace("-", "")):
            te.element_type = ElementCategory.DATA_PLACEHOLDER
            te.data_type = DataType.ACCOUNT_NUMBER
            return
        if _MASKED_ACCT_RE.match(text) and any(c.isdigit() for c in text):
            # Must have both mask chars and digits
            has_mask = any(c in text for c in "Xx*")
            has_digits = any(c.isdigit() for c in text)
            if has_mask and has_digits:
                te.element_type = ElementCategory.DATA_PLACEHOLDER
                te.data_type = DataType.ACCOUNT_NUMBER
                return

        # Reference numbers (long alphanumeric, all caps)
        if _REF_NUM_RE.match(text) and len(text) >= 10:
            has_letter = any(c.isalpha() for c in text)
            has_digit = any(c.isdigit() for c in text)
            if has_letter and has_digit:
                te.element_type = ElementCategory.DATA_PLACEHOLDER
                te.data_type = DataType.REFERENCE
                return

    def _classify_address_blocks(self, template: PDFTemplate) -> None:
        """Detect mailing address blocks (name + street + city/state/zip).

        Address blocks typically appear in the top portion of page 0,
        as a vertical cluster of 2-4 lines.
        """
        page0_texts = [
            te for te in template.text_elements if te.page == 0 and te.element_type == ElementCategory.STRUCTURAL
        ]
        if not page0_texts:
            return

        max_y = max(te.y for te in page0_texts)
        # Look in the upper 40% for address blocks
        upper_texts = sorted(
            [te for te in page0_texts if te.y < max_y * 0.4],
            key=lambda t: (t.y, t.x),
        )

        # Group into vertical clusters (lines within 3pt y-gap)
        line_groups: list[list[TextElement]] = []
        current_line: list[TextElement] = []
        current_y: float | None = None

        for te in upper_texts:
            if current_y is None or abs(te.y - current_y) > 3:
                if current_line:
                    line_groups.append(current_line)
                current_line = [te]
                current_y = te.y
            else:
                current_line.append(te)
        if current_line:
            line_groups.append(current_line)

        # Look for city/state/zip lines
        for i, line in enumerate(line_groups):
            line_text = " ".join(te.text for te in line)
            if _CITY_STATE_ZIP_RE.match(line_text.strip()):
                # This line is address — mark it
                for te in line:
                    te.element_type = ElementCategory.DATA_PLACEHOLDER
                    te.data_type = DataType.ADDRESS

                # Lines above it (up to 3) are likely name + street
                for j in range(max(0, i - 3), i):
                    prev_text = " ".join(te.text for te in line_groups[j])
                    prev_stripped = prev_text.strip()
                    if _STREET_RE.match(prev_stripped) or _PO_BOX_RE.match(prev_stripped):
                        for te in line_groups[j]:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.ADDRESS
                    elif j == i - 2 or j == i - 3:
                        # Likely the name line(s)
                        for te in line_groups[j]:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.NAME

    def _classify_bottom_address_block(self, template: PDFTemplate) -> None:
        """Detect mailing address at the bottom of page 0 (payment coupon area).

        Credit card statements often have the cardholder's name and address
        at the bottom-left of page 0 in the payment remittance section.
        The bank's return address (right side) is structural and kept as-is.
        """
        page0_texts = [
            te for te in template.text_elements
            if te.page == 0 and te.element_type == ElementCategory.STRUCTURAL
        ]
        if not page0_texts:
            return

        max_y = max(te.y for te in page0_texts)
        page_width = 612.0  # standard letter width
        if template.page_dimensions:
            page_width = template.page_dimensions[0].width
        mid_x = page_width / 2

        # Look in the bottom 15%, LEFT side only (user's address, not bank's)
        bottom_texts = sorted(
            [te for te in page0_texts if te.y > max_y * 0.85 and te.x < mid_x],
            key=lambda t: (t.y, t.x),
        )

        # Group into lines
        line_groups: list[list[TextElement]] = []
        current_line: list[TextElement] = []
        current_y: float | None = None

        for te in bottom_texts:
            if current_y is None or abs(te.y - current_y) > 3:
                if current_line:
                    line_groups.append(current_line)
                current_line = [te]
                current_y = te.y
            else:
                current_line.append(te)
        if current_line:
            line_groups.append(current_line)

        # Look for city/state/zip line
        for i, line in enumerate(line_groups):
            line_text = " ".join(te.text for te in line)
            if _CITY_STATE_ZIP_RE.match(line_text.strip()):
                for te in line:
                    te.element_type = ElementCategory.DATA_PLACEHOLDER
                    te.data_type = DataType.ADDRESS
                # Lines above: street then name
                for j in range(max(0, i - 3), i):
                    prev_text = " ".join(te.text for te in line_groups[j])
                    prev_stripped = prev_text.strip()
                    if _STREET_RE.match(prev_stripped) or _PO_BOX_RE.match(prev_stripped):
                        for te in line_groups[j]:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.ADDRESS
                    elif _is_likely_person_name(prev_stripped):
                        for te in line_groups[j]:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.NAME

    def _classify_cardholder_names(self, template: PDFTemplate) -> None:
        """Detect repeated cardholder names across pages.

        If the same ALL CAPS name appears on 2+ pages in header positions,
        it's almost certainly the cardholder name (PII).
        """
        # Find candidate name elements: ALL CAPS, 2-3 words, each 2+ chars
        from collections import Counter
        name_counter: Counter[str] = Counter()
        name_elements: dict[str, list[TextElement]] = {}

        for te in template.text_elements:
            if te.element_type != ElementCategory.STRUCTURAL:
                continue
            text = te.text.strip()
            if not _is_likely_person_name(text):
                continue
            # Must be in header area (top 10% of page)
            if te.y > 100:  # rough header threshold
                continue
            name_counter[text] += 1
            name_elements.setdefault(text, []).append(te)

        # Names appearing on 2+ pages are cardholder names
        for name, count in name_counter.items():
            if count >= 2:
                pages = set(te.page for te in name_elements[name])
                if len(pages) >= 2:
                    logger.info("Detected cardholder name: %s (appears on %d pages)", name, len(pages))
                    # Classify ALL occurrences (not just header ones)
                    for te in template.text_elements:
                        if te.text.strip() == name and te.element_type == ElementCategory.STRUCTURAL:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.NAME

    def _classify_transaction_rows(self, template: PDFTemplate) -> None:
        """Detect transaction table rows and classify description elements.

        Finds the transaction table by looking for a cluster of rows
        with date + amount patterns, then classifies non-date/non-amount
        elements in those rows as descriptions.

        Row indices are globally unique across pages to avoid collisions.
        """
        global_row_idx = 0  # Running counter across all pages
        first_tx_page: int | None = None
        first_tx_y: float | None = None
        all_gaps: list[float] = []

        for page_idx in range(template.page_count):
            page_texts = [te for te in template.text_elements if te.page == page_idx]
            if not page_texts:
                continue

            # Group elements by y-position into rows
            rows = self._group_into_rows(page_texts)

            # Find rows that have both a date and an amount element
            transaction_rows: list[tuple[float, list[TextElement]]] = []
            for y_pos, elements in rows:
                has_date = any(te.data_type == DataType.DATE for te in elements)
                has_amount = any(te.data_type == DataType.AMOUNT for te in elements)
                if has_date and has_amount:
                    transaction_rows.append((y_pos, elements))

            if not transaction_rows:
                continue

            # Record first page with transactions
            if first_tx_page is None:
                first_tx_page = page_idx
                first_tx_y = transaction_rows[0][0]

            # Determine the right-edge of the transaction table: the max x1 of
            # amount elements.  Anything further right is a separate column
            # (e.g. rewards summary) and should NOT be pulled into the row.
            amount_max_x = 0.0
            for _y, elems in transaction_rows:
                for te in elems:
                    if te.data_type == DataType.AMOUNT and te.width:
                        amount_max_x = max(amount_max_x, te.x + te.width)
            # Add a small margin (20pt) beyond the amount column
            tx_right_boundary = amount_max_x + 20 if amount_max_x > 0 else 9999

            # Assign globally unique row indices
            for _local_idx, (y_pos, elements) in enumerate(transaction_rows):
                for te in elements:
                    # Skip elements beyond the transaction table boundary
                    if te.x > tx_right_boundary:
                        continue
                    if te.element_type == ElementCategory.DATA_PLACEHOLDER:
                        te.row_index = global_row_idx
                    elif te.element_type == ElementCategory.STRUCTURAL:
                        text = te.text.strip()
                        if len(text) > 2 and text.lower() not in _STRUCTURAL_LABELS:
                            te.element_type = ElementCategory.DATA_PLACEHOLDER
                            te.data_type = DataType.DESCRIPTION
                            te.row_index = global_row_idx
                global_row_idx += 1

            # Compute row height from consecutive rows on this page
            if len(transaction_rows) >= 2:
                for i in range(len(transaction_rows) - 1):
                    all_gaps.append(transaction_rows[i + 1][0] - transaction_rows[i][0])

        # Record transaction area metadata
        if first_tx_page is not None and first_tx_y is not None:
            template.transaction_area_page = first_tx_page
            template.transaction_area_start_y = first_tx_y
            if all_gaps:
                template.transaction_row_height = round(sum(all_gaps) / len(all_gaps), 2)

    def _group_into_rows(
        self, elements: list[TextElement], tolerance: float = 3.0
    ) -> list[tuple[float, list[TextElement]]]:
        """Group text elements into rows by y-position."""
        if not elements:
            return []

        sorted_els = sorted(elements, key=lambda t: t.y)
        rows: list[tuple[float, list[TextElement]]] = []
        current_y: float | None = None
        current_row: list[TextElement] = []

        for te in sorted_els:
            if current_y is None or abs(te.y - current_y) > tolerance:
                if current_row and current_y is not None:
                    rows.append((current_y, current_row))
                current_y = te.y
                current_row = [te]
            else:
                current_row.append(te)

        if current_row and current_y is not None:
            rows.append((current_y, current_row))

        return rows

    def _compute_summary(self, template: PDFTemplate) -> None:
        """Compute data field counts."""
        summary = template.data_field_summary
        max_row = -1

        for te in template.text_elements:
            if te.element_type != ElementCategory.DATA_PLACEHOLDER:
                continue
            if te.data_type == DataType.AMOUNT:
                summary.amounts += 1
            elif te.data_type == DataType.DATE:
                summary.dates += 1
            elif te.data_type == DataType.NAME:
                summary.names += 1
            elif te.data_type == DataType.ADDRESS:
                summary.addresses += 1
            elif te.data_type == DataType.ACCOUNT_NUMBER:
                summary.account_numbers += 1
            elif te.data_type == DataType.DESCRIPTION:
                summary.descriptions += 1
            elif te.data_type == DataType.PHONE:
                summary.phones += 1
            elif te.data_type == DataType.EMAIL:
                summary.emails += 1
            elif te.data_type == DataType.REFERENCE:
                summary.references += 1

            if te.row_index is not None and te.row_index > max_row:
                max_row = te.row_index

        summary.transaction_rows = max_row + 1 if max_row >= 0 else 0


def _is_likely_date(text: str) -> bool:
    """Check if text matches a known date pattern."""
    stripped = text.strip()
    return any(p.match(stripped) for p in _DATE_PATTERNS)


def _is_likely_person_name(text: str) -> bool:
    """Check if text looks like a person's name (ALL CAPS, 2-3 words)."""
    words = text.split()
    if len(words) < 2 or len(words) > 4:
        return False
    # Each word must be 2+ alphabetic chars, all caps
    for w in words:
        if len(w) < 2 or not w.isalpha() or not w.isupper():
            return False
    # Must not be a known structural label
    if text.lower() in _STRUCTURAL_LABELS:
        return False
    # Must not contain section keywords
    text_lower = text.lower()
    if any(kw in text_lower for kw in _SECTION_KEYWORDS):
        return False
    return True

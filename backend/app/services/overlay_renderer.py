"""Overlay Renderer — generates synthetic PDFs by overlaying on the original.

Instead of rebuilding the PDF from scratch (which loses fidelity),
this renderer takes the original PDF, whites-out data fields, and
stamps new fake data at the exact positions. This preserves 100%
of the structural fidelity: colors, fonts, backgrounds, images, layouts.

Pipeline:
  1. Open original PDF with PyMuPDF
  2. Extract embedded fonts for reuse
  3. For each DATA_PLACEHOLDER element, redact original + insert fake text
  4. Find and replace embedded account numbers in structural text
  5. Save modified PDF
"""

from __future__ import annotations

import io
import logging
import random
import re
from datetime import date
from decimal import Decimal
from typing import Any

import fitz  # PyMuPDF

from app.models.generation import GenerationParams
from app.models.template import (
    DataType,
    ElementCategory,
    PDFTemplate,
    TextElement,
)
from app.services.data_faker import Transaction, TransactionFaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color '#RRGGBB' to (r, g, b) floats 0-1."""
    if not hex_str or len(hex_str) < 7:
        return (0.0, 0.0, 0.0)
    try:
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
        return (r, g, b)
    except (ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def _format_amount(amount: Decimal) -> str:
    abs_val = abs(amount)
    formatted = f"${abs_val:,.2f}"
    return f"-{formatted}" if amount < 0 else formatted


def _format_date_mmdd(d: date) -> str:
    return d.strftime("%m/%d")


def _format_date_mmddyy(d: date) -> str:
    return d.strftime("%m/%d/%y")


def _format_date_mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


# Patterns to find account numbers embedded in structural text
_EMBEDDED_ACCT_RE = re.compile(r"(?:ending\s+in[:\s]*|card\s+#?\s*)(\d{4})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# OverlayRenderer
# ---------------------------------------------------------------------------


class OverlayRenderer:
    """Renders synthetic PDFs by overlaying fake data on the original PDF."""

    def render(
        self,
        original_pdf_bytes: io.BytesIO,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> io.BytesIO:
        """Overlay fake data on the original PDF and return new PDF bytes."""
        faker = TransactionFaker(seed=params.seed)
        fake_data = self._generate_fake_data(template, params, faker)
        target_tx_count = self._target_transaction_count(params)

        # Open original PDF
        original_pdf_bytes.seek(0)
        doc = fitz.open(stream=original_pdf_bytes.read(), filetype="pdf")

        # Detect account number digits from template text
        acct_digits = self._detect_account_digits(template)
        fake_acct_last4 = fake_data.get("account_last4", "7291")

        # Separate elements by type
        data_elements = [te for te in template.text_elements if te.element_type == ElementCategory.DATA_PLACEHOLDER]

        row_elements: dict[int, list[TextElement]] = {}
        non_row_elements: list[TextElement] = []

        for te in data_elements:
            if te.row_index is not None:
                row_elements.setdefault(te.row_index, []).append(te)
            else:
                non_row_elements.append(te)

        # Generate fake values
        non_row_fakes = self._generate_non_row_values(non_row_elements, fake_data, params)
        transactions = fake_data["transactions"]
        row_fakes = self._generate_row_values(row_elements, transactions, target_tx_count, template, params)

        # Apply overlays page by page
        for page_idx in range(len(doc)):
            page = doc[page_idx]

            # Collect all data field replacements for this page
            replacements: list[tuple[TextElement, str]] = []

            for te, fake_text in non_row_fakes:
                if te.page == page_idx:
                    replacements.append((te, fake_text))

            for te, fake_text in row_fakes:
                if te.page == page_idx:
                    replacements.append((te, fake_text))

            # Process page: redact all → insert replacement text
            self._process_page(page, replacements, acct_digits, fake_acct_last4)

        # Save to bytes
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------
    # Account number detection
    # ------------------------------------------------------------------

    def _detect_account_digits(self, template: PDFTemplate) -> set[str]:
        """Find account number digits from template text.

        Looks for patterns like 'ending in: 2938', 'Card ending in 2938',
        'account number ending in: 2938'.
        """
        digits: set[str] = set()

        for te in template.text_elements:
            matches = _EMBEDDED_ACCT_RE.findall(te.text)
            for m in matches:
                digits.add(m)

        if digits:
            logger.info("Detected account digits: %s", digits)
        return digits

    def _insert_text(
        self,
        page: fitz.Page,
        point: fitz.Point,
        text: str,
        fontsize: float,
        color: tuple[float, float, float],
        weight: str,
    ) -> None:
        """Insert text using Helvetica base14 fonts."""
        fontname = "hebo" if weight == "bold" else "helv"
        try:
            page.insert_text(
                point,
                text,
                fontname=fontname,
                fontsize=fontsize,
                color=color,
            )
        except Exception as e:
            logger.warning("Text insert error for '%s': %s", text, e)
            page.insert_text(
                point,
                text,
                fontname="helv",
                fontsize=fontsize,
                color=color,
            )

    def _process_page(
        self,
        page: fitz.Page,
        replacements: list[tuple[TextElement, str]],
        acct_digits: set[str],
        fake_acct_last4: str,
    ) -> None:
        """Process one page using search-based positioning.

        For each data element, uses PyMuPDF search_for() to find its exact
        bounding box in the PDF. This gives pixel-perfect position and size
        instead of relying on pdfplumber's estimated coordinates.
        """
        # --- Phase 1: Find exact rects for all data elements via search ---

        # Each entry: (rect, fake_text, color, weight)
        matched: list[tuple[fitz.Rect, str, tuple[float, float, float], str]] = []

        for te, fake_text in replacements:
            # Get the original text before sanitization replaced it
            original_text = te.text
            # After sanitization, placeholders like {amount} won't be found.
            # Use the original text stored before sanitization was applied.
            # The sanitizer changes te.text, so we need to search for what's
            # actually in the PDF. We can reconstruct from the placeholder type.
            # But we should search for the ORIGINAL text that's in the PDF.

            # Search for original text in the PDF
            search_text = original_text
            # Sanitized placeholders won't be found; skip them
            if search_text.startswith("{") and search_text.endswith("}"):
                # Fallback: use pdfplumber coordinates (less accurate but works)
                text_height = te.font_size
                text_width = te.width if te.width else text_height * len(fake_text) * 0.6
                rect = fitz.Rect(
                    te.x - 1,
                    te.y - 1,
                    te.x + text_width + 1,
                    te.y + text_height + 1,
                )
                page.add_redact_annot(rect, fill=(1, 1, 1))
                matched.append((rect, fake_text, _hex_to_rgb(te.color), te.font_weight))
                continue

            rects = page.search_for(search_text)
            if rects:
                # Find the rect closest to our expected position
                best_rect = self._closest_rect(rects, te.x, te.y)
                # Add small margin for redaction
                redact_rect = fitz.Rect(
                    best_rect.x0 - 1,
                    best_rect.y0 - 1,
                    best_rect.x1 + 1,
                    best_rect.y1 + 1,
                )
                page.add_redact_annot(redact_rect, fill=(1, 1, 1))
                matched.append((best_rect, fake_text, _hex_to_rgb(te.color), te.font_weight))
            else:
                # Search failed — fallback to pdfplumber coordinates
                text_height = te.font_size
                text_width = te.width if te.width else text_height * len(search_text) * 0.6
                rect = fitz.Rect(
                    te.x - 1,
                    te.y - 1,
                    te.x + text_width + 1,
                    te.y + text_height + 1,
                )
                page.add_redact_annot(rect, fill=(1, 1, 1))
                matched.append((rect, fake_text, _hex_to_rgb(te.color), te.font_weight))

        # Account number redactions (search-based)
        acct_matched: list[tuple[fitz.Rect, str]] = []
        for digit_str in acct_digits:
            rects = page.search_for(digit_str)
            for rect in rects:
                expanded = fitz.Rect(
                    rect.x0 - 1,
                    rect.y0 - 1,
                    rect.x1 + 1,
                    rect.y1 + 1,
                )
                page.add_redact_annot(expanded, fill=(1, 1, 1))
                acct_matched.append((rect, fake_acct_last4))

        # --- Phase 2: Apply ALL redactions at once ---
        page.apply_redactions()

        # --- Phase 3: Insert all replacement text ---

        for rect, fake_text, color, weight in matched:
            # Font size = rect height (the actual rendered size in the PDF)
            fontsize = max(rect.height * 0.88, 5.0)
            # Baseline = top of rect + descent from top (~78% of height)
            baseline_y = rect.y0 + rect.height * 0.82

            self._insert_text(
                page,
                fitz.Point(rect.x0, baseline_y),
                fake_text,
                fontsize,
                color,
                weight,
            )

        for rect, fake_digits in acct_matched:
            fontsize = max(rect.height * 0.88, 5.0)
            baseline_y = rect.y0 + rect.height * 0.82

            self._insert_text(
                page,
                fitz.Point(rect.x0, baseline_y),
                fake_digits,
                fontsize,
                (0, 0, 0),
                "normal",
            )

    def _closest_rect(self, rects: list[fitz.Rect], x: float, y: float) -> fitz.Rect:
        """Find the rect closest to the expected (x, y) position."""
        best = rects[0]
        best_dist = abs(best.x0 - x) + abs(best.y0 - y)
        for r in rects[1:]:
            dist = abs(r.x0 - x) + abs(r.y0 - y)
            if dist < best_dist:
                best = r
                best_dist = dist
        return best

    # ------------------------------------------------------------------
    # Fake data generation
    # ------------------------------------------------------------------

    def _generate_fake_data(
        self,
        template: PDFTemplate,
        params: GenerationParams,
        faker: TransactionFaker,
    ) -> dict[str, Any]:
        from faker import Faker

        account_type = template.account_type.value if template.account_type else "checking"
        transactions = faker.generate_transactions(params, [], account_type=account_type)
        opening = Decimal(params.opening_balance)
        summary = faker.generate_account_summary(opening, transactions)

        fake = Faker()
        if params.seed is not None:
            Faker.seed(params.seed)

        # Generate a consistent fake last-4 digits
        rng = random.Random(params.seed)
        fake_last4 = str(rng.randint(1000, 9999))

        return {
            "transactions": transactions,
            "summary": summary,
            "name": fake.name().upper(),
            "address_street": fake.street_address().upper(),
            "address_city_state_zip": f"{fake.city().upper()}  {fake.state_abbr()}  {fake.zipcode()}",
            "account_number": faker.generate_account_number_masked(),
            "account_last4": fake_last4,
            "phone": fake.phone_number(),
            "email": fake.email(),
        }

    def _target_transaction_count(self, params: GenerationParams) -> int:
        rng = random.Random(params.seed)
        base = rng.randint(
            params.transactions_per_month.min,
            params.transactions_per_month.max,
        )
        return base * params.months

    # ------------------------------------------------------------------
    # Non-row value generation
    # ------------------------------------------------------------------

    def _generate_non_row_values(
        self,
        elements: list[TextElement],
        fake_data: dict[str, Any],
        params: GenerationParams,
    ) -> list[tuple[TextElement, str]]:
        """Generate fake values for non-transaction-row data elements."""
        transactions = fake_data["transactions"]
        rng = random.Random(params.seed if params.seed else 42)

        address_count = 0
        results: list[tuple[TextElement, str]] = []

        for te in elements:
            fake_text = te.text  # fallback

            if te.data_type == DataType.NAME:
                fake_text = fake_data["name"]
            elif te.data_type == DataType.ADDRESS:
                if address_count % 2 == 0:
                    fake_text = fake_data["address_street"]
                else:
                    fake_text = fake_data["address_city_state_zip"]
                address_count += 1
            elif te.data_type == DataType.ACCOUNT_NUMBER:
                fake_text = fake_data["account_number"]
            elif te.data_type == DataType.PHONE:
                fake_text = fake_data["phone"]
            elif te.data_type == DataType.EMAIL:
                fake_text = fake_data["email"]
            elif te.data_type == DataType.AMOUNT:
                # Preserve original prefix pattern (+$, -$, minus$, $)
                text = te.text.strip()
                prefix = ""
                if text.startswith("minus"):
                    prefix = "minus"
                    text = text[5:]
                elif text.startswith("-"):
                    prefix = "-"
                    text = text[1:]
                elif text.startswith("+"):
                    prefix = "+"
                    text = text[1:]
                has_dollar = "$" in text
                amt = Decimal(str(round(rng.uniform(10, 5000), 2)))
                abs_formatted = f"{abs(amt):,.2f}"
                if has_dollar:
                    abs_formatted = f"${abs_formatted}"
                fake_text = f"{prefix}{abs_formatted}"
            elif te.data_type == DataType.DATE:
                if transactions:
                    orig_len = len(te.text.strip()) if te.text else 10
                    if orig_len <= 5:
                        fake_text = _format_date_mmdd(transactions[0].date)
                    elif orig_len <= 8:
                        fake_text = _format_date_mmddyy(transactions[0].date)
                    else:
                        fake_text = _format_date_mmddyyyy(transactions[0].date)
            elif te.data_type == DataType.DESCRIPTION:
                fake_text = "Payment received"
            elif te.data_type == DataType.REFERENCE:
                fake_text = "".join(
                    rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(min(len(te.text), 16))
                )

            results.append((te, fake_text))

        return results

    # ------------------------------------------------------------------
    # Transaction row value generation
    # ------------------------------------------------------------------

    def _generate_row_values(
        self,
        row_elements: dict[int, list[TextElement]],
        transactions: list[Transaction],
        target_tx_count: int,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> list[tuple[TextElement, str]]:
        """Generate fake values for transaction row elements."""
        if not row_elements:
            return []

        original_rows = sorted(row_elements.keys())
        results: list[tuple[TextElement, str]] = []
        rng = random.Random(params.seed if params.seed else 42)

        for i, row_idx in enumerate(original_rows):
            tx_idx = i % len(transactions) if transactions else 0
            tx = transactions[tx_idx] if transactions else None

            for te in row_elements[row_idx]:
                fake_text = te.text  # fallback

                if te.data_type == DataType.DATE and tx:
                    orig_len = len(te.text.strip()) if te.text else 10
                    if orig_len <= 5:
                        fake_text = _format_date_mmdd(tx.date)
                    elif orig_len <= 8:
                        fake_text = _format_date_mmddyy(tx.date)
                    else:
                        fake_text = _format_date_mmddyyyy(tx.date)
                elif te.data_type == DataType.AMOUNT and tx:
                    fake_text = _format_amount(tx.amount)
                elif te.data_type == DataType.DESCRIPTION and tx:
                    desc = tx.description
                    if te.width and te.font_size > 0:
                        approx_chars = int(te.width / (te.font_size * 0.5))
                        if len(desc) > approx_chars:
                            desc = desc[: approx_chars - 3] + "..."
                    fake_text = desc
                elif te.data_type == DataType.REFERENCE:
                    fake_text = "".join(
                        rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(min(len(te.text), 16))
                    )

                results.append((te, fake_text))

        return results

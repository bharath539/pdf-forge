"""Redacted Renderer — generates synthetic PDFs by overlaying on stored redacted PDFs.

V3 approach: the redacted PDF (with all PII whited out) is stored in the DB.
At generation time, we open it and insert fake data at the pre-recorded positions.
No search_for() needed — positions were found during the learn phase.

This gives pixel-perfect fidelity: all structural elements (logos, colors,
fine print, backgrounds, lines) are preserved exactly from the original.
"""

from __future__ import annotations

import io
import logging
import random
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any

import fitz

from app.models.generation import GenerationParams, Scenario
from app.models.template import (
    DataType,
    ElementCategory,
    PDFTemplate,
    RedactedRect,
    TextElement,
)
from app.services.data_faker import Transaction, TransactionFaker
from app.services.pdf_helpers import (
    format_amount,
    format_date_mmdd,
    format_date_mmddyy,
    format_date_mmddyyyy,
    hex_to_rgb,
    insert_text,
)

logger = logging.getLogger(__name__)


class RedactedRenderer:
    """Renders synthetic PDFs by overlaying fake data on stored redacted PDFs."""

    def render(
        self,
        redacted_pdf_bytes: bytes,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> io.BytesIO:
        """Overlay fake data on the redacted PDF and return new PDF bytes."""
        faker = TransactionFaker(seed=params.seed)
        fake_data = self._generate_fake_data(template, params, faker)
        target_tx_count = self._target_transaction_count(params)

        # Open the stored redacted PDF (already has PII whited out)
        doc = fitz.open(stream=redacted_pdf_bytes, filetype="pdf")

        # Build rect lookup: element_index -> RedactedRect
        rect_lookup: dict[int, RedactedRect] = {
            rr.element_index: rr for rr in template.redacted_rects
        }

        # Separate data elements into row vs non-row
        data_elements = [
            (i, te)
            for i, te in enumerate(template.text_elements)
            if te.element_type == ElementCategory.DATA_PLACEHOLDER
        ]

        row_elements: dict[int, list[tuple[int, TextElement]]] = {}
        non_row_elements: list[tuple[int, TextElement]] = []

        for idx, te in data_elements:
            if te.row_index is not None:
                row_elements.setdefault(te.row_index, []).append((idx, te))
            else:
                non_row_elements.append((idx, te))

        # Generate fake values
        non_row_fakes = self._generate_non_row_values(
            non_row_elements, fake_data, params
        )
        row_fakes = self._generate_row_values(
            row_elements, fake_data["transactions"], target_tx_count, params
        )

        # Insert fake text at pre-recorded positions
        all_replacements = non_row_fakes + row_fakes

        for elem_idx, fake_text in all_replacements:
            rr = rect_lookup.get(elem_idx)
            if not rr:
                continue
            if rr.page >= len(doc):
                continue

            page = doc[rr.page]
            te = template.text_elements[elem_idx]

            # Font size from rect height
            fontsize = max((rr.y1 - rr.y0) * 0.88, 5.0)
            # Baseline position
            baseline_y = rr.y0 + (rr.y1 - rr.y0) * 0.82

            color = hex_to_rgb(te.color)
            insert_text(
                page,
                fitz.Point(rr.x0, baseline_y),
                fake_text,
                fontsize,
                color,
                te.font_weight,
            )

        # Also handle embedded account number replacements
        fake_last4 = fake_data.get("account_last4", "7291")
        from app.services.pdf_helpers import detect_account_digits

        acct_digits = detect_account_digits(template)
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            for digit_str in acct_digits:
                for rect in page.search_for(digit_str):
                    # These digits were redacted at learn time, but since we stored
                    # the redacted PDF, they're already white. However, the redacted
                    # PDF might have residual matches if search finds similar digits
                    # in structural text. Only insert at exact match positions.
                    fontsize = max(rect.height * 0.88, 5.0)
                    baseline_y = rect.y0 + rect.height * 0.82
                    insert_text(
                        page,
                        fitz.Point(rect.x0, baseline_y),
                        fake_last4,
                        fontsize,
                        (0, 0, 0),
                        "normal",
                    )

        # Save to bytes
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)
        return buf

    def render_preview(
        self,
        redacted_pdf_bytes: bytes,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> io.BytesIO:
        """Render only the first page as a preview."""
        full_pdf = self.render(redacted_pdf_bytes, template, params)
        # Extract first page only
        doc = fitz.open(stream=full_pdf.read(), filetype="pdf")
        if len(doc) > 1:
            doc.select([0])
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        buf.seek(0)
        return buf

    def render_batch(
        self,
        redacted_pdf_bytes: bytes,
        template: PDFTemplate,
        scenarios: list[Scenario],
        start_date: date,
        seed: int | None = None,
    ) -> io.BytesIO:
        """Generate multiple PDFs (one per scenario) and return as a zip."""
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, scenario in enumerate(scenarios):
                scenario_seed = (seed + i) if seed is not None else None
                params = GenerationParams(
                    schema_id=template.bank_name,  # placeholder
                    scenario=scenario,
                    start_date=start_date,
                    seed=scenario_seed,
                    months=3 if scenario == Scenario.MULTI_MONTH else 1,
                    opening_balance="5000.00",
                )
                pdf_buf = self.render(redacted_pdf_bytes, template, params)
                filename = f"statement-{scenario.value}-{i + 1}.pdf"
                zf.writestr(filename, pdf_buf.getvalue())

        zip_buf.seek(0)
        return zip_buf

    # ------------------------------------------------------------------
    # Fake data generation (reused from overlay_renderer patterns)
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

    def _generate_non_row_values(
        self,
        elements: list[tuple[int, TextElement]],
        fake_data: dict[str, Any],
        params: GenerationParams,
    ) -> list[tuple[int, str]]:
        """Generate fake values for non-transaction-row data elements."""
        transactions = fake_data["transactions"]
        summary = fake_data["summary"]
        rng = random.Random(params.seed if params.seed else 42)

        address_count = 0
        results: list[tuple[int, str]] = []

        for elem_idx, te in elements:
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
                fake_text = self._generate_matching_amount(te.text, summary, rng)
            elif te.data_type == DataType.DATE:
                if transactions:
                    orig_len = len(te.text.strip()) if te.text else 10
                    if orig_len <= 5:
                        fake_text = format_date_mmdd(transactions[0].date)
                    elif orig_len <= 8:
                        fake_text = format_date_mmddyy(transactions[0].date)
                    else:
                        fake_text = format_date_mmddyyyy(transactions[0].date)
            elif te.data_type == DataType.DESCRIPTION:
                fake_text = "Payment received"
            elif te.data_type == DataType.REFERENCE:
                fake_text = "".join(
                    rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                    for _ in range(min(len(te.text), 16))
                )

            results.append((elem_idx, fake_text))

        return results

    def _generate_matching_amount(
        self, original_text: str, summary: dict[str, Any], rng: random.Random
    ) -> str:
        """Generate a fake amount that preserves the original text's format/prefix.

        Matches the prefix pattern (+$, -$, minus$, $) and generates a
        contextually appropriate amount.
        """
        text = original_text.strip()

        # Detect prefix pattern
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

        # Generate a random amount in a reasonable range
        amt = Decimal(str(round(rng.uniform(10, 5000), 2)))
        abs_formatted = f"{abs(amt):,.2f}"

        if has_dollar:
            abs_formatted = f"${abs_formatted}"

        return f"{prefix}{abs_formatted}"

    def _generate_row_values(
        self,
        row_elements: dict[int, list[tuple[int, TextElement]]],
        transactions: list[Transaction],
        target_tx_count: int,
        params: GenerationParams,
    ) -> list[tuple[int, str]]:
        """Generate fake values for transaction row elements."""
        if not row_elements:
            return []

        original_rows = sorted(row_elements.keys())
        results: list[tuple[int, str]] = []
        rng = random.Random(params.seed if params.seed else 42)

        for i, row_idx in enumerate(original_rows):
            if i >= len(transactions):
                # More template rows than transactions — leave blank
                for elem_idx, te in row_elements[row_idx]:
                    results.append((elem_idx, ""))
                continue

            tx = transactions[i]

            for elem_idx, te in row_elements[row_idx]:
                fake_text = ""

                if te.data_type == DataType.DATE:
                    orig_len = len(te.text.strip()) if te.text else 10
                    if orig_len <= 5:
                        fake_text = format_date_mmdd(tx.date)
                    elif orig_len <= 8:
                        fake_text = format_date_mmddyy(tx.date)
                    else:
                        fake_text = format_date_mmddyyyy(tx.date)
                elif te.data_type == DataType.AMOUNT:
                    fake_text = format_amount(tx.amount)
                elif te.data_type == DataType.DESCRIPTION:
                    desc = tx.description
                    if te.width and te.font_size > 0:
                        approx_chars = int(te.width / (te.font_size * 0.5))
                        if len(desc) > approx_chars:
                            desc = desc[: approx_chars - 3] + "..."
                    fake_text = desc
                elif te.data_type == DataType.REFERENCE:
                    fake_text = "".join(
                        rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                        for _ in range(min(len(te.text), 16))
                    )

                results.append((elem_idx, fake_text))

        return results

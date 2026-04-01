"""Template Renderer — replays a PDF template with fake data.

Takes a sanitized PDFTemplate and GenerationParams, generates fake
transaction data, injects it into placeholder positions, and renders
a pixel-perfect PDF using reportlab.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from faker import Faker
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfgen.canvas import Canvas

from app.models.generation import GenerationParams, Scenario
from app.models.template import (
    DataType,
    ElementCategory,
    ImageElement,
    LineElement,
    PDFTemplate,
    PageDimensions,
    RectElement,
    TextElement,
)
from app.services.data_faker import TransactionFaker, Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Font mapping
# ---------------------------------------------------------------------------

_FONT_MAP: dict[str, tuple[str, str]] = {
    "helvetica": ("Helvetica", "Helvetica-Bold"),
    "arial": ("Helvetica", "Helvetica-Bold"),
    "courier": ("Courier", "Courier-Bold"),
    "times": ("Times-Roman", "Times-Bold"),
    "times new roman": ("Times-Roman", "Times-Bold"),
    "times-roman": ("Times-Roman", "Times-Bold"),
}

_DEFAULT_FONT = ("Helvetica", "Helvetica-Bold")
_MIN_FONT_SIZE = 6.0


def _resolve_font(family: str, weight: str = "normal") -> str:
    key = family.lower().strip()
    normal, bold = _FONT_MAP.get(key, _DEFAULT_FONT)
    return bold if weight == "bold" else normal


def _hex_to_color(hex_str: str) -> Color:
    if not hex_str:
        return HexColor("#000000")
    try:
        return HexColor(hex_str)
    except Exception:
        return HexColor("#000000")


# ---------------------------------------------------------------------------
# Amount / date formatting
# ---------------------------------------------------------------------------

def _format_amount(amount: Decimal) -> str:
    """Format a decimal amount as $X,XXX.XX."""
    abs_val = abs(amount)
    formatted = f"${abs_val:,.2f}"
    if amount < 0:
        return f"-{formatted}"
    return formatted


def _format_date_mmdd(d: date) -> str:
    return d.strftime("%m/%d")


def _format_date_mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _format_date_mmddyy(d: date) -> str:
    return d.strftime("%m/%d/%y")


def _guess_date_format(placeholder_width: float | None, original_text: str = "") -> str:
    """Guess date format from the original placeholder context."""
    # Try to infer from the original text pattern that was there
    if original_text:
        if len(original_text) == 5:  # MM/DD
            return "short"
        if len(original_text) == 8:  # MM/DD/YY
            return "medium"
    return "long"  # MM/DD/YYYY


# ---------------------------------------------------------------------------
# TemplateRenderer
# ---------------------------------------------------------------------------

class TemplateRenderer:
    """Renders a PDF from a template by replaying all elements with fake data."""

    def render(
        self,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> io.BytesIO:
        """Render the template with generated fake data and return PDF bytes."""
        faker = TransactionFaker(seed=params.seed)
        fake_data = self._generate_fake_data(template, params, faker)

        buf = io.BytesIO()
        page_dims = template.page_dimensions
        if not page_dims:
            page_dims = [PageDimensions(width=612, height=792)]

        first_page = page_dims[0]
        c = Canvas(buf, pagesize=(first_page.width, first_page.height))

        # Determine which pages to render and handle transaction expansion
        target_tx_count = self._target_transaction_count(params)
        original_tx_count = template.data_field_summary.transaction_rows

        # Build modified text elements with fake data injected
        rendered_texts = self._inject_fake_data(template, fake_data, target_tx_count)

        # Group all elements by page
        max_page = template.page_count - 1

        for page_idx in range(template.page_count):
            if page_idx > 0:
                dims = page_dims[page_idx] if page_idx < len(page_dims) else first_page
                c.setPageSize((dims.width, dims.height))
                c.showPage()

            dims = page_dims[page_idx] if page_idx < len(page_dims) else first_page
            page_height = dims.height

            # Draw rectangles (background fills first)
            for rect in template.rect_elements:
                if rect.page != page_idx:
                    continue
                self._draw_rect(c, rect, page_height)

            # Draw lines
            for line in template.line_elements:
                if line.page != page_idx:
                    continue
                self._draw_line(c, line, page_height)

            # Draw images (placeholder boxes)
            for img in template.image_elements:
                if img.page != page_idx:
                    continue
                self._draw_image_placeholder(c, img, page_height)

            # Draw text elements
            for te in rendered_texts:
                if te.page != page_idx:
                    continue
                self._draw_text(c, te, page_height)

        c.save()
        buf.seek(0)
        return buf

    def render_preview(
        self,
        template: PDFTemplate,
        params: GenerationParams,
    ) -> io.BytesIO:
        """Render a single-page preview."""
        preview_params = params.model_copy(
            update={
                "months": 1,
                "transactions_per_month": params.transactions_per_month.model_copy(
                    update={"min": 5, "max": 10}
                ),
            }
        )
        return self.render(template, preview_params)

    def render_batch(
        self,
        template: PDFTemplate,
        scenarios: list[Scenario],
        start_date: date,
        seed: int | None = None,
    ) -> io.BytesIO:
        """Render multiple scenario PDFs as a zip."""
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, scenario in enumerate(scenarios):
                scenario_seed = (seed + i) if seed is not None else None
                params = GenerationParams(
                    schema_id="00000000-0000-0000-0000-000000000000",
                    scenario=scenario,
                    start_date=start_date,
                    seed=scenario_seed,
                    months=3 if scenario == Scenario.MULTI_MONTH else 1,
                    opening_balance="5000.00",
                )
                pdf_bytes = self.render(template, params)
                filename = f"{template.bank_name}_{scenario.value}_{i + 1}.pdf"
                filename = "".join(
                    ch if ch.isalnum() or ch in ("_", "-", ".") else "_"
                    for ch in filename
                )
                zf.writestr(filename, pdf_bytes.read())

        zip_buf.seek(0)
        return zip_buf

    # ------------------------------------------------------------------
    # Fake data generation
    # ------------------------------------------------------------------

    def _generate_fake_data(
        self,
        template: PDFTemplate,
        params: GenerationParams,
        faker: TransactionFaker,
    ) -> dict[str, Any]:
        """Generate all fake data needed to fill the template."""
        # Generate transactions
        transactions = faker.generate_transactions(params, [])
        opening = Decimal(params.opening_balance)
        summary = faker.generate_account_summary(opening, transactions)

        # Generate personal info
        fake = Faker()
        if params.seed is not None:
            Faker.seed(params.seed)

        data: dict[str, Any] = {
            "transactions": transactions,
            "summary": summary,
            "name": fake.name(),
            "address_street": fake.street_address(),
            "address_city_state_zip": f"{fake.city()}, {fake.state_abbr()} {fake.zipcode()}",
            "account_number": faker.generate_account_number_masked(),
            "phone": fake.phone_number(),
            "email": fake.email(),
        }
        return data

    def _target_transaction_count(self, params: GenerationParams) -> int:
        """Determine how many transactions to generate."""
        import random
        rng = random.Random(params.seed)
        base = rng.randint(
            params.transactions_per_month.min,
            params.transactions_per_month.max,
        )
        return base * params.months

    # ------------------------------------------------------------------
    # Data injection — fill placeholders with fake values
    # ------------------------------------------------------------------

    def _inject_fake_data(
        self,
        template: PDFTemplate,
        fake_data: dict[str, Any],
        target_tx_count: int,
    ) -> list[TextElement]:
        """Create a copy of text elements with placeholders filled."""
        transactions: list[Transaction] = fake_data["transactions"]
        summary = fake_data["summary"]

        # Counters for sequential injection
        tx_idx = 0  # which transaction we're on
        date_in_row: dict[int, int] = {}  # row_index -> how many dates used
        amount_in_row: dict[int, int] = {}
        desc_in_row: dict[int, int] = {}
        name_count = 0
        address_count = 0
        acct_count = 0
        ref_count = 0
        # For non-row amounts (summary amounts)
        summary_amount_idx = 0
        summary_amounts = [
            _format_amount(summary["opening_balance"]),
            _format_amount(summary["total_deposits"]),
            _format_amount(summary["total_withdrawals"]),
            _format_amount(summary["closing_balance"]),
        ]

        result: list[TextElement] = []

        # Separate transaction-row elements from non-row elements
        row_elements: dict[int, list[TextElement]] = {}
        non_row_elements: list[TextElement] = []

        for te in template.text_elements:
            if te.row_index is not None:
                row_elements.setdefault(te.row_index, []).append(te)
            else:
                non_row_elements.append(te)

        # Handle non-row elements (structural + non-row data like names, addresses)
        for te in non_row_elements:
            new_te = te.model_copy()

            if te.element_type == ElementCategory.DATA_PLACEHOLDER:
                if te.data_type == DataType.NAME:
                    new_te.text = fake_data["name"]
                    name_count += 1
                elif te.data_type == DataType.ADDRESS:
                    if address_count == 0:
                        new_te.text = fake_data["address_street"]
                    else:
                        new_te.text = fake_data["address_city_state_zip"]
                    address_count += 1
                elif te.data_type == DataType.ACCOUNT_NUMBER:
                    new_te.text = fake_data["account_number"]
                    acct_count += 1
                elif te.data_type == DataType.PHONE:
                    new_te.text = fake_data["phone"]
                elif te.data_type == DataType.EMAIL:
                    new_te.text = fake_data["email"]
                elif te.data_type == DataType.AMOUNT:
                    # Non-row amount = summary amount
                    if summary_amount_idx < len(summary_amounts):
                        new_te.text = summary_amounts[summary_amount_idx]
                        summary_amount_idx += 1
                    else:
                        new_te.text = _format_amount(summary["closing_balance"])
                elif te.data_type == DataType.DATE:
                    # Non-row date — use statement period dates
                    if transactions:
                        new_te.text = _format_date_mmddyyyy(transactions[0].date)
                    else:
                        new_te.text = "{date}"
                elif te.data_type == DataType.REFERENCE:
                    import random as _rand
                    rng = _rand.Random(ref_count)
                    new_te.text = "".join(
                        rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                        for _ in range(16)
                    )
                    ref_count += 1

            result.append(new_te)

        # Handle transaction row elements
        original_rows = sorted(row_elements.keys())
        original_row_count = len(original_rows)
        target_count = min(target_tx_count, len(transactions))

        if original_row_count == 0:
            return result

        # Template row to use for expanding (use elements from row 0 as pattern)
        template_row_0 = row_elements.get(original_rows[0], [])
        row_height = template.transaction_row_height or 12.0
        base_y = template.transaction_area_start_y or (
            template_row_0[0].y if template_row_0 else 200
        )

        for new_row_idx in range(target_count):
            tx = transactions[new_row_idx] if new_row_idx < len(transactions) else transactions[-1]

            # Pick the template row to clone (cycle through original rows)
            source_row_idx = original_rows[new_row_idx % original_row_count]
            source_elements = row_elements.get(source_row_idx, [])

            # Calculate y-offset from source row to new position
            if source_elements:
                source_y = source_elements[0].y
            else:
                source_y = base_y + source_row_idx * row_height

            new_y = base_y + new_row_idx * row_height
            y_offset = new_y - source_y

            for te in source_elements:
                new_te = te.model_copy()
                new_te.y = round(te.y + y_offset, 2)
                new_te.row_index = new_row_idx

                if te.element_type == ElementCategory.DATA_PLACEHOLDER:
                    if te.data_type == DataType.DATE:
                        new_te.text = _format_date_mmddyyyy(tx.date)
                        # Try to match original format length
                        if te.width and te.width < 50:
                            new_te.text = _format_date_mmdd(tx.date)
                        elif te.width and te.width < 65:
                            new_te.text = _format_date_mmddyy(tx.date)
                    elif te.data_type == DataType.AMOUNT:
                        new_te.text = _format_amount(tx.amount)
                    elif te.data_type == DataType.DESCRIPTION:
                        desc = tx.description
                        # Truncate to fit original width roughly
                        if te.width and te.font_size > 0:
                            approx_chars = int(te.width / (te.font_size * 0.5))
                            if len(desc) > approx_chars:
                                desc = desc[:approx_chars - 3] + "..."
                        new_te.text = desc
                    elif te.data_type == DataType.REFERENCE:
                        import random as _rand
                        rng = _rand.Random(new_row_idx + 1000)
                        new_te.text = "".join(
                            rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                            for _ in range(16)
                        )

                result.append(new_te)

        # Shift elements below the transaction area
        if target_count != original_row_count and original_row_count > 0:
            y_shift = (target_count - original_row_count) * row_height
            last_original_y = base_y + original_row_count * row_height
            for te in result:
                if te.row_index is None and te.y > last_original_y:
                    te.y = round(te.y + y_shift, 2)

        return result

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_text(self, c: Canvas, te: TextElement, page_height: float) -> None:
        """Draw a text element on the canvas."""
        # Convert from pdfplumber top-down Y to reportlab bottom-up Y
        rl_y = page_height - te.y - te.font_size

        fname = _resolve_font(te.font_family, te.font_weight)
        fsize = max(te.font_size, _MIN_FONT_SIZE)
        color = _hex_to_color(te.color)

        c.setFont(fname, fsize)
        c.setFillColor(color)
        c.drawString(te.x, rl_y, te.text)

    def _draw_line(self, c: Canvas, line: LineElement, page_height: float) -> None:
        """Draw a line element."""
        rl_y0 = page_height - line.y0
        rl_y1 = page_height - line.y1

        c.setStrokeColor(_hex_to_color(line.stroke_color))
        c.setLineWidth(max(line.stroke_width, 0.1))
        c.line(line.x0, rl_y0, line.x1, rl_y1)

    def _draw_rect(self, c: Canvas, rect: RectElement, page_height: float) -> None:
        """Draw a rectangle element."""
        rl_y = page_height - rect.y1  # bottom-left in reportlab coords
        width = rect.x1 - rect.x0
        height = rect.y1 - rect.y0

        has_fill = rect.fill_color is not None
        has_stroke = rect.stroke_color is not None and rect.stroke_width > 0

        if has_fill:
            c.setFillColor(_hex_to_color(rect.fill_color))
        if has_stroke:
            c.setStrokeColor(_hex_to_color(rect.stroke_color))
            c.setLineWidth(rect.stroke_width)

        c.rect(
            rect.x0, rl_y, width, height,
            stroke=1 if has_stroke else 0,
            fill=1 if has_fill else 0,
        )

    def _draw_image_placeholder(self, c: Canvas, img: ImageElement, page_height: float) -> None:
        """Draw an image placeholder (gray box with 'LOGO' text)."""
        rl_y = page_height - img.y1
        width = img.x1 - img.x0
        height = img.y1 - img.y0

        c.setFillColor(HexColor("#CCCCCC"))
        c.rect(img.x0, rl_y, width, height, stroke=1, fill=1)
        c.setFillColor(HexColor("#666666"))
        c.setFont("Helvetica", min(10, height * 0.4))
        c.drawCentredString(
            img.x0 + width / 2,
            rl_y + height / 2 - 4,
            "LOGO",
        )

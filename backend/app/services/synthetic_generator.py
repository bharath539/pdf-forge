"""Generates synthetic PDF documents from learned format schemas.

Takes a format schema and generation parameters, then produces
realistic-looking PDF documents with fake but plausible data.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from app.models.generation import GenerationParams, Scenario
from app.models.schema import (
    FontRole,
    FontSpec,
    FormatSchema,
    Margins,
    PageLayout,
    Section,
    SectionType,
    TableColumn,
)
from app.services.data_faker import TransactionFaker, Transaction


# ---------------------------------------------------------------------------
# Font mapping: schema family names -> reportlab built-in font names
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


def _resolve_font(family: str, weight: str = "normal") -> str:
    """Map a schema font family + weight to a reportlab built-in font name."""
    key = family.lower().strip()
    normal, bold = _FONT_MAP.get(key, _DEFAULT_FONT)
    if weight == "bold":
        return bold
    return normal


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_date(d: date, fmt: str) -> str:
    """Apply a date format pattern.

    Supports common patterns:
      MM/DD/YYYY, MM-DD-YYYY, DD/MM/YYYY, YYYY-MM-DD,
      Mon DD, YYYY, etc.
    Falls back to strftime-style if the pattern contains '%'.
    """
    if not fmt:
        return d.strftime("%m/%d/%Y")

    if "%" in fmt:
        return d.strftime(fmt)

    result = fmt
    # Order matters — replace longer tokens first
    result = result.replace("YYYY", str(d.year))
    result = result.replace("YY", f"{d.year % 100:02d}")
    result = result.replace("MM", f"{d.month:02d}")
    result = result.replace("DD", f"{d.day:02d}")

    # Month abbreviation
    if "Mon" in result:
        result = result.replace("Mon", d.strftime("%b"))

    return result


def format_amount(amount: Decimal, fmt: str) -> str:
    """Apply an amount format pattern.

    Supported patterns:
      $#,##0.00  — US dollar with commas
      -$#,##0.00 — negative prefix
      (#,##0.00) — accounting style (parentheses for negatives)
      #,##0.00   — no currency symbol
    Falls back to simple two-decimal formatting.
    """
    abs_val = abs(amount)
    is_negative = amount < 0

    if not fmt:
        fmt = "$#,##0.00"

    # Determine if accounting style (parentheses)
    accounting = "(" in fmt and ")" in fmt

    # Determine currency symbol
    symbol = ""
    if "$" in fmt:
        symbol = "$"

    # Format the absolute value with commas and 2 decimals
    formatted = f"{abs_val:,.2f}"

    if accounting and is_negative:
        return f"({symbol}{formatted})"
    elif is_negative:
        return f"-{symbol}{formatted}"
    else:
        return f"{symbol}{formatted}"


def _hex_to_color(hex_str: str) -> Color:
    """Convert a hex color string to a reportlab Color."""
    if not hex_str:
        return HexColor("#000000")
    try:
        return HexColor(hex_str)
    except Exception:
        return HexColor("#000000")


def _draw_text(
    c: Canvas,
    x: float,
    y: float,
    text: str,
    font_spec: FontSpec | None = None,
    font_name: str = "Helvetica",
    font_size: float = 10,
    color: str = "#000000",
    alignment: str = "left",
) -> None:
    """Draw text on the canvas with the given font spec or explicit params."""
    if font_spec is not None:
        fname = _resolve_font(font_spec.family, font_spec.weight)
        fsize = font_spec.size
        fcolor = font_spec.color
    else:
        fname = font_name
        fsize = font_size
        fcolor = color

    c.setFont(fname, fsize)
    c.setFillColor(_hex_to_color(fcolor))

    if alignment == "right":
        c.drawRightString(x, y, text)
    elif alignment == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


# ---------------------------------------------------------------------------
# Default dimensions / fallbacks
# ---------------------------------------------------------------------------

_DEFAULT_PAGE_WIDTH = 612.0   # US Letter
_DEFAULT_PAGE_HEIGHT = 792.0
_DEFAULT_MARGINS = Margins(top=72, right=54, bottom=72, left=54)
_DEFAULT_ROW_HEIGHT = 14.0
_FOOTER_HEIGHT = 50.0


# ---------------------------------------------------------------------------
# SyntheticGenerator
# ---------------------------------------------------------------------------

class SyntheticGenerator:
    """Generates synthetic PDF documents from learned format schemas.

    Takes a format schema and generation parameters, then produces
    realistic-looking PDF documents with fake but plausible data.
    """

    def __init__(self) -> None:
        self._font_cache: dict[FontRole, FontSpec] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, schema: FormatSchema, params: GenerationParams) -> io.BytesIO:
        """Generate a complete synthetic PDF and return it as BytesIO.

        This is the main entry point. Handles single-month, multi-month,
        multi-page, and all other scenarios.
        """
        faker = TransactionFaker(seed=params.seed)
        buf = io.BytesIO()

        page = schema.page if schema.page else PageLayout(
            width=_DEFAULT_PAGE_WIDTH,
            height=_DEFAULT_PAGE_HEIGHT,
            margins=_DEFAULT_MARGINS,
        )
        margins = page.margins if page.margins else _DEFAULT_MARGINS

        c = Canvas(buf, pagesize=(page.width, page.height))

        # Build font lookup
        self._font_cache = {fs.role: fs for fs in (schema.fonts or [])}

        # Generate statement periods
        periods = faker.generate_statement_period(params.start_date, params.months)
        opening = Decimal(params.opening_balance)

        is_multi_month = (
            params.scenario == Scenario.MULTI_MONTH or params.months > 1
        )

        all_transactions = faker.generate_transactions(
            params, schema.description_patterns
        )

        if is_multi_month and len(periods) > 1:
            # Split transactions across months
            month_txns = self._split_transactions_by_month(all_transactions, periods)
            balance_carry = opening
            for i, (period_start, period_end) in enumerate(periods):
                txns = month_txns.get(i, [])
                summary = faker.generate_account_summary(balance_carry, txns)
                acct_number = faker.generate_account_number_masked()

                if i > 0:
                    c.showPage()

                self._render_statement(
                    c, schema, page, margins, faker,
                    txns, summary, acct_number,
                    period_start, period_end,
                    balance_carry,
                )

                if txns:
                    balance_carry = txns[-1].balance
        else:
            # Single period
            period_start, period_end = periods[0]
            summary = faker.generate_account_summary(opening, all_transactions)
            acct_number = faker.generate_account_number_masked()

            self._render_statement(
                c, schema, page, margins, faker,
                all_transactions, summary, acct_number,
                period_start, period_end,
                opening,
            )

        c.save()
        buf.seek(0)
        return buf

    def generate_preview(
        self, schema: FormatSchema, params: GenerationParams
    ) -> io.BytesIO:
        """Generate a first-page preview.

        For V1 this returns a single-page PDF in BytesIO.
        # TODO: Use pdf2image or similar to convert to PNG for true preview.
        """
        # Limit to a small number of transactions so only one page is produced
        preview_params = params.model_copy(
            update={
                "months": 1,
                "transactions_per_month": params.transactions_per_month.model_copy(
                    update={"min": 5, "max": 15}
                ),
            }
        )
        return self.generate(schema, preview_params)

    def generate_batch(
        self,
        schema: FormatSchema,
        scenarios: list[Scenario],
        start_date: date,
        seed: int | None = None,
    ) -> io.BytesIO:
        """Generate multiple PDFs (one per scenario) and return as a zip in BytesIO."""
        zip_buf = io.BytesIO()

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, scenario in enumerate(scenarios):
                scenario_seed = (seed + i) if seed is not None else None
                params = GenerationParams(
                    schema_id=schema.schema_version,  # placeholder; caller sets real ID
                    scenario=scenario,
                    start_date=start_date,
                    seed=scenario_seed,
                    months=3 if scenario == Scenario.MULTI_MONTH else 1,
                    opening_balance="5000.00",
                )
                pdf_bytes = self.generate(schema, params)
                filename = f"{schema.bank_name}_{scenario.value}_{i + 1}.pdf"
                # Sanitize filename
                filename = "".join(
                    ch if ch.isalnum() or ch in ("_", "-", ".") else "_"
                    for ch in filename
                )
                zf.writestr(filename, pdf_bytes.read())

        zip_buf.seek(0)
        return zip_buf

    # ------------------------------------------------------------------
    # Internal: full statement rendering
    # ------------------------------------------------------------------

    def _render_statement(
        self,
        c: Canvas,
        schema: FormatSchema,
        page: PageLayout,
        margins: Margins,
        faker: TransactionFaker,
        transactions: list[Transaction],
        summary: dict[str, Any],
        acct_number: str,
        period_start: date,
        period_end: date,
        opening_balance: Decimal,
    ) -> None:
        """Render a complete statement (possibly spanning multiple pages)."""
        page_width = page.width
        page_height = page.height
        page_break_rules = schema.page_break_rules

        # Organize sections by type for ordered rendering
        sections_by_type: dict[SectionType, Section] = {}
        ordered_sections: list[Section] = []
        for sec in (schema.sections or []):
            sections_by_type[sec.type] = sec
            ordered_sections.append(sec)

        # If no sections defined, use defaults
        if not ordered_sections:
            ordered_sections = self._default_sections()
            sections_by_type = {s.type: s for s in ordered_sections}

        # Detect date/amount formats from schema
        date_fmt = self._detect_date_format(sections_by_type.get(SectionType.TRANSACTION_TABLE))
        amount_fmt = self._detect_amount_format(sections_by_type.get(SectionType.TRANSACTION_TABLE))

        # Track current Y position (reportlab Y=0 is bottom)
        current_y = page_height - margins.top
        page_num = 1
        total_pages_estimate = max(1, self._estimate_total_pages(
            len(transactions), sections_by_type, page_height, margins,
        ))

        # --- Render header ---
        header_sec = sections_by_type.get(SectionType.HEADER)
        current_y = self._render_header(
            c, schema, header_sec, margins,
            page_width, page_height,
            period_start, period_end, current_y,
        )

        # --- Render account summary ---
        summary_sec = sections_by_type.get(SectionType.ACCOUNT_SUMMARY)
        current_y = self._render_account_summary(
            c, summary_sec, margins, summary,
            acct_number, current_y, date_fmt, amount_fmt,
            period_start, period_end,
        )

        # --- Render transaction table ---
        table_sec = sections_by_type.get(SectionType.TRANSACTION_TABLE)
        footer_sec = sections_by_type.get(SectionType.FOOTER)

        # Draw column headers
        current_y = self._render_table_headers(c, table_sec, margins, current_y)

        row_height = (table_sec.row_height if table_sec and table_sec.row_height
                      else _DEFAULT_ROW_HEIGHT)
        min_rows = page_break_rules.min_rows_before_break
        bottom_limit = margins.bottom + _FOOTER_HEIGHT

        for idx, tx in enumerate(transactions):
            # Check if we need a page break
            rows_remaining_space = (current_y - bottom_limit) / row_height
            if rows_remaining_space < 1 or (rows_remaining_space < min_rows and idx < len(transactions) - 1):
                # Draw footer on current page
                self._render_footer(
                    c, footer_sec, margins, page_width, page_height,
                    page_num, total_pages_estimate,
                )
                # Start new page
                c.showPage()
                page_num += 1
                current_y = page_height - margins.top

                # Continuation header
                if page_break_rules.continuation_header:
                    current_y = self._render_table_headers(c, table_sec, margins, current_y)

            # Draw alternating row background
            if (table_sec and table_sec.alternate_row_fill
                    and idx % 2 == 1):
                fill_color = _hex_to_color(table_sec.alternate_row_fill)
                c.setFillColor(fill_color)
                c.rect(
                    margins.left, current_y - row_height + 2,
                    page_width - margins.left - margins.right, row_height,
                    stroke=0, fill=1,
                )

            # Draw transaction row
            current_y = self._render_transaction_row(
                c, table_sec, margins, tx, current_y,
                row_height, date_fmt, amount_fmt,
            )

        # --- Render footer on last page ---
        self._render_footer(
            c, footer_sec, margins, page_width, page_height,
            page_num, total_pages_estimate,
        )

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_header(
        self,
        c: Canvas,
        schema: FormatSchema,
        header_sec: Section | None,
        margins: Margins,
        page_width: float,
        page_height: float,
        period_start: date,
        period_end: date,
        y: float,
    ) -> float:
        """Draw the header section: logo placeholder, bank name, statement period."""
        header_font = self._font_cache.get(FontRole.HEADER)
        subheader_font = self._font_cache.get(FontRole.SUBHEADER)

        # Logo placeholder — gray rectangle
        logo_x = margins.left
        logo_y = y - 40
        logo_w = 80
        logo_h = 36
        c.setFillColor(HexColor("#CCCCCC"))
        c.rect(logo_x, logo_y, logo_w, logo_h, stroke=1, fill=1)
        c.setFillColor(HexColor("#666666"))
        c.setFont("Helvetica", 10)
        c.drawCentredString(logo_x + logo_w / 2, logo_y + 14, "LOGO")

        # Bank name
        bank_name_x = logo_x + logo_w + 16
        bank_name_y = y - 16
        _draw_text(
            c, bank_name_x, bank_name_y, schema.bank_name,
            font_spec=header_font,
            font_name="Helvetica-Bold", font_size=16,
        )

        # Statement period
        period_text = (
            f"Statement Period: "
            f"{period_start.strftime('%B %d, %Y')} - "
            f"{period_end.strftime('%B %d, %Y')}"
        )
        _draw_text(
            c, bank_name_x, bank_name_y - 18, period_text,
            font_spec=subheader_font,
            font_name="Helvetica", font_size=10,
        )

        # Account type
        _draw_text(
            c, bank_name_x, bank_name_y - 32,
            f"{schema.account_type.value.replace('_', ' ').title()} Account",
            font_name="Helvetica", font_size=9, color="#555555",
        )

        # Horizontal rule under header
        rule_y = y - 52
        c.setStrokeColor(HexColor("#AAAAAA"))
        c.setLineWidth(0.5)
        c.line(margins.left, rule_y, page_width - margins.right, rule_y)

        return rule_y - 12

    def _render_account_summary(
        self,
        c: Canvas,
        summary_sec: Section | None,
        margins: Margins,
        summary: dict[str, Any],
        acct_number: str,
        y: float,
        date_fmt: str,
        amount_fmt: str,
        period_start: date,
        period_end: date,
    ) -> float:
        """Draw account summary label-value pairs."""
        body_font = self._font_cache.get(FontRole.BODY)
        line_height = 16

        # Default fields if section has none
        fields = []
        if summary_sec and summary_sec.fields:
            fields = summary_sec.fields
        else:
            # Built-in default fields
            from app.models.schema import SummaryField
            fields = [
                SummaryField(role="account_number_masked", label="Account Number:", format="text"),
                SummaryField(role="opening_balance", label="Opening Balance:", format="$#,##0.00"),
                SummaryField(role="closing_balance", label="Closing Balance:", format="$#,##0.00"),
                SummaryField(role="total_deposits", label="Total Deposits:", format="$#,##0.00"),
                SummaryField(role="total_withdrawals", label="Total Withdrawals:", format="$#,##0.00"),
                SummaryField(role="num_transactions", label="Number of Transactions:", format="integer"),
            ]

        # Map role names to values
        value_map: dict[str, str] = {
            "account_number_masked": acct_number,
            "opening_balance": format_amount(summary["opening_balance"], amount_fmt),
            "closing_balance": format_amount(summary["closing_balance"], amount_fmt),
            "total_deposits": format_amount(summary["total_deposits"], amount_fmt),
            "total_withdrawals": format_amount(summary["total_withdrawals"], amount_fmt),
            "num_transactions": str(summary["num_transactions"]),
            "statement_period": (
                f"{period_start.strftime('%m/%d/%Y')} - {period_end.strftime('%m/%d/%Y')}"
            ),
        }

        label_x = margins.left
        value_x = margins.left + 160

        for field in fields:
            # Label
            _draw_text(
                c, label_x, y, field.label,
                font_spec=body_font,
                font_name="Helvetica-Bold", font_size=9,
            )
            # Value
            val = value_map.get(field.role, "—")
            _draw_text(
                c, value_x, y, val,
                font_spec=body_font,
                font_name="Helvetica", font_size=9,
            )
            y -= line_height

        return y - 12

    def _render_table_headers(
        self,
        c: Canvas,
        table_sec: Section | None,
        margins: Margins,
        y: float,
    ) -> float:
        """Draw column header row for the transaction table."""
        th_font = self._font_cache.get(FontRole.TABLE_HEADER)

        columns = self._get_columns(table_sec, margins)

        for col in columns:
            _draw_text(
                c, col.x_start, y, col.header,
                font_spec=th_font,
                font_name="Helvetica-Bold", font_size=9,
                alignment=col.alignment,
            )

        # Header underline
        if table_sec and table_sec.header_underline:
            c.setStrokeColor(HexColor("#333333"))
            c.setLineWidth(0.5)
            underline_y = y - 4
            if columns:
                c.line(columns[0].x_start, underline_y,
                       columns[-1].x_end, underline_y)

        return y - 18

    def _render_transaction_row(
        self,
        c: Canvas,
        table_sec: Section | None,
        margins: Margins,
        tx: Transaction,
        y: float,
        row_height: float,
        date_fmt: str,
        amount_fmt: str,
    ) -> float:
        """Draw a single transaction row."""
        tb_font = self._font_cache.get(FontRole.TABLE_BODY)
        columns = self._get_columns(table_sec, margins)

        # We need at least date, description, amount, balance
        col_values = self._map_tx_to_columns(tx, columns, date_fmt, amount_fmt)

        for col, val in zip(columns, col_values):
            # Truncate if max_chars specified
            display_val = val
            if col.max_chars and len(val) > col.max_chars:
                display_val = val[: col.max_chars - 3] + "..."

            # Color negative amounts red
            text_color = "#000000"
            if col.format == "amount" and tx.amount < 0:
                text_color = "#CC0000"

            _draw_text(
                c, col.x_start if col.alignment != "right" else col.x_end,
                y, display_val,
                font_spec=tb_font,
                font_name="Helvetica", font_size=8,
                color=text_color,
                alignment=col.alignment,
            )

        return y - row_height

    def _render_footer(
        self,
        c: Canvas,
        footer_sec: Section | None,
        margins: Margins,
        page_width: float,
        page_height: float,
        page_num: int,
        total_pages: int,
    ) -> None:
        """Draw footer: page number and disclaimer."""
        footer_font = self._font_cache.get(FontRole.FOOTER)
        footer_y = margins.bottom

        # Page number — determine format from section or use default
        page_fmt = "Page {n} of {total}"
        if footer_sec and footer_sec.elements:
            for elem in footer_sec.elements:
                if elem.format and "{n}" in elem.format:
                    page_fmt = elem.format
                    break

        page_text = page_fmt.replace("{n}", str(page_num)).replace("{total}", str(total_pages))
        _draw_text(
            c, page_width - margins.right, footer_y, page_text,
            font_spec=footer_font,
            font_name="Helvetica", font_size=8, color="#888888",
            alignment="right",
        )

        # Disclaimer
        disclaimer = (
            "This is a synthetic bank statement generated for testing purposes. "
            "All data is fictitious."
        )
        _draw_text(
            c, margins.left, footer_y - 12, disclaimer,
            font_spec=footer_font,
            font_name="Helvetica", font_size=6, color="#AAAAAA",
        )

    # ------------------------------------------------------------------
    # Column / format helpers
    # ------------------------------------------------------------------

    def _get_columns(self, table_sec: Section | None, margins: Margins) -> list[TableColumn]:
        """Return columns from the section or sensible defaults."""
        if table_sec and table_sec.columns:
            return table_sec.columns

        # Default 4-column layout
        left = margins.left
        return [
            TableColumn(header="Date", x_start=left, x_end=left + 70,
                        format="date", alignment="left"),
            TableColumn(header="Description", x_start=left + 80, x_end=left + 340,
                        format="text", alignment="left", max_chars=50),
            TableColumn(header="Amount", x_start=left + 350, x_end=left + 430,
                        format="amount", alignment="right"),
            TableColumn(header="Balance", x_start=left + 440, x_end=left + 510,
                        format="amount", alignment="right"),
        ]

    def _map_tx_to_columns(
        self,
        tx: Transaction,
        columns: list[TableColumn],
        date_fmt: str,
        amount_fmt: str,
    ) -> list[str]:
        """Map a transaction to column string values based on column format types."""
        values: list[str] = []
        for col in columns:
            header_lower = col.header.lower()
            if col.format == "date" or "date" in header_lower:
                values.append(format_date(tx.date, date_fmt))
            elif col.format == "amount":
                if "balance" in header_lower:
                    values.append(format_amount(tx.balance, amount_fmt))
                else:
                    values.append(format_amount(tx.amount, amount_fmt))
            elif "description" in header_lower or "memo" in header_lower:
                values.append(tx.description)
            elif "balance" in header_lower:
                values.append(format_amount(tx.balance, amount_fmt))
            elif "amount" in header_lower or "debit" in header_lower or "credit" in header_lower:
                values.append(format_amount(tx.amount, amount_fmt))
            else:
                values.append(tx.description)
        return values

    def _detect_date_format(self, table_sec: Section | None) -> str:
        """Extract date format from the table section columns, or use default."""
        if table_sec and table_sec.columns:
            for col in table_sec.columns:
                if col.format and col.format not in ("date", "text", "amount"):
                    # Assume it's a date format pattern like MM/DD/YYYY
                    return col.format
        return "MM/DD/YYYY"

    def _detect_amount_format(self, table_sec: Section | None) -> str:
        """Extract amount format from the table section columns, or use default."""
        if table_sec and table_sec.columns:
            for col in table_sec.columns:
                if col.format == "amount" and col.header:
                    pass  # format is just "amount", not a pattern
                elif col.format and "$" in col.format:
                    return col.format
        return "$#,##0.00"

    def _estimate_total_pages(
        self,
        tx_count: int,
        sections_by_type: dict[SectionType, Section],
        page_height: float,
        margins: Margins,
    ) -> int:
        """Rough estimate of total pages for page number rendering."""
        # First page has header + summary, consuming ~150pt
        usable_first = page_height - margins.top - margins.bottom - _FOOTER_HEIGHT - 150
        # Subsequent pages have just continuation headers (~20pt)
        usable_subsequent = page_height - margins.top - margins.bottom - _FOOTER_HEIGHT - 20

        table_sec = sections_by_type.get(SectionType.TRANSACTION_TABLE)
        row_h = (table_sec.row_height if table_sec and table_sec.row_height
                 else _DEFAULT_ROW_HEIGHT)

        if tx_count == 0:
            return 1

        rows_first = max(1, int(usable_first / row_h))
        remaining = max(0, tx_count - rows_first)

        if remaining == 0:
            return 1

        rows_per_page = max(1, int(usable_subsequent / row_h))
        extra_pages = (remaining + rows_per_page - 1) // rows_per_page
        return 1 + extra_pages

    # ------------------------------------------------------------------
    # Multi-month helpers
    # ------------------------------------------------------------------

    def _split_transactions_by_month(
        self,
        transactions: list[Transaction],
        periods: list[tuple[date, date]],
    ) -> dict[int, list[Transaction]]:
        """Split a flat transaction list into buckets by period index."""
        result: dict[int, list[Transaction]] = {i: [] for i in range(len(periods))}

        for tx in transactions:
            for i, (ps, pe) in enumerate(periods):
                if ps <= tx.date <= pe:
                    result[i].append(tx)
                    break
            else:
                # Transaction date doesn't fall in any period — put in last
                result[len(periods) - 1].append(tx)

        return result

    # ------------------------------------------------------------------
    # Default section definitions (used when schema has no sections)
    # ------------------------------------------------------------------

    def _default_sections(self) -> list[Section]:
        """Return a minimal set of sections for schemas that don't define any."""
        return [
            Section(type=SectionType.HEADER, y_start=0),
            Section(type=SectionType.ACCOUNT_SUMMARY, y_start=100),
            Section(type=SectionType.TRANSACTION_TABLE, y_start=220, row_height=_DEFAULT_ROW_HEIGHT),
            Section(type=SectionType.FOOTER, y_start=-60),
        ]

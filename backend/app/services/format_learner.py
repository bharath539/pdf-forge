"""Format Learner — extracts structural format schemas from bank statement PDFs.

Parses a PDF in memory and produces a FormatSchema describing the layout,
fonts, sections, table structure, and patterns. Never stores actual data values.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from io import BytesIO
from typing import Any

import pdfplumber

from app.models.schema import (
    AccountType,
    BoundingBox,
    DescriptionPattern,
    ElementType,
    FontRole,
    FontSpec,
    FormatSchema,
    Margins,
    PageBreakRules,
    PageLayout,
    Section,
    SectionElement,
    SectionType,
    SummaryField,
    TableColumn,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for detecting data types in table cells
# ---------------------------------------------------------------------------
_DATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("MM/DD/YYYY", re.compile(r"^\d{2}/\d{2}/\d{4}$")),
    ("M/DD/YYYY", re.compile(r"^\d{1,2}/\d{2}/\d{4}$")),
    ("MM/DD/YY", re.compile(r"^\d{2}/\d{2}/\d{2}$")),
    ("MM/DD", re.compile(r"^\d{2}/\d{2}$")),
    ("M/D", re.compile(r"^\d{1,2}/\d{1,2}$")),
    ("DD Mon YYYY", re.compile(r"^\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}$")),
    ("Mon DD, YYYY", re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}$")),
    ("YYYY-MM-DD", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
]

_AMOUNT_RE = re.compile(
    r"^\s*[\(\-]?\s*[\$\€\£]?\s*[\-]?\s*"
    r"\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?"
    r"\s*[\)\-]?\s*$"
)

# Common description prefixes used by US banks
_DESC_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "debit_card",
        re.compile(
            r"^(DEBIT\s+CARD\s+PURCHASE\s*[-–—]\s*)(.+?)\s+([A-Za-z]{2,})\s+([A-Za-z]{2})$",
            re.IGNORECASE,
        ),
        "DEBIT CARD PURCHASE - {merchant} {city} {state}",
    ),
    (
        "debit_card",
        re.compile(r"^(POS\s+PURCHASE\s*[-–—]\s*)(.+)", re.IGNORECASE),
        "POS PURCHASE - {merchant}",
    ),
    (
        "ach",
        re.compile(r"^(ACH\s+)(CREDIT|DEBIT)\s+(.+)", re.IGNORECASE),
        "ACH {direction} {originator}",
    ),
    (
        "check",
        re.compile(r"^(CHECK\s*#?\s*)(\d+)", re.IGNORECASE),
        "CHECK #{number}",
    ),
    (
        "transfer",
        re.compile(r"^(ONLINE\s+TRANSFER\s+)(TO|FROM)\s+(.+)", re.IGNORECASE),
        "ONLINE TRANSFER {direction} {account_ref}",
    ),
    (
        "transfer",
        re.compile(r"^(WIRE\s+TRANSFER\s*[-–—]?\s*)(.+)", re.IGNORECASE),
        "WIRE TRANSFER - {details}",
    ),
    (
        "atm",
        re.compile(r"^(ATM\s+)(WITHDRAWAL|DEPOSIT)\s*[-–—]?\s*(.*)", re.IGNORECASE),
        "ATM {action} - {location}",
    ),
    (
        "direct_deposit",
        re.compile(r"^(DIRECT\s+DEP(?:OSIT)?\s*)(.+)", re.IGNORECASE),
        "DIRECT DEPOSIT {originator}",
    ),
    (
        "fee",
        re.compile(r"^((?:MONTHLY\s+)?(?:SERVICE\s+)?FEE)", re.IGNORECASE),
        "{fee_type} FEE",
    ),
    (
        "zelle",
        re.compile(
            r"^(Zelle\s+(?:Payment|Transfer)\s+(?:To|From))\s+(.+?)(?:\s+(\d+))?\s*$",
            re.IGNORECASE,
        ),
        "Zelle {direction} {name} {ref}",
    ),
    (
        "payroll",
        re.compile(r"^(.+?),?\s+Payroll\s+PPD\s+ID:\s*(\S+)", re.IGNORECASE),
        "{originator}, Payroll PPD ID: {id}",
    ),
    (
        "autopay",
        re.compile(
            r"^(.+?)\s+(?:Credit\s+Crd|Credit\s+Card)\s+Autopay\s+PPD\s+ID:\s*(\S+)",
            re.IGNORECASE,
        ),
        "{originator} Credit Crd Autopay PPD ID: {id}",
    ),
    (
        "web_payment",
        re.compile(r"^(.+?)\s+Web\s+ID:\s*(\S+)", re.IGNORECASE),
        "{originator} Web ID: {id}",
    ),
    (
        "ppd",
        re.compile(r"^(.+?)\s+PPD\s+ID:\s*(\S+)", re.IGNORECASE),
        "{originator} PPD ID: {id}",
    ),
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _hex_color(color: Any) -> str:
    """Convert a pdfplumber color value to a hex string."""
    if color is None:
        return "#000000"
    if isinstance(color, (list, tuple)):
        # RGB tuple (0-1 range)
        if len(color) >= 3:
            r, g, b = (int(min(max(c, 0), 1) * 255) for c in color[:3])
            return f"#{r:02x}{g:02x}{b:02x}"
        if len(color) == 1:
            # grayscale
            v = int(min(max(color[0], 0), 1) * 255)
            return f"#{v:02x}{v:02x}{v:02x}"
    return "#000000"


def _font_weight(fontname: str) -> str:
    """Infer font weight from the font name string."""
    lower = fontname.lower()
    if "bold" in lower:
        return "bold"
    if "light" in lower or "thin" in lower:
        return "light"
    if "italic" in lower or "oblique" in lower:
        return "normal"  # italic is style, not weight
    return "normal"


_KNOWN_BANK_NAMES = {
    "chase", "jpmorgan chase", "jp morgan", "bank of america",
    "wells fargo", "citibank", "citi", "capital one", "us bank",
    "u.s. bank", "pnc", "truist", "td bank", "ally", "discover",
    "american express", "amex", "usaa", "navy federal",
    "schwab", "charles schwab", "fidelity", "goldman sachs",
    "marcus", "sofi", "chime", "huntington", "regions", "fifth third",
    "citizens", "key bank", "m&t bank", "synchrony", "barclays",
}

_DATE_LINE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|\d{1,2}/\d{1,2}/\d{2,4}|through|thru)",
    re.IGNORECASE,
)

_ADDRESS_LINE_RE = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|"
    r"MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|"
    r"TN|TX|UT|VT|VA|WA|WV|WI|WY)\s+\d{5}",
)

_KNOWN_FONT_FAMILIES = {
    "helvetica", "arial", "courier", "times", "times new roman",
    "times-roman", "verdana", "georgia", "tahoma", "calibri",
    "cambria", "garamond", "palatino", "century", "bookman",
    "futura", "optima", "gill sans", "avenir", "roboto", "open sans",
    "lato", "source sans", "noto sans", "inter",
}


def _font_family(fontname: str) -> str:
    """Extract a clean font family name.

    Maps proprietary/encoded font names to known families or 'Helvetica' fallback.
    """
    # Strip common suffixes added by PDF encoders
    name = fontname
    for suffix in [
        "-Bold", "-Italic", "-BoldItalic", "-Light",
        ",Bold", ",Italic", ",BoldItalic",
        "-Regular", ",Regular", "-Roman",
    ]:
        name = name.replace(suffix, "")
    # Strip subset prefix like ABCDEF+
    if "+" in name:
        name = name.split("+", 1)[1]

    if not name:
        return "Helvetica"

    # Check if the extracted name matches a known font family
    name_lower = name.lower().strip()
    if name_lower in _KNOWN_FONT_FAMILIES:
        return name

    # Check if name contains a known family as a substring
    for known in _KNOWN_FONT_FAMILIES:
        if known in name_lower:
            return known.title()

    # Proprietary/encoded font — fall back to Helvetica
    return "Helvetica"


def _detect_date_format(values: list[str]) -> str | None:
    """Given sampled cell values, return the date format if most match."""
    for fmt_name, pattern in _DATE_PATTERNS:
        matches = sum(1 for v in values if pattern.match(v.strip()))
        if matches >= len(values) * 0.5 and matches >= 2:
            return fmt_name
    return None


def _is_amount(value: str) -> bool:
    return bool(_AMOUNT_RE.match(value.strip()))


def _detect_amount_format(values: list[str]) -> dict[str, Any]:
    """Detect currency symbol, separators, decimal places, debit notation."""
    info: dict[str, Any] = {
        "currency_symbol": "$",
        "thousands_separator": ",",
        "decimal_places": 2,
        "debit_notation": "negative",
    }
    has_parens = False
    has_trailing_minus = False
    has_leading_minus = False
    symbols: Counter[str] = Counter()

    for raw in values:
        v = raw.strip()
        if not v:
            continue
        for ch in ("$", "€", "£", "¥"):
            if ch in v:
                symbols[ch] += 1
        if v.startswith("(") and v.endswith(")"):
            has_parens = True
        if v.endswith("-") or v.endswith("–"):
            has_trailing_minus = True
        if v.startswith("-"):
            has_leading_minus = True

    if symbols:
        info["currency_symbol"] = symbols.most_common(1)[0][0]
    if has_parens:
        info["debit_notation"] = "parentheses"
    elif has_trailing_minus:
        info["debit_notation"] = "trailing_minus"
    elif has_leading_minus:
        info["debit_notation"] = "negative"

    return info


# ---------------------------------------------------------------------------
# FormatLearner
# ---------------------------------------------------------------------------

_MIN_FONT_SIZE = 4.0  # Ignore fonts below this size (often invisible form fields)


class FormatLearner:
    """Analyzes uploaded PDF files to extract structural patterns.

    Responsible for identifying layout elements (headers, tables, footers),
    font usage, spacing, and repeating patterns that define a PDF format.
    All processing happens in-memory via BytesIO -- never writes to disk.
    """

    def learn(self, pdf_bytes: BytesIO) -> FormatSchema:
        """Parse a bank statement PDF and return its structural format schema.

        Args:
            pdf_bytes: In-memory PDF file.

        Returns:
            A complete FormatSchema describing the PDF's structure and patterns.
        """
        logger.info("Starting format learning from PDF bytes (%d bytes)", pdf_bytes.getbuffer().nbytes)

        with pdfplumber.open(pdf_bytes) as pdf:
            pages = pdf.pages
            if not pages:
                raise ValueError("PDF has no pages")

            first_page = pages[0]

            # --- Step 1: Page Layout ---
            page_layout = self._extract_page_layout(first_page)
            logger.info("Page layout: %.0fx%.0f", page_layout.width, page_layout.height)

            # --- Step 2: Font Analysis ---
            fonts = self._extract_fonts(pages, page_layout.height)
            logger.info("Detected %d font roles", len(fonts))

            # --- Step 3: Section Detection ---
            sections = self._detect_sections(pages, page_layout, fonts)
            logger.info("Detected %d sections", len(sections))

            # --- Step 4: Transaction Table Analysis ---
            table_section, table_values = self._analyze_transaction_table(
                pages, page_layout, fonts, sections
            )
            if table_section:
                # Replace or insert the transaction_table section
                sections = [
                    s for s in sections if s.type != SectionType.TRANSACTION_TABLE
                ]
                sections.append(table_section)
                sections.sort(key=lambda s: abs(s.y_start))
            logger.info("Transaction table analysis complete")

            # --- Step 5: Pattern Detection ---
            description_patterns = self._detect_description_patterns(table_values)
            logger.info("Detected %d description patterns", len(description_patterns))

            # --- Step 6: Page Break Rules ---
            page_break_rules = self._detect_page_break_rules(pages, table_section)
            logger.info("Page break rules: %s", page_break_rules)

            # --- Step 7: Assemble ---
            bank_name = self._detect_bank_name(first_page, page_layout)
            account_type = self._infer_account_type(table_section, bank_name, sections)

        schema = FormatSchema(
            schema_version="1.0",
            bank_name=bank_name,
            account_type=account_type,
            display_name=f"{bank_name} {account_type.value.replace('_', ' ').title()}",
            page=page_layout,
            fonts=fonts,
            sections=sections,
            page_break_rules=page_break_rules,
            description_patterns=description_patterns,
        )
        logger.info("Format schema assembled for '%s'", schema.display_name)
        return schema

    # ------------------------------------------------------------------
    # Step 1: Page Layout Extraction
    # ------------------------------------------------------------------

    def _extract_page_layout(self, page: pdfplumber.page.Page) -> PageLayout:
        """Extract page dimensions and margins from text/line bounding boxes."""
        width = float(page.width)
        height = float(page.height)

        # Find bounding box of all content
        chars = page.chars or []
        lines = page.lines or []
        rects = page.rects or []

        all_x0: list[float] = []
        all_y0: list[float] = []
        all_x1: list[float] = []
        all_y1: list[float] = []

        for c in chars:
            all_x0.append(float(c["x0"]))
            all_y0.append(float(c["top"]))
            all_x1.append(float(c["x1"]))
            all_y1.append(float(c["bottom"]))

        for obj in lines + rects:
            all_x0.append(float(obj["x0"]))
            all_y0.append(float(obj["top"]))
            all_x1.append(float(obj["x1"]))
            all_y1.append(float(obj["bottom"]))

        if all_x0:
            left_margin = max(min(all_x0), 0)
            top_margin = max(min(all_y0), 0)
            right_margin = max(width - max(all_x1), 0)
            bottom_margin = max(height - max(all_y1), 0)
        else:
            # Fallback: standard margins (1 inch = 72 pt)
            left_margin = top_margin = right_margin = bottom_margin = 72.0

        margins = Margins(
            top=round(top_margin, 1),
            right=round(right_margin, 1),
            bottom=round(bottom_margin, 1),
            left=round(left_margin, 1),
        )
        return PageLayout(width=width, height=height, margins=margins)

    # ------------------------------------------------------------------
    # Step 2: Font Analysis
    # ------------------------------------------------------------------

    def _extract_fonts(
        self, pages: list[pdfplumber.page.Page], page_height: float
    ) -> list[FontSpec]:
        """Collect unique font specs and classify them by role."""
        # font_key -> { family, size, weight, color, count, positions }
        font_map: dict[tuple[str, float, str], dict[str, Any]] = {}

        for page in pages:
            for char in page.chars or []:
                fontname = char.get("fontname", "Unknown")
                size = round(float(char.get("size", 10)), 1)
                weight = _font_weight(fontname)
                family = _font_family(fontname)
                color = _hex_color(char.get("non_stroking_color"))

                key = (family, size, weight)
                if key not in font_map:
                    font_map[key] = {
                        "family": family,
                        "size": size,
                        "weight": weight,
                        "color": color,
                        "count": 0,
                        "y_positions": [],
                    }
                font_map[key]["count"] += 1
                font_map[key]["y_positions"].append(float(char.get("top", 0)))

        # Filter out invisible/tiny fonts (e.g., form fields, hidden chars)
        readable_font_map = {
            k: v for k, v in font_map.items() if v["size"] >= _MIN_FONT_SIZE
        }
        if not readable_font_map:
            # Fall back to all fonts if filtering removed everything
            readable_font_map = font_map

        if not readable_font_map:
            logger.warning("No fonts detected; returning minimal defaults")
            return [
                FontSpec(role=FontRole.BODY, family="Helvetica", size=10, weight="normal"),
            ]

        # Sort by size descending
        sorted_fonts = sorted(readable_font_map.values(), key=lambda f: f["size"], reverse=True)

        # Find most common font (by char count)
        most_common = max(readable_font_map.values(), key=lambda f: f["count"])

        # Classify roles
        assigned_roles: dict[FontRole, dict[str, Any]] = {}

        # Header = largest font
        if sorted_fonts:
            assigned_roles[FontRole.HEADER] = sorted_fonts[0]

        # Subheader = second largest (if different from header)
        if len(sorted_fonts) >= 2 and sorted_fonts[1]["size"] != sorted_fonts[0]["size"]:
            assigned_roles[FontRole.SUBHEADER] = sorted_fonts[1]

        # Body = most common
        assigned_roles[FontRole.BODY] = most_common

        # Footer = smallest font appearing in bottom 15% of page
        footer_threshold = page_height * 0.85
        footer_candidates = [
            f for f in readable_font_map.values()
            if any(y > footer_threshold for y in f["y_positions"])
        ]
        if footer_candidates:
            assigned_roles[FontRole.FOOTER] = min(footer_candidates, key=lambda f: f["size"])

        # Table header and body detection deferred to section analysis
        # For now, use heuristics based on body font
        # Table body is typically same as body or slightly smaller
        assigned_roles.setdefault(FontRole.TABLE_BODY, most_common)
        # Table header is often bold version of body size or slightly larger
        bold_body_candidates = [
            f for f in readable_font_map.values()
            if f["weight"] == "bold"
            and abs(f["size"] - most_common["size"]) <= 2
        ]
        if bold_body_candidates:
            assigned_roles[FontRole.TABLE_HEADER] = bold_body_candidates[0]
        else:
            assigned_roles.setdefault(FontRole.TABLE_HEADER, most_common)

        result: list[FontSpec] = []
        for role, fdata in assigned_roles.items():
            result.append(FontSpec(
                role=role,
                family=fdata["family"],
                size=fdata["size"],
                weight=fdata["weight"],
                color=fdata.get("color", "#000000"),
            ))

        return result

    # ------------------------------------------------------------------
    # Step 3: Section Detection
    # ------------------------------------------------------------------

    def _detect_sections(
        self,
        pages: list[pdfplumber.page.Page],
        layout: PageLayout,
        fonts: list[FontSpec],
    ) -> list[Section]:
        """Detect major sections of the bank statement on the first page."""
        sections: list[Section] = []
        page = pages[0]
        page_h = layout.height
        chars = page.chars or []
        lines = page.lines or []
        images = page.images or []

        if not chars:
            logger.warning("No characters on first page; section detection skipped")
            return sections

        # Group characters into text lines by y-position (cluster by top)
        line_groups = self._cluster_text_lines(chars)

        # Detect horizontal rules
        h_rules = [
            float(ln["top"])
            for ln in lines
            if abs(float(ln["top"]) - float(ln["bottom"])) < 3
            and (float(ln["x1"]) - float(ln["x0"])) > layout.width * 0.3
        ]
        h_rules.sort()

        # --- Header section ---
        try:
            header_y_end = layout.margins.top + page_h * 0.12
            # Extend if a rule exists nearby
            for ry in h_rules:
                if layout.margins.top < ry < page_h * 0.25:
                    header_y_end = ry
                    break

            header_elements: list[SectionElement] = []

            # Logo placeholder from images in top area
            for img in images:
                img_top = float(img.get("top", 0))
                if img_top < header_y_end:
                    header_elements.append(SectionElement(
                        type=ElementType.LOGO_PLACEHOLDER,
                        bbox=BoundingBox(
                            x0=float(img["x0"]),
                            y0=float(img["top"]),
                            x1=float(img["x1"]),
                            y1=float(img["bottom"]),
                        ),
                    ))

            # Text fields in header
            for y_pos, line_chars in sorted(line_groups.items()):
                if y_pos < header_y_end:
                    avg_size = sum(float(c.get("size", 10)) for c in line_chars) / len(line_chars)
                    header_font = self._font_role_for_size(fonts, avg_size)
                    xs = [float(c["x0"]) for c in line_chars]
                    xe = [float(c["x1"]) for c in line_chars]
                    header_elements.append(SectionElement(
                        type=ElementType.TEXT_FIELD,
                        role="bank_name" if avg_size >= self._header_font_size(fonts) else "statement_info",
                        bbox=BoundingBox(
                            x0=min(xs), y0=y_pos,
                            x1=max(xe), y1=y_pos + avg_size,
                        ),
                        font_ref=header_font,
                    ))

            sections.append(Section(
                type=SectionType.HEADER,
                y_start=round(layout.margins.top, 1),
                y_end=round(header_y_end, 1),
                elements=header_elements if header_elements else None,
            ))
        except Exception:
            logger.exception("Error detecting header section")

        # --- Footer section ---
        try:
            footer_y_start = page_h - layout.margins.bottom - page_h * 0.08
            footer_elements: list[SectionElement] = []

            for y_pos, line_chars in sorted(line_groups.items()):
                if y_pos > footer_y_start:
                    text = "".join(c.get("text", "") for c in sorted(line_chars, key=lambda c: float(c["x0"])))
                    role = "page_number" if re.search(r"page\s+\d+", text, re.IGNORECASE) else "disclaimer"
                    fmt = None
                    if role == "page_number":
                        if re.search(r"page\s+\d+\s+of\s+\d+", text, re.IGNORECASE):
                            fmt = "Page {n} of {total}"
                        else:
                            fmt = "Page {n}"
                    footer_elements.append(SectionElement(
                        type=ElementType.TEXT_FIELD,
                        role=role,
                        format=fmt,
                    ))

            sections.append(Section(
                type=SectionType.FOOTER,
                y_start=round(-(page_h - footer_y_start), 1),
                elements=footer_elements if footer_elements else None,
            ))
        except Exception:
            logger.exception("Error detecting footer section")

        # --- Account Summary (area between header and table/mid-page) ---
        try:
            header_end = sections[0].y_end if sections and sections[0].y_end else layout.margins.top + 80
            summary_y_start = header_end
            summary_y_end = header_end + page_h * 0.25

            # Known financial summary roles — only keep fields matching these
            _KNOWN_SUMMARY_ROLES = {
                "opening_balance", "closing_balance", "account_number_masked",
                "statement_period", "payment_due_date", "minimum_payment",
                "credit_limit", "total_deposits", "total_withdrawals",
                "new_balance", "previous_balance", "available_credit",
                "purchases", "cash_advances", "fees", "interest_charged",
            }

            # Look for label-value pairs (two text clusters on the same line)
            summary_fields: list[SummaryField] = []
            for y_pos, line_chars in sorted(line_groups.items()):
                if summary_y_start <= y_pos <= summary_y_end:
                    sorted_chars = sorted(line_chars, key=lambda c: float(c["x0"]))
                    words = self._chars_to_words(sorted_chars)
                    full_text = " ".join(w["text"] for w in words)

                    # Skip form markers and hidden fields
                    if full_text.startswith("*") or full_text.startswith("_"):
                        continue

                    # Method 1: Colon-separated key-value
                    if ":" in full_text:
                        parts = full_text.split(":", 1)
                        label = parts[0].strip()
                        role = self._classify_summary_role(label)
                        fmt = self._infer_summary_format(role)
                        if role and label:
                            summary_fields.append(SummaryField(
                                role=role, label=label, format=fmt
                            ))
                        continue

                    # Method 2: Large x-gap between word groups (>50pt)
                    if len(words) >= 2:
                        max_gap = 0.0
                        split_idx = -1
                        for wi in range(len(words) - 1):
                            gap = words[wi + 1]["x0"] - words[wi]["x1"]
                            if gap > max_gap:
                                max_gap = gap
                                split_idx = wi
                        if max_gap > 50 and split_idx >= 0:
                            label = " ".join(w["text"] for w in words[:split_idx + 1]).strip()
                            role = self._classify_summary_role(label)
                            fmt = self._infer_summary_format(role)
                            if role and label and len(label) > 2:
                                summary_fields.append(SummaryField(
                                    role=role, label=label, format=fmt
                                ))

            # Filter: only keep fields with recognized financial roles
            summary_fields = [
                f for f in summary_fields
                if f.role in _KNOWN_SUMMARY_ROLES
            ]

            if summary_fields:
                sections.append(Section(
                    type=SectionType.ACCOUNT_SUMMARY,
                    y_start=round(summary_y_start, 1),
                    y_end=round(summary_y_end, 1),
                    fields=summary_fields,
                ))
        except Exception:
            logger.exception("Error detecting account summary section")

        # Placeholder for transaction_table -- filled in step 4
        sections.append(Section(
            type=SectionType.TRANSACTION_TABLE,
            y_start=round(layout.height * 0.3, 1),
        ))

        sections.sort(key=lambda s: abs(s.y_start))
        return sections

    # ------------------------------------------------------------------
    # Step 4: Transaction Table Analysis
    # ------------------------------------------------------------------

    def _analyze_transaction_table(
        self,
        pages: list[pdfplumber.page.Page],
        layout: PageLayout,
        fonts: list[FontSpec],
        sections: list[Section],
    ) -> tuple[Section | None, dict[str, list[str]]]:
        """Find and analyze the main transaction table.

        Returns:
            A tuple of (Section for the table, dict mapping column header
            to sampled values for pattern detection).
        """
        table_values: dict[str, list[str]] = {}

        # Try pdfplumber's built-in table extraction first
        try:
            return self._analyze_table_via_pdfplumber(pages, layout, fonts, sections, table_values)
        except Exception:
            logger.info("pdfplumber table extraction failed; falling back to manual column detection")

        # Fallback: manual column detection via character x-positions
        try:
            return self._analyze_table_manually(pages, layout, fonts, sections, table_values)
        except Exception:
            logger.exception("Manual table analysis also failed")

        return None, table_values

    def _analyze_table_via_pdfplumber(
        self,
        pages: list[pdfplumber.page.Page],
        layout: PageLayout,
        fonts: list[FontSpec],
        sections: list[Section],
        table_values: dict[str, list[str]],
    ) -> tuple[Section | None, dict[str, list[str]]]:
        """Use pdfplumber.extract_table() to detect the transaction table."""
        for page_idx, page in enumerate(pages):
            tables = page.extract_tables()
            if not tables:
                continue

            # Use the largest table (most rows)
            table = max(tables, key=lambda t: len(t))
            if len(table) < 2:
                continue

            headers_row = table[0]
            if not headers_row or all(h is None for h in headers_row):
                continue

            # Filter out None/empty headers, tracking original indices
            valid_cols: list[tuple[int, str]] = []
            for i, h in enumerate(headers_row):
                text = str(h).strip() if h else ""
                if text:
                    valid_cols.append((i, text))

            if not valid_cols:
                continue

            headers = [vc[1] for vc in valid_cols]
            logger.info("Table headers detected via pdfplumber: %s", headers)

            # Find table bounding box using page.find_tables()
            found_tables = page.find_tables()
            if not found_tables:
                continue
            largest_ft = max(found_tables, key=lambda t: (t.bbox[3] - t.bbox[1]) * (t.bbox[2] - t.bbox[0]))
            bbox = largest_ft.bbox  # (x0, top, x1, bottom)

            # Build column boundaries from actual cell positions if available
            n_valid = len(valid_cols)
            table_width = bbox[2] - bbox[0]
            col_boundaries: list[tuple[float, float]] = []
            try:
                if largest_ft.cells:
                    # Extract unique x-boundaries from cells
                    all_x = sorted(set(cell[0] for cell in largest_ft.cells) | set(cell[2] for cell in largest_ft.cells))
                    if len(all_x) >= n_valid + 1:
                        for idx in range(min(n_valid, len(all_x) - 1)):
                            col_boundaries.append((round(all_x[idx], 1), round(all_x[idx + 1], 1)))
            except Exception:
                pass

            if len(col_boundaries) != n_valid:
                # Fallback: equal division
                col_w = table_width / max(n_valid, 1)
                col_boundaries = [
                    (round(bbox[0] + i * col_w, 1), round(bbox[0] + (i + 1) * col_w, 1))
                    for i in range(n_valid)
                ]

            columns: list[TableColumn] = []
            for idx, (orig_i, header) in enumerate(valid_cols):
                x_start, x_end = col_boundaries[idx]

                # Sample values using original column index
                col_vals = [
                    str(row[orig_i]).strip()
                    for row in table[1:]
                    if row and orig_i < len(row) and row[orig_i]
                ]
                # Store for pattern detection, then determine format
                table_values[header] = col_vals[:50]  # cap samples

                col_format = self._detect_column_format(header, col_vals)
                alignment = "right" if col_format in ("amount", "$#,##0.00") else "left"
                max_chars = max((len(v) for v in col_vals), default=20) if col_vals else None

                columns.append(TableColumn(
                    header=header,
                    x_start=x_start,
                    x_end=x_end,
                    format=col_format,
                    max_chars=max_chars if col_format == "text" else None,
                    alignment=alignment,
                ))

            # Post-validate: remove mostly-empty columns
            validated_columns: list[TableColumn] = []
            for col in columns:
                vals = table_values.get(col.header, [])
                if not vals:
                    validated_columns.append(col)
                    continue
                non_empty = sum(1 for v in vals if v.strip())
                if non_empty / len(vals) >= 0.2:
                    validated_columns.append(col)
                else:
                    logger.info("Dropping phantom column '%s' (%.0f%% empty)", col.header, (1 - non_empty / len(vals)) * 100)
                    table_values.pop(col.header, None)
            columns = validated_columns

            # Cap at 8 columns max for bank statements
            if len(columns) > 8:
                logger.warning("Table has %d columns; capping at 8", len(columns))
                columns = columns[:8]

            # Estimate row height
            data_rows = table[1:]
            row_height = round((bbox[3] - bbox[1]) / max(len(table), 1), 1)

            # Detect alternate row fill from rectangles
            alt_fill = self._detect_alternate_row_fill(page, bbox)

            # Detect header underline
            header_underline = self._detect_header_underline(page, bbox)

            section = Section(
                type=SectionType.TRANSACTION_TABLE,
                y_start=round(float(bbox[1]), 1),
                y_end=round(float(bbox[3]), 1),
                columns=columns,
                row_height=row_height,
                alternate_row_fill=alt_fill,
                header_underline=header_underline,
            )
            return section, table_values

        # No table found via pdfplumber
        raise ValueError("No tables found via pdfplumber")

    def _analyze_table_manually(
        self,
        pages: list[pdfplumber.page.Page],
        layout: PageLayout,
        fonts: list[FontSpec],
        sections: list[Section],
        table_values: dict[str, list[str]],
    ) -> tuple[Section | None, dict[str, list[str]]]:
        """Detect table columns by analyzing aligned character x-positions."""
        page = pages[0]
        chars = page.chars or []
        if not chars:
            return None, table_values

        page_h = layout.height

        # Focus on the middle portion of the page (skip header/footer)
        mid_chars = [
            c for c in chars
            if page_h * 0.2 < float(c["top"]) < page_h * 0.9
        ]
        if not mid_chars:
            return None, table_values

        # Cluster characters into text lines
        line_groups = self._cluster_text_lines(mid_chars)
        sorted_lines = sorted(line_groups.items())
        if len(sorted_lines) < 3:
            return None, table_values

        # Detect column boundaries by finding frequently occurring x0 positions
        x0_counter: Counter[int] = Counter()
        for _y, line_chars in sorted_lines:
            # For each line, find word-start positions
            words = self._chars_to_words(line_chars)
            for w in words:
                x0_counter[int(w["x0"])] += 1

        # Cluster nearby x0 values (within 5pt)
        col_starts = self._cluster_x_positions(x0_counter, tolerance=8)
        if len(col_starts) < 2:
            return None, table_values

        # The first row with text at most column positions is likely the header
        header_y = None
        header_texts: list[str] = []
        for y_pos, line_chars in sorted_lines:
            words = self._chars_to_words(line_chars)
            word_x0s = [int(w["x0"]) for w in words]
            # Check how many column starts are represented
            matched = sum(
                1 for cs in col_starts
                if any(abs(wx - cs) < 10 for wx in word_x0s)
            )
            if matched >= len(col_starts) * 0.6:
                header_y = y_pos
                header_texts = [w["text"] for w in sorted(words, key=lambda w: w["x0"])]
                break

        if header_y is None:
            return None, table_values

        # Refine column starts using only actual data rows (after header)
        # This filters out phantom x-positions from footer/disclaimer text
        data_x0_counter: Counter[int] = Counter()
        data_row_count = 0
        for y_pos, line_chars in sorted_lines:
            if y_pos <= header_y:
                continue
            data_row_count += 1
            words = self._chars_to_words(line_chars)
            for w in words:
                data_x0_counter[int(w["x0"])] += 1

        if data_row_count >= 3:
            # Re-cluster using only data row x-positions, require at least 30% of data rows
            refined_starts = self._cluster_x_positions(data_x0_counter, tolerance=8)
            min_count = max(3, int(data_row_count * 0.3))
            refined_starts = [
                x for x in refined_starts
                if sum(data_x0_counter[p] for p in range(x - 8, x + 9) if p in data_x0_counter) >= min_count
            ]
            if len(refined_starts) >= 2:
                col_starts = refined_starts

        # Build columns using detected x_starts
        col_starts_sorted = sorted(col_starts)

        # Cap at 8 columns
        if len(col_starts_sorted) > 8:
            col_starts_sorted = col_starts_sorted[:8]

        columns: list[TableColumn] = []
        for i, x_start in enumerate(col_starts_sorted):
            x_end = col_starts_sorted[i + 1] if i + 1 < len(col_starts_sorted) else layout.width - layout.margins.right
            # Find header text nearest this x_start
            header_text = ""
            if i < len(header_texts):
                header_text = header_texts[i]

            # Collect column values from data rows
            col_vals: list[str] = []
            for y_pos, line_chars in sorted_lines:
                if y_pos <= header_y:
                    continue
                words = self._chars_to_words(line_chars)
                for w in words:
                    if x_start - 5 <= w["x0"] <= x_start + (x_end - x_start) * 0.3:
                        col_vals.append(w["text"])
                        break
                if len(col_vals) >= 50:
                    break

            table_values[header_text] = col_vals
            col_format = self._detect_column_format(header_text, col_vals)
            alignment = "right" if col_format in ("amount", "$#,##0.00") else "left"
            max_chars = max((len(v) for v in col_vals), default=20) if col_vals else None

            columns.append(TableColumn(
                header=header_text,
                x_start=round(x_start, 1),
                x_end=round(x_end, 1),
                format=col_format,
                max_chars=max_chars if col_format == "text" else None,
                alignment=alignment,
            ))

        # Post-validate: remove mostly-empty columns
        validated_columns: list[TableColumn] = []
        for col in columns:
            vals = table_values.get(col.header, [])
            if not vals:
                continue  # No data = phantom
            non_empty = sum(1 for v in vals if v.strip())
            if non_empty / max(len(vals), 1) >= 0.2:
                validated_columns.append(col)
            else:
                logger.info("Dropping phantom column '%s' (%.0f%% empty)", col.header, (1 - non_empty / max(len(vals), 1)) * 100)
                table_values.pop(col.header, None)
        columns = validated_columns if validated_columns else columns

        # Estimate row height from line spacing
        data_ys = [y for y, _ in sorted_lines if y > header_y]
        if len(data_ys) >= 2:
            gaps = [data_ys[i + 1] - data_ys[i] for i in range(len(data_ys) - 1)]
            row_height = round(sum(gaps) / len(gaps), 1)
        else:
            row_height = 14.0

        section = Section(
            type=SectionType.TRANSACTION_TABLE,
            y_start=round(header_y, 1),
            columns=columns,
            row_height=row_height,
            header_underline=self._detect_header_underline(page, None),
        )
        return section, table_values

    # ------------------------------------------------------------------
    # Step 5: Pattern Detection
    # ------------------------------------------------------------------

    def _detect_description_patterns(
        self, table_values: dict[str, list[str]]
    ) -> list[DescriptionPattern]:
        """Analyze description column values and extract structural patterns."""
        patterns: list[DescriptionPattern] = []
        seen_categories: set[str] = set()

        # Find the description column (usually named Description, Details, etc.)
        desc_keywords = ("description", "details", "transaction", "memo", "payee", "narrative", "reference")
        desc_values: list[str] = []
        for header, vals in table_values.items():
            if any(kw in header.lower() for kw in desc_keywords):
                desc_values = vals
                break
        if not desc_values:
            # Fallback: use the column with the longest average string
            longest_col = max(
                table_values.items(),
                key=lambda kv: (sum(len(v) for v in kv[1]) / max(len(kv[1]), 1)),
                default=("", []),
            )
            desc_values = longest_col[1]

        for _category, regex, pattern_template in _DESC_PATTERNS:
            for val in desc_values:
                if regex.search(val.strip()):
                    if _category not in seen_categories:
                        patterns.append(DescriptionPattern(
                            category=_category,
                            pattern=pattern_template,
                        ))
                        seen_categories.add(_category)
                    break  # one match per pattern is enough

        # If no known patterns matched, try to infer a generic pattern from
        # common prefixes
        if not patterns and desc_values:
            prefix_counter: Counter[str] = Counter()
            for val in desc_values:
                words = val.strip().split()
                if len(words) >= 2:
                    prefix = " ".join(words[:2]).upper()
                    if len(prefix) >= 5:
                        prefix_counter[prefix] += 1
            for prefix, count in prefix_counter.most_common(5):
                if count >= 2:
                    patterns.append(DescriptionPattern(
                        category="general",
                        pattern=f"{prefix} {{details}}",
                    ))

        return patterns

    # ------------------------------------------------------------------
    # Step 6: Page Break Rules
    # ------------------------------------------------------------------

    def _detect_page_break_rules(
        self,
        pages: list[pdfplumber.page.Page],
        table_section: Section | None,
    ) -> PageBreakRules:
        """Detect page break behavior from multi-page PDFs."""
        rules = PageBreakRules(
            min_rows_before_break=3,
            continuation_header=True,
            orphan_control=True,
        )

        if len(pages) < 2 or not table_section or not table_section.columns:
            return rules

        # Check if column headers repeat on page 2
        try:
            expected_headers = [c.header.lower() for c in table_section.columns]
            page2 = pages[1]
            tables = page2.extract_tables()
            if tables:
                for t in tables:
                    if t and t[0]:
                        row_texts = [
                            str(cell).strip().lower() for cell in t[0] if cell
                        ]
                        matches = sum(
                            1 for h in expected_headers if h in row_texts
                        )
                        if matches >= len(expected_headers) * 0.5:
                            rules.continuation_header = True
                            break
                else:
                    rules.continuation_header = False
        except Exception:
            logger.debug("Could not determine continuation_header; defaulting to True")

        # Estimate min_rows_before_break by checking how many rows appear
        # on the last table segment of page 1
        try:
            page1_tables = pages[0].extract_tables()
            if page1_tables:
                largest = max(page1_tables, key=len)
                data_rows = len(largest) - 1  # minus header
                # If the table ends near the bottom and has at least 3 rows,
                # min_rows_before_break is capped at 3
                rules.min_rows_before_break = min(data_rows, 3) if data_rows > 0 else 3
        except Exception:
            pass

        return rules

    # ------------------------------------------------------------------
    # Step 7 helpers: bank name and account type inference
    # ------------------------------------------------------------------

    def _detect_bank_name(
        self, page: pdfplumber.page.Page, layout: PageLayout
    ) -> str:
        """Try to extract the bank name from the header area of the first page."""
        chars = page.chars or []
        if not chars:
            return "Detected Bank"

        # Look at text in the top 12% of the page with the largest font
        header_chars = [
            c for c in chars
            if float(c["top"]) < layout.height * 0.12
        ]
        if not header_chars:
            header_chars = [
                c for c in chars
                if float(c["top"]) < layout.height * 0.2
            ]

        if not header_chars:
            return "Detected Bank"

        # Group by lines, build candidates sorted by font size descending
        line_groups = self._cluster_text_lines(header_chars)
        candidates: list[tuple[float, str]] = []

        for _y, line_chars in line_groups.items():
            avg_size = sum(float(c.get("size", 0)) for c in line_chars) / len(line_chars)
            words = self._chars_to_words(sorted(line_chars, key=lambda c: float(c["x0"])))
            text = " ".join(w["text"] for w in words).strip()
            candidates.append((avg_size, text))

        candidates.sort(key=lambda t: t[0], reverse=True)

        for _size, text in candidates:
            if not text or len(text) < 2:
                continue
            # Skip lines that are clearly dates or addresses
            if _DATE_LINE_RE.search(text):
                continue
            if _ADDRESS_LINE_RE.search(text):
                continue
            # Skip lines that look like account numbers or PII
            if re.search(r"\d{6,}", text):
                continue

            name = text[:40].strip()
            # Remove trailing numbers/dates
            name = re.sub(r"\s+\d[\d/\-\.]+\s*$", "", name).strip()

            if not name or len(name) < 2:
                continue

            return name

        return "Detected Bank"

    def _infer_account_type(
        self,
        table_section: Section | None,
        bank_name: str = "",
        sections: list[Section] | None = None,
    ) -> AccountType:
        """Infer account type from column structure, bank name, and summary fields."""
        # Check bank name for credit card indicators
        name_lower = bank_name.lower()
        credit_card_name_keywords = [
            "visa", "mastercard", "amex", "american express",
            "discover", "credit card", "card by",
        ]
        if any(kw in name_lower for kw in credit_card_name_keywords):
            return AccountType.CREDIT_CARD

        # Check summary field labels for credit card indicators
        if sections:
            for sec in sections:
                if sec.type == SectionType.ACCOUNT_SUMMARY and sec.fields:
                    all_labels = " ".join(f.label.lower() for f in sec.fields)
                    if any(kw in all_labels for kw in [
                        "minimum payment", "credit limit", "new balance",
                        "payment due", "previous balance", "cash advance",
                        "purchases", "new charges",
                    ]):
                        return AccountType.CREDIT_CARD

        # Check table column headers
        if table_section and table_section.columns:
            headers_lower = [c.header.lower() for c in table_section.columns]
            all_headers = " ".join(headers_lower)

            if any(kw in all_headers for kw in [
                "minimum payment", "credit limit", "new charges",
                "payment due", "previous balance", "new balance",
                "purchases", "cash advance",
            ]):
                return AccountType.CREDIT_CARD

            # Credit cards often lack a running "balance" column but have credits/debits
            has_balance = any("balance" in h for h in headers_lower)
            has_credit_debit = (
                any("credit" in h for h in headers_lower)
                and any("debit" in h for h in headers_lower)
            )
            if has_credit_debit and not has_balance:
                return AccountType.CREDIT_CARD

        # Savings vs checking is hard to distinguish from table alone
        return AccountType.CHECKING

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    def _cluster_text_lines(
        self, chars: list[dict[str, Any]], tolerance: float = 3.0
    ) -> dict[float, list[dict[str, Any]]]:
        """Group characters into lines based on their y-position (top)."""
        if not chars:
            return {}

        sorted_chars = sorted(chars, key=lambda c: float(c["top"]))
        groups: dict[float, list[dict[str, Any]]] = {}
        current_y: float | None = None

        for c in sorted_chars:
            y = float(c["top"])
            if current_y is None or abs(y - current_y) > tolerance:
                current_y = y
                groups[current_y] = []
            groups[current_y].append(c)

        return groups

    def _chars_to_words(
        self, chars: list[dict[str, Any]], gap: float = 4.0
    ) -> list[dict[str, Any]]:
        """Merge characters into words based on x-gaps."""
        if not chars:
            return []

        sorted_chars = sorted(chars, key=lambda c: float(c["x0"]))
        words: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for c in sorted_chars:
            x0 = float(c["x0"])
            if current is None or x0 - current["x1"] > gap:
                if current:
                    words.append(current)
                current = {
                    "text": c.get("text", ""),
                    "x0": x0,
                    "x1": float(c["x1"]),
                }
            else:
                current["text"] += c.get("text", "")
                current["x1"] = float(c["x1"])

        if current:
            words.append(current)
        return words

    def _cluster_x_positions(
        self, counter: Counter[int], tolerance: int = 8
    ) -> list[int]:
        """Cluster nearby x positions and return the representative value for each cluster."""
        if not counter:
            return []

        positions = sorted(counter.keys())
        clusters: list[list[int]] = [[positions[0]]]

        for pos in positions[1:]:
            if pos - clusters[-1][-1] <= tolerance:
                clusters[-1].append(pos)
            else:
                clusters.append([pos])

        # Return the most common position in each cluster (weighted by count)
        result: list[int] = []
        for cluster in clusters:
            # Weight by frequency
            best = max(cluster, key=lambda p: counter[p])
            total_count = sum(counter[p] for p in cluster)
            # Only keep clusters with enough occurrences (at least 3 rows)
            if total_count >= 3:
                result.append(best)

        return result

    def _detect_column_format(self, header: str, values: list[str]) -> str:
        """Detect whether a column contains dates, amounts, or text."""
        if not values:
            return "text"

        header_lower = header.lower()

        # Check header name hints
        if any(kw in header_lower for kw in ("date", "posted", "trans date")):
            date_fmt = _detect_date_format(values)
            return date_fmt if date_fmt else "date"

        if any(kw in header_lower for kw in (
            "amount", "debit", "credit", "balance",
            "withdrawal", "deposit", "charge", "payment",
        )):
            # Verify with sample values — don't trust header alone
            sample = [v for v in values[:20] if v.strip()]
            if sample:
                match_count = sum(1 for v in sample if _is_amount(v))
                if match_count / len(sample) < 0.3:
                    logger.info(
                        "Header '%s' suggests amount but only %d/%d values match; returning 'text'",
                        header, match_count, len(sample),
                    )
                    return "text"
            amt_info = _detect_amount_format(values)
            symbol = amt_info.get("currency_symbol", "$")
            return f"{symbol}#,##0.00"

        # Sample-based detection
        date_fmt = _detect_date_format(values[:20])
        if date_fmt:
            return date_fmt

        amount_count = sum(1 for v in values[:20] if _is_amount(v))
        if amount_count >= len(values[:20]) * 0.5 and amount_count >= 2:
            amt_info = _detect_amount_format(values)
            symbol = amt_info.get("currency_symbol", "$")
            return f"{symbol}#,##0.00"

        return "text"

    def _detect_alternate_row_fill(
        self, page: pdfplumber.page.Page, bbox: tuple[float, ...]
    ) -> str | None:
        """Check for alternating row background fills in the table area."""
        rects = page.rects or []
        table_rects = [
            r for r in rects
            if (float(r.get("top", 0)) >= bbox[1]
                and float(r.get("bottom", 0)) <= bbox[3]
                and float(r.get("x0", 0)) <= bbox[0] + 10
                and float(r.get("x1", 0)) >= bbox[2] - 10)
        ]

        if not table_rects:
            return None

        # Look for filled rects with a non-white, non-black fill
        fills: list[str] = []
        for r in table_rects:
            fill = r.get("non_stroking_color")
            if fill:
                color = _hex_color(fill)
                if color not in ("#000000", "#ffffff", "#FFFFFF"):
                    fills.append(color)

        if fills:
            return Counter(fills).most_common(1)[0][0]
        return None

    def _detect_header_underline(
        self, page: pdfplumber.page.Page, bbox: tuple[float, ...] | None
    ) -> bool:
        """Check if there is a horizontal line right below the table header row."""
        lines = page.lines or []
        if not lines:
            return False

        # Look for horizontal lines in the table area
        for ln in lines:
            if abs(float(ln["top"]) - float(ln["bottom"])) < 2:
                width = float(ln["x1"]) - float(ln["x0"])
                if width > 100:
                    if bbox is None or (
                        float(ln["top"]) >= bbox[1]
                        and float(ln["top"]) <= bbox[1] + 30
                    ):
                        return True
        return False

    def _font_role_for_size(self, fonts: list[FontSpec], size: float) -> FontRole:
        """Find the closest font role for a given size."""
        if not fonts:
            return FontRole.BODY
        closest = min(fonts, key=lambda f: abs(f.size - size))
        return closest.role

    def _header_font_size(self, fonts: list[FontSpec]) -> float:
        """Return the header font size, or a large default."""
        for f in fonts:
            if f.role == FontRole.HEADER:
                return f.size
        return 14.0

    def _classify_summary_role(self, label: str) -> str:
        """Map a label string to a summary field role."""
        lower = label.lower()
        if "account" in lower and ("number" in lower or "no" in lower or "#" in lower):
            return "account_number_masked"
        if "opening" in lower or "beginning" in lower or "previous" in lower:
            return "opening_balance"
        if "closing" in lower or "ending" in lower or "new" in lower:
            return "closing_balance"
        if "statement" in lower and ("period" in lower or "date" in lower):
            return "statement_period"
        if "payment" in lower and "due" in lower:
            return "payment_due_date"
        if "minimum" in lower:
            return "minimum_payment"
        if "credit" in lower and "limit" in lower:
            return "credit_limit"
        # Generic
        return label.lower().replace(" ", "_")[:30]

    def _infer_summary_format(self, role: str) -> str:
        """Return a format pattern for a summary field role."""
        if "balance" in role or "payment" in role or "limit" in role:
            return "$#,##0.00"
        if "account_number" in role:
            return "XXXX-XXXX-{4digits}"
        if "period" in role or "date" in role:
            return "MM/DD/YYYY - MM/DD/YYYY"
        return "{value}"

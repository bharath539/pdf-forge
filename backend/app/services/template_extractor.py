"""Template Extractor — extracts ALL visual elements from a PDF.

Iterates every page and captures every character (grouped into words),
line, rectangle, and image with exact positions. This forms the raw
template before data classification.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import pdfplumber

from app.models.template import (
    AccountType,
    ImageElement,
    LineElement,
    PageDimensions,
    PDFTemplate,
    RectElement,
    TextElement,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known font family mapping (proprietary → standard)
# ---------------------------------------------------------------------------

_KNOWN_FAMILIES = {
    "helvetica",
    "arial",
    "courier",
    "times",
    "times new roman",
    "times-roman",
    "verdana",
    "georgia",
    "tahoma",
    "calibri",
    "cambria",
    "garamond",
    "palatino",
    "roboto",
    "open sans",
    "lato",
    "inter",
    "futura",
    "optima",
    "gill sans",
    "avenir",
}


def _clean_font_family(fontname: str) -> str:
    """Extract a clean font family, mapping proprietary names to Helvetica."""
    name = fontname
    for suffix in [
        "-Bold",
        "-Italic",
        "-BoldItalic",
        "-Light",
        ",Bold",
        ",Italic",
        ",BoldItalic",
        "-Regular",
        ",Regular",
        "-Roman",
    ]:
        name = name.replace(suffix, "")
    if "+" in name:
        name = name.split("+", 1)[1]
    if not name:
        return "Helvetica"
    lower = name.lower().strip()
    if lower in _KNOWN_FAMILIES:
        return name
    for known in _KNOWN_FAMILIES:
        if known in lower:
            return known.title()
    return "Helvetica"


def _font_weight(fontname: str) -> str:
    """Infer weight from font name."""
    lower = fontname.lower()
    if "bold" in lower:
        return "bold"
    if "light" in lower or "thin" in lower:
        return "light"
    return "normal"


def _hex_color(color: Any) -> str:
    """Convert pdfplumber color value to hex string."""
    if color is None:
        return "#000000"
    if isinstance(color, (list, tuple)):
        if len(color) >= 3:
            r, g, b = (int(min(max(c, 0), 1) * 255) for c in color[:3])
            return f"#{r:02x}{g:02x}{b:02x}"
        if len(color) == 1:
            v = int(min(max(color[0], 0), 1) * 255)
            return f"#{v:02x}{v:02x}{v:02x}"
    return "#000000"


# ---------------------------------------------------------------------------
# Word grouping
# ---------------------------------------------------------------------------


def _chars_to_words(chars: list[dict[str, Any]], gap: float = 3.0) -> list[dict[str, Any]]:
    """Merge characters into words based on x-gaps.

    Each word dict has: text, x0, x1, top, bottom, fontname, size, color.
    """
    if not chars:
        return []

    sorted_chars = sorted(chars, key=lambda c: float(c["x0"]))
    words: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for c in sorted_chars:
        x0 = float(c["x0"])
        char_text = c.get("text", "")

        if current is None or x0 - current["x1"] > gap:
            if current:
                words.append(current)
            current = {
                "text": char_text,
                "x0": x0,
                "x1": float(c["x1"]),
                "top": float(c.get("top", 0)),
                "bottom": float(c.get("bottom", 0)),
                "fontname": c.get("fontname", "Unknown"),
                "size": float(c.get("size", 10)),
                "color": c.get("non_stroking_color"),
            }
        else:
            current["text"] += char_text
            current["x1"] = float(c["x1"])
            # Keep the dominant font attributes from the first char

    if current:
        words.append(current)
    return words


def _cluster_lines(chars: list[dict[str, Any]], tolerance: float = 2.0) -> dict[float, list[dict[str, Any]]]:
    """Group characters into lines by y-position."""
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


# ---------------------------------------------------------------------------
# Credit card detection from bank name
# ---------------------------------------------------------------------------

_CC_KEYWORDS = [
    "visa",
    "mastercard",
    "amex",
    "american express",
    "discover",
    "credit card",
    "card by",
]


def _infer_account_type(bank_name: str, text_elements: list[TextElement]) -> AccountType:
    """Infer account type from bank name and page text."""
    name_lower = bank_name.lower()
    if any(kw in name_lower for kw in _CC_KEYWORDS):
        return AccountType.CREDIT_CARD

    # Check all text on first page for credit card indicators
    page0_text = " ".join(te.text.lower() for te in text_elements if te.page == 0)
    cc_indicators = [
        "minimum payment",
        "credit limit",
        "new balance",
        "payment due",
        "previous balance",
        "cash advance",
        "annual percentage rate",
        "apr",
    ]
    if sum(1 for kw in cc_indicators if kw in page0_text) >= 2:
        return AccountType.CREDIT_CARD

    return AccountType.CHECKING


# ---------------------------------------------------------------------------
# TemplateExtractor
# ---------------------------------------------------------------------------

_MIN_FONT_SIZE = 3.0  # Ignore characters below this size


class TemplateExtractor:
    """Extracts all visual elements from a PDF to build a template."""

    def extract(self, pdf_bytes: BytesIO) -> PDFTemplate:
        """Parse a PDF and return a template with every visual element."""
        logger.info("Starting template extraction (%d bytes)", pdf_bytes.getbuffer().nbytes)

        text_elements: list[TextElement] = []
        line_elements: list[LineElement] = []
        rect_elements: list[RectElement] = []
        image_elements: list[ImageElement] = []
        page_dims: list[PageDimensions] = []

        with pdfplumber.open(pdf_bytes) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_dims.append(
                    PageDimensions(
                        width=float(page.width),
                        height=float(page.height),
                    )
                )

                # --- Extract text elements (grouped into words) ---
                chars = page.chars or []
                # Filter out invisible/tiny characters
                visible_chars = [c for c in chars if float(c.get("size", 0)) >= _MIN_FONT_SIZE]

                line_groups = _cluster_lines(visible_chars)
                for y_pos, line_chars in sorted(line_groups.items()):
                    words = _chars_to_words(line_chars)
                    for w in words:
                        text = w["text"].strip()
                        if not text:
                            continue
                        text_elements.append(
                            TextElement(
                                page=page_idx,
                                x=round(w["x0"], 2),
                                y=round(w["top"], 2),
                                text=text,
                                font_family=_clean_font_family(w["fontname"]),
                                font_size=round(w["size"], 1),
                                font_weight=_font_weight(w["fontname"]),
                                color=_hex_color(w["color"]),
                                width=round(w["x1"] - w["x0"], 2),
                            )
                        )

                # --- Extract lines ---
                for ln in page.lines or []:
                    line_elements.append(
                        LineElement(
                            page=page_idx,
                            x0=round(float(ln["x0"]), 2),
                            y0=round(float(ln["top"]), 2),
                            x1=round(float(ln["x1"]), 2),
                            y1=round(float(ln["bottom"]), 2),
                            stroke_color=_hex_color(ln.get("stroking_color")),
                            stroke_width=round(float(ln.get("linewidth", 0.5)), 2),
                        )
                    )

                # --- Extract rectangles ---
                for r in page.rects or []:
                    fill = r.get("non_stroking_color")
                    stroke = r.get("stroking_color")
                    rect_elements.append(
                        RectElement(
                            page=page_idx,
                            x0=round(float(r["x0"]), 2),
                            y0=round(float(r["top"]), 2),
                            x1=round(float(r["x1"]), 2),
                            y1=round(float(r["bottom"]), 2),
                            fill_color=_hex_color(fill) if fill else None,
                            stroke_color=_hex_color(stroke) if stroke else None,
                            stroke_width=round(float(r.get("linewidth", 0)), 2),
                        )
                    )

                # --- Extract images (bounding boxes only) ---
                for img in page.images or []:
                    image_elements.append(
                        ImageElement(
                            page=page_idx,
                            x0=round(float(img["x0"]), 2),
                            y0=round(float(img["top"]), 2),
                            x1=round(float(img["x1"]), 2),
                            y1=round(float(img["bottom"]), 2),
                        )
                    )

        # Detect bank name from largest font on page 0
        bank_name = self._detect_bank_name(text_elements)
        account_type = _infer_account_type(bank_name, text_elements)

        template = PDFTemplate(
            bank_name=bank_name,
            account_type=account_type,
            display_name=f"{bank_name} {account_type.value.replace('_', ' ').title()}",
            page_dimensions=page_dims,
            text_elements=text_elements,
            line_elements=line_elements,
            rect_elements=rect_elements,
            image_elements=image_elements,
            page_count=len(page_dims),
        )

        logger.info(
            "Extraction complete: %d text, %d lines, %d rects, %d images across %d pages",
            len(text_elements),
            len(line_elements),
            len(rect_elements),
            len(image_elements),
            len(page_dims),
        )
        return template

    def _detect_bank_name(self, text_elements: list[TextElement]) -> str:
        """Find the bank name from the largest font text on page 0 header area."""
        page0 = [te for te in text_elements if te.page == 0]
        if not page0:
            return "Detected Bank"

        # Look in top 15% of page
        max_y = max(te.y for te in page0) if page0 else 100
        header_threshold = max_y * 0.15 if max_y > 0 else 100
        header_texts = [te for te in page0 if te.y < header_threshold]

        if not header_texts:
            # Fallback: just use top 5 elements
            header_texts = sorted(page0, key=lambda t: t.y)[:5]

        if not header_texts:
            return "Detected Bank"

        # Pick the text with the largest font
        best = max(header_texts, key=lambda t: t.font_size)
        name = best.text.strip()[:60]

        # Clean up
        import re

        name = re.sub(r"\s+\d[\d/\-\.]+\s*$", "", name).strip()
        return name if name else "Detected Bank"

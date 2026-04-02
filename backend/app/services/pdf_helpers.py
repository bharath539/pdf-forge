"""Shared PyMuPDF helper functions used by pdf_redactor and redacted_renderer."""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal

import fitz

from app.models.template import PDFTemplate

logger = logging.getLogger(__name__)

# Patterns to find account numbers embedded in structural text
EMBEDDED_ACCT_RE = re.compile(r"(?:ending\s+in[:\s]*|card\s+#?\s*)(\d{4})\b", re.IGNORECASE)


def hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    """Convert hex color '#RRGGBB' to (r, g, b) floats 0-1.

    Light/bright colors (yellow, white, light gray) that would be invisible
    on a white background are remapped to black. This handles cases where
    pdfplumber extracts incorrect color values from complex PDF color spaces.
    """
    if not hex_str or len(hex_str) < 7:
        return (0.0, 0.0, 0.0)
    try:
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
        # If the color is too light (luminance > 0.7), remap to black
        # to avoid invisible text on white background
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        if luminance > 0.7:
            return (0.0, 0.0, 0.0)
        return (r, g, b)
    except (ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def format_amount(amount: Decimal) -> str:
    """Format a decimal as a US dollar string."""
    abs_val = abs(amount)
    formatted = f"${abs_val:,.2f}"
    return f"-{formatted}" if amount < 0 else formatted


def format_date_mmdd(d: date) -> str:
    return d.strftime("%m/%d")


def format_date_mmddyy(d: date) -> str:
    return d.strftime("%m/%d/%y")


def format_date_mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def closest_rect(rects: list[fitz.Rect], x: float, y: float) -> fitz.Rect:
    """Find the rect closest to the expected (x, y) position."""
    best = rects[0]
    best_dist = abs(best.x0 - x) + abs(best.y0 - y)
    for r in rects[1:]:
        dist = abs(r.x0 - x) + abs(r.y0 - y)
        if dist < best_dist:
            best = r
            best_dist = dist
    return best


def detect_account_digits(template: PDFTemplate) -> set[str]:
    """Find last-4 account number digits from template text."""
    digits: set[str] = set()
    for te in template.text_elements:
        matches = EMBEDDED_ACCT_RE.findall(te.text)
        for m in matches:
            digits.add(m)
    if digits:
        logger.info("Detected account digits: %s", digits)
    return digits


def insert_text(
    page: fitz.Page,
    point: fitz.Point,
    text: str,
    fontsize: float,
    color: tuple[float, float, float],
    weight: str,
) -> None:
    """Insert text using Helvetica base14 fonts with fallback."""
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

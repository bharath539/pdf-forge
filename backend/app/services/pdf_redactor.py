"""PDF Redactor — whites out all PII/data fields in the original PDF.

Called during the learn phase BEFORE sanitization. Produces a redacted copy
of the original PDF (safe to store) plus a list of RedactedRects recording
the exact position of each whited-out field.

The redacted PDF + rects are stored in the database and used by the
RedactedRenderer at generation time to overlay fake data.
"""

from __future__ import annotations

import io
import logging

import fitz

from app.models.template import (
    ElementCategory,
    PDFTemplate,
    RedactedRect,
)
from app.services.pdf_helpers import closest_rect, detect_account_digits

logger = logging.getLogger(__name__)


class PDFRedactor:
    """Creates a redacted copy of a PDF with all data fields whited out."""

    def redact(
        self, pdf_bytes: bytes, template: PDFTemplate
    ) -> tuple[bytes, list[RedactedRect]]:
        """White out all data fields in the PDF.

        Args:
            pdf_bytes: The original PDF file bytes.
            template: Classified template (BEFORE sanitization) — data elements
                      still contain their original text for search_for() to find.

        Returns:
            Tuple of (redacted PDF bytes, list of RedactedRects).
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        redacted_rects: list[RedactedRect] = []

        # Collect data elements with original text (before sanitization)
        data_elements = [
            (i, te)
            for i, te in enumerate(template.text_elements)
            if te.element_type == ElementCategory.DATA_PLACEHOLDER
        ]

        # Detect embedded account number digits in structural text
        acct_digits = detect_account_digits(template)

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_elements = [(i, te) for i, te in data_elements if te.page == page_idx]

            for elem_idx, te in page_elements:
                original_text = te.text

                # Skip already-sanitized placeholders (shouldn't happen if called before sanitizer)
                if original_text.startswith("{") and original_text.endswith("}"):
                    logger.warning(
                        "Element %d appears already sanitized: '%s'", elem_idx, original_text
                    )
                    continue

                # Search for the original text in the PDF
                rects = page.search_for(original_text)
                if rects:
                    best_rect = closest_rect(rects, te.x, te.y)
                    # Add small margin for clean redaction
                    expanded = fitz.Rect(
                        best_rect.x0 - 1,
                        best_rect.y0 - 1,
                        best_rect.x1 + 1,
                        best_rect.y1 + 1,
                    )
                    page.add_redact_annot(expanded, fill=(1, 1, 1))
                    redacted_rects.append(
                        RedactedRect(
                            page=page_idx,
                            x0=best_rect.x0,
                            y0=best_rect.y0,
                            x1=best_rect.x1,
                            y1=best_rect.y1,
                            element_index=elem_idx,
                        )
                    )
                else:
                    # Fallback: use pdfplumber coordinates
                    text_height = te.font_size
                    text_width = te.width or text_height * len(original_text) * 0.6
                    rect = fitz.Rect(
                        te.x - 1,
                        te.y - 1,
                        te.x + text_width + 1,
                        te.y + text_height + 1,
                    )
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    redacted_rects.append(
                        RedactedRect(
                            page=page_idx,
                            x0=te.x,
                            y0=te.y,
                            x1=te.x + text_width,
                            y1=te.y + text_height,
                            element_index=elem_idx,
                        )
                    )
                    logger.debug(
                        "search_for failed for element %d '%s', using pdfplumber coords",
                        elem_idx,
                        original_text[:30],
                    )

            # Redact embedded account number digits
            for digit_str in acct_digits:
                for rect in page.search_for(digit_str):
                    expanded = fitz.Rect(
                        rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1
                    )
                    page.add_redact_annot(expanded, fill=(1, 1, 1))

            # Apply all redactions for this page at once
            page.apply_redactions()

        # Save redacted PDF to bytes
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()

        logger.info(
            "Redacted PDF: %d data elements, %d rects found, %d bytes",
            len(data_elements),
            len(redacted_rects),
            buf.tell(),
        )

        return buf.getvalue(), redacted_rects

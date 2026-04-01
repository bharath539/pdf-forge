#!/usr/bin/env python3
"""Local test script: runs the full V2 pipeline on a real PDF.

Usage: python3 test_local_pipeline.py <input_pdf> [output_pdf]
"""

from __future__ import annotations

import sys
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import UUID

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.models.generation import GenerationParams, Scenario, TransactionRange
from app.services.data_classifier import DataClassifier
from app.services.template_extractor import TemplateExtractor
from app.services.overlay_renderer import OverlayRenderer
from app.services.template_renderer import TemplateRenderer
from app.services.template_sanitizer import TemplateSanitizer


def run_pipeline(input_path: str, output_path: str) -> None:
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print()

    # Step 1: Extract
    print("=== Step 1: Extracting template ===")
    with open(input_path, "rb") as f:
        pdf_bytes = BytesIO(f.read())

    extractor = TemplateExtractor()
    template = extractor.extract(pdf_bytes)

    print(f"  Bank: {template.bank_name}")
    print(f"  Account type: {template.account_type}")
    print(f"  Pages: {template.page_count}")
    print(f"  Text elements: {len(template.text_elements)}")
    print(f"  Line elements: {len(template.line_elements)}")
    print(f"  Rect elements: {len(template.rect_elements)}")
    print(f"  Image elements: {len(template.image_elements)}")
    for img in template.image_elements:
        w = img.x1 - img.x0
        h = img.y1 - img.y0
        print(f"    Image page={img.page} ({w:.0f}x{h:.0f}) at ({img.x0:.0f},{img.y0:.0f}) placeholder={img.placeholder}")
    print()

    # Step 2: Classify
    print("=== Step 2: Classifying data elements ===")
    classifier = DataClassifier()
    template = classifier.classify(template)

    summary = template.data_field_summary
    print(f"  Amounts: {summary.amounts}")
    print(f"  Dates: {summary.dates}")
    print(f"  Names: {summary.names}")
    print(f"  Addresses: {summary.addresses}")
    print(f"  Account numbers: {summary.account_numbers}")
    print(f"  Descriptions: {summary.descriptions}")
    print(f"  Phones: {summary.phones}")
    print(f"  Emails: {summary.emails}")
    print(f"  References: {summary.references}")
    print(f"  Transaction rows: {summary.transaction_rows}")
    print(f"  Tx area page: {template.transaction_area_page}")
    print(f"  Tx area start y: {template.transaction_area_start_y}")
    print(f"  Tx row height: {template.transaction_row_height}")
    print()

    # Show some classified elements for debugging
    from app.models.template import ElementCategory
    data_els = [te for te in template.text_elements if te.element_type == ElementCategory.DATA_PLACEHOLDER]
    struct_els = [te for te in template.text_elements if te.element_type == ElementCategory.STRUCTURAL]
    print(f"  Data elements ({len(data_els)}):")
    for te in data_els[:20]:
        print(f"    [{te.data_type}] row={te.row_index} page={te.page} y={te.y:.1f} x={te.x:.1f}: {te.text!r}")
    if len(data_els) > 20:
        print(f"    ... and {len(data_els) - 20} more")

    print(f"\n  Structural elements ({len(struct_els)}):")
    for te in struct_els[:30]:
        print(f"    page={te.page} y={te.y:.1f} x={te.x:.1f}: {te.text!r}")
    if len(struct_els) > 30:
        print(f"    ... and {len(struct_els) - 30} more")
    print()

    # Step 3: Sanitize — SKIPPED for overlay renderer
    # The overlay renderer searches for original text in the PDF,
    # so we keep the original text in the template (not placeholders).
    # Sanitization is only needed for the reportlab-based renderer.
    print("=== Step 3: Sanitize (skipped — overlay uses original text) ===")
    print()

    # Step 4: Render (overlay on original PDF)
    print("=== Step 4: Rendering synthetic PDF (overlay method) ===")
    params = GenerationParams(
        schema_id=UUID("00000000-0000-0000-0000-000000000000"),
        scenario=Scenario.SINGLE_MONTH,
        start_date=date(2026, 2, 1),
        months=1,
        transactions_per_month=TransactionRange(min=15, max=25),
        opening_balance="5000.00",
        seed=42,
    )

    # Re-read original PDF for overlay
    with open(input_path, "rb") as f:
        original_pdf = BytesIO(f.read())

    overlay = OverlayRenderer()
    pdf_buf = overlay.render(original_pdf, template, params)
    output_bytes = pdf_buf.read()
    print(f"  Generated PDF size: {len(output_bytes)} bytes")

    with open(output_path, "wb") as f:
        f.write(output_bytes)
    print(f"  Written to: {output_path}")
    print()
    print("Done! Compare the output PDF with the original.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_local_pipeline.py <input_pdf> [output_pdf]")
        sys.exit(1)

    input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    else:
        output_file = str(Path(input_file).parent / f"synthetic_{Path(input_file).stem}.pdf")

    run_pipeline(input_file, output_file)

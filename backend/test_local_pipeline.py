#!/usr/bin/env python3
"""Local test script: runs the full V3 pipeline on a real PDF.

V3 pipeline: extract → classify → redact (create redacted PDF) → sanitize → render from redacted PDF.

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
from app.models.template import ElementCategory
from app.services.data_classifier import DataClassifier
from app.services.pdf_redactor import PDFRedactor
from app.services.redacted_renderer import RedactedRenderer
from app.services.template_extractor import TemplateExtractor
from app.services.template_sanitizer import TemplateSanitizer


def run_pipeline(input_path: str, output_path: str) -> None:
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print()

    # Read original PDF
    with open(input_path, "rb") as f:
        original_bytes = f.read()

    # Step 1: Extract
    print("=== Step 1: Extracting template ===")
    pdf_buffer = BytesIO(original_bytes)
    extractor = TemplateExtractor()
    template = extractor.extract(pdf_buffer)

    print(f"  Bank: {template.bank_name}")
    print(f"  Account type: {template.account_type}")
    print(f"  Pages: {template.page_count}")
    print(f"  Text elements: {len(template.text_elements)}")
    print(f"  Line elements: {len(template.line_elements)}")
    print(f"  Rect elements: {len(template.rect_elements)}")
    print(f"  Image elements: {len(template.image_elements)}")
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
    print()

    # Show some classified elements
    data_els = [te for te in template.text_elements if te.element_type == ElementCategory.DATA_PLACEHOLDER]
    print(f"  Data elements ({len(data_els)}):")
    for te in data_els[:15]:
        print(f"    [{te.data_type}] row={te.row_index} page={te.page} y={te.y:.1f} x={te.x:.1f}: {te.text!r}")
    if len(data_els) > 15:
        print(f"    ... and {len(data_els) - 15} more")
    print()

    # Step 3: Redact (V3) — MUST run before sanitizer
    print("=== Step 3: Redacting PDF (V3) ===")
    redactor = PDFRedactor()
    redacted_pdf_bytes, redacted_rects = redactor.redact(original_bytes, template)
    template.redacted_rects = redacted_rects
    print(f"  Redacted PDF size: {len(redacted_pdf_bytes)} bytes")
    print(f"  Redacted rects: {len(redacted_rects)}")

    # Save redacted PDF for inspection
    redacted_path = str(Path(output_path).parent / f"redacted_{Path(input_path).stem}.pdf")
    with open(redacted_path, "wb") as f:
        f.write(redacted_pdf_bytes)
    print(f"  Saved redacted PDF: {redacted_path}")
    print()

    # Step 4: Sanitize (replaces data text with placeholders in metadata)
    print("=== Step 4: Sanitizing template metadata ===")
    sanitizer = TemplateSanitizer()
    template = sanitizer.sanitize(template)
    print(f"  Done — data element text replaced with placeholders")
    print()

    # Step 5: Render from redacted PDF
    print("=== Step 5: Rendering synthetic PDF (V3 redacted method) ===")
    params = GenerationParams(
        schema_id=UUID("00000000-0000-0000-0000-000000000000"),
        scenario=Scenario.SINGLE_MONTH,
        start_date=date(2026, 3, 1),
        months=1,
        transactions_per_month=TransactionRange(min=15, max=25),
        opening_balance="5000.00",
        seed=42,
    )

    renderer = RedactedRenderer()
    pdf_buf = renderer.render(redacted_pdf_bytes, template, params)
    output_bytes = pdf_buf.read()
    print(f"  Generated PDF size: {len(output_bytes)} bytes")

    with open(output_path, "wb") as f:
        f.write(output_bytes)
    print(f"  Written to: {output_path}")
    print()
    print("Done! Compare the output PDF with the original.")
    print(f"  Original:  {input_path}")
    print(f"  Redacted:  {redacted_path}")
    print(f"  Synthetic: {output_path}")


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

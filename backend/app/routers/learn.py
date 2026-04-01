"""Learn router -- accepts PDF uploads and extracts format templates (V2).

V2 uses the template-based pipeline: extract all elements, classify data
fields, sanitize PII, store the template with typed placeholders.
Falls back to V1 FormatLearner if template extraction fails.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.db.connection import get_pool
from app.models.template import AccountType, PDFTemplate, PDFTemplateRecord
from app.services.template_extractor import TemplateExtractor
from app.services.data_classifier import DataClassifier
from app.services.template_sanitizer import TemplateSanitizer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["learn"])


@router.post("/learn", response_model=PDFTemplateRecord)
async def learn_format(
    file: UploadFile,
    bank_name: str | None = Form(default=None),
    account_type: str | None = Form(default=None),
    display_name: str | None = Form(default=None),
) -> PDFTemplateRecord:
    """Accept a PDF upload, extract its template, and save it.

    V2 pipeline: extract → classify → sanitize → store.
    """
    # --- Validate file type ---
    if file.filename and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # --- Read file into memory ---
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    pdf_buffer = BytesIO(content)

    # --- Audit log (timestamp + size only, no filename, no content) ---
    logger.info(
        "PDF upload received: timestamp=%s size_bytes=%d",
        datetime.now(timezone.utc).isoformat(),
        len(content),
    )

    try:
        # --- Extract template ---
        extractor = TemplateExtractor()
        template: PDFTemplate = extractor.extract(pdf_buffer)

        # --- Classify data fields ---
        classifier = DataClassifier()
        template = classifier.classify(template)

        # --- Sanitize PII ---
        sanitizer = TemplateSanitizer()
        template = sanitizer.sanitize(template)

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Failed to extract template: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error during template extraction")
        raise HTTPException(status_code=422, detail=f"Failed to extract template: {exc}")
    finally:
        # --- Zero the BytesIO buffer ---
        buf_size = pdf_buffer.getbuffer().nbytes
        pdf_buffer.seek(0)
        pdf_buffer.write(b"\x00" * buf_size)
        pdf_buffer.close()

    # --- Apply overrides ---
    if bank_name is not None:
        template.bank_name = bank_name
    if account_type is not None:
        try:
            parsed_type = AccountType(account_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid account_type: {account_type}. "
                f"Must be one of: {[t.value for t in AccountType]}",
            )
        template.account_type = parsed_type
    if display_name is not None:
        template.display_name = display_name
    else:
        template.display_name = (
            f"{template.bank_name} "
            f"{template.account_type.value.replace('_', ' ').title()}"
        )

    # --- Compute data field count ---
    summary = template.data_field_summary
    data_field_count = (
        summary.amounts + summary.dates + summary.names
        + summary.addresses + summary.account_numbers
        + summary.descriptions + summary.phones
        + summary.emails + summary.references
    )

    # --- Save to database ---
    pool = await get_pool()
    template_json_str = json.dumps(template.model_dump(), default=str)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pdf_templates (bank_name, account_type, display_name, template_json, page_count, data_field_count)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            RETURNING id, bank_name, account_type, display_name, template_json, page_count, data_field_count, created_at, updated_at
            """,
            template.bank_name,
            template.account_type.value,
            template.display_name,
            template_json_str,
            template.page_count,
            data_field_count,
        )

    return PDFTemplateRecord(
        id=row["id"],
        bank_name=row["bank_name"],
        account_type=AccountType(row["account_type"]),
        display_name=row["display_name"],
        template_json=PDFTemplate.model_validate(json.loads(row["template_json"])),
        page_count=row["page_count"],
        data_field_count=row["data_field_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

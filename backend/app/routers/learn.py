"""Learn router -- accepts PDF uploads and extracts format schemas."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.db.connection import get_pool
from app.models.schema import AccountType, FormatSchema, FormatSchemaRecord
from app.services.format_learner import FormatLearner
from app.services.schema_sanitizer import SchemaSanitizer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["learn"])


@router.post("/learn", response_model=FormatSchemaRecord)
async def learn_format(
    file: UploadFile,
    bank_name: str | None = Form(default=None),
    account_type: str | None = Form(default=None),
    display_name: str | None = Form(default=None),
) -> FormatSchemaRecord:
    """Accept a PDF upload, learn its format/structure, and save the schema.

    Accepts optional form fields to override detected bank_name, account_type,
    and display_name values.
    """
    # --- Validate file type ---
    if not file.content_type or file.content_type != "application/pdf":
        if file.filename and not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
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
        # --- Learn format ---
        learner = FormatLearner()
        schema: FormatSchema = learner.learn(pdf_buffer)

        # --- Count pages (re-read buffer) ---
        pdf_buffer.seek(0)
        import pdfplumber

        with pdfplumber.open(pdf_buffer) as pdf:
            page_count = len(pdf.pages)

        # --- Sanitize ---
        sanitizer = SchemaSanitizer()
        schema = sanitizer.sanitize(schema)

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Failed to extract format: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error during format learning")
        raise HTTPException(status_code=422, detail=f"Failed to extract format: {exc}")
    finally:
        # --- Zero the BytesIO buffer ---
        buf_size = pdf_buffer.getbuffer().nbytes
        pdf_buffer.seek(0)
        pdf_buffer.write(b"\x00" * buf_size)
        pdf_buffer.close()

    # --- Apply overrides ---
    if bank_name is not None:
        schema = schema.model_copy(update={"bank_name": bank_name})
    if account_type is not None:
        try:
            parsed_type = AccountType(account_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid account_type: {account_type}. "
                f"Must be one of: {[t.value for t in AccountType]}",
            )
        schema = schema.model_copy(update={"account_type": parsed_type})
    if display_name is not None:
        schema = schema.model_copy(update={"display_name": display_name})

    # --- Save to database ---
    pool = await get_pool()
    schema_json_str = json.dumps(schema.model_dump(), default=str)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO format_schemas (bank_name, account_type, display_name, schema_json, page_count)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            RETURNING id, bank_name, account_type, display_name, schema_json, page_count, created_at, updated_at
            """,
            schema.bank_name,
            schema.account_type.value,
            schema.display_name,
            schema_json_str,
            page_count,
        )

    return FormatSchemaRecord(
        id=row["id"],
        bank_name=row["bank_name"],
        account_type=AccountType(row["account_type"]),
        display_name=row["display_name"],
        schema_json=FormatSchema.model_validate(json.loads(row["schema_json"])),
        page_count=row["page_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

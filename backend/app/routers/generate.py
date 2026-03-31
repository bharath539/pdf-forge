"""Generate router -- produces synthetic PDFs from learned format schemas."""

from __future__ import annotations

import json
import logging
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.db.connection import get_pool
from app.models.generation import (
    BatchGenerationRequest,
    GenerationParams,
    GenerationRequest,
    PreviewRequest,
    Scenario,
)
from app.models.schema import AccountType, FormatSchema
from app.services.synthetic_generator import SyntheticGenerator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


async def _fetch_schema(schema_id: UUID) -> tuple[FormatSchema, str, str]:
    """Fetch a FormatSchema from the database by ID.

    Returns (schema, bank_name, account_type_value).
    Raises HTTPException 404 if not found.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT schema_json, bank_name, account_type FROM format_schemas WHERE id = $1",
            schema_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Format schema {schema_id} not found.")

    schema = FormatSchema.model_validate(json.loads(row["schema_json"]))
    return schema, row["bank_name"], row["account_type"]


async def _log_generation(
    schema_id: UUID,
    scenario: str,
    parameters: dict,
    file_count: int = 1,
) -> None:
    """Write an entry to the generation_log table."""
    pool = await get_pool()
    params_json = json.dumps(parameters, default=str)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO generation_log (schema_id, scenario, parameters, file_count)
            VALUES ($1, $2, $3::jsonb, $4)
            """,
            schema_id,
            scenario,
            params_json,
            file_count,
        )


def _sanitize_filename(name: str) -> str:
    """Replace non-alphanumeric characters (except _ - .) with underscores."""
    return "".join(
        ch if ch.isalnum() or ch in ("_", "-", ".") else "_"
        for ch in name
    )


@router.post("/generate")
async def generate_pdf(body: GenerationRequest) -> StreamingResponse:
    """Generate a single synthetic PDF from a learned format schema."""
    params = body.params
    schema, bank_name, account_type = await _fetch_schema(params.schema_id)

    generator = SyntheticGenerator()
    pdf_buffer: BytesIO = generator.generate(schema, params)

    # Log the generation
    await _log_generation(
        schema_id=params.schema_id,
        scenario=params.scenario.value,
        parameters=params.model_dump(),
        file_count=1,
    )

    filename = _sanitize_filename(f"{bank_name}_{account_type}_{params.scenario.value}.pdf")

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/generate/preview")
async def generate_preview(body: PreviewRequest) -> StreamingResponse:
    """Generate a first-page preview PDF from a learned format schema."""
    params = body.params
    schema, bank_name, account_type = await _fetch_schema(params.schema_id)

    generator = SyntheticGenerator()
    pdf_buffer: BytesIO = generator.generate_preview(schema, params)

    # Log the generation
    await _log_generation(
        schema_id=params.schema_id,
        scenario=params.scenario.value,
        parameters=params.model_dump(),
        file_count=1,
    )

    filename = _sanitize_filename(f"{bank_name}_{account_type}_preview.pdf")

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/generate/batch")
async def generate_batch(body: BatchGenerationRequest) -> StreamingResponse:
    """Generate multiple scenario PDFs as a zip archive."""
    schema, bank_name, account_type = await _fetch_schema(body.schema_id)

    generator = SyntheticGenerator()
    zip_buffer: BytesIO = generator.generate_batch(
        schema=schema,
        scenarios=body.scenarios,
        start_date=body.start_date,
        seed=body.seed,
    )

    # Log the generation
    await _log_generation(
        schema_id=body.schema_id,
        scenario="batch",
        parameters=body.model_dump(),
        file_count=len(body.scenarios),
    )

    filename = _sanitize_filename(f"{bank_name}_{account_type}_batch.zip")

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

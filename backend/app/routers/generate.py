"""Generate router -- produces synthetic PDFs from learned templates (V2).

Uses the template renderer to replay PDF templates with fake data.
"""

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
)
from app.models.template import PDFTemplate
from app.services.template_renderer import TemplateRenderer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


async def _fetch_template(
    template_id: UUID,
) -> tuple[PDFTemplate, str, str, bytes | None, str]:
    """Fetch a PDFTemplate from the database by ID.

    Looks in pdf_templates first (V2/V3), falls back to format_schemas (V1).
    Returns (template, bank_name, account_type_value, redacted_pdf_bytes, template_version).
    """
    pool = await get_pool()

    # Try V2/V3 templates first
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT template_json, bank_name, account_type,
                      redacted_pdf, template_version
               FROM pdf_templates WHERE id = $1""",
            template_id,
        )

    if row is not None:
        template = PDFTemplate.model_validate(json.loads(row["template_json"]))
        return (
            template,
            row["bank_name"],
            row["account_type"],
            row.get("redacted_pdf"),
            row.get("template_version", "v2"),
        )

    # Fall back to V1 format_schemas
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT schema_json, bank_name, account_type FROM format_schemas WHERE id = $1",
            template_id,
        )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_id} not found.",
        )

    # V1 schema — use the old generator
    from app.models.schema import FormatSchema

    schema = FormatSchema.model_validate(json.loads(row["schema_json"]))
    # Return None to signal V1 mode
    raise _V1Fallback(schema, row["bank_name"], row["account_type"])


class _V1Fallback(Exception):
    """Signal to use V1 generator."""

    def __init__(self, schema, bank_name: str, account_type: str):
        self.schema = schema
        self.bank_name = bank_name
        self.account_type = account_type


async def _log_generation(
    schema_id: UUID,
    scenario: str,
    parameters: dict,
    file_count: int = 1,
    is_template: bool = True,
) -> None:
    """Write an entry to the generation_log table."""
    pool = await get_pool()
    params_json = json.dumps(parameters, default=str)

    id_col = "template_id" if is_template else "schema_id"

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO generation_log ({id_col}, scenario, parameters, file_count)
            VALUES ($1, $2, $3::jsonb, $4)
            """,
            schema_id,
            scenario,
            params_json,
            file_count,
        )


def _sanitize_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in name)


@router.post("/generate")
async def generate_pdf(params: GenerationParams) -> StreamingResponse:
    """Generate a single synthetic PDF."""
    try:
        template, bank_name, account_type, redacted_pdf, tmpl_version = await _fetch_template(params.schema_id)
    except _V1Fallback as v1:
        # V1 fallback
        from app.services.synthetic_generator import SyntheticGenerator

        generator = SyntheticGenerator()
        pdf_buffer = generator.generate(v1.schema, params)
        await _log_generation(
            schema_id=params.schema_id,
            scenario=params.scenario.value,
            parameters=params.model_dump(),
            is_template=False,
        )
        filename = _sanitize_filename(f"{v1.bank_name}_{v1.account_type}_{params.scenario.value}.pdf")
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # V3: use redacted PDF renderer if available
    if tmpl_version == "v3" and redacted_pdf:
        from app.services.redacted_renderer import RedactedRenderer

        renderer_v3 = RedactedRenderer()
        pdf_buffer: BytesIO = renderer_v3.render(redacted_pdf, template, params)
    else:
        # V2 fallback: reportlab-based renderer
        renderer = TemplateRenderer()
        pdf_buffer: BytesIO = renderer.render(template, params)

    await _log_generation(
        schema_id=params.schema_id,
        scenario=params.scenario.value,
        parameters=params.model_dump(),
    )

    filename = _sanitize_filename(f"{bank_name}_{account_type}_{params.scenario.value}.pdf")

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/generate/preview")
async def generate_preview(params: GenerationParams) -> StreamingResponse:
    """Generate a first-page preview PDF."""
    try:
        template, bank_name, account_type, redacted_pdf, tmpl_version = await _fetch_template(params.schema_id)
    except _V1Fallback as v1:
        from app.services.synthetic_generator import SyntheticGenerator

        generator = SyntheticGenerator()
        pdf_buffer = generator.generate_preview(v1.schema, params)
        await _log_generation(
            schema_id=params.schema_id,
            scenario=params.scenario.value,
            parameters=params.model_dump(),
            is_template=False,
        )
        filename = _sanitize_filename(f"{v1.bank_name}_{v1.account_type}_preview.pdf")
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if tmpl_version == "v3" and redacted_pdf:
        from app.services.redacted_renderer import RedactedRenderer

        renderer_v3 = RedactedRenderer()
        pdf_buffer: BytesIO = renderer_v3.render_preview(redacted_pdf, template, params)
    else:
        renderer = TemplateRenderer()
        pdf_buffer: BytesIO = renderer.render_preview(template, params)

    await _log_generation(
        schema_id=params.schema_id,
        scenario=params.scenario.value,
        parameters=params.model_dump(),
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
    try:
        template, bank_name, account_type, redacted_pdf, tmpl_version = await _fetch_template(body.schema_id)
    except _V1Fallback as v1:
        from app.services.synthetic_generator import SyntheticGenerator

        generator = SyntheticGenerator()
        zip_buffer = generator.generate_batch(
            schema=v1.schema,
            scenarios=body.scenarios,
            start_date=body.start_date,
            seed=body.seed,
        )
        await _log_generation(
            schema_id=body.schema_id,
            scenario="batch",
            parameters=body.model_dump(),
            file_count=len(body.scenarios),
            is_template=False,
        )
        filename = _sanitize_filename(f"{v1.bank_name}_{v1.account_type}_batch.zip")
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if tmpl_version == "v3" and redacted_pdf:
        from app.services.redacted_renderer import RedactedRenderer

        renderer_v3 = RedactedRenderer()
        zip_buffer: BytesIO = renderer_v3.render_batch(
            redacted_pdf_bytes=redacted_pdf,
            template=template,
            scenarios=body.scenarios,
            start_date=body.start_date,
            seed=body.seed,
        )
    else:
        renderer = TemplateRenderer()
        zip_buffer: BytesIO = renderer.render_batch(
            template=template,
            scenarios=body.scenarios,
            start_date=body.start_date,
            seed=body.seed,
        )

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

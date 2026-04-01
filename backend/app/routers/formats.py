"""Formats CRUD router -- list, get, update, and delete formats.

Lists both V1 format_schemas and V2 pdf_templates in a unified view.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.db.connection import get_pool
from app.models.schema import (
    AccountType,
    FormatSchema,
    FormatSchemaRecord,
    FormatSchemaUpdate,
)

router = APIRouter(tags=["formats"])


class FormatListItem(BaseModel):
    """Unified list item for both V1 and V2 formats."""
    id: UUID
    bank_name: str
    account_type: str
    display_name: str
    page_count: int
    created_at: str
    version: str = "v1"  # "v1" or "v2"


@router.get("/formats")
async def list_formats() -> list[FormatListItem]:
    """List all learned PDF formats (V1 schemas + V2 templates)."""
    pool = await get_pool()
    results: list[FormatListItem] = []

    async with pool.acquire() as conn:
        # V2 templates
        v2_rows = await conn.fetch(
            """
            SELECT id, bank_name, account_type, display_name, page_count, created_at
            FROM pdf_templates
            ORDER BY created_at DESC
            """
        )
        for row in v2_rows:
            results.append(FormatListItem(
                id=row["id"],
                bank_name=row["bank_name"],
                account_type=row["account_type"],
                display_name=row["display_name"],
                page_count=row["page_count"],
                created_at=str(row["created_at"]),
                version="v2",
            ))

        # V1 schemas
        v1_rows = await conn.fetch(
            """
            SELECT id, bank_name, account_type, display_name, page_count, created_at
            FROM format_schemas
            ORDER BY created_at DESC
            """
        )
        for row in v1_rows:
            results.append(FormatListItem(
                id=row["id"],
                bank_name=row["bank_name"],
                account_type=row["account_type"],
                display_name=row["display_name"],
                page_count=row["page_count"],
                created_at=str(row["created_at"]),
                version="v1",
            ))

    # Sort by created_at desc
    results.sort(key=lambda x: x.created_at, reverse=True)
    return results


@router.get("/formats/{format_id}")
async def get_format(format_id: UUID):
    """Get a single format by ID (tries V2 first, then V1)."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Try V2
        row = await conn.fetchrow(
            """
            SELECT id, bank_name, account_type, display_name, template_json, page_count, data_field_count, created_at, updated_at
            FROM pdf_templates WHERE id = $1
            """,
            format_id,
        )
        if row is not None:
            return {
                "id": str(row["id"]),
                "bank_name": row["bank_name"],
                "account_type": row["account_type"],
                "display_name": row["display_name"],
                "page_count": row["page_count"],
                "data_field_count": row["data_field_count"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "version": "v2",
            }

        # Try V1
        row = await conn.fetchrow(
            """
            SELECT id, bank_name, account_type, display_name, schema_json, page_count, created_at, updated_at
            FROM format_schemas WHERE id = $1
            """,
            format_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Format {format_id} not found.")

    return {
        "id": str(row["id"]),
        "bank_name": row["bank_name"],
        "account_type": row["account_type"],
        "display_name": row["display_name"],
        "page_count": row["page_count"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "version": "v1",
    }


@router.put("/formats/{format_id}")
async def update_format(format_id: UUID, body: FormatSchemaUpdate):
    """Update metadata on a format (V2 or V1)."""
    pool = await get_pool()

    updates: dict[str, str] = {}
    params: list[object] = []
    param_idx = 2

    if body.bank_name is not None:
        updates["bank_name"] = f"${param_idx}"
        params.append(body.bank_name)
        param_idx += 1
    if body.account_type is not None:
        updates["account_type"] = f"${param_idx}"
        params.append(body.account_type.value)
        param_idx += 1
    if body.display_name is not None:
        updates["display_name"] = f"${param_idx}"
        params.append(body.display_name)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    set_clause = ", ".join(f"{col} = {ph}" for col, ph in updates.items())

    async with pool.acquire() as conn:
        # Try V2 first
        row = await conn.fetchrow(
            f"UPDATE pdf_templates SET {set_clause} WHERE id = $1 "
            f"RETURNING id, bank_name, account_type, display_name, page_count, created_at, updated_at",
            format_id, *params,
        )
        if row is not None:
            return {
                "id": str(row["id"]),
                "bank_name": row["bank_name"],
                "account_type": row["account_type"],
                "display_name": row["display_name"],
                "page_count": row["page_count"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "version": "v2",
            }

        # Try V1
        row = await conn.fetchrow(
            f"UPDATE format_schemas SET {set_clause} WHERE id = $1 "
            f"RETURNING id, bank_name, account_type, display_name, page_count, created_at, updated_at",
            format_id, *params,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Format {format_id} not found.")

    return {
        "id": str(row["id"]),
        "bank_name": row["bank_name"],
        "account_type": row["account_type"],
        "display_name": row["display_name"],
        "page_count": row["page_count"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "version": "v1",
    }


@router.delete("/formats/{format_id}", status_code=204)
async def delete_format(format_id: UUID) -> Response:
    """Delete a format by ID (tries V2 first, then V1)."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Try V2
        result = await conn.execute(
            "DELETE FROM pdf_templates WHERE id = $1", format_id,
        )
        if result != "DELETE 0":
            return Response(status_code=204)

        # Try V1
        result = await conn.execute(
            "DELETE FROM format_schemas WHERE id = $1", format_id,
        )

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail=f"Format {format_id} not found.")

    return Response(status_code=204)

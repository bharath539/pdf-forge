"""Formats CRUD router -- list, get, update, and delete format schemas."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.db.connection import get_pool
from app.models.schema import (
    AccountType,
    FormatSchema,
    FormatSchemaListItem,
    FormatSchemaRecord,
    FormatSchemaUpdate,
)

router = APIRouter(tags=["formats"])


@router.get("/formats", response_model=list[FormatSchemaListItem])
async def list_formats() -> list[FormatSchemaListItem]:
    """List all learned PDF format schemas (without full schema_json)."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, bank_name, account_type, display_name, page_count, created_at
            FROM format_schemas
            ORDER BY created_at DESC
            """
        )

    return [
        FormatSchemaListItem(
            id=row["id"],
            bank_name=row["bank_name"],
            account_type=AccountType(row["account_type"]),
            display_name=row["display_name"],
            page_count=row["page_count"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/formats/{format_id}", response_model=FormatSchemaRecord)
async def get_format(format_id: UUID) -> FormatSchemaRecord:
    """Get a single format schema by ID, including full schema_json."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, bank_name, account_type, display_name, schema_json, page_count, created_at, updated_at
            FROM format_schemas
            WHERE id = $1
            """,
            format_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Format schema {format_id} not found.")

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


@router.put("/formats/{format_id}", response_model=FormatSchemaRecord)
async def update_format(format_id: UUID, body: FormatSchemaUpdate) -> FormatSchemaRecord:
    """Update metadata (bank_name, account_type, display_name) on a format schema."""
    pool = await get_pool()

    # Build SET clause dynamically from provided fields
    updates: dict[str, str] = {}
    params: list[object] = []
    param_idx = 2  # $1 is the id

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

    set_clause = ", ".join(f"{col} = {placeholder}" for col, placeholder in updates.items())
    query = f"""
        UPDATE format_schemas
        SET {set_clause}
        WHERE id = $1
        RETURNING id, bank_name, account_type, display_name, schema_json, page_count, created_at, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, format_id, *params)

    if row is None:
        raise HTTPException(status_code=404, detail=f"Format schema {format_id} not found.")

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


@router.delete("/formats/{format_id}", status_code=204)
async def delete_format(format_id: UUID) -> Response:
    """Delete a format schema by ID."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM format_schemas WHERE id = $1",
            format_id,
        )

    # asyncpg returns "DELETE N" where N is the number of rows deleted
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail=f"Format schema {format_id} not found.")

    return Response(status_code=204)

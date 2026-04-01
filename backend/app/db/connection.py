"""Database connection pool management using asyncpg."""

import asyncio
import logging

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncio.wait_for(
            asyncpg.create_pool(
                dsn=settings.database_url_async,
                min_size=1,
                max_size=10,
            ),
            timeout=10,
        )
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def run_migrations() -> None:
    """Run SQL migration files in order."""
    import pathlib

    pool = await get_pool()
    migrations_dir = pathlib.Path(__file__).parent / "migrations"

    async with pool.acquire() as conn:
        # Create migrations tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        # Find and run pending migrations
        applied = {row["filename"] for row in await conn.fetch("SELECT filename FROM _migrations")}
        migration_files = sorted(migrations_dir.glob("*.sql"))

        for migration_file in migration_files:
            if migration_file.name not in applied:
                sql = migration_file.read_text()
                await conn.execute(sql)
                await conn.execute("INSERT INTO _migrations (filename) VALUES ($1)", migration_file.name)

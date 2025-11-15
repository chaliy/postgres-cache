from __future__ import annotations

import uuid

import asyncpg
import pytest

from postgres_cache import CacheSettings
from postgres_cache.migrations import apply_migrations, schema_is_current
from postgres_cache.schema import resolve_schema_names


def _unique_prefix() -> str:
    return f"test_{uuid.uuid4().hex[:6]}_"


@pytest.mark.asyncio
async def test_apply_migrations_creates_prefixed_objects(db_dsn: str) -> None:
    prefix = _unique_prefix()
    settings = CacheSettings(dsn=db_dsn, schema_prefix=prefix)
    await apply_migrations(settings)
    names = resolve_schema_names(prefix)

    conn = await asyncpg.connect(dsn=db_dsn)
    try:
        exists = await conn.fetchval(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = $1
            """,
            names.entries_table,
        )
        assert exists == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_schema_is_current_detects_outdated_version(db_dsn: str) -> None:
    prefix = _unique_prefix()
    settings = CacheSettings(dsn=db_dsn, schema_prefix=prefix)
    await apply_migrations(settings)
    assert await schema_is_current(settings)

    names = resolve_schema_names(prefix)
    conn = await asyncpg.connect(dsn=db_dsn)
    try:
        await conn.execute(f"UPDATE {names.schema_table} SET version = 0 WHERE id = 1")
    finally:
        await conn.close()

    assert not await schema_is_current(settings)

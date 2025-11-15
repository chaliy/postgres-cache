from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
import pytest_asyncio

from postgres_cache import CacheSettings, PostgresCache
from postgres_cache.migrations import init_postgres_cache_db_sync
from postgres_cache.schema import resolve_schema_names

DEFAULT_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:  # type: ignore[override]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def db_dsn() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DSN)


@pytest.fixture(scope="session")
def base_settings(db_dsn: str) -> CacheSettings:
    return CacheSettings(dsn=db_dsn)


@pytest.fixture(scope="session", autouse=True)
def _migrations(base_settings: CacheSettings) -> None:
    init_postgres_cache_db_sync(base_settings)


@pytest_asyncio.fixture(autouse=True)
async def cleanup(base_settings: CacheSettings) -> None:
    names = resolve_schema_names(base_settings.schema_prefix)
    conn = await asyncpg.connect(dsn=base_settings.dsn)
    try:
        await conn.execute(f"TRUNCATE {names.entries_table}")
    finally:
        await conn.close()


@pytest_asyncio.fixture()
async def cache_client(base_settings: CacheSettings) -> PostgresCache:
    client = PostgresCache(base_settings)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()

"""Versioned migrations for the PostgreSQL cache schema."""

from __future__ import annotations

import asyncio
from typing import Sequence, TypedDict

import asyncpg

from .config import CacheSettings
from .schema import SchemaNames, resolve_schema_names


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class _Migration(TypedDict):
    version: int
    statements: Sequence[str]


def _context(names: SchemaNames, settings: CacheSettings) -> dict[str, str]:
    return {
        "entries_table": names.entries_table,
        "expires_index": names.expires_index,
        "set_updated_function": names.set_updated_function,
        "set_updated_trigger": names.set_updated_trigger,
        "broadcast_function": names.broadcast_function,
        "broadcast_trigger": names.broadcast_trigger,
        "cleanup_function": names.cleanup_function,
        "schema_table": names.schema_table,
        "notify_channel_literal": _quote_literal(settings.notify_channel),
    }


MIGRATIONS: list[_Migration] = [
    _Migration(
        version=1,
        statements=(
            """
            CREATE TABLE IF NOT EXISTS {entries_table} (
                cache_key text PRIMARY KEY,
                value bytea NOT NULL,
                version bigint NOT NULL DEFAULT 1,
                expires_at timestamptz,
                created_at timestamptz NOT NULL DEFAULT timezone('UTC', now()),
                updated_at timestamptz NOT NULL DEFAULT timezone('UTC', now())
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS {expires_index}
            ON {entries_table} (expires_at);
            """,
            """
            CREATE OR REPLACE FUNCTION {set_updated_function}() RETURNS trigger AS $$
            BEGIN
                NEW.updated_at := timezone('UTC', now());
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            """
            DROP TRIGGER IF EXISTS {set_updated_trigger} ON {entries_table};
            CREATE TRIGGER {set_updated_trigger}
            BEFORE UPDATE ON {entries_table}
            FOR EACH ROW
            EXECUTE FUNCTION {set_updated_function}();
            """,
            """
            CREATE OR REPLACE FUNCTION {broadcast_function}()
            RETURNS trigger AS $$
            DECLARE
                rec {entries_table}%ROWTYPE;
                target_channel text := COALESCE(TG_ARGV[0], {notify_channel_literal});
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    rec := OLD;
                ELSE
                    rec := NEW;
                END IF;

                PERFORM pg_notify(
                    target_channel,
                    json_build_object(
                        'key', rec.cache_key,
                        'version', rec.version,
                        'event', TG_OP
                    )::text
                );

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END;
            $$ LANGUAGE plpgsql;
            """,
            """
            DROP TRIGGER IF EXISTS {broadcast_trigger} ON {entries_table};
            CREATE TRIGGER {broadcast_trigger}
            AFTER INSERT OR UPDATE OR DELETE ON {entries_table}
            FOR EACH ROW
            EXECUTE FUNCTION {broadcast_function}({notify_channel_literal});
            """,
            """
            CREATE OR REPLACE FUNCTION {cleanup_function}(limit_rows integer DEFAULT 500)
            RETURNS integer AS $$
            DECLARE
                removed integer;
            BEGIN
                WITH expired AS (
                    SELECT cache_key
                    FROM {entries_table}
                    WHERE expires_at IS NOT NULL AND expires_at <= timezone('UTC', now())
                    LIMIT limit_rows
                )
                DELETE FROM {entries_table} ce
                USING expired e
                WHERE ce.cache_key = e.cache_key;

                GET DIAGNOSTICS removed = ROW_COUNT;
                RETURN COALESCE(removed, 0);
            END;
            $$ LANGUAGE plpgsql;
            """,
        ),
    ),
    _Migration(
        version=2,
        statements=(
            """
            CREATE OR REPLACE FUNCTION {broadcast_function}()
            RETURNS trigger AS $$
            DECLARE
                rec {entries_table}%ROWTYPE;
                target_channel text := COALESCE(TG_ARGV[0], {notify_channel_literal});
                event_code text;
                payload text;
                separator text := E'\x1f';
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    rec := OLD;
                    event_code := 'd';
                ELSE
                    rec := NEW;
                    event_code := 'u';
                END IF;

                payload := event_code || rec.version::text || separator ||
                    replace(rec.cache_key, separator, separator || separator);

                PERFORM pg_notify(target_channel, payload);

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END;
            $$ LANGUAGE plpgsql;
            """,
        ),
    ),
]


async def apply_migrations(
    settings: CacheSettings,
    *,
    upto_version: int | None = None,
) -> int:
    """Apply bundled migrations up to the requested version."""

    names = resolve_schema_names(settings.schema_prefix)
    ctx = _context(names, settings)
    conn = await asyncpg.connect(dsn=settings.dsn)
    try:
        await _ensure_schema_table(conn, names)
        current = await _current_version(conn, names)
        target = upto_version or MIGRATIONS[-1]["version"]
        pending = [m for m in MIGRATIONS if current < m["version"] <= target]
        for migration in pending:
            await _apply_migration(conn, migration, ctx, names)
        return await _current_version(conn, names)
    finally:
        await conn.close()


def apply_migrations_sync(
    settings: CacheSettings,
    *,
    upto_version: int | None = None,
) -> int:
    return asyncio.run(apply_migrations(settings, upto_version=upto_version))


async def init_postgres_cache_db(settings: CacheSettings) -> None:
    await apply_migrations(settings)


def init_postgres_cache_db_sync(settings: CacheSettings) -> None:
    apply_migrations_sync(settings)


async def schema_version(settings: CacheSettings) -> int:
    names = resolve_schema_names(settings.schema_prefix)
    conn = await asyncpg.connect(dsn=settings.dsn)
    try:
        await _ensure_schema_table(conn, names)
        return await _current_version(conn, names)
    finally:
        await conn.close()


def schema_version_sync(settings: CacheSettings) -> int:
    return asyncio.run(schema_version(settings))


async def schema_is_current(settings: CacheSettings) -> bool:
    current = await schema_version(settings)
    return current >= MIGRATIONS[-1]["version"]


def schema_is_current_sync(settings: CacheSettings) -> bool:
    return asyncio.run(schema_is_current(settings))


async def _ensure_schema_table(conn: asyncpg.Connection, names: SchemaNames) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {names.schema_table} (
            id integer PRIMARY KEY CHECK (id = 1),
            version integer NOT NULL
        );
        """
    )
    await conn.execute(
        f"""
        INSERT INTO {names.schema_table} (id, version)
        VALUES (1, 0)
        ON CONFLICT (id) DO NOTHING;
        """
    )


async def _current_version(conn: asyncpg.Connection, names: SchemaNames) -> int:
    version = await conn.fetchval(f"SELECT version FROM {names.schema_table} WHERE id = 1")
    return int(version or 0)


async def _apply_migration(
    conn: asyncpg.Connection,
    migration: _Migration,
    ctx: dict[str, str],
    names: SchemaNames,
) -> None:
    async with conn.transaction():
        for statement in migration["statements"]:
            await conn.execute(statement.format(**ctx))
        await conn.execute(
            f"UPDATE {names.schema_table} SET version = $1 WHERE id = 1", migration["version"]
        )


__all__ = [
    "_Migration",
    "apply_migrations",
    "apply_migrations_sync",
    "init_postgres_cache_db",
    "init_postgres_cache_db_sync",
    "schema_is_current",
    "schema_is_current_sync",
    "schema_version",
    "schema_version_sync",
]

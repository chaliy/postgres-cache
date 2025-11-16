"""Cache client implementations backed by PostgreSQL."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta, timezone
from hashlib import blake2b
from typing import Any, TypedDict

import asyncpg
from asyncpg.exceptions import TooManyConnectionsError

from .base import Loader, resolve_loader
from .client_secondary_cache import ClientSecondaryCache
from .config import CacheSettings
from .migrations import init_postgres_cache_db
from .schema import SchemaNames, resolve_schema_names
from .serialization import JsonSerializer, Serializer

logger = logging.getLogger(__name__)


class _CacheRow(TypedDict):
    value: Any
    version: int
    expires_at: datetime | None


class PostgresCache:
    """Async cache implementation that persists entries in PostgreSQL."""

    def __init__(self, settings: CacheSettings, serializer: Serializer | None = None) -> None:
        self.settings = settings
        self.serializer = serializer or JsonSerializer()
        self._pool: asyncpg.Pool | None = None
        self._listener: _NotificationListener | None = None
        self._local_cache = ClientSecondaryCache(self.settings.local_max_entries)
        self._schema: SchemaNames = resolve_schema_names(self.settings.schema_prefix)
        self._notification_task: asyncio.Task[None] | None = None
        self._notifications_enabled = False

    async def __aenter__(self) -> "PostgresCache":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @staticmethod
    async def init_db(settings: CacheSettings) -> None:
        """Apply bundled migrations to the target database."""
        await init_postgres_cache_db(settings)

    async def connect(self) -> None:
        if self._pool:
            return
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self.settings.dsn,
                min_size=self.settings.min_pool_size,
                max_size=self.settings.max_pool_size,
            )
        except TooManyConnectionsError as exc:
            raise RuntimeError(
                "PostgreSQL refused new connections (too many clients). "
                "Consider lowering setting disable_notiffy=True to conserve connections."
            ) from exc

        cache_wants_notifications = self._local_cache.enabled
        self._notifications_enabled = (
            cache_wants_notifications and not self.settings.disable_notiffy
        )
        if not self._notifications_enabled:
            self._notification_queue = None
            self._listener = None
            self._notification_task = None
            return

        self._notification_queue = asyncio.Queue(maxsize=self.settings.notification_queue_size)
        self._listener = _NotificationListener(
            self.settings.dsn, self.settings.notify_channel, self._notification_queue
        )
        await self._listener.start()
        self._notification_task = asyncio.create_task(
            self._notification_worker(), name="cache-notifications"
        )

    async def close(self) -> None:
        if self._listener:
            await self._listener.stop()
            self._listener = None
        if self._notification_task:
            self._notification_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._notification_task
            self._notification_task = None
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._notification_queue:
            self._notification_queue = None
        self._notifications_enabled = False

    async def get(self, key: str) -> Any | None:
        entry = self._local_cache.get(key)
        if entry:
            return entry["value"]
        row = await self._fetch_remote(key)
        if not row:
            return None
        ttl = self._ttl_from_row(row)
        self._local_cache.set(key, row["value"], row["version"], ttl)
        return row["value"]

    async def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        await self._write_row(key, value, ttl_seconds)

    async def delete(self, key: str) -> None:
        if not self._pool:
            raise RuntimeError("Cache not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self._schema.entries_table} WHERE cache_key = $1", key
            )
        self._local_cache.delete(key)

    async def invalidate(self, key: str) -> None:
        await self.delete(key)

    async def get_or_set(self, key: str, loader: Loader, ttl_seconds: float | None = None) -> Any:
        value = await self.get(key)
        if value is not None:
            return value
        return await self._with_distributed_lock(key, loader, ttl_seconds)

    async def cleanup_expired(self) -> int:
        if not self._pool:
            raise RuntimeError("Cache not connected")
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(
                f"SELECT {self._schema.cleanup_function}($1)",
                self.settings.cleanup_batch_size,
            )
            return int(result or 0)

    async def _notification_worker(self) -> None:
        if not self._notification_queue:
            return
        try:
            while True:
                batch = [await self._notification_queue.get()]
                while True:
                    try:
                        batch.append(self._notification_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                self._process_notification_batch(batch)
        except asyncio.CancelledError:
            logger.debug("notification worker cancelled")
            raise

    def _process_notification_batch(self, payloads: list[str]) -> None:
        if not payloads:
            return
        if not self._local_cache.enabled or len(self._local_cache) == 0:
            return
        latest_events: dict[str, tuple[bool, int]] = {}
        for payload in payloads:
            decoded = _decode_notification_payload(payload)
            if not decoded:
                logger.warning("ignoring invalid notification payload: %s", payload)
                continue
            key, version, is_delete = decoded
            latest_events[key] = (is_delete, version)
        if not latest_events:
            return
        for key, (is_delete, version) in latest_events.items():
            if is_delete:
                self._local_cache.delete(key)
            else:
                self._local_cache.drop_if_stale(key, version)

    async def _fetch_remote(
        self, key: str, conn: asyncpg.Connection | None = None
    ) -> _CacheRow | None:
        if not self._pool:
            raise RuntimeError("Cache not connected")
        close_conn = False
        if conn is None:
            conn = await self._pool.acquire()
            close_conn = True
        try:
            row = await conn.fetchrow(
                f"""
                SELECT value, version, expires_at
                FROM {self._schema.entries_table}
                WHERE cache_key = $1
                  AND (expires_at IS NULL OR expires_at > timezone('UTC', now()))
                """,
                key,
            )
        finally:
            if close_conn:
                await self._pool.release(conn)
        if not row:
            return None
        value = self.serializer.loads(row["value"])
        return _CacheRow(value=value, version=row["version"], expires_at=row["expires_at"])

    async def _write_row(
        self,
        key: str,
        value: Any,
        ttl_seconds: float | None,
        conn: asyncpg.Connection | None = None,
    ) -> _CacheRow:
        if not self._pool:
            raise RuntimeError("Cache not connected")
        encoded = self.serializer.dumps(value)
        expires_at = None
        if ttl_seconds is None:
            ttl_seconds = self.settings.default_ttl_seconds
        if ttl_seconds > 0:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl_seconds)
        close_conn = False
        if conn is None:
            conn = await self._pool.acquire()
            close_conn = True
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {self._schema.entries_table} (cache_key, value, expires_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (cache_key)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    expires_at = EXCLUDED.expires_at,
                    version = {self._schema.entries_table}.version + 1,
                    updated_at = timezone('UTC', now())
                RETURNING version, expires_at
                """,
                key,
                encoded,
                expires_at,
            )
        finally:
            if close_conn:
                await self._pool.release(conn)
        typed_row = _CacheRow(value=value, version=row["version"], expires_at=row["expires_at"])
        ttl = self._ttl_from_row(typed_row)
        self._local_cache.set(key, typed_row["value"], typed_row["version"], ttl)
        return typed_row

    def _ttl_from_row(self, row: _CacheRow) -> float | None:
        if not row["expires_at"]:
            return None
        remaining = (row["expires_at"] - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, remaining)

    async def _with_distributed_lock(
        self, key: str, loader: Loader, ttl_seconds: float | None
    ) -> Any:
        if not self._pool:
            raise RuntimeError("Cache not connected")
        key_hash = _hash_key(key)
        conn = await self._pool.acquire()
        try:
            if not await self._acquire_lock(conn, key_hash):
                raise TimeoutError(f"failed to lock cache key {key}")
            row = await self._fetch_remote(key, conn)
            if row:
                ttl = self._ttl_from_row(row)
                self._local_cache.set(key, row["value"], row["version"], ttl)
                return row["value"]
            value = await resolve_loader(loader)
            await self._write_row(
                key, value, ttl_seconds or self.settings.default_ttl_seconds, conn
            )
            return value
        finally:
            try:
                await conn.execute("SELECT pg_advisory_unlock($1)", key_hash)
            finally:
                await self._pool.release(conn)

    async def _acquire_lock(self, conn: asyncpg.Connection, key_hash: int) -> bool:
        deadline = time.monotonic() + self.settings.lock_timeout_seconds
        while True:
            locked = await conn.fetchval("SELECT pg_try_advisory_lock($1)", key_hash)
            if locked:
                return True
            if time.monotonic() > deadline:
                return False
            await asyncio.sleep(0.05)


def _hash_key(key: str) -> int:
    digest = blake2b(key.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    if value >= 2**63:
        value -= 2**64
    return value


class _NotificationListener:
    """Dedicated connection that relays LISTEN/NOTIFY messages to a queue."""

    def __init__(self, dsn: str, channel: str, queue: asyncio.Queue[str]) -> None:
        self._dsn = dsn
        self._channel = channel
        self._queue = queue
        self._conn: asyncpg.Connection | None = None

    async def start(self) -> None:
        if self._conn:
            return
        self._conn = await asyncpg.connect(dsn=self._dsn)
        await self._conn.add_listener(self._channel, self._on_notify)

    async def stop(self) -> None:
        if not self._conn:
            return
        await self._conn.remove_listener(self._channel, self._on_notify)
        await self._conn.close()
        self._conn = None

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Notification queue full; dropping message")


_PAYLOAD_SEPARATOR = "\x1f"
_ESCAPED_SEPARATOR = _PAYLOAD_SEPARATOR * 2


def _decode_notification_payload(payload: str) -> tuple[str, int, bool] | None:
    if not payload:
        return None
    event_code = payload[0]
    rest = payload[1:]
    if not rest:
        return None
    sep_index = rest.find(_PAYLOAD_SEPARATOR)
    if sep_index == -1:
        return _decode_hex_payload(event_code, rest)
    version_part = rest[:sep_index]
    key_part = rest[sep_index + 1 :]
    if not version_part:
        return None
    try:
        version = int(version_part)
    except ValueError:
        return None
    key = key_part.replace(_ESCAPED_SEPARATOR, _PAYLOAD_SEPARATOR)
    is_delete = event_code == "d"
    return key, version, is_delete


def _decode_hex_payload(event_code: str, payload_rest: str) -> tuple[str, int, bool] | None:
    try:
        version_part, key_hex = payload_rest.split("|", 1)
    except ValueError:
        return None
    if not version_part or not key_hex:
        return None
    try:
        version = int(version_part)
    except ValueError:
        return None
    try:
        key_bytes = bytes.fromhex(key_hex)
        key = key_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return key, version, event_code == "d"

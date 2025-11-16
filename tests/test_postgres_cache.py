from __future__ import annotations

import asyncio

import pytest
from asyncpg.exceptions import TooManyConnectionsError

from postgres_cache import CacheSettings, PostgresCache
from postgres_cache.postgres_cache import _decode_notification_payload

_SEP = "\x1f"


def _payload(event_code: str, version: int, key: str) -> str:
    escaped = key.replace(_SEP, _SEP + _SEP)
    return f"{event_code}{version}{_SEP}{escaped}"


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(cache_client: PostgresCache) -> None:
    await cache_client.set("alpha", {"value": 1}, ttl_seconds=10)
    result = await cache_client.get("alpha")
    assert result == {"value": 1}


@pytest.mark.asyncio
async def test_expiration_removes_entry(cache_client: PostgresCache) -> None:
    await cache_client.set("ephemeral", "data", ttl_seconds=0.5)
    assert await cache_client.get("ephemeral") == "data"
    await asyncio.sleep(0.7)
    assert await cache_client.get("ephemeral") is None


@pytest.mark.asyncio
async def test_forced_invalidation(cache_client: PostgresCache) -> None:
    await cache_client.set("victim", 42, ttl_seconds=5)
    await cache_client.invalidate("victim")
    assert await cache_client.get("victim") is None


@pytest.mark.asyncio
async def test_notifications_clear_local_cache(db_dsn: str) -> None:
    settings = CacheSettings(dsn=db_dsn, default_ttl_seconds=60)
    async with PostgresCache(settings) as writer, PostgresCache(settings) as reader:
        await writer.set("shared", {"step": 1}, ttl_seconds=5)
        assert await reader.get("shared") == {"step": 1}
        await writer.set("shared", {"step": 2}, ttl_seconds=5)
        await asyncio.sleep(0.2)
        assert await reader.get("shared") == {"step": 2}


@pytest.mark.asyncio
async def test_get_or_set_runs_loader_once(cache_client: PostgresCache) -> None:
    counter = 0

    async def loader() -> int:
        nonlocal counter
        await asyncio.sleep(0.05)
        counter += 1
        return counter

    results = await asyncio.gather(*[
        cache_client.get_or_set("heavy", loader, ttl_seconds=1) for _ in range(5)
    ])
    assert all(value == 1 for value in results)
    assert counter == 1


@pytest.mark.asyncio
async def test_disable_notifications_skips_listener(db_dsn: str) -> None:
    settings = CacheSettings(dsn=db_dsn, disable_notiffy=True)
    cache = PostgresCache(settings)
    await cache.connect()
    try:
        assert cache._listener is None  # type: ignore[attr-defined]
        assert cache._notification_task is None  # type: ignore[attr-defined]
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_local_cache_can_be_disabled(db_dsn: str) -> None:
    settings = CacheSettings(dsn=db_dsn, local_max_entries=0)
    cache = PostgresCache(settings)
    await cache.connect()
    try:
        assert cache._listener is None  # type: ignore[attr-defined]
        assert cache._notification_task is None  # type: ignore[attr-defined]
        await cache.set("alpha", {"value": 1}, ttl_seconds=5)
        assert await cache.get("alpha") == {"value": 1}
        stats = cache._local_cache.stats()  # type: ignore[attr-defined]
        assert stats["items"] == 0
        assert stats["enabled"] == 0
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_connect_reports_too_many_connections(monkeypatch, db_dsn: str) -> None:
    async def fake_create_pool(*args, **kwargs):
        raise TooManyConnectionsError("sorry, too many clients already")

    monkeypatch.setattr("postgres_cache.postgres_cache.asyncpg.create_pool", fake_create_pool)
    cache = PostgresCache(CacheSettings(dsn=db_dsn))
    with pytest.raises(RuntimeError) as excinfo:
        await cache.connect()
    assert "disable_notiffy" in str(excinfo.value)


def test_decode_notification_payload_roundtrip() -> None:
    payload = _payload("u", 42, "alpha")
    decoded = _decode_notification_payload(payload)
    assert decoded == ("alpha", 42, False)


def test_decode_notification_payload_for_delete() -> None:
    payload = _payload("d", 3, "victim")
    decoded = _decode_notification_payload(payload)
    assert decoded == ("victim", 3, True)


def test_decode_notification_payload_rejects_garbage() -> None:
    assert _decode_notification_payload("bad-payload") is None


def test_process_notification_batch_drops_local_cache_entries() -> None:
    cache = PostgresCache(CacheSettings(dsn="postgresql://localhost/test"))
    cache._local_cache.set("victim", {"value": 1}, version=1, ttl_seconds=None)  # type: ignore[attr-defined]
    cache._local_cache.set("stale", {"value": 1}, version=1, ttl_seconds=None)  # type: ignore[attr-defined]

    cache._process_notification_batch([
        _payload("d", 1, "victim"),
        _payload("u", 2, "stale"),
    ])

    assert cache._local_cache.get("victim") is None  # type: ignore[attr-defined]
    assert cache._local_cache.get("stale") is None  # type: ignore[attr-defined]


def test_decode_notification_payload_handles_separator_in_keys() -> None:
    key = f"prefix{_SEP}suffix"
    payload = _payload("u", 7, key)
    decoded = _decode_notification_payload(payload)
    assert decoded == (key, 7, False)


def test_decode_notification_payload_handles_legacy_hex_format() -> None:
    payload = f"u12|{'legacy'.encode('utf-8').hex()}"
    decoded = _decode_notification_payload(payload)
    assert decoded == ("legacy", 12, False)

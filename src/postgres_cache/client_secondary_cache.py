"""Simple in-process cache with TTL tracking."""

from __future__ import annotations

import time
from typing import Any, Dict, TypedDict


class _LocalEntry(TypedDict):
    value: Any
    version: int
    expires_at: float | None


class ClientSecondaryCache:
    """Bounded dictionary with TTL semantics used for client-side caching."""

    def __init__(self, max_entries: int = 4096) -> None:
        self._max_entries = max_entries
        self._store: Dict[str, _LocalEntry] = {}

    def get(self, key: str) -> _LocalEntry | None:
        now = time.time()
        entry = self._store.get(key)
        if not entry:
            return None
        if _is_expired(entry, now):
            self._store.pop(key, None)
            return None
        return entry

    def set(self, key: str, value: Any, version: int, ttl_seconds: float | None) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        if len(self._store) >= self._max_entries:
            self._evict_one()
        self._store[key] = _LocalEntry(value=value, version=version, expires_at=expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def drop_if_stale(self, key: str, new_version: int) -> None:
        entry = self._store.get(key)
        if entry and entry["version"] < new_version:
            self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def _evict_one(self) -> None:
        if not self._store:
            return
        victim_key = min(self._store.items(), key=lambda kv: kv[1]["expires_at"] or float("inf"))[0]
        self._store.pop(victim_key, None)

    def stats(self) -> Dict[str, int]:
        return {"items": len(self._store)}


def _is_expired(entry: _LocalEntry, now: float) -> bool:
    expires_at = entry.get("expires_at")
    return expires_at is not None and expires_at <= now

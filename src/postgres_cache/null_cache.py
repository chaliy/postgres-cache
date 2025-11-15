"""No-op cache implementation for disabling caching."""

from __future__ import annotations

from typing import Any

from .base import Cache, Loader, resolve_loader


class NullCache(Cache):
    """A cache implementation that simply calls the loader every time."""

    async def __aenter__(self) -> "NullCache":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def invalidate(self, key: str) -> None:
        return None

    async def get_or_set(self, key: str, loader: Loader, ttl_seconds: float | None = None) -> Any:
        return await resolve_loader(loader)

    async def cleanup_expired(self) -> int:
        return 0

"""Base protocol definitions shared across cache implementations."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Protocol

Loader = Callable[[], Awaitable[Any]] | Callable[[], Any]


class Cache(Protocol):
    """Typed contract for cache clients."""

    async def __aenter__(self) -> "Cache": ...

    async def __aexit__(self, *exc: object) -> None: ...

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def invalidate(self, key: str) -> None: ...

    async def get_or_set(
        self, key: str, loader: Loader, ttl_seconds: float | None = None
    ) -> Any: ...

    async def cleanup_expired(self) -> int: ...


async def resolve_loader(loader: Loader) -> Any:
    """Execute a loader that may be sync or async."""

    result = loader()
    if inspect.isawaitable(result):
        return await result  # type: ignore[return-value]
    return result

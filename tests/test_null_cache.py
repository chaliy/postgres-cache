from __future__ import annotations

import pytest

from postgres_cache import NullCache


@pytest.mark.asyncio
async def test_null_cache_never_stores_values() -> None:
    cache = NullCache()
    async with cache:
        assert await cache.get("missing") is None
        await cache.set("foo", "bar")
        assert await cache.get("foo") is None

        counter = 0

        async def loader() -> int:
            nonlocal counter
            counter += 1
            return counter

        value1 = await cache.get_or_set("key", loader)
        value2 = await cache.get_or_set("key", loader)
        assert value1 == 1
        assert value2 == 2

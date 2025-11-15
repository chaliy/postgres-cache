"""Basic end-to-end example for the PostgreSQL cache client."""

from __future__ import annotations

import asyncio
import os
from typing import Dict

from postgres_cache import CacheSettings, PostgresCache

DEFAULT_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", DEFAULT_DSN)
    settings = CacheSettings(dsn=dsn)
    await PostgresCache.init_db(settings)
    async with PostgresCache(settings) as cache:

        async def loader() -> Dict[str, int]:
            print("cache miss: computing value...")
            await asyncio.sleep(0.1)
            return {"counter": 1}

        value = await cache.get_or_set("demo:key", loader, ttl_seconds=2)
        print("Initial fetch:", value)

        repeated = await cache.get("demo:key")
        print("Second fetch (served from cache):", repeated)

        await cache.invalidate("demo:key")
        print("Forced invalidation; next call will recompute")

        value = await cache.get_or_set("demo:key", loader, ttl_seconds=2)
        print("Fetched after invalidation:", value)


if __name__ == "__main__":
    asyncio.run(main())

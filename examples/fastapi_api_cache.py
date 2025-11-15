"""FastAPI example that serves a cached random number for 10 seconds."""

from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request

from postgres_cache import CacheSettings, PostgresCache

DEFAULT_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"
CACHE_KEY = "demo:random-number"


def build_settings() -> CacheSettings:
    return CacheSettings(dsn=os.getenv("DATABASE_URL", DEFAULT_DSN))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = build_settings()
    print("Initializing cache tables...")
    await PostgresCache.init_db(settings)
    cache = PostgresCache(settings)
    await cache.connect()
    app.state.cache = cache
    try:
        yield
    finally:
        await app.state.cache.close()


app = FastAPI(lifespan=lifespan)


async def get_cache(request: Request) -> PostgresCache:
    return request.app.state.cache


def build_payload() -> dict[str, Any]:
    return {
        "value": random.randint(1, 10_000),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/number")
async def cached_number(cache: PostgresCache = Depends(get_cache)) -> dict[str, Any]:
    async def loader() -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return build_payload()

    payload = await cache.get_or_set(CACHE_KEY, loader, ttl_seconds=10)
    return {"data": payload}


@app.post("/number")
async def set_number(cache: PostgresCache = Depends(get_cache)) -> dict[str, Any]:
    payload = build_payload()
    await cache.set(CACHE_KEY, payload, ttl_seconds=10)
    return {"data": payload}


# Run with: uvicorn examples.fastapi_api_cache:app --reload

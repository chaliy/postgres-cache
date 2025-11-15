#!/usr/bin/env python3
"""Ad-hoc load harness that simulates many clients hitting the cache."""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time
from dataclasses import dataclass
from typing import List

import asyncpg

from postgres_cache import CacheSettings, PostgresCache
from postgres_cache.schema import resolve_schema_names

DEFAULT_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL", DEFAULT_DSN))
    parser.add_argument("--writers", type=int, default=10)
    parser.add_argument("--reads", type=int, default=10)
    parser.add_argument("--write-iterations", type=int, default=200)
    parser.add_argument("--read-iterations", type=int, default=400)
    parser.add_argument("--ttl", type=float, default=2.0, help="TTL for written keys")
    args = parser.parse_args()

    settings = CacheSettings(dsn=args.dsn)
    await PostgresCache.init_db(settings)

    conn = await asyncpg.connect(dsn=args.dsn)
    try:
        print("Clearing existing cache entries before load test...")
        names = resolve_schema_names(settings.schema_prefix)
        await conn.execute(f"TRUNCATE {names.entries_table}")
    finally:
        await conn.close()

    total_clients = args.writers + args.reads
    caches = [PostgresCache(settings) for _ in range(total_clients)]
    for cache in caches:
        await cache.connect()

    writers = caches[: args.writers]
    readers = caches[args.writers : args.writers + args.reads]

    @dataclass
    class Result:
        kind: str
        latency: float
        hit_rate: float | None = None

    async def writer_task(client: PostgresCache, idx: int) -> Result:
        key = f"writer-{idx}"
        latencies: List[float] = []
        for iteration in range(args.write_iterations):
            payload = {"writer": idx, "iteration": iteration}
            start = time.perf_counter()
            await client.set(key, payload, ttl_seconds=args.ttl)
            latencies.append(time.perf_counter() - start)
            await asyncio.sleep(random.uniform(0.0, 0.02))
        return Result("write", statistics.mean(latencies))

    async def reader_task(client: PostgresCache) -> Result:
        latencies: List[float] = []
        hits = 0
        for _ in range(args.read_iterations):
            key = f"writer-{random.randrange(args.writers)}"
            start = time.perf_counter()
            value = await client.get(key)
            latencies.append(time.perf_counter() - start)
            if value:
                hits += 1
            await asyncio.sleep(random.uniform(0.0, 0.01))
        hit_rate = hits / args.read_iterations
        return Result("read", statistics.mean(latencies), hit_rate)

    try:
        writer_results = await asyncio.gather(*[
            writer_task(cache, idx) for idx, cache in enumerate(writers)
        ])
        reader_results = await asyncio.gather(*[reader_task(cache) for cache in readers])
    finally:
        await asyncio.gather(*[cache.close() for cache in caches])

    writer_latencies = [result.latency for result in writer_results]
    reader_latencies = [result.latency for result in reader_results]
    reader_hit_rates = [result.hit_rate for result in reader_results if result.hit_rate is not None]
    print(
        f"Writers: {args.writers}, mean latency: {statistics.mean(writer_latencies):.4f}s, "
        f"p95: {statistics.quantiles(writer_latencies, n=20)[-1]:.4f}s"
    )
    reader_hit_rate = statistics.mean(reader_hit_rates) if reader_hit_rates else 0.0
    print(
        f"Readers: {args.reads}, mean latency: {statistics.mean(reader_latencies):.4f}s, "
        f"p95: {statistics.quantiles(reader_latencies, n=20)[-1]:.4f}s, "
        f"hit rate: {reader_hit_rate:.2%}"
    )


if __name__ == "__main__":
    asyncio.run(main())

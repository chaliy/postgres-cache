#!/usr/bin/env python3
"""Benchmark Postgres-backed cache against Valkey."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Protocol

import asyncpg

from postgres_cache import CacheSettings, PostgresCache
from postgres_cache.schema import resolve_schema_names

try:
    from redis import asyncio as aioredis
except ModuleNotFoundError:  # pragma: no cover - redis is declared as a dependency
    aioredis = None  # type: ignore

DEFAULT_POSTGRES_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"
DEFAULT_VALKEY_URL = "redis://localhost:6379/0"


class BenchmarkClient(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None: ...

    async def get(self, key: str) -> Any | None: ...


@dataclass
class TaskResult:
    kind: str
    latencies: List[float]
    iterations: int
    hits: int
    started_at: float
    finished_at: float


@dataclass
class BenchmarkSummary:
    name: str
    writer_mean_ms: float
    writer_p95_ms: float
    writer_throughput: float
    reader_mean_ms: float
    reader_p95_ms: float
    reader_throughput: float
    reader_hit_rate: float


class PostgresBenchmarkClient:
    def __init__(self, settings: CacheSettings) -> None:
        self.settings = settings
        self._client: PostgresCache | None = None

    async def connect(self) -> None:
        self._client = PostgresCache(self.settings)
        await self._client.connect()

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if not self._client:
            raise RuntimeError("Client not connected")
        await self._client.set(key, value, ttl_seconds=ttl_seconds)

    async def get(self, key: str) -> Any | None:
        if not self._client:
            raise RuntimeError("Client not connected")
        return await self._client.get(key)


class ValkeyBenchmarkClient:
    def __init__(self, url: str) -> None:
        if aioredis is None:  # pragma: no cover - dependency provided via pyproject
            raise RuntimeError("redis extra is not installed")
        self._url = url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        if aioredis is None:  # pragma: no cover
            return
        self._client = aioredis.from_url(
            self._url, encoding="utf-8", decode_responses=True
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if not self._client:
            raise RuntimeError("Client not connected")
        payload = json.dumps(value)
        ttl_ms = max(1, int(ttl_seconds * 1000))
        await self._client.set(key, payload, px=ttl_ms)

    async def get(self, key: str) -> Any | None:
        if not self._client:
            raise RuntimeError("Client not connected")
        data = await self._client.get(key)
        if data is None:
            return None
        return json.loads(data)


class BenchmarkBackend(Protocol):
    name: str

    async def prepare(self) -> None: ...

    def make_client(self) -> BenchmarkClient: ...


class PostgresBackend:
    def __init__(
        self,
        dsn: str,
        name: str = "postgres",
        *,
        disable_local_cache: bool = False,
        disable_notify: bool = False,
    ) -> None:
        settings = CacheSettings(dsn=dsn)
        if disable_local_cache:
            settings = replace(settings, local_max_entries=0)
        if disable_notify:
            settings = replace(settings, disable_notiffy=True)
        self.name = name
        self.settings = settings

    async def prepare(self) -> None:
        await PostgresCache.init_db(self.settings)
        conn = await asyncpg.connect(dsn=self.settings.dsn)
        try:
            names = resolve_schema_names(self.settings.schema_prefix)
            await conn.execute(f"TRUNCATE {names.entries_table}")
        finally:
            await conn.close()

    def make_client(self) -> BenchmarkClient:
        return PostgresBenchmarkClient(self.settings)


class ValkeyBackend:
    def __init__(self, url: str) -> None:
        self.name = "valkey"
        self._url = url

    async def prepare(self) -> None:
        if aioredis is None:
            raise RuntimeError("redis extra is not installed")
        client = aioredis.from_url(self._url)
        try:
            await client.flushdb()
        finally:
            await client.close()

    def make_client(self) -> BenchmarkClient:
        return ValkeyBenchmarkClient(self._url)


@dataclass
class BenchmarkConfig:
    writers: int
    readers: int
    write_iterations: int
    read_iterations: int
    keyspace: int
    ttl: float
    writer_jitter: float = 0.005
    reader_jitter: float = 0.002


async def run_benchmark(backend: BenchmarkBackend, config: BenchmarkConfig) -> BenchmarkSummary:
    await backend.prepare()
    total_clients = config.writers + config.readers
    clients = [backend.make_client() for _ in range(total_clients)]
    await asyncio.gather(*(client.connect() for client in clients))

    writers = clients[: config.writers]
    readers = clients[config.writers : config.writers + config.readers]
    keyspace = [f"benchmark-key-{i}" for i in range(config.keyspace)]

    async def writer_task(client: BenchmarkClient, idx: int) -> TaskResult:
        latencies: List[float] = []
        started = time.perf_counter()
        for iteration in range(config.write_iterations):
            key = random.choice(keyspace)
            payload = {"writer": idx, "iteration": iteration, "ts": time.time()}
            op_start = time.perf_counter()
            await client.set(key, payload, ttl_seconds=config.ttl)
            latencies.append(time.perf_counter() - op_start)
            if config.writer_jitter:
                await asyncio.sleep(random.uniform(0, config.writer_jitter))
        finished = time.perf_counter()
        return TaskResult(
            "write",
            latencies,
            iterations=config.write_iterations,
            hits=0,
            started_at=started,
            finished_at=finished,
        )

    async def reader_task(client: BenchmarkClient) -> TaskResult:
        latencies: List[float] = []
        hits = 0
        started = time.perf_counter()
        for _ in range(config.read_iterations):
            key = random.choice(keyspace)
            op_start = time.perf_counter()
            value = await client.get(key)
            latencies.append(time.perf_counter() - op_start)
            if value is not None:
                hits += 1
            if config.reader_jitter:
                await asyncio.sleep(random.uniform(0, config.reader_jitter))
        finished = time.perf_counter()
        return TaskResult(
            "read",
            latencies,
            iterations=config.read_iterations,
            hits=hits,
            started_at=started,
            finished_at=finished,
        )

    try:
        tasks = [writer_task(client, idx) for idx, client in enumerate(writers)]
        tasks.extend(reader_task(client) for client in readers)
        results = await asyncio.gather(*tasks)
    finally:
        await asyncio.gather(*(client.close() for client in clients))

    writer_results = [res for res in results if res.kind == "write"]
    reader_results = [res for res in results if res.kind == "read"]

    def _flatten_latencies(items: Iterable[TaskResult]) -> List[float]:
        values: List[float] = []
        for item in items:
            values.extend(item.latencies)
        return values

    writer_latencies = _flatten_latencies(writer_results)
    reader_latencies = _flatten_latencies(reader_results)

    def _p95(values: List[float]) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        return statistics.quantiles(values, n=20)[-1]

    def _mean(values: List[float]) -> float:
        if not values:
            return 0.0
        return statistics.mean(values)

    def _throughput(results: List[TaskResult]) -> float:
        if not results:
            return 0.0
        start = min(result.started_at for result in results)
        end = max(result.finished_at for result in results)
        duration = max(end - start, 1e-9)
        iterations = sum(result.iterations for result in results)
        return iterations / duration

    reader_iterations = sum(result.iterations for result in reader_results)
    reader_hits = sum(result.hits for result in reader_results)
    hit_rate = (reader_hits / reader_iterations) if reader_iterations else 0.0

    return BenchmarkSummary(
        name=backend.name,
        writer_mean_ms=_mean(writer_latencies) * 1000,
        writer_p95_ms=_p95(writer_latencies) * 1000,
        writer_throughput=_throughput(writer_results),
        reader_mean_ms=_mean(reader_latencies) * 1000,
        reader_p95_ms=_p95(reader_latencies) * 1000,
        reader_throughput=_throughput(reader_results),
        reader_hit_rate=hit_rate,
    )


def format_summary_table(results: List[BenchmarkSummary]) -> str:
    headers = [
        "backend",
        "write mean (ms)",
        "write p95 (ms)",
        "write ops/s",
        "read mean (ms)",
        "read p95 (ms)",
        "read ops/s",
        "hit rate",
    ]
    rows = [
        [
            result.name,
            f"{result.writer_mean_ms:.3f}",
            f"{result.writer_p95_ms:.3f}",
            f"{result.writer_throughput:.1f}",
            f"{result.reader_mean_ms:.3f}",
            f"{result.reader_p95_ms:.3f}",
            f"{result.reader_throughput:.1f}",
            f"{result.reader_hit_rate:.1%}",
        ]
        for result in results
    ]

    col_widths = [max(len(header), *(len(row[idx]) for row in rows)) for idx, header in enumerate(headers)]

    def _format_row(row: List[str]) -> str:
        return " | ".join(cell.ljust(col_widths[idx]) for idx, cell in enumerate(row))

    lines = [_format_row(headers)]
    lines.append("-+-".join("-" * width for width in col_widths))
    lines.extend(_format_row(row) for row in rows)
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-dsn", default=os.getenv("POSTGRES_DSN", DEFAULT_POSTGRES_DSN))
    parser.add_argument("--valkey-url", default=os.getenv("VALKEY_URL", DEFAULT_VALKEY_URL))
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=[
            "postgres",
            "postgres-no-local-cache",
            "postgres-no-notify",
            "valkey",
        ],
        default=[
            "postgres",
            "postgres-no-local-cache",
            "postgres-no-notify",
            "valkey",
        ],
        help="Backends to benchmark",
    )
    parser.add_argument("--writers", type=int, default=16, help="Number of concurrent writers")
    parser.add_argument("--readers", type=int, default=32, help="Number of concurrent readers")
    parser.add_argument("--write-iterations", type=int, default=400, help="Writes per writer client")
    parser.add_argument("--read-iterations", type=int, default=800, help="Reads per reader client")
    parser.add_argument("--keyspace", type=int, default=64, help="Number of cache keys in the rotation")
    parser.add_argument("--ttl", type=float, default=5.0, help="TTL for all writes in seconds")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    config = BenchmarkConfig(
        writers=args.writers,
        readers=args.readers,
        write_iterations=args.write_iterations,
        read_iterations=args.read_iterations,
        keyspace=args.keyspace,
        ttl=args.ttl,
    )

    backends: List[BenchmarkBackend] = []
    for backend_name in args.backends:
        if backend_name == "postgres":
            backends.append(PostgresBackend(args.postgres_dsn))
        elif backend_name == "postgres-no-local-cache":
            backends.append(
                PostgresBackend(
                    args.postgres_dsn,
                    name="postgres-no-local-cache",
                    disable_local_cache=True,
                )
            )
        elif backend_name == "postgres-no-notify":
            backends.append(
                PostgresBackend(
                    args.postgres_dsn,
                    name="postgres-no-notify",
                    disable_notify=True,
                )
            )
        elif backend_name == "valkey":
            if not args.valkey_url:
                raise SystemExit("--valkey-url must be provided when benchmarking Valkey")
            backends.append(ValkeyBackend(args.valkey_url))

    if not backends:
        raise SystemExit("No backends selected")

    results: List[BenchmarkSummary] = []
    for backend in backends:
        print(f"\nRunning benchmark for {backend.name}...")
        summary = await run_benchmark(backend, config)
        results.append(summary)
        print(
            f"Completed {backend.name}: write mean={summary.writer_mean_ms:.3f}ms, "
            f"read mean={summary.reader_mean_ms:.3f}ms, hit rate={summary.reader_hit_rate:.1%}"
        )

    print("\n=== Benchmark summary ===")
    print(format_summary_table(results))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

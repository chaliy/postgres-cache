[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg)](https://vshymanskyy.github.io/StandWithUkraine/)

# postgres-cache

Postgres Cache is a single purpose library to cover a need of a distributed cache and not willing to use Redis/Valkey/Memcached or other external caching systems.

Idea of the library is to store persisted cache in Postgres, and utilize couple of specific optimizations to make it behave comparable with other caching solutions. Local in-memory cache with invalidation via LISTEN/NOTIFY are among those optimizations.

## Features

- **Pure Postgres backend** – no bespoke services, just a single table plus triggers and LISTEN/NOTIFY for invalidations.

- **TTL + forced invalidation** – each entry stores an optional `expires_at`, and clients can delete rows explicitly.

- **Dogpile protection** – `get_or_set` uses PostgreSQL advisory locks so only one client recomputes missing items.

- **Local in-memory cache** – every client keeps a bounded TTL cache that is updated/evicted via database notifications.

- **Configurable Postgres objects** – `notify_channel` controls the LISTEN/NOTIFY channel, and `schema_prefix` namespaces every table/function created by the library.

- **Optional notifications** – set `disable_notiffy=True` to skip LISTEN/NOTIFY when Postgres connection budgets are tight.

- **Load harness** – runnable script that spins up many clients to assert read consistency and provide latency stats.

## Usage

Install the library from PyPI:

```bash
pip install postgres-cache
```

### PostgreSQL-backed cache

```python
import asyncio
from postgres_cache import CacheSettings, PostgresCache

async def main():
    dsn = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"
    settings = CacheSettings(
        dsn=dsn,
        notify_channel="cache_events_marketing",
        schema_prefix="marketing_",
    )
    await PostgresCache.init_db(settings)
    async with PostgresCache(settings) as cache:
        await cache.set("profile:123", {"name": "Ava"}, ttl_seconds=300)
        user = await cache.get_or_set(
            "profile:456",
            loader=lambda: {"name": "Nova"},
            ttl_seconds=120,
        )
        print(user)

asyncio.run(main())
```

The clients automatically:
- Maintain a bounded local cache.
- Listen on `notify_channel` so updates/deletes on any node evict stale entries everywhere.
- Use advisory locks on `get_or_set` to avoid thundering herds.

### Null cache

Need a drop-in implementation that always hits the loader (for local dev or tests)?
```python
from postgres_cache import NullCache

async with NullCache() as cache:
    await cache.set("noop", "value")  # does nothing
    assert await cache.get("noop") is None
```

## Development setup

Python 3.11+ and uv are required for local development.

- `make tests` – run the pytest suite (requires Postgres running via `docker compose up`).
- `make lint-and-format` – format & lint code
- `make harness-load-test` – launch the load harness against a local Postgres.
- `make examples-basic-usage` / `make examples-fastapi-api-cache` – run example scripts.

## Load testing

See [`harness/README.md`](harness/README.md) for the load-test instructions and `make harness-load-test` helper.

## Benchmarking

See [`benchmarks/README.md`](benchmarks/README.md) for installation steps, CLI flags, and instructions for adding more backends to the report. Note that these numbers come from an intentionally narrow, unrealistic benchmark that ignores network latency to focus purely on cache/DB interactions on the same host.

### Benchmark summary

| backend                 | write mean (ms) | write p95 (ms) | write ops/s | read mean (ms) | read p95 (ms) | read ops/s | hit rate |
|-------------------------|-----------------|----------------|-------------|----------------|---------------|------------|----------|
| postgres-cache          | 12.887          | 29.943         | 1023.4      | 1.937          | 5.099         | 10071.9    | 95.9%    |
| postgres-no-local-cache | 4.290           | 8.626          | 2284.4      | 2.274          | 3.600         | 9364.5     | 97.9%    |
| postgres-no-notify      | 1.458           | 2.958          | 3865.2      | 0.208          | 1.624         | 23652.9    | 98.4%    |
| valkey                  | 0.502           | 0.691          | 4804.9      | 0.468          | 0.683         | 18786.0    | 99.1%    |

`postgres-no-local-cache` disables the client-side cache (`local_max_entries=0`), so the benchmark issues direct Postgres reads without invalidating values pulled from the backend.
`postgres-no-notify` turns off LISTEN/NOTIFY fan-out (`disable_notiffy=True`), which means no backend invalidations occur and only the local TTL policy expires entries.
Interpretation: "optimizations" implemented in this libray, does not provide any advantage.

## License

Released under the [MIT License](LICENSE).

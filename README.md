# postgres-cache

Postgres Cache is a single purpose library to cover a need of a distributed cache and not willing to use Redis/Valkey/Memcached or other external caching systems.

Idea of the library is to store persisted cache in Postgres, and utilize couple of specific optimizations to make it behave comparable with other caching solutions.

## Features

- **Pure Postgres backend** – no bespoke services, just a single table plus triggers and LISTEN/NOTIFY for invalidations.

- **TTL + forced invalidation** – each entry stores an optional `expires_at`, and clients can delete rows explicitly.

- **Dogpile protection** – `get_or_set` uses PostgreSQL advisory locks so only one client recomputes missing items.

- **Local in-memory cache** – every client keeps a bounded TTL cache that is updated/evicted via database notifications.

- **Configurable Postgres objects** – `notify_channel` controls the LISTEN/NOTIFY channel, and `schema_prefix` namespaces every table/function created by the library.

- **Optional notifications** – set `disable_notiffy=True` to skip LISTEN/NOTIFY when Postgres connection budgets are tight.

- **Load harness** – runnable script that spins up many clients to assert read consistency and provide latency stats.

## Usage

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

## Load harness & schema

- See [`harness/README.md`](harness/README.md) for the load-test instructions and `make harness-load-test` helper.
- Schema details (tables/triggers/functions) live in the same document so the operational guidance stays in one place.

## License

Released under the [MIT License](LICENSE).

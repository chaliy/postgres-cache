"""Simple migration runner for local development."""

from __future__ import annotations

import argparse
import asyncio
import os

from postgres_cache import CacheSettings, PostgresCache

DEFAULT_DSN = "postgresql://cache_user:cache_pass@localhost:5432/cache_proto"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL", DEFAULT_DSN))
    parser.add_argument(
        "--notify-channel", default=os.getenv("CACHE_NOTIFY_CHANNEL", "cache_events")
    )
    parser.add_argument("--schema-prefix", default=os.getenv("CACHE_SCHEMA_PREFIX", ""))
    args = parser.parse_args()
    settings = CacheSettings(
        dsn=args.dsn,
        notify_channel=args.notify_channel,
        schema_prefix=args.schema_prefix,
    )
    asyncio.run(PostgresCache.init_db(settings))


if __name__ == "__main__":
    main()

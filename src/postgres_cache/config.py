"""Configuration objects for the cache client."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_NOTIFY_CHANNEL = "cache_events"
DEFAULT_OBJECT_PREFIX = ""


@dataclass(slots=True)
class CacheSettings:
    """Runtime knobs for the cache client.

    Attributes:
        dsn: PostgreSQL DSN used for all pool connections.
        notify_channel: LISTEN/NOTIFY channel name for cross-node invalidations.
        disable_notiffy: Skip LISTEN/NOTIFY wiring to conserve database connections.
        schema_prefix: Optional prefix applied to every table/function the library creates.
        min_pool_size: Minimum connection pool size per client instance.
        max_pool_size: Maximum connection pool size per client instance.
        local_max_entries: Size of the client-side secondary cache.
        default_ttl_seconds: TTL applied when none is provided explicitly.
        notification_queue_size: Max pending notifications per client listener.
        lock_timeout_seconds: Advisory-lock wait timeout for dogpile protection.
        fetch_timeout_seconds: (Reserved for future use.)
        cleanup_batch_size: Rows to delete per invocation of the cleanup function.
    """

    dsn: str
    notify_channel: str = DEFAULT_NOTIFY_CHANNEL
    disable_notiffy: bool = False
    schema_prefix: str = DEFAULT_OBJECT_PREFIX
    min_pool_size: int = 1
    max_pool_size: int = 10
    local_max_entries: int = 4096
    default_ttl_seconds: float = 300.0
    notification_queue_size: int = 2048
    lock_timeout_seconds: float = 5.0
    fetch_timeout_seconds: float = 2.0
    cleanup_batch_size: int = 500

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("CacheSettings requires a non-empty 'dsn'")
        if not self._valid_prefix(self.schema_prefix):
            raise ValueError("schema_prefix may only contain letters, digits, and underscores")

    @staticmethod
    def _valid_prefix(prefix: str) -> bool:
        if not prefix:
            return True
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        return all(char in allowed for char in prefix)

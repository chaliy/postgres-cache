"""Helpers for deriving database object names from configuration."""

from __future__ import annotations

from dataclasses import dataclass


def _sanitize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if not all(char in allowed for char in prefix):
        raise ValueError("schema_prefix may only contain letters, digits, and underscores")
    return prefix


@dataclass(frozen=True)
class SchemaNames:
    """Resolved identifiers for PostgreSQL objects."""

    entries_table: str
    expires_index: str
    set_updated_function: str
    set_updated_trigger: str
    broadcast_function: str
    broadcast_trigger: str
    cleanup_function: str
    schema_table: str


def resolve_schema_names(prefix: str) -> SchemaNames:
    clean_prefix = _sanitize_prefix(prefix)

    def name(suffix: str) -> str:
        return f"{clean_prefix}{suffix}"

    return SchemaNames(
        entries_table=name("cache_entries"),
        expires_index=name("cache_entries_expires_idx"),
        set_updated_function=name("cache_set_updated_at"),
        set_updated_trigger=name("cache_set_updated_at_trigger"),
        broadcast_function=name("cache_broadcast_change"),
        broadcast_trigger=name("cache_broadcast_change_trigger"),
        cleanup_function=name("cache_cleanup_expired"),
        schema_table=name("cache_schema"),
    )


__all__ = ["SchemaNames", "resolve_schema_names"]

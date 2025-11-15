# Terminology

## PostgreSQL notify channel

- `CacheSettings.notify_channel` sets the LISTEN/NOTIFY channel name.
- Every write/delete triggers the broadcast trigger, which publishes a JSON payload to that channel (defaults to `cache_events`).
- Each `PostgresCache` instance maintains a dedicated LISTEN connection; when a notification arrives, the local in-memory cache evicts or refreshes the associated key.
- Notifications can be disabled entirely by setting `disable_notiffy=True`, which saves two database connections per client at the expense of cross-node invalidations.

## Object prefix

- `CacheSettings.schema_prefix` is prepended to every PostgreSQL object (`tables`, `functions`, `triggers`, `indexes`, and the schema metadata table) that the library creates.
- Using unique prefixes lets multiple tenants share the same database safely.

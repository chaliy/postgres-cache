# Benchmarks

This directory hosts the asyncio benchmark harness that compares the Postgres-backed cache
against Valkey/Redis under concurrent writer + reader load.

## Requirements

- Docker + Docker Compose (used to run Postgres + Valkey locally).
- Python 3.11 with the benchmark extras installed:
  ```bash
  uv pip install -e '.[benchmarks]'
  ```

## Quick start

The fastest way to boot the services and run all available backends is the `make benchmark`
target:

```bash
make benchmark
```

The target will:
1. Launch the services declared in [`compose.yaml`](compose.yaml) (Postgres + Valkey).
2. Run `benchmarks/cache_benchmark.py`, which hits the following backends by default:
   - `postgres` – full feature set.
   - `postgres-no-local-cache` – disables the client-side cache (`local_max_entries=0`).
   - `postgres-no-notify` – disables LISTEN/NOTIFY fan-out (`disable_notiffy=True`).
   - `valkey` – native Valkey/Redis.
3. Tear the containers down when the benchmark completes (even if it fails).

## Manual run

Want to tweak CLI flags manually? These steps mirror the make target:

```bash
docker compose -f benchmarks/compose.yaml up -d
python benchmarks/cache_benchmark.py --writers 24 --readers 48 --keyspace 96
# ...additional CLI tweaks...
docker compose -f benchmarks/compose.yaml down
```

Environment variables `POSTGRES_DSN` and `VALKEY_URL` control the connection targets. The
defaults already line up with the Docker Compose stack (`postgresql://cache_user:cache_pass@localhost:15432/cache_proto`
and `redis://localhost:16379/0`), which avoids clashing with the load-test harness ports.

To benchmark a subset of backends use the `--backends` flag:

```bash
python benchmarks/cache_benchmark.py --backends postgres valkey
```

Additional flags (`--writers`, `--readers`, `--ttl`, `--write-iterations`, `--read-iterations`,
`--keyspace`) make it straightforward to dial the workload up or down.

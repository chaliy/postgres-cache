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
   - `postgres-cache` – full feature set.
   - `postgres-no-local-cache` – disables the client-side cache (`local_max_entries=0`),
     effectively issuing direct Postgres reads without invalidating values coming from
     the backend.
   - `postgres-no-notify` – disables LISTEN/NOTIFY fan-out (`disable_notiffy=True`),
     so backend invalidation is turned off and only local TTL expiry applies.
   - `valkey` – native Valkey/Redis.
3. Tear the containers down when the benchmark completes (even if it fails).

Need to reset the Docker state completely? `make benchmark-cleanup` runs
`docker compose -f benchmarks/compose.yaml down -v --remove-orphans`, removing the
Postgres and Valkey containers along with their volumes.

Looking for something closer to a managed-service deployment (application on EC2/ECS, RDS, and
Valkey all in the same AWS region)? Use the `make benchmark-simulated-network` target instead.
It runs the same workflow but injects ~1.5 ms of latency plus 0.5 ms of jitter ahead of every
cache call—roughly the cross-AZ round-trip most teams see for managed services within a single
region.

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
python benchmarks/cache_benchmark.py --backends postgres-cache valkey
```

Additional flags (`--writers`, `--readers`, `--ttl`, `--write-iterations`, `--read-iterations`,
`--keyspace`) make it straightforward to dial the workload up or down.

### Network emulation

Need to mimic higher latency links without touching Docker networking? Use the artificial
latency flags exposed by the benchmark script:

```bash
python benchmarks/cache_benchmark.py --network-latency-ms 15 --network-jitter-ms 5
```

`--network-latency-ms` adds a fixed delay before every cache operation, while
`--network-jitter-ms` adds a random 0..N millisecond offset on top. This combination simulates
WAN-like conditions and lets you quickly evaluate how local caching + invalidation behave when
the Postgres round-trip gets slower.

For a ready-made profile that approximates AWS managed services within the same region, run
`make benchmark-simulated-network`, which hard-codes a 1.5 ms base delay with 0.5 ms jitter.

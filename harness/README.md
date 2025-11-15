# Load harness / proof of scale

`harness/load_test.py` opens dozens of independent clients, all hammering cache with short TTLs. The script asserts monotonic versions (read consistency) and reports loader executions + worker latencies.

Example:

```bash
make harness-load-test \
  -- --dsn postgresql://cache_user:cache_pass@localhost:5432/cache_proto
```
Or invoke `python harness/load_test.py` directly. Both approaches print aggregated mean/p95 latencies for writers/readers and the reader hit rate so you can gauge cache effectiveness at a glance.

## How to run

1. `docker compose up` (from this directory) to start Postgres.
2. `make harness-load-test` or `python harness/load_test.py --writers 20 --reads 30 --write-iterations 200 --read-iterations 400`

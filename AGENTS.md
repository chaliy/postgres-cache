# AGENTS

Project goal: implement a distributed cache solution that uses PostgreSQL as the backend and a Python client.

## Dev environment hints

- Uses uv, so `uv sync` to setup dependecies
- Test harness is located in ./harness folder, use docker compose to run PostgreSQL instance for tests and enxamples

## Testing hints

- `make tests` - runs all tests
- Most tests require a running PostgreSQL instance. There is docker compose file in ./harness folder with good config

## Benchmarking hints

- Instructions in ./benchmarks/AGENTS.md

## PR instructions

- Title format: <Title>
- Always run `make lint-and-format` before submitting a PR
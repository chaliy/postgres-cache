.PHONY: lint lint-and-format format tests examples-basic-usage examples-fastapi-api-cache harness-load-test benchmark

lint-and-format: format lint

format:
	ruff format .

lint:
	ruff check --fix .

tests:
	pytest

examples-basic-usage:
	python examples/basic_usage.py

examples-fastapi-api-cache:
	uvicorn examples.fastapi_api_cache:app --reload

harness-load-test:
	python harness/load_test.py

benchmark:
	bash -c 'set -euo pipefail; \
 		docker compose -f benchmarks/compose.yaml up -d --wait --wait-timeout 120; \
  		trap "docker compose -f benchmarks/compose.yaml down" EXIT; \
  		python benchmarks/cache_benchmark.py'

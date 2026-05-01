.DEFAULT_GOAL := all

.PHONY: install install-all test test-cov lint lint-fix typecheck demo stats clean all

install:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[all,dev]"

test:
	pytest tests/ -q

test-cov:
	pytest tests/ --cov=retrace --cov-report=term-missing

lint:
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

typecheck:
	mypy src/retrace/

demo:
	python tools/generate_demo.py generate

stats:
	python tools/readme_stats.py update

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf dist/ build/

all: lint test typecheck

# Contributing to re:trace

Thanks for your interest in contributing! This document covers how to get started.

## How to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected vs. actual behavior, and your OS/Python version.
- **Feature requests** — Open an issue describing the use case. PRs without a linked issue may be closed.
- **Code contributions** — Fork the repo, make your changes on a branch, and open a PR against `master`.

## Development Setup

```bash
git clone https://github.com/ericrihm/retrace.git
cd retrace
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest                          # full suite (~1377 tests)
pytest tests/test_parser.py     # single module
pytest -q --tb=short            # quiet with short tracebacks
```

All tests must pass before submitting a PR. New functionality should include tests.

## Code Style

re:trace uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
ruff check src tests            # lint
ruff format src tests           # format
```

CI enforces both. Run them locally before pushing to avoid failed checks.

## PR Process

1. Open an issue first for non-trivial changes.
2. Branch off `master` using a descriptive name (`fix/jtag-parser-crash`, `feat/bga-detection`).
3. Keep PRs focused — one logical change per PR.
4. Update docstrings and comments for any changed public API.
5. Ensure `pytest` and `ruff check` both pass.
6. Fill out the PR description with what changed and why.

A maintainer will review within a few days. Small, well-tested PRs are merged fastest.

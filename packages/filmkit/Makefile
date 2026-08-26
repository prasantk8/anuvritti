PY := .venv/bin/python
.DEFAULT_GOAL := check

.PHONY: install lint format types test cov check clean

install:
	$(PY) -m pip install -q -e ".[dev]"

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:
	$(PY) -m ruff format src tests
	$(PY) -m ruff check src tests --fix

types:
	$(PY) -m mypy

test:
	$(PY) -m pytest

# The gate this package inherited: >= 90%. Every expensive dependency here is a
# port, so there is no honest excuse for an untested branch - a browser and an
# encoder can both be faked, and what is worth testing is the decision, not the
# pixels.
cov:
	$(PY) -m pytest --cov=filmkit --cov-report=term-missing --cov-fail-under=90

check: lint types cov

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} +

PY := .venv/bin/python
.DEFAULT_GOAL := check

.PHONY: install lint format types test cov cov-core check run tracker clean world design specimen

install:
	$(PY) -m pip install -q -r requirements-dev.txt

# packages/world emits the design language. tests/design refuses to run against a
# stale dist, so the gate builds it first rather than testing yesterday's interface.
world:
	npm --prefix packages/world run build --silent

design: world
	$(PY) -m pytest tests/design -q
	npm --prefix packages/world test --silent

specimen: world
	@echo "serving packages/world/specimen at http://127.0.0.1:8765/specimen/"
	@cd packages/world && python3 -m http.server 8765 --bind 127.0.0.1

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

# CLAUDE.md: >= 90% unit. The domain and application layers hold every rule the PRD
# promises, so they carry the strict gate.
cov-core:
	$(PY) -m pytest --cov=anuvritti.domain --cov=anuvritti.application \
		--cov-report=term-missing --cov-fail-under=90

# CLAUDE.md: >= 80% integration. Adapters and the HTTP edge are included here.
cov:
	$(PY) -m pytest --cov=anuvritti --cov-report=term-missing --cov-fail-under=90

check: world lint types cov-core cov design

run:
	$(PY) -m uvicorn anuvritti.interfaces.http.asgi:app --host 0.0.0.0 --port 8000

tracker:
	$(PY) scripts/tracker.py show

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} +

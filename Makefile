PY := .venv/bin/python
.DEFAULT_GOAL := check

.PHONY: install lint format types test cov cov-core check run tracker clean world client app design filmkit specimen

install:
	$(PY) -m pip install -q -r requirements-dev.txt

# packages/world emits the design language. tests/design refuses to run against a
# stale dist, so the gate builds it first rather than testing yesterday's interface.
world:
	npm --prefix packages/world run build --silent

# packages/client is generated from docs/contracts/openapi.yaml. The generated file is
# committed, and `make check` fails if it no longer matches the contract - a generated
# artefact that is not verified is just a second source of truth wearing the first's clothes.
client:
	$(PY) packages/client/codegen/generate.py

# Deliberately does *not* depend on `client`: regenerating and then checking for drift
# would check the file against itself and pass forever. `make client` is a decision.
# The app's decisions - what a share means, what comes back today - are pure functions
# with no `expo-*` import, so they run here. What cannot run here is the view layer, which
# needs a device; TASK-513 is the checklist for that.
app:
	npm --prefix apps/anuvritti test --silent

design: world
	$(PY) -m pytest tests/design -q
	npm --prefix packages/world test --silent
	$(PY) packages/client/codegen/generate.py --check
	npm --prefix packages/client test --silent
	npm --prefix apps/anuvritti test --silent

# filmkit is source in this monorepo, not an opaque dependency. Its own strict package
# gate stays authoritative, including the compiler's branch-coverage promise.
filmkit:
	$(MAKE) -C packages/filmkit check PY=$(CURDIR)/$(PY)

specimen: world
	@echo "serving packages/world/specimen at http://127.0.0.1:8765/specimen/"
	@cd packages/world && python3 -m http.server 8765 --bind 127.0.0.1

lint:
	$(PY) -m ruff check src tests packages/client/codegen
	$(PY) -m ruff format --check src tests packages/client/codegen

format:
	$(PY) -m ruff format src tests packages/client/codegen
	$(PY) -m ruff check src tests packages/client/codegen --fix

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

check: world lint types cov-core cov design filmkit

run:
	$(PY) -m uvicorn anuvritti.interfaces.http.asgi:app --host 0.0.0.0 --port 8000

tracker:
	$(PY) scripts/tracker.py show

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} +

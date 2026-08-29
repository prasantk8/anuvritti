PY := .venv/bin/python
.DEFAULT_GOAL := check

.PHONY: install lint format types types-ts test cov cov-core check run tracker clean world client app design filmkit specimen film film-prepare film-font-review teaser

install:
	$(PY) -m pip install -q -r requirements-dev.txt
	$(PY) -m playwright install chromium
	npm --prefix packages/world install --no-package-lock --silent

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

# A FilmExport is already plaintext family material. Its browser workspace and the
# founder's inspection still therefore stay under ignored var/, beside the finished film.
FILM_OUTPUT ?= var/film/film.mp4
FILM_STILL ?= var/film/still.png

film-prepare:
	@test -n "$(REQUIREMENTS)" || (echo "usage: make film-prepare REQUIREMENTS=/path/to/render-requirements.json" && exit 2)
	node packages/world/scripts/prepare-film.ts "$(REQUIREMENTS)" --requirements-only
	npm --prefix packages/world install --no-package-lock
	node packages/world/scripts/prepare-film.ts "$(REQUIREMENTS)"

film-font-review:
	@test -n "$(CANDIDATE_FONTS)" -a -n "$(CANDIDATE_VERSION)" || (echo "usage: make film-font-review CANDIDATE_FONTS=/path/to/node_modules CANDIDATE_VERSION=5.4.0" && exit 2)
	node packages/world/scripts/review-film-fonts.ts \
		--candidate-root "$(CANDIDATE_FONTS)" --candidate-version "$(CANDIDATE_VERSION)" \
		--output var/film/font-review-$(CANDIDATE_VERSION)

film:
	@test -n "$(ARCHIVE)" || (echo "usage: make film ARCHIVE=/path/to/FilmExport" && exit 2)
	PYTHONPATH=src $(PY) -m anuvritti.adapters.film.render --archive "$(ARCHIVE)" \
		--output "$(FILM_OUTPUT)" --still "$(FILM_STILL)" --workspace var/film/work

# The seed is intentionally generated under ignored var/: it demonstrates the destination
# without putting either demo media or a family's media in source control.
teaser:
	PYTHONPATH=src $(PY) scripts/teaser.py

# `scripts/` is in scope because it is not scaffolding: backup, restore, the SBOM, the
# image scan and the release runner are the operational surface, and for three phases they
# were the only Python in the repo that no gate ever read.
LINT_PATHS := src tests scripts packages/client/codegen

lint:
	$(PY) -m ruff check $(LINT_PATHS)
	$(PY) -m ruff format --check $(LINT_PATHS)

format:
	$(PY) -m ruff format $(LINT_PATHS)
	$(PY) -m ruff check $(LINT_PATHS) --fix

types:
	$(PY) -m mypy

# The other half of the type gate. `node --test` strips types without checking them, so
# until this existed the whole TypeScript surface - the client, the design language and the
# app - compiled in nobody's head. Four projects because they run in three different hosts:
# Hermes has no DOM, Node has no React Native, and the tests are Node programs that read the
# app's own source.
types-ts:
	npm run typecheck --silent

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

# Every gate runs, and the failures are reported together. Make stops at the first failed
# prerequisite, so a target list hides everything behind the first thing that is red - for
# three phases `lint` sat second and the type and coverage gates were never reached. `-k`
# keeps going after a failure; the `$(MAKE)` recursion is what makes each gate a separate
# job rather than one shell whose exit code is the last command's.
check:
	@$(MAKE) -k _gates || (echo ""; echo "make check: one or more gates failed - see above"; exit 1)

.PHONY: _gates
_gates: world lint types types-ts cov-core cov design filmkit
	@echo "all gates green"

run:
	$(PY) -m uvicorn anuvritti.interfaces.http.asgi:app --host 0.0.0.0 --port 8000

tracker:
	$(PY) scripts/tracker.py show

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} +

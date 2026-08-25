# Anuvritti

> **For the little things you don't want life to erase.**

A private family presence system that helps a parent capture meaningful intentions and
everyday moments, remember *why* they mattered, and bring them back when they can become
real shared experiences.

This repository is **V0**: a small, complete backend built to answer one question
([PRD §48](docs/PRD.md)):

> *Can saved digital intention become a real family moment that otherwise would have been forgotten?*

---

## The loop

```
  Share → Anuvritti           a father sees a reel, taps share.        < 10 seconds
        ↓
  "Saved ✨"                  the system infers what, who, likely intent, likely age
        ↓
  "What made you save this?"  optional, skippable, voice preferred
        ↓
  ... eight months pass ...
        ↓
  ✨ Worth Bringing Back      "You saved this 8 months ago.
                               You said: 'I want to see his face when it launches.'
                               Aarav may be ready now."
                              [Maybe later] [Let's do it] [Not relevant anymore]
        ↓
  ❤️ Did this happen?          one photo, five seconds of audio, one sentence — or nothing
        ↓
  A Moment
```

That path is one test: [`tests/e2e/test_golden_path.py`](tests/e2e/test_golden_path.py).
If it fails, the product does not work, whatever else passes.

---

## Quick start

```bash
make install
cp .env.example .env    # fill in ANUVRITTI_MEDIA_KEY
make run                # http://127.0.0.1:8000/docs
make check              # lint, strict types, both coverage gates
```

> V0 has **no authentication** — it is scoped to one family on a private network.
> See [HARDENING.md §5.1](docs/HARDENING.md#51-high--there-is-no-authentication) before
> exposing it anywhere.

---

## How it is built

Modular monolith, hexagonal internals, DDD. The domain imports nothing but the standard
library — enforced by a test, not a convention.

```
interfaces ──▶ application ──▶ domain          ◀── stdlib only
     │              │
     └──▶ adapters ─┘                          adapters implement application ports
```

| | |
|---|---|
| **Store** | SQLite — the family owns one file ([ADR-0003](docs/architecture/ADR-0003-sqlite-local-first.md)) |
| **AI** | A port, not a dependency. V0 ships a deterministic offline engine ([ADR-0004](docs/architecture/ADR-0004-heuristic-intent-engine.md)) |
| **Errors** | `Result[T, DomainError]` — expected failures are values ([ADR-0002](docs/architecture/ADR-0002-result-error-handling.md)) |
| **Provenance** | Every AI-derived field carries value / source / confidence / human_override ([ADR-0005](docs/architecture/ADR-0005-provenance-on-every-ai-field.md)) |

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Three ideas the code takes literally

**The human always wins.** An AI field can be corrected once and is never re-inferred —
not after fifty passes of the engine. Certainty is reserved for what a person actually
said; the machine's confidence is capped below it (PRD §8.7, §13).

**A Spark outlives its link.** Anuvritti never downloads third-party media. It keeps the
creator, the title, the date, and the parent's own words, so the Spark still means
something after the reel is deleted (PRD §43).

**No guilt.** The Return Engine is a pure function with six signals and hard limits: a
quiet period before anything can be brought back, a real cooldown behind "maybe later",
a permanent stop behind "not relevant anymore", and a small daily cap. A test generates
every string it can show a parent and fails if any of them nags (PRD §8.5).

---

## The constitution is executable

PRD §47 calls its boundaries constitutional. They are tests, and CI runs them:

| Suite | Enforces |
|---|---|
| [`tests/constitution/`](tests/constitution/) | No guilt · no surveillance · V0 scope · AI honesty |
| [`tests/architecture/`](tests/architecture/) | The dependency rule, as a fitness function |

A PRD violation fails the build.

---

## Status

```
1025 tests passing
coverage   98.5% domain + application   ·   97.0% overall
mypy       strict, clean
ruff       clean
bandit     0 medium / 0 high
```

Progress against the plan lives in [`tracker.json`](tracker.json) (`make tracker`).

---

## Documentation

| | |
|---|---|
| [PRD.md](docs/PRD.md) | The founder's product constitution — the source of every decision here |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Bounded contexts, the Spark lifecycle, the Return Engine |
| [HARDENING.md](docs/HARDENING.md) | Threat model, controls, findings, open items |
| [RUNBOOK.md](docs/RUNBOOK.md) | Run, back up, restore, export, delete |
| [contracts/](docs/contracts/) | OpenAPI, domain events, error catalog |

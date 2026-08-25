# Hardening Report — Anuvritti V0

**Role:** Principal SRE & DevSecOps Lead
**Date:** 2026-08-25 · **Scope:** the V0 backend at the commit this report ships with
**Verdict:** ready for the single-family validation deployment described in PRD §54.
Not yet ready for multi-tenant hosting — see [Open items](#5-open-items-before-multi-family).

---

## 1. Threat model

This system holds a small amount of exceptionally sensitive data: a child's photographs,
a family's voices, a parent's private reasons for things. There is little to steal
commercially and a great deal to lose personally. That shapes the priorities.

| # | Threat | Severity | Status |
|---|---|---|---|
| T1 | Device or backup theft exposes a child's photos and voice | **High** | Mitigated — Fernet encryption at rest, key never in the image or repo |
| T2 | Family archive silently corrupted or partially written | **High** | Mitigated — WAL, `synchronous=FULL`, transactional `UnitOfWork`, content hashes |
| T3 | Family content leaks into logs, metrics or the audit trail | **High** | Mitigated — formatter-level redaction, structural-only events, route-template labels |
| T4 | A parent's private note becomes visible to the child | **High** | Mitigated — `Visibility` enforced in the application layer, tested |
| T5 | Third-party media content copied and retained without right | Medium | Mitigated — the product never fetches a URL (PRD §43) |
| T6 | SQL injection via search | Medium | Mitigated — fully parameterised, tested with hostile input |
| T7 | Concurrent requests corrupt the SQLite archive | **High** | **Fixed during build** — see §3.1 |
| T8 | An AI guess hardens into a remembered fact | **High** | Mitigated — provenance on every inferred field, human override permanent |
| T9 | Product drifts into surveillance or engagement mechanics | **High** | Mitigated — PRD §46/§47 enforced as failing tests in CI |
| T10 | Malicious upload (HTML/executable) served back to a browser | Medium | Mitigated — MIME allow-list, `no-store`, size cap |
| T11 | Supply-chain compromise via a dependency | Medium | Partial — 5 runtime deps, `pip-audit` blocking; no hash pinning yet |
| T12 | Unauthenticated access to the API | **High** | **Closed** — device pairing, TASK-511. See §5.1 |

---

## 2. Controls in place

### 2.1 Data protection (PRD §44)

| Control | Implementation | Verified by |
|---|---|---|
| Encryption at rest | Fernet (AES-128-CBC + HMAC), key from `ANUVRITTI_MEDIA_KEY` | `test_media_store.py::TestEncryptionAtRest` |
| Encryption in transit | TLS at ingress; app refuses to boot with `ENV=production` + `TLS_REQUIRED=false` | `test_settings.py::TestProductionSafety` |
| Zero secrets in repo | `Settings` reads env only; `.env` gitignored and CI-checked | `test_toolchain.py::test_no_secrets_committed` |
| Integrity | SHA-256 content hash verified on every read | `test_media_store.py::TestIntegrity` |
| Export everything | `GET /v1/families/{id}/export` — complete, readable, versioned JSON | `test_privacy_rights.py::TestExportEverything` |
| Delete everything | Hard delete incl. media bytes; verified by grepping the raw DB file | `test_privacy_rights.py::test_no_trace_of_the_childs_words_survives_anywhere` |
| No model training | The intent engine makes no network call at all | `test_heuristic_intent.py::test_it_makes_no_network_call` |
| Fine-grained visibility | `Visibility` checked in the application layer, not the query | `test_vault.py::TestVisibility` |

### 2.2 Telemetry boundaries (PRD §44, §46)

Telemetry must not become a second copy of the archive.

- **Logs** — `JsonFormatter` redacts `why_text`, `reflection`, `note`, `answer`, `child_name`,
  `source_url` and others at the formatter, the one place no caller can forget. Access logs
  record the **route template** (`/v1/families/{family_id}`), never the populated path.
- **Metrics** — no label carries a family id, child name or URL. The Prometheus text output
  is asserted to contain neither.
- **Audit events** — payloads are structural only. A test walks the AST of `events.py` and
  fails if any event grows a bare `str` field outside an allow-list of identifiers.

### 2.3 Product ethics as CI gates (PRD §8.5, §46, §47, §49)

The PRD calls its boundaries "constitutional". They are enforced as tests, not conventions:

- `tests/constitution/test_no_guilt.py` generates **every string** the Return Engine can
  show a parent (>1000 variants across elapsed time, age, intent and why) and asserts none
  contains guilt, urgency, scorekeeping, an exclamation mark, or a prediction about the child.
- `tests/constitution/test_no_surveillance.py` asserts the *capability* for GPS, screen
  monitoring, emotion detection and behavioural scoring is absent from source, schema and
  OpenAPI — and that an attempt to POST a latitude is refused.
- `tests/constitution/test_v0_scope.py` asserts each PRD §49 exclusion is absent, and
  inversely that all nine V0 features exist.
- `tests/constitution/test_ai_honesty.py` asserts the engine never claims certainty and a
  human correction survives fifty re-inferences.

### 2.4 Supply chain & build

- **5 runtime dependencies.** A dependency count test fails the build above six.
- `pip-audit --strict` and `bandit -ll` are blocking CI jobs; `gitleaks` scans for secrets.
- Multi-stage image: no compiler, no package index credential, no build tooling in the
  final layer. Runs as uid 10001, `nologin` shell.
- CI verifies at build time that the image **does not run as root** and that it **refuses to
  start in production without an encryption key**.
- Workflow permissions are `contents: read`; no action tracks a moving branch.

### 2.5 Architecture as a control

- `tests/architecture/test_dependency_rule.py` fails if the domain imports anything beyond
  the standard library, or if any layer imports one it may not. This is what keeps the
  local-first promise a configuration choice rather than a rewrite.

---

## 3. Findings raised and fixed during this build

### 3.1 `HIGH` — shared SQLite connection was not thread-safe

**Found by** `test_resilience.py::TestConcurrency`, which failed with 20 concurrent writes:
`InterfaceError: bad parameter or other API misuse`.

Sync FastAPI endpoints run in a threadpool, so concurrent requests genuinely reach one
`sqlite3.Connection`. `check_same_thread=False` permits that; it does not make it correct.
Two requests could interleave inside a transaction.

**Fixed** — `GuardedConnection` serialises access behind a re-entrant lock and materialises
rows inside the lock rather than returning a live cursor. `SqliteUnitOfWork` holds the same
lock for the whole transaction. SQLite is single-writer regardless, so a one-family product
pays nothing. Documented in ADR-0003.

### 3.2 `MEDIUM` — Worth Bringing Back could resurface something saved hours earlier

The Return Engine weighted elapsed time but did not gate on it, so a fresh, well-matched
Spark cleared the threshold and was "brought back" the same day it was saved. That is
manufactured engagement, which PRD §8.5 and §47 rule out.

**Fixed** — a hard quiet period (`ANUVRITTI_MIN_DAYS_BEFORE_RETURN`, default 7 days) gates
eligibility before any scoring. Covered by `TestQuietPeriod`.

### 3.3 `MEDIUM` — suggestion copy hardcoded a gendered pronoun

PRD §48 F6 phrases the suggestion as *"He may be ready now"* — written about one specific
son. Shipped as product code it would misgender other families' children on their own screen.

**Fixed** — the child is named when the family told us their name, and referred to neutrally
otherwise. A test asserts no gendered pronoun is ever emitted.

### 3.4 `LOW` — orchestrator silently processed zero tasks

`scripts/orchestrate.sh` iterated `$(jq -r '.phases[].name')` unquoted, so a phase named
`"Phase 1: Foundations"` word-split into three phantom phases, no task matched, and the run
reported success having done nothing.

**Fixed** — task selection is delegated to the unit-tested `scripts/tracker.py`, which also
adds dependency gating and schema validation. Regression test in `test_orchestrator.py`.

### 3.5 `LOW` — log handler bound `sys.stdout` at construction

Logging stopped silently if stdout was reassigned (embedding host, captured subprocess,
test harness). **Fixed** — `_StdoutHandler` resolves the stream at emit time.

### 3.6 `INFO` — three bandit B608 findings reviewed and annotated

String-built SQL in `sqlite.py`. All three interpolate only code-controlled fragments
(column names from `spark_to_row`, literal clause strings, runs of `?`); every user value is
a bound parameter. Annotated inline with justification and covered by an injection test.

---

## 4. Verification

```
ruff check src tests            all checks passed
ruff format --check src tests   all checks passed
mypy (strict)                   no issues in 44 source files
pytest                          1025 passed
coverage: domain + application  98.5%   (gate: 90%)
coverage: overall               97.0%   (gate: 90%)
bandit -ll                      0 medium, 0 high
pip-audit                       no known vulnerabilities
```

---

## 5. Open items before multi-family

These are deliberate V0 gaps, not oversights. Each is a decision to make before a second
family is onboarded.

### 5.1 `HIGH` — there is no authentication — **closed (TASK-511)**

*Was:* every endpoint took `actor_id` on trust, so any caller who could reach the port could
read any family's archive by typing a different id.

*Now:* every route below the pairing boundary resolves a bearer device token to a
`DeviceIdentity`, and the handler is given **that** family id rather than the request's. The
rule is stated once, in `interfaces/http/auth.py`: an id in a path, query or body is an
assertion, not an instruction, and it must agree with the token or the request is refused.
Disagreement is a `403` rather than a silent redirect into the right family, so a client with
a stale id finds out.

| Property | How |
|---|---|
| Pairing | Bootstrap pairs the founding device in the same call that creates the family, so there is no window between "the family exists" and "the family is protected". Later devices claim an 8-character Crockford code shown on a device already inside the house. |
| Code strength | 40 bits, single use, ten minutes, and **five failed attempts per window across the whole server**. Per-code counting is the intuitive design and is worthless — a wrong guess matches no stored fingerprint, so there is nothing to increment. |
| Storage | Only SHA-256 fingerprints, for both tokens and codes. A stolen copy of the archive yields nothing replayable. SHA-256 rather than Argon2 is correct for 256-bit *random* secrets: there is no dictionary, and a slow KDF on every request is itself a denial-of-service lever. |
| Comparison | `hmac.compare_digest`, everywhere. |
| Failure | Wrong, malformed, expired, already-claimed and locked-out all answer `PAIRING_FAILED` identically. `ClaimPairingRequest.code` carries no `min_length` for the same reason — a `422` for an empty code and a `401` for a wrong one are two different answers. |
| Revocation | A parent can list what is paired by a name they chose and cut a lost phone off. Deleting the family cascades to its devices, so "delete everything" leaves nobody holding a working key. |

*Verified by* `tests/integration/test_pairing.py` (52 tests, including a parameterised sweep
asserting every route is closed), `tests/unit/domain/test_access.py`, and
`tests/e2e/test_the_app_against_the_server.py`, which asserts the plaintext token never
reaches the database.

**What is still open.** Bootstrap remains unauthenticated, because it is how the first token
is obtained. On a production box it refuses once a family exists (`409`), which closes it
after first use; in development it stays open so the tests above can exist. Real accounts,
and therefore a second family, are TASK-901.

### 5.2 `MEDIUM` — no rate limiting

Nothing bounds request volume. Low risk while unauthenticated access is prevented by
network placement; required before public exposure.

### 5.3 `MEDIUM` — dependency hashes are not pinned

`requirements.txt` uses floors, not `--require-hashes`. The Dockerfile is written to prefer
hashes when a pinned file is present. Generate one with `pip-compile --generate-hashes`
before any deployment that matters.

### 5.4 `MEDIUM` — no backup or restore procedure

The archive is a single SQLite file plus a media directory. That makes backup trivial and
therefore easy to forget. See the runbook.

### 5.5 `LOW` — key rotation is manual

Rotating `ANUVRITTI_MEDIA_KEY` currently invalidates existing media. Envelope encryption
(per-object data keys wrapped by a master key) makes rotation cheap; worth doing before
the archive is large enough that re-encryption is painful.

### 5.6 `LOW` — no structured retention policy

PRD §45 anticipates a child gaining rights over their own story. The data model separates
owner from subject, which is the hard part; the transition rules are not yet built.

---

## 6. Recommended next actions, in order

1. ~~**Add authentication** before a second family (§5.1).~~ Done — TASK-511.
2. **Pin dependency hashes** and commit the lock file (§5.3).
3. **Automate the backup** in §2 of the runbook and test a restore.
4. **Envelope-encrypt media** so key rotation is cheap (§5.5).
5. Run the PRD §54 validation for 30 days and let the answer decide what comes next.

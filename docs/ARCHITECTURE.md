# Anuvritti — System Architecture (V0)

> Derived from `docs/PRD.md` (Founder PRD v1.0). Governed by `CLAUDE.md`.
> Status: **Frozen for V0**. Changes require an ADR in `docs/architecture/`.

---

## 1. Architectural Position

Anuvritti V0 is a **single-family, privacy-first intent & memory engine**.

The PRD's central claim (§48) is testable:

> Can saved digital intention become a real family moment that otherwise would have been forgotten?

Everything in V0 exists to make **Intent → Moment Conversion Rate** (§53) measurable.
Anything that does not serve that loop is out of scope (§49).

### 1.1 Style

| Concern | Decision |
|---|---|
| Macro style | **Modular monolith**, one deployable |
| Internal style | **Hexagonal (Ports & Adapters)** + **Clean Architecture** layering |
| Modelling | **DDD** — aggregates, value objects, domain events, bounded contexts |
| Error handling | **`Result[T, E]`** (explicit Either). No exceptions for expected failures |
| Persistence | SQLite (local-first, §44), repository ports, no ORM leakage into domain |
| AI | **Port, not dependency.** V0 ships a deterministic heuristic adapter |
| Deps in domain | **Zero.** `anuvritti.domain` imports stdlib only |

### 1.2 The Dependency Rule

```
interfaces ──▶ application ──▶ domain
     │              │
     └──▶ adapters ─┘        (adapters implement application ports)

domain imports nothing but stdlib.
application imports domain.
adapters import application (ports) + domain.
interfaces import application. Never the reverse.
```

Enforced by an executable test: `tests/architecture/test_dependency_rule.py`.

---

## 2. Bounded Contexts (C4 Level 2)

```text
┌───────────────────────────────────────────────────────────────────────┐
│                        ANUVRITTI  (one deployable)                    │
│                                                                       │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │   CAPTURE   │──▶│UNDERSTANDING │──▶│    VAULT     │                │
│  │  Spark is   │   │ Intent Engine│   │ search /     │                │
│  │  born (§11) │   │   (§13)      │   │ retrieval §48│                │
│  └─────────────┘   └──────────────┘   └──────┬───────┘                │
│                                              │                        │
│                                       ┌──────▼───────┐                │
│  ┌─────────────┐                      │   RETURN     │                │
│  │  PRESENCE   │◀─────────────────────│ Resurfacing  │                │
│  │ LittleThings│                      │   (§14)      │                │
│  │ RightNow §17│                      └──────┬───────┘                │
│  └─────────────┘                             │                        │
│                                       ┌──────▼───────┐                │
│  ┌─────────────┐                      │    MOMENT    │                │
│  │   FAMILY    │  identity, roles,    │ Spark → lived│                │
│  │  §26 §45    │  visibility, rights  │  life  (§15) │                │
│  └─────────────┘                      └──────────────┘                │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │ SHARED KERNEL: Result, Ids, Clock, Provenance, DomainError    │     │
│  └──────────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────────┘
```

| Context | Aggregate root | Owns | PRD |
|---|---|---|---|
| **Capture** | `Spark` | source, raw payload, capture-time metadata | §9–§11 |
| **Understanding** | (service) | `IntentEngine` port, AI-derived fields + provenance | §13 |
| **Vault** | (read model) | facet + keyword retrieval over Sparks | §48 F5 |
| **Return** | (service) | relevance scoring, suggestion lifecycle | §14, §48 F6 |
| **Moment** | `Moment` | what actually happened, evidence | §15, §48 F7 |
| **Presence** | `LittleThing`, `RightNowSnapshot` | ambient family capture | §17, §18 |
| **Family** | `Family` | members, children, visibility, child data rights | §26, §44–46 |

V0 keeps all contexts in-process. Context boundaries are **package boundaries**, so a later
split into services (V2 "Family OS") is mechanical, not a rewrite.

---

## 3. The Spark Aggregate

`Spark` is *the* aggregate (PRD §9–§10). Its invariants:

1. A Spark **always retains meaning** even if its external source dies (§43).
   → We never store third-party media bytes for external URLs; we store
   `SourceRef(url, creator, title, saved_at)` + human `why` + inferred fields.
2. **Lifecycle is a state machine**, not a free field.
3. **Every AI-derived field carries provenance** (§13, §42): `value / source / confidence / human_override`.
4. A human override **always wins** and is never re-inferred.
5. `subject` (child) and `owner` (capturer) are distinct — parental capture does not
   imply permanent parental ownership (§45).

### 3.1 Lifecycle state machine (§10)

```text
            capture()
               │
               ▼
          ┌─────────┐  enrich()   ┌─────────┐
          │CAPTURED │────────────▶│ WAITING │
          └─────────┘             └────┬────┘
                                       │ return-engine: score ≥ threshold
                                       ▼
                                  ┌──────────┐
                                  │ RELEVANT │
                                  └────┬─────┘
                                       │ suggest()
                                       ▼
                                  ┌───────────┐
              "not relevant   ┌───│ SUGGESTED │───┐  "let's do it"
               anymore"       │   └───────────┘   │
                              ▼         │         ▼
                        ┌──────────┐    │   ┌─────────┐
                        │ ARCHIVED │    │   │ PLANNED │
                        └──────────┘    │   └────┬────┘
                                        │        │ mark_done()
                        "maybe later"   │        ▼
                                        │  ┌─────────────┐
                                        └─▶│ EXPERIENCED │──▶ Moment created
                          (back to WAITING)└──────┬──────┘
                                                  │ reflection attached
                                                  ▼
                                           ┌────────────┐
                                           │ REMEMBERED │
                                           └────────────┘
```

Illegal transitions return `Err(InvalidTransition)`. They never raise.

### 3.2 Six V0 intents (§48 F4)

`DO · BUY · WATCH · READ · TEACH · REMEMBER`

`COOK/VISIT/TELL/LISTEN` from §10 are modelled in the enum but **gated off** for V0 by
`IntentType.v0_set()`, so V1 enables them without a migration.

---

## 4. The Return Engine (§14)

The Return Engine is a **pure function** over (Spark, FamilyContext, now). Pure ⇒ testable ⇒
trustworthy. No hidden model, no network, no randomness.

```text
score(spark, ctx, now) = Σ wᵢ · signalᵢ   ∈ [0, 1]
```

V0 signals (deliberately few — §49 forbids a "large recommendation engine"):

| Signal | Weight | Rationale (PRD) |
|---|---|---|
| `age_fit` — child's age inside `age_range` | 0.35 | §14 "child age, developmental stage" |
| `maturation` — time since capture, saturating ~180d | 0.20 | §48 F6 "you saved this 3 months ago" |
| `occasion_fit` — weekend / season match | 0.15 | §14 "weekend, season" |
| `intent_actionability` — DO/TEACH act sooner than BUY | 0.15 | §13 urgency |
| `why_present` — human "why" recorded | 0.10 | §12 "most valuable human metadata" |
| `novelty` — decays if recently suggested | 0.05 | §8.5 no guilt, no nagging |

**Constitutional dampers** (hard rules, not tunable weights — §8.5, §47):

- A **quiet period** (default 7d) after capture. Worth Bringing Back returns things that were
  *forgotten*; something saved this morning has not been. Scoring cannot enforce this — a fresh,
  well-matched Spark clears any sensible threshold — so it gates eligibility.
- A Spark declined with "maybe later" enters a **cooldown** (default 30d) and cannot be suggested.
- A Spark declined "not relevant anymore" is **archived permanently**.
- At most `MAX_SUGGESTIONS_PER_DAY` (default 3) — anti-metric: notification volume (§53).
- No urgency language, no streaks, no counters in the payload. Enforced by test.

---

## 5. Data Model (physical) — implements §42

```text
family(id, name, created_at)
member(id, family_id, display_name, role, created_at)          role: PARENT|CO_PARENT|CHILD|GRANDPARENT
child_profile(id, family_id, member_id, display_name, date_of_birth)

spark(id, family_id, owner_id, subject_child_id,
      title, note,
      source_kind, source_url, source_creator, source_title, source_captured_text,
      media_id,
      intent_value, intent_source, intent_confidence, intent_overridden,
      age_min, age_max, age_source, age_confidence, age_overridden,
      category_value, category_source, category_confidence, category_overridden,
      tags_json,
      why_text, why_voice_media_id, why_recorded_at,
      status, visibility,
      suggested_count, last_suggested_at, snoozed_until,
      created_at, updated_at)

moment(id, family_id, spark_id, happened_on, reflection,
       photo_media_id, audio_media_id, created_by, created_at)

little_thing(id, family_id, author_id, subject_child_id, text, audio_media_id, created_at)
right_now(id, family_id, child_id, prompt, answer, captured_at)

media(id, family_id, kind, content_hash, byte_size, mime_type,
      storage_key, encrypted, created_at)

domain_event(id, family_id, aggregate_id, name, payload_json, occurred_at)
```

`spark` intentionally stores AI fields as **4-tuples** (`value/source/confidence/overridden`)
rather than a JSON blob, so provenance is queryable and cannot be silently lost (§42).

---

## 6. Ports (application boundary)

```python
SparkRepository      MomentRepository       FamilyRepository
LittleThingRepository  RightNowRepository   MediaStore
IntentEngine         Transcriber            EventPublisher
Clock                IdGenerator            UnitOfWork
```

### V0 adapter matrix

| Port | V0 adapter | V1 path |
|---|---|---|
| `*Repository` | `SqliteSparkRepository`, … (thread-serialised, ADR-0003) | Postgres / encrypted sync |
| `MediaStore` | `EncryptedFilesystemMediaStore` (content-addressed, Fernet at rest) | Object store + envelope encryption |
| `IntentEngine` | `HeuristicIntentEngine` (deterministic rules, calibrated confidence) | LLM adapter behind same port |
| `Transcriber` | `NullTranscriber` (stores audio, no ASR) | on-device ASR (§44 local-first) |
| `Clock` | `SystemClock` / `FrozenClock` in tests | — |

**Why heuristic AI in V0:** §8.1 "Human Before AI" and §49 "no advanced agents". A rules
adapter is free, offline, deterministic, and keeps the `IntentEngine` port honest. Swapping in an
LLM is a one-file change and requires no domain change.

---

## 7. Data Flow — the golden path (C4 Level 3)

```text
 Share sheet / HTTP POST /v1/sparks
        │
        ▼
 CaptureSpark (application)
        │ 1. Family/permission check      (Family ctx)
        │ 2. Spark.capture()              (domain — status=CAPTURED)
        │ 3. IntentEngine.infer()         (port → heuristic adapter)
        │ 4. spark.apply_inference()      (provenance-stamped, status=WAITING)
        │ 5. repo.save() + events         (UnitOfWork)
        ▼
 SparkCaptured, SparkEnriched  ──▶ EventPublisher (in-proc; audit log)

 ... time passes ...

 GET /v1/return/worth-bringing-back
        │
        ▼
 GetWorthBringingBack
        │ 1. repo.find_returnable(family)
        │ 2. ReturnEngine.score(...)      (pure domain service)
        │ 3. apply constitutional dampers
        │ 4. spark.mark_suggested()
        ▼
 [{spark, reason: "You saved this 8 months ago. He may be ready now."}]

 POST /v1/return/{spark_id}/respond {"response": "lets_do_it"}
        ▼  spark.plan()                      status=PLANNED

 POST /v1/sparks/{id}/done  {photo|audio|sentence}
        ▼  MarkAsDone → Moment created       status=EXPERIENCED
           MomentCreated event → metric: intent_to_moment
```

---

## 8. Privacy Architecture (§44–§46) — non-negotiable

| Requirement | V0 implementation |
|---|---|
| Encryption at rest | Media encrypted with Fernet key from `ANUVRITTI_MEDIA_KEY` (env, never in repo) |
| Encryption in transit | TLS terminated at ingress; app refuses to boot with `ENV=production` + `TLS_REQUIRED=false` |
| Zero secrets in code | 12-factor `Settings` loaded from env only; `.env.example` documents keys, holds none |
| Fine-grained visibility | `Visibility{PRIVATE, FAMILY, CHILD_VISIBLE}` on every Spark/Moment; enforced in application, tested |
| Export everything | `GET /v1/family/{id}/export` → complete JSON + media manifest |
| Delete everything | `DELETE /v1/family/{id}` → hard delete incl. media bytes, verified by test |
| No public-model training | `IntentEngine` V0 makes no network call at all |
| AI provenance visible | every inferred field returns `source`/`confidence`/`human_override` in the API |
| No surveillance (§46) | No location tracking, no screen monitoring, no scoring. Enforced by constitution test |

### Ethical Constitution as executable tests
`tests/constitution/` asserts the §47 boundaries the code must never cross — e.g. no field named
`streak`/`score` is ever exposed to the client, suggestion payloads contain no urgency vocabulary,
and no endpoint accepts child location. **A PRD violation fails CI.**

---

## 9. Observability (§63.4)

- **Structured JSON logs** to stdout (12-factor), with `request_id`, never PII bodies.
- `/health` (liveness), `/ready` (dependency check), `/metrics` (Prometheus text, stdlib-rendered).
- Product metrics mirror §53, including **anti-metrics**: `anuvritti_suggestions_emitted_total`
  is tracked precisely so it can be kept *low*.

---

## 10. Explicit V0 Non-Scope (§49)

Not built, and the architecture must not accrete it: family social network, marketplace, price
engine, health/learning platform, voice cloning, Ask My Family, knowledge-graph UI, Memory
Constellations, generative child content, grandparent app, 18-year book generator, complex
analytics, wearables, location tracking, screen monitoring, advanced agents, large recommender.

---

## 11. ADR Index

| ADR | Decision |
|---|---|
| [ADR-0001](architecture/ADR-0001-modular-monolith.md) | Modular monolith + hexagonal |
| [ADR-0002](architecture/ADR-0002-result-error-handling.md) | `Result` over exceptions |
| [ADR-0003](architecture/ADR-0003-sqlite-local-first.md) | SQLite for local-first V0 |
| [ADR-0004](architecture/ADR-0004-heuristic-intent-engine.md) | Deterministic intent engine behind a port |
| [ADR-0005](architecture/ADR-0005-provenance-on-every-ai-field.md) | 4-tuple provenance columns |

# Anuvritti V1 — Make It Magical

PRD §50. V0 (phases 1–4, 29 tasks) is complete; this plans phases 5–9, 39 tasks.
`tracker.json` is the operational source of truth — this file records only the
decisions behind it, which the tracker cannot express.

## The premise

`~/Projects/autovideo-engine` is governed by one rule: *"the video may only show
output the application actually produced."* Anuvritti §8.7/§47 says *"AI is not
historical truth; never fabricate family memories."* These are the same mechanism —
a checkpoint and an ethical boundary — pointed at different subjects.

So autovideo is not a dependency Anuvritti picks up. It is Anuvritti's memory
compiler, and it already carries the right ethics in its architecture.

## Decisions (2026-08-25)

| Decision | Chosen | Why |
|---|---|---|
| Surface | Native iOS **and** Android, via Expo / React Native | Real Share Extension and SEND intent on both. Critically: the design tokens are then TypeScript and CSS, so `packages/world` renders **both** the app and the film's Chromium scenes. Flutter cannot share tokens with an HTML renderer. |
| Order | The Surface first; Voice and the Memory Compiler **immediately** after | Nothing matters if capture isn't under ten seconds (§8.2). But voice and the film are next, not eventually — recorded here at the user's explicit request. |
| Repos | Extract a shared `filmkit` package from autovideo-engine | Narration, timing, timeline, captions, compositor, cache store, browser render, manifest. autovideo's existing tests must pass unchanged against it — that is the proof the extraction was faithful. |

## Phases

| Phase | Tasks | What it is |
|---|---|---|
| 5 — The Surface | 13 | The design language as code, the Spark as an object, share capture on both platforms, offline queue, one-tap correction, `tests/design/`, device pairing auth. |
| 6 — Voice | 6 | Hold-to-talk, waveform, on-device transcription with no network call, voice→intent, Little Things. |
| 7 — The Memory Compiler | 10 | Extract `filmkit`; compile Moments into a provenance-bound film; narration from the parent's real voice. |
| 8 — Frictionless Meaning | 5 | FamilyLexicon, emergent constellations, email-in, on-device semantic search. |
| 9 — Trust and the Second Family | 5 | Real auth (closes HARDENING §5.1), co-parent, grandparent, child data rights, tested restore. |

## Three positions worth defending

**The interface gets constitution tests.** `tests/constitution/test_no_guilt.py`
already generates every string the Return Engine can show and fails CI on guilt or
scorekeeping. `tests/design/` extends the same mechanism to pixels: no badges, no
counts, no streaks, no red dots, no urgency colour outside destructive actions, and
elapsed time never rendered as a number — the client is never handed the number, so
the shortcut cannot be taken under deadline pressure later.

**The film cannot contain anything that did not happen.** Every scene declares the
Spark, Moment and media ids it draws from; a frame that cannot cite a real one fails
the build, and `provenance.json` ships beside the film. No generated imagery of a
child, no synthesised loved ones — not as a policy someone could relax, but as a
compiler that refuses to produce output. §55.5 Trust, executable.

**Every Little Thing is a line in the film.** Voice capture's real adoption problem
is that it feels like effort with no visible return. The clips *are* the narration
track, so the return is structural rather than promised. This also makes §39's
permanent restraint on voice cloning costless — the real voice was always better.

## Prerequisite

TASK-501. `~/Projects/autovideo-engine` has **zero commits** — 4,779 lines and 13
test files exist only as working-tree state. Phase 7 begins by pulling it apart.
Run its suite and preserve it first. Committing needs the user's authorisation.

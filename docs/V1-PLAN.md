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

---

## Progress

### Both repositories are now under version control (2026-08-25)

Neither had a single commit. In both cases the reason was the same: media and logic
shared a tree with no line between them, so committing meant committing renders.

- `autovideo-engine` → `d1e5e64`, 71 files, 529 KB. The 50 MiB of dangling media
  blobs left by an earlier staging attempt were pruned; the store is 284 KB.
  **Baseline for TASK-702: 97 tests, ~1s.**
- `dadaa` → 145 files, 815 KB. `packages/world/dist/` is ignored — `make world`
  regenerates it, and `tests/design` refuses to run against a stale copy, so a
  committed copy would only become a second truth.

One near-miss worth remembering: a bare `media/` ignore rule matches at *any* depth
and silently dropped `src/anuvritti/adapters/media/` — real source — out of the first
commit. Scope runtime-output rules to their actual path, then diff
`find src -name '*.py'` against `git ls-files src` before trusting the result.

### Phase 5 — the design language (TASK-502, 503, 504 complete)

`packages/world` is the visual language as code, with zero dependencies: Node strips
the types natively and `node:test` runs the suite. Every token carries the role it
plays and the reason it exists, which is what makes the constitution enforceable —
the same provenance ethic the domain applies to `Attributed[T]`.

Three positions the tests now hold:

1. **Exactly one red, and it means erased.** Enforced by measuring chroma and hue
   across the whole palette in both themes, not by reviewing intent. Lateness is not
   urgent, and a child is never an error state.
2. **Saffron is rationed to the voice role.** When a parent sees it, someone actually
   spoke. Nothing else may occupy that hue at strength.
3. **Elapsed time loses precision on purpose.** Past a fortnight, the exact day count
   is absent from the string entirely, so no interface can recover it.

All four rules were mutation-tested — a red used for something other than deletion, a
leaked day count, a token defined only behind a theme guard, and a streak added to the
application layer. All four were caught.

The specimen catches what review does not. It is what revealed that elevation was
light-theme-only: warm indigo-tinted shadows are invisible on a dark ground, so the
whole elevation row simply vanished. Elevation is now themed like colour.

Gate at this point: ruff clean, mypy clean over 44 files, **1,089 tests** passing,
98.48% domain and application coverage, 97.49% overall, 20 `packages/world` tests, and
no drift between the specimen and the emitted stylesheet. `make check` runs all of it.

### Phase 5 complete — the Surface (TASK-505 to 513)

**42/68. `make check`: 1,229 Python tests, 105 TypeScript tests, 97.29% domain coverage.**

#### HARDENING §5.1 is closed

V0 took `actor_id` on trust. Every route below the pairing boundary now resolves a bearer
device token to a `DeviceIdentity` and is handed *that* family id. The rule is stated once,
in `interfaces/http/auth.py`, and it is the less obvious of the two readings:

> An id in a path, a query or a body is an assertion, not an instruction. It must agree with
> the token, or the request is refused.

Ignoring a wrong `family_id` and silently using the token's would be safe *and* wrong — a
client with a stale id would write into the right family and never learn it had a bug.

Three decisions in the pairing design are worth keeping:

1. **Attempt limiting is global, not per code.** Per-code counting is the intuitive design
   and it is worthless: a wrong guess matches no stored fingerprint, so there is no record to
   increment and the attacker sweeps the keyspace paying nothing.
2. **SHA-256, not Argon2.** These are 256-bit and 40-bit *random* secrets, not passwords.
   There is no dictionary to run, and a slow KDF on every authenticated request is itself a
   denial-of-service lever. The 40-bit code is protected by five attempts and ten minutes.
3. **One error for every failure.** Wrong, malformed, expired, claimed and locked-out all
   answer `PAIRING_FAILED`. A test caught the leak this rule exists to prevent: an empty code
   was returning `422` from Pydantic's `min_length` while a wrong one returned `401`, which
   told a caller their guess was at least the right shape.

#### The contract is now enforced in both directions

`tests/integration/test_contract_conformance.py` compares `openapi.yaml` to the routed
application, method by method. It found two undocumented endpoints on its first run —
`GET /media/{media_id}`, routed since V0, and `GET /families/{family_id}`. The path-only
version of that test passes on both, which is why it compares operations.

#### `packages/client` — generated, and zero dependencies

A Python generator emits the typed surface (22 operations, 32 schemas) and a hand-written
runtime supplies transport, `Result`, session and queue. `openapi-typescript` would also have
worked and was rejected for two reasons: its output is types only, so the transport is
hand-written either way; and adding it would put a `node_modules` and a lockfile back into the
one part of this repository that has managed without them. The generator **refuses** rather
than guessing — an unknown schema type, an unknown brand, a missing `operationId` — because a
generated `unknown` is how a contract stops being enforced without anyone noticing.

#### Time as language, held on both sides

`days_since_capture` is gone from the wire; `Spark.saved` and `Suggestion.elapsed` carry the
phrase. That alone is one deploy away from being worked around, so the client holds the other
half: `Instant` is branded and is deliberately not a `Date`, and `packages/client` contains no
`Date.parse`, `new Date`, `Date.now`, `getTime` or `valueOf` — asserted by a test that
mutation-checks its own regexes against the exact line someone would write under a deadline.

The design test that was *supposed* to catch this had been passing for a year: it scanned
Pydantic `AnnAssign` fields, and `days_since_capture` was in a dict literal inside
`render_suggestion`. It now reads the renderers' dict keys too.

#### Native capture, verified against the packages rather than remembered

`expo-sharing`'s first-party config plugin — added in SDK 55 — covers the iOS share extension
*and* the Android `SEND` filters in one declaration. Verified by unpacking the published
57.0.15 tarball rather than trusting a summary, which is also how the keychain option turned
out to be `accessGroup` and not `keychainAccessGroup`.

The alternative, `expo-share-extension`, renders a React Native view inside the share sheet so
the app never opens. It is the nicer interaction and it is broken on SDK 55+: the view
controller boots the runtime without an Expo `AppContext`, so `globalThis.expo` is never
installed and the bundle throws on import. The fix exists only in a `6.0.0-beta` from February
2026 in a repository untouched since April. Recorded in `capture/incoming.ts` with the
condition for revisiting.

#### End to end, across both languages

`tests/e2e/test_the_app_against_the_server.py` starts the real ASGI application on a real port
and runs the real generated TypeScript client against it, in Node, with the server's
`FrozenClock` advanced eight months between the two halves of the story. Nothing is stubbed:
JSON on the wire, bearer tokens in headers, the offline queue holding a capture with no
network and replaying it without duplicating it.

`docs/DEVICE.md` is the remainder — four things that genuinely need hardware, and it is short
because everything checkable without a device is already a test.

### Phase 6 complete — Voice (TASK-601 to 606)

**48/68. `make check`: 1,664 Python tests, 168 TypeScript tests, 96.90% domain coverage.**

#### One rule, held in four places

> The recording is the artifact. The transcript is only an index.

That reads as a UI preference and it is a data rule, because every downstream pressure runs
the other way: text is searchable, diffable, cheap to render and easy to summarise, and a
4.2-second m4a of a man laughing halfway through a sentence is none of those. Every system
that has stored both has ended up treating the text as the record.

So it is held where it cannot be argued with:

* **The aggregate is the recording.** `VoiceNote`'s identity is the `MediaId` of the audio,
  not a surrogate key. There is no constructor that produces a note without audio.
* **The table agrees.** `voice_note.media_id` is the primary key, so there is no row that can
  hold a paraphrase of something a parent said whose audio has gone.
* **Attaching a transcript cannot reach the audio.** `indexed_by(transcript)` takes one
  argument. No store, no path, no id is in scope.
* **The client's type has no shape for the wrong screen.** `Playback.player` is
  non-nullable and `Playback.words` is not.

#### Nothing is rejected for being unpolished

PRD §24 is written about content and it is really about engineering, because the ways a
system quietly polishes a recording are all small and all reasonable: a minimum duration so
a stray tap does not make an empty note, a silence trim, a loudness normalisation, a
re-record button, discarding audio once a transcript exists.

`tests/constitution/test_preserve_imperfection.py` scans for all five, in the shapes they
would actually be written — a named constant, an inline `duration < 0.5`, a Pydantic `ge`,
a verb, a string on a button — and mutation-checks every scanner against the exact line
someone would write. There is one distinction it draws carefully, and it is the whole
design of hold-to-talk:

> The **gesture** may have a threshold. The **recording** may not.

A press arms for 200ms before any audio is captured, so a tap never produces a recording —
not a discarded one, not a short one, none. That filters an input. Once audio exists it is
kept: half a second, silence, an interruption by a phone call, all of it.

#### "No public-model training by default" is no longer a default

The load-bearing word in PRD §44 was *default*, and a default is a setting. It is now
structural: `tests/constitution/test_no_public_model.py` walks the transitive import graph
of everything under `anuvritti.adapters` and fails the build if `socket`, `http`,
`urllib.request`, `httpx` or a vendor SDK appears. A **static** walk, because a runtime
check fires on the request that already sent the audio.

The `SpeechModel` port takes bytes and a mime type and nothing else — no id, no store, no
session, no URL. An adapter behind it can still do something foolish with the bytes; it
cannot be handed the address of anywhere to send them. The shipping default returns
nothing at all, and that is a complete answer: a wrong transcript is a plausible lie
attached to a piece of family history, and the recording loses nothing by being unindexed.

#### Speaking earns what typing earns

PRD §13's intent list is eight first-person sentences, and `HeuristicIntentEngine` was
built for captions — nouns and product names, where "buy" is a button label rather than
something a person wants. Run a transcript through it alone and speaking earns *less*
understanding than typing, which makes voice the expensive way to save something.

`SpokenIntentEngine` decorates it for `VOICE` sources only, and handles the three things
captions never do:

1. **People correct themselves.** "I want him to watch this — no, actually I want to do
   this with him." Matches are weighted by where they fall; the last statement wins.
2. **People negate.** The caption engine reads "I don't want to buy him another one" as
   BUY, which is worse than reading nothing. Negation is scoped to its clause, a phrase
   carrying its own negation is immune ("I don't want to forget this" is the most emphatic
   REMEMBER there is), and a negated intent **vetoes** the caption's score rather than
   merely failing to add to it — refusing to add is not enough when the score is already there.
3. **People hesitate.** Fillers are stripped, so a hesitant parent is not read as a less
   certain one. "actually" is deliberately *not* a filler: it is the word carrying the
   correction.

`tests/unit/adapters/test_heuristic_voice.py` asserts parity in the strong direction — the
same words spoken are never understood *worse* than the same words typed — and that closed
the gap at its cause: a transcript is now passed to the inner engine as the parent's own
words, which is what it is.

#### The vault has no count

`GET /v1/voice` returns `{recordings: [...]}` and nothing else. `shelve` groups by month
and neither the shelf nor a period carries a length that means anything but "rows to draw",
so a badge would need a field that does not exist. `VoiceNoteKept` carries no duration
either — the obvious payload field, and the one that would make the audit trail totalable.

The reason to record is stated once, in the present tense, at the moment it is most true:
after a recording is kept, *"That's in this year's film."* Phase 7 compiles from what is
already in the archive, so it is a statement rather than a promise.

#### Verified against the tarball, again

`expo-audio@57.0.4`, unpacked and read rather than recalled. Three facts that recall would
have got wrong, each of which would have shipped a silent bug:

* `useAudioRecorderState(recorder, interval)` **polls**, default 500ms. A waveform at that
  rate is four bars for a two-second recording — a still image. The app uses 60ms.
* `metering` is absent unless `isMeteringEnabled: true`, and **neither** `RecordingPresets`
  sets it. The presets alone give a permanently flat waveform.
* `RecordingPresets.HIGH_QUALITY` is 44.1kHz **stereo** at 128kbps: a stereo recording of a
  mono source at four times the bitrate speech needs. The app's own preset is mono at
  32kbps — a five-second why is about 20KB, which matters because these are kept forever.

The `.m4a` mime type is the other one worth writing down: `audio/mp4` by the book, but both
platforms hand over `audio/x-m4a` often enough that the server now accepts all three. A 415
here is the one failure on this path that loses a thing rather than delaying it.

#### End to end, including the voice

The cross-language E2E now records a why in January and plays it back in September: the
bytes go up, the note says what they are, the handset's reading arrives with machine
provenance, the recording comes back **byte for byte** eight months later — which is how
the test proves nothing trimmed or re-encoded it — a parent corrects the transcript by
hand, and the export carries both the audio and who said which words.

**Next: TASK-701** — extract `filmkit`. Phase 7 turns a year of these recordings into the
film they were always for, and TASK-707 will measure narration against the
`duration_seconds` this phase started recording.

# Wave 1 — nine prompts, eight of them in parallel

Every prompt below is self-contained: open a new chat in `/Users/prashantsingh/Projects/dadaa`,
paste one, and leave it alone until it reports. Each chat reads
[WORKING.md](WORKING.md) first, works in its own git worktree so the chats never touch
each other's files, records itself on the shared board, and writes a report to
`var/reviews/TASK-NNN.md`.

**Order.** TASK-711 runs alone, first, in the main tree — it commits everything that is
currently uncommitted (Phase 7, the harness, these prompts) and gives every other chat a
clean base. When it reports, open up to eight chats and paste the rest in any order.

**Watching.** `.venv/bin/python scripts/tracker.py board` lists everything in flight,
blocked, or landed with a commit. Reports live in `var/reviews/`.

**Review.** When you want work looked at, say *"review 713 and 717"* (or *"review the
board"*). The review reads the report, diffs the branch against `main`, reruns the
gates, merges what holds, commits the tracker, and tells you what it refused and why.

---

## TASK-711 — Commit Phase 7 and unbreak CI  *(alone, first, main tree; pushes to GitHub)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-711; start with
`python3 scripts/tracker.py brief TASK-711`. Work in the main tree, not a worktree: the
job is the uncommitted tree itself.

What is true right now: the working tree carries all of Phase 7 (film domain, provenance,
the FilmExport, packages/world/scenes, tests/constitution/test_film_provenance.py) plus
docs/prompts/ and a tracker.py with `brief`, `board` and `set --commit`. `make check` is
green. requirements-dev.txt ends in `../filmkit`, which only resolves on this laptop, so
the next push to GitHub fails at pip install. This repository has no git remote at all.
gh is authenticated as prasantk8.

Decide filmkit's home. The recommendation is to fold it into this monorepo as
packages/filmkit (`git subtree add --prefix packages/filmkit ~/Projects/filmkit main`
keeps its history, including cc42d5b, the extraction commit), because one repository
means one CI, one version, one review; requirements-dev.txt then says `-e packages/filmkit`
and the production image still never installs it (read the comment above that line and
keep its promise). If, after reading filmkit's Makefile and tests, you believe it should
stay separate and be pinned by SHA, do that instead and say why in the report. Either
way filmkit's 97 tests must run in this repository's CI.

Then: review the diff as the founder would (git status, git diff --stat; open anything
that looks like generated media, a family's data, node_modules or dist, and make sure
.gitignore already refuses it) and commit Phase 7 in a few well-named commits, not one
blob — the domain and provenance, the world scenes, the tests, the tooling and docs.
Add the three npm suites (packages/world, packages/client, apps/anuvritti) to
.github/workflows/ci.yml alongside the Python gate, so CI runs exactly what `make check`
runs. Create a private GitHub repository (`gh repo create anuvritti --private
--source=. --push`; if filmkit stays separate, one for it too, and note whether
autovideo-engine at ~/Projects should get the same), push, and watch the first run with
`gh run watch`; fix until it is green. Record what you pushed and the run URL in the
report.

Done means: `.venv/bin/python -m pytest tests/foundation -q` and `make check` pass here,
CI is green on GitHub, `git status` is clean, and the tracker records TASK-711 completed
with the commit. Report per WORKING.md, at var/reviews/TASK-711.md and as your final
message. Nothing else may start until you report.
```

---

## TASK-712 — FilmRenderer: the first pixel  *(parallel; needs Chromium in the dev venv)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-712; start with
`python3 scripts/tracker.py brief TASK-712`, then enter worktree task-712 as WORKING.md
describes.

This is the task the whole product has been waiting for. The app already says "That's
in this year's film", and today nothing in this repository draws a pixel: the compiler
(src/anuvritti/adapters/film/filmkit_compiler.py, export.py) emits a provenance-verified
film.json and a media bundle, and stops. Make the first frame exist, and make it look
like the design language — packages/world is the only source of type, colour and
rhythm; a frame of the film and a screen of the app must be recognisably the same
world.

Shape: a FilmRenderer port in application/ports.py, a ChromiumFfmpegRenderer adapter at
src/anuvritti/adapters/film/render.py, and a fake for tests/support. Each scene becomes
HTML through packages/world/scenes with world.css, scenes.css, the fonts and the
photograph inlined — Chromium's set_content has no base URL, so a frame must be the same
offline. One PNG per scene via filmkit.browser; silence generated for silent scenes;
per-scene render and concat via filmkit.compositor. `make film ARCHIVE=<dir>` renders a
FilmExport folder to an mp4 in var/. Playwright and Chromium belong to the dev venv
only; read the comment at the end of requirements-dev.txt and keep the production image
free of them.

The gate is tests/integration/test_render.py, and it must not merely check that a file
exists: ffprobe's account of the mp4 (duration, stream count, frame size) must agree
with the compiled timeline, and every frame must trace to a real scene in film.json —
provenance is the film's ethics (tests/constitution/test_film_provenance.py). Write one
still to var/film/ so the founder can look at a frame; never commit it.

Report per WORKING.md, at var/reviews/TASK-712.md and as your final message. Under
"What surprised you", say what the first frame taught you about packages/world/scenes.
```

---

## TASK-713 — The phone, wired  *(parallel; Expo)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-713; start with
`python3 scripts/tracker.py brief TASK-713`, then enter worktree task-713 as WORKING.md
describes.

apps/anuvritti has never actually run: no node_modules, no lockfile, nothing routes to
/pair, so a fresh install reads "Nothing today. That's normal." while every request
401s. This task makes a fresh install truthful end to end, and the standard is the
product's own: capture must take seconds (PRD 8.2), and a recording of a parent's voice
is never lost.

Do, in this order, verifying each against the installed package and not from memory:
`npx expo install --fix`, tsc clean, a committed package-lock.json. A pairing gate in
app/_layout.tsx so an unpaired phone reaches /pair and `router.replace('/')` after
pairing, with no flash of the empty home. Image shares uploaded and captured instead of
dropped (src/provider.tsx:104). Playback authenticated — read expo-audio's installed
typings for how useAudioPlayer takes `{uri, headers}`. HoldToTalk's arm cancelled when
the finger lifts during the OS permission sheet, so a first-time user is not left
recording. Voice uploads spooled (src/storage) so a recording survives a dead network
and a killed app, and is uploaded exactly once. Every one of these gets a test in
apps/anuvritti/test that fails before and passes after.

Gate: `npm --prefix apps/anuvritti test && npx --prefix apps/anuvritti tsc --noEmit`,
then `make check`. Do not change copy or colour — TASK-714 and TASK-715 own the words and
the saffron; if you see them wrong, put it in Proposed tasks. Report per WORKING.md, at
var/reviews/TASK-713.md and as your final message, including the exact device or
simulator you ran it on, or that you could not.
```

---

## TASK-717 — Measured on the server, never trusted from the handset  *(parallel)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-717; start with
`python3 scripts/tracker.py brief TASK-717`, then enter worktree task-717 as WORKING.md
describes.

VoiceNote.duration_seconds (src/anuvritti/domain/voice.py) is the one number the film
depends on, and today it arrives from the handset and is believed. The constitution
says a recording is never cut off (tests/constitution/test_real_voice.py); a clip the
client under-reports can pass that invariant and still be truncated in the film. Make
the invariant unforgeable: duration is probed from the bytes at keep time
(filmkit.narration.measure over ffprobe), and the handset's figure is only compared.

Shape: a MediaProbe port in application/ports.py, an adapter at
src/anuvritti/adapters/media/measure.py, a fake in tests/support/fakes.py, and the keep
path in application/voice.py using the port. Decide what a disagreement means — a
tolerance, and beyond it a recorded discrepancy rather than a silent overwrite, because
"the phone said 12 seconds, the bytes say 9" is itself something a parent might one day
want to know about that recording (ADR-0005: provenance, not guesses). An unreadable
file is a Result error, never an exception across the port. Nothing about this may make
capture slower than a human can notice; if probing is not sub-second on a real file,
say so and propose where it moves.

Gate: `.venv/bin/python -m pytest tests/unit/adapters/test_measure.py
tests/constitution/test_real_voice.py -q`, then `make check`. Strengthen
test_real_voice.py so an under-reporting client is caught, and keep the HTTP contract
(docs/contracts/openapi.yaml) honest if the response shape changes. Report per
WORKING.md, at var/reviews/TASK-717.md and as your final message.
```

---

## TASK-801 — FamilyLexicon  *(parallel)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-801; start with
`python3 scripts/tracker.py brief TASK-801`, then enter worktree task-801 as WORKING.md
describes.

Every family has its own words: Nani, the blue bunny, "the big park", the way one child
says "pasghetti". The intent engine (src/anuvritti/adapters/intent/heuristic.py,
spoken.py) does not know them, so every correction a parent makes is thrown away. Build
FamilyLexicon in src/anuvritti/domain/lexicon.py: every correction trains that one
family's private lexicon, held in the family's own archive
(adapters/persistence/schema.py, sqlite.py), consulted by the engine on the next capture.
No shared model, no network, no other family's data — tests/constitution/
test_no_public_model.py and test_no_surveillance.py are the judges, and PRD 44 is why.

Ambition: a lexicon that a parent never has to manage. Corrections are the only
training signal; what is learned carries provenance (Attributed[T] in domain/values.py,
ADR-0005: the lexicon's confidence is earned by repetition, not asserted); an entry
decays or is forgotten when the family stops using it, because PRD 8.8 says not
everything needs to be remembered. Find where a correction already enters the system
(application/capture.py, the HTTP surface) and wire the use case there; if the contract
has no way to correct, add one to docs/contracts/openapi.yaml and say `make client` is
needed in the report.

Gate: `.venv/bin/python -m pytest tests/unit/domain/test_lexicon.py -q`, then
`make check`, with a constitution test of your own that proves two families' lexicons
cannot see each other. Report per WORKING.md, at var/reviews/TASK-801.md and as your
final message; under Proposed tasks, say what TASK-802 (constellations) and TASK-805
(search) should take from this.
```

---

## TASK-815 — Return signals beyond age and weekend  *(parallel)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-815; start with
`python3 scripts/tracker.py brief TASK-815`, then enter worktree task-815 as WORKING.md
describes.

The Return Engine (src/anuvritti/domain/return_engine.py: ReturnContext, Score,
Suggestion, ReturnEngine) is the product's whole reason to exist — resurfacing matters
more than saving (PRD 8.3, 14, 55.4) — and today it knows two things: the child's age
and whether it is a weekend. Teach it to notice: the season, a birthday within the
month, the child's stated interests from Right Now (domain/presence.py), and a
parent-approved event. "You once saved something about the moon. Look outside tonight"
becomes possible.

Design rule, non-negotiable: each signal is a pure scorer with a name, and no signal may
raise urgency — only fit. The engine may say "this fits tonight"; it may never say
"you have not done this in a while". tests/constitution/test_no_guilt.py is the judge;
extend it so that a signal that tries to raise urgency is rejected by construction, not
by review. The reason line on a Suggestion should come from the signal that won, in
words a parent would say, never in the app's voice — "Winter, and she said she likes
snow", not "seasonal match score 0.8". Keep describe_elapsed's promise: no `N days`.

Gate: `.venv/bin/python -m pytest tests/unit/domain/test_return_engine.py
tests/constitution/test_no_guilt.py -q`, then `make check`; property-style tests for
"fit never becomes urgency" are welcome if hypothesis is already in the venv. Report
per WORKING.md, at var/reviews/TASK-815.md and as your final message, and propose how
Papa Today (TASK-807) should draw its one line a day from these signals.
```

---

## TASK-816 — Lift the V0 gate: COOK, VISIT, TELL, LISTEN  *(parallel)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-816; start with
`python3 scripts/tracker.py brief TASK-816`, then enter worktree task-816 as WORKING.md
describes.

IntentType (src/anuvritti/domain/values.py) still wears V0's gate. A recipe a parent
wants to cook with the child, a place to take her, a story to tell him one day, a song
to listen to together — each has nowhere to go. Add COOK, VISIT, TELL and LISTEN (PRD
13, PRD 50), and teach the spoken engine (adapters/intent/spoken.py, heuristic.py) their
first-person shapes: "I want to make this with her", "we should go here when he's
older", "remind me to tell her about", "play this for him". A parent speaks these to
the phone in one breath; the engine should get them right without a menu.

tests/constitution/test_v0_scope.py exists precisely to stop scope creeping; read it,
understand what it protects, and change it deliberately, with a commit message that
says this is V1 opening the gate, not V0 forgetting it. Check every place an intent is
enumerated — the HTTP contract (docs/contracts/openapi.yaml, the generated client, the
app's worth.ts) and the film — and either carry the new intents through or record in
the report exactly where they stop and who picks them up (TASK-811 needs TELL).
Confidence and provenance rules (Attributed[T], ADR-0004, ADR-0005) apply to the new
shapes exactly as to the old.

Gate: `.venv/bin/python -m pytest tests/unit/domain/test_values.py
tests/unit/adapters/test_heuristic_voice.py -q`, then `make check`. Report per
WORKING.md, at var/reviews/TASK-816.md and as your final message, with a table of the
sentences you taught and how confidently each is classified.
```

---

## TASK-817 — Right Now returns to its own cadence  *(parallel; this is the founder's decision, made)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-817; start with
`python3 scripts/tracker.py brief TASK-817`, then enter worktree task-817 as WORKING.md
describes.

Right Now was written (PRD 17, V0 Feature 9 under PRD 48) as an occasional snapshot:
every few months, two minutes, several fields at once — what she is into, what he says
wrong, what scares her, the question he asked that you could not answer. It shipped as
a daily single question. A daily question is the shape of a habit, and the anti-metrics
(PRD 8.5, PRD 53) exist to refuse habits. The founder has decided: return it to its
cadence.

Change src/anuvritti/application/presence.py (CaptureRightNowCommand,
CaptureRightNowUseCase) and domain/presence.py so a snapshot carries several fields at
once, is offered only when months have passed since the last one, and is never
counted, streaked or reminded about — a family that never fills one in loses nothing.
Carry it through the HTTP contract (docs/contracts/openapi.yaml, then `make client`)
and note what the app's Today screen must change (that screen belongs to TASK-713/715;
propose it, don't touch it). Existing daily answers stay readable: a migration or a
reader that treats an old single answer as a one-field snapshot, never a deletion (PRD
8.6). The "question you could not answer" field is the seed of TASK-811; shape it so
that task can read it.

Gate: `.venv/bin/python -m pytest tests/unit/application/test_presence.py
tests/constitution -q`, then `make check`. tests/constitution/test_no_guilt.py should
gain the case that makes the old daily cadence impossible to reintroduce. Report per
WORKING.md, at var/reviews/TASK-817.md and as your final message.
```

---

## TASK-905 — A backup that has been restored  *(parallel; infrastructure)*

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-905; start with
`python3 scripts/tracker.py brief TASK-905`, then enter worktree task-905 as WORKING.md
describes.

A backup nobody has restored is a hope. The archive is one SQLite file (ADR-0003) plus
a media directory under var/ (ANUVRITTI_MEDIA_DIR), encrypted at rest with a Fernet key
from src/anuvritti/config/settings.py. Build the thing a family can lean on: a
scheduled `sqlite3 .backup` (a consistent snapshot, never a file copy of a live db)
plus media to an off-site copy; the key escrowed where a second person can find it;
and a restore performed into a scratch container from the existing Dockerfile, proving
the restored archive serves the same data — the same kept recording plays, the same
film.json compiles byte for byte.

Shape: scripts/backup.sh and scripts/restore.sh (or a small Python module under
adapters/ if it needs the settings), parametrised by an off-site target the founder
supplies (an rclone remote, a second disk, an S3-compatible bucket) — invent no
credentials and hard-code no host. tests/integration/test_backup.py runs backup and
restore against a temporary archive and asserts equality; it must run in CI without
Docker, with the container rehearsal as a documented manual step. docs/RUNBOOK.md gets
the operating procedure; a new docs/CONTINUITY.md says, in ten lines a grieving spouse
could follow, where the key is, where the backup is, and how to restore. Read PRD 44 and
HARDENING 5.4 first; the whole point is that the family's material survives the founder.

Gate: `.venv/bin/python -m pytest tests/integration/test_backup.py -q`, then
`make check`. Report per WORKING.md, at var/reviews/TASK-905.md and as your final
message, and state plainly what the founder still has to do by hand (choose the
off-site target, place the escrowed key) before this is real. TASK-909 (ADR-0006) and
TASK-1101 (migrations) build on this; propose what they should assume.
```

---

## After wave 1

When 711 has landed, `tracker.py next` and the board tell you what unlocked. Wave 2 is
already visible from the tracker: 714, 715 (after 713); 709, 710, 716 (after 712);
802, 804, 805 (after 801); 811 (after 816); 906 (after 711); 908, 1009 (after 713);
909, 1101 (after 905). Ask for *"wave 2 prompts"* and they will be written against what
wave 1 actually built, not against what it was supposed to.

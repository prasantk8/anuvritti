# Wave 2 — nine prompts, and one thing to stop pretending

Same rules as [wave-1.md](wave-1.md): open a new chat in
`/Users/prashantsingh/Projects/dadaa`, paste one prompt, leave it alone until it reports.
Every chat reads [WORKING.md](WORKING.md) first, works in its own git worktree, records
itself on the shared board, and writes a report to `var/reviews/TASK-NNN.md`.

## Why this wave exists

Phases 9, 10 and 11 built a great deal of good code that nothing runs. Ten modules pass
their own tests and no screen, route, container or script constructs any of them: the
in-app camera, the device vault, the resumable uploader, the resource budget, the return
notifications, the widget payload, `papaToday`, the Future Inbox store, the importer, and
the rehearse-before-apply migration engine.

That is the whole distance between "we have the code" and "there is a product to look at",
which is what this wave closes. `tracker.py audit` and
`tests/architecture/test_reachability.py` are the scoreboard: **this wave is finished when
`NOT_IN_SERVICE` and `TS_NOT_IN_SERVICE` are empty and `audit` prints `board OK`.**

## The thirty-day gate is deferred (2026-08-29)

TASK-910 used to be a `dependencies` entry on fifty-seven tasks. It is not any more, and
neither is TASK-907. Both stay open, both are release gates held in writing
(`docs/VALIDATION.md`, `docs/DEVICE.md`), both carry `runs_on` in `tracker.json`, and
`scripts/tracker.py validate` refuses to let either become a dependency edge again. **No
chat in this wave is blocked on hardware or on a month.** If your task genuinely needs a
phone in a hand, say so in the report and record `blocked` — do not simulate it, and do not
write down a result you did not observe.

## Order

**Round 1 — four chats, in parallel, start now.**
TASK-1101, TASK-1002, TASK-1004, TASK-1012.

**Round 2 — four chats, after Round 1 reports.**
TASK-1003 (wants TASK-1002's decision about which uploader survives), TASK-1008 (meters
the drain TASK-1002 rebuilt), TASK-819 and TASK-908 (both touch the composition root
TASK-1101 changes — run these two one after the other, not together).

**Held, and honestly.** TASK-1005 and TASK-1010 are in the last section. Neither is a chat
you open today.

---

## Round 1

### TASK-1101 — the container rehearses a migration before it applies one

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1101; start with
`python3 scripts/tracker.py brief TASK-1101`.

What is true right now: src/anuvritti/adapters/persistence/migrations.py implements a
forward path and a rehearsed way back, it is tested by tests/integration/test_migrations.py,
and nothing constructs it. The container calls schema.migrate() directly, so the engine
that was built to rehearse against a copy of a real archive before touching one has never
run against anything. It is named in NOT_IN_SERVICE in tests/architecture/test_reachability.py
with your task id.

Your job is the wiring and the proof, not a second engine. The container is the composition
root; find it, read how schema.migrate() is called today, and make the migration engine the
thing that runs on startup — including the rehearsal, because the rehearsal is the whole
point. A migration that is applied without having been rehearsed against a copy is the
failure this task exists to prevent, and an archive is a family's photographs.

Think hard about what happens when the rehearsal fails. The app must not start on a schema
it could not prove it can move, and it must say why in a way an operator at 3am can act on.
docs/RUNBOOK.md is where that goes.

Done means: the line for `anuvritti.adapters.persistence.migrations` is DELETED from
NOT_IN_SERVICE (deleting a line there is the definition of "wired"), a test proves the
container refuses to start when a rehearsal fails, `make check` is green, and the report
says what happens on the next real deployment.
```

### TASK-1002 — one uploader, and it is the resumable one

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1002; start with
`python3 scripts/tracker.py brief TASK-1002`.

Read this before you plan: THE APP ALREADY HAS A WORKING UPLOADER. apps/anuvritti/src/upload/spool.ts
is the Outbox from TASK-713 — it holds files rather than JSON, writes before it sends,
survives the app being killed, and lands exactly once. It is wired into provider.tsx and it
drains on connect, on foreground, and on launch. Phase 10 then built a SECOND uploader,
apps/anuvritti/src/sync/uploader.ts, which adds the thing the first one does not have:
chunked, byte-resumable transfer that picks up mid-file after the process dies. Nothing
imports it.

So this task is not "wire it in". It is a reconciliation, and the deliverable is ONE
uploader. Read both, honestly. The likely answer is that the Outbox keeps its custody and
exactly-once semantics and delegates the actual transfer to the resumable uploader, so a
parent on a train who loses signal 8MB into a 12MB video resumes at 8MB instead of at zero —
but decide it from the code, and if the right answer is to fold the resumable logic into
spool.ts and delete sync/uploader.ts, do that and say why. Two implementations of the same
promise is how the app and the archive come to disagree about what "uploaded" means.

The server side has to agree. Chunked resumable upload is an HTTP contract: read
docs/contracts/openapi.yaml, decide whether the media endpoint already supports a byte
range or needs to, and if it changes, change the contract and regenerate the client
(`make client` — say so in the report).

Done means: src/sync/uploader.ts is DELETED from TS_NOT_IN_SERVICE in
tests/architecture/test_reachability.py (or the file is gone and its logic lives in
spool.ts), a test kills the process mid-transfer and proves the resume, `make check` is
green, and the report names the uploader that survived and the one that did not.
```

### TASK-1004 — the return arrives on the lock screen

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1004; start with
`python3 scripts/tracker.py brief TASK-1004`.

What is true right now: apps/anuvritti/src/return/notifications.ts is complete and good —
zero server push, at most one a day, permanent silence that survives a cold boot and an
upgrade, no streaks and no guilt copy. No screen registers it, so it has never scheduled a
notification. It is named in TS_NOT_IN_SERVICE with your task id.

Wire it where the app actually starts: app/_layout.tsx. The scheduler needs the Return
Engine's suggestion for today, which the provider already fetches, and it needs to run
without the app being open — read the installed expo-notifications package (do not recall
its API from memory, recall goes stale) and decide honestly whether a local schedule alone
delivers this or whether a background task is required.

Then build the half that does not exist yet: THE OFF SWITCH. "Silenceable forever in one
tap" is a promise in the task description and there is no tap anywhere in the app. A parent
who is grieving, or overwhelmed, or simply does not want this, must be able to end it in one
gesture and never be asked again — not a settings screen three levels down, and never a
"are you sure?" that argues. Design that surface with the same care as the Spark: read
docs/PRD.md sections 8.3, 8.5, 14 and 53, and packages/world for the language and the type.
This is the part the founder will look at.

Done means: src/return/notifications.ts is DELETED from TS_NOT_IN_SERVICE, a test proves
silence survives a simulated app upgrade, the one-tap off switch exists on a real screen,
`make check` is green, and the report describes what a parent sees on their lock screen and
what happens when they turn it off.
```

### TASK-1012 — the app speaks the family's language, including out loud

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1012; start with
`python3 scripts/tracker.py brief TASK-1012`.

What is true right now, and it is the whole task: every visible word in this app has been
translated into three languages, and every word it SAYS OUT LOUD is hardcoded English.
Open apps/anuvritti/src/a11y/accessibility.ts — `Memory idea: ${title}`,
`Why it was saved: ${why}`, `Recording microphone active. ${n} seconds elapsed.`,
`Right Now daily question for ${child}` — none of it goes through the translator. A parent
using Anuvritti in Hindi with VoiceOver hears an English app describing their child's
memories. Same for src/said.ts if it holds announcement copy; check it.

Move every announcement into packages/world/src/language beside the visible copy, and make
the a11y builders take the translator the way the screens do. Read
apps/anuvritti/src/useTranslator.ts and a screen that uses it before you design the shape.

The interesting part is not the plumbing, it is the sentences. A screen-reader announcement
is not a translated label — it is a sentence spoken aloud, and the three languages do not
put the pieces in the same order. `Why you saved ${title}` cannot be assembled from
fragments in Hindi. Build the copy so a translator writes whole sentences with named
placeholders, not concatenated parts, and say in the report which announcements had to be
rewritten because the English structure did not survive.

The Hindi and Spanish strings currently in the catalogue have not been read by a native
speaker. Do not add to that debt silently: flag every string you add that needs a review
pass, in one place, and propose it as a task.

Done means: no announcement string is built in a component or in the a11y module,
tests/design/test_the_app.py stays green (it brace-matches expression-valued props now and
will catch a literal in an `accessibilityLabel={...}`), `make check` and
`npm --prefix packages/world test` pass, and the report says what a Hindi-speaking parent
now hears.
```

---

## Round 2

### TASK-1003 — the camera is in the app, and the vault is on the path

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1003; start with
`python3 scripts/tracker.py brief TASK-1003`. Read var/reviews/TASK-1002.md first — that
chat decided which uploader survives, and your capture path ends in it.

What is true right now: apps/anuvritti/src/capture/native.ts (NativeCaptureManager, a 10
second cold-start budget) and apps/anuvritti/src/vault/device-vault.ts (AES-256-GCM envelope
encryption, key in the Secure Enclave under WHEN_UNLOCKED_THIS_DEVICE_ONLY, in the App
Group) are both complete, both tested, and both dark. There is no camera screen. A parent
can share a photograph in from another app and can hold a button to talk — they cannot point
this app at their child and press.

Build the screen. This is the most-used surface in the product and the one the ten-second
budget is about, so it is a design task as much as a wiring task: read docs/PRD.md 11 and
8.2, docs/DESIGN-BRIEF.md, and packages/world. Cold start to encrypted local save under ten
seconds, measured, not asserted — and the capture is saved before anything touches the
network, because PRD 8.2 says saving a memory is a local disk write.

The vault closes with you. src/vault/device-vault.ts is excused under TASK-1001 for exactly
one reason — its only importer is capture/native.ts, which is dark — so when your screen is
real, `encryptedQueueStore` must be on the actual capture path and not merely importable.
Record TASK-1001 completed too, with a note saying what now constructs it.

Verify the native APIs by reading the installed packages (expo-camera, expo-audio,
expo-secure-store), not from memory. If a capability genuinely needs a device to prove —
whether the Secure Enclave key really is device-only — say so in the report and add it to
docs/DEVICE.md rather than mocking it and calling it proven.

Done means: src/capture/native.ts AND src/vault/device-vault.ts are both DELETED from
TS_NOT_IN_SERVICE, a test measures the cold-start path against the budget, `make check` is
green, and the report describes the ten seconds as a parent experiences them.
```

### TASK-1008 — the budget meters the drain

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-1008; start with
`python3 scripts/tracker.py brief TASK-1008`. Read var/reviews/TASK-1002.md first — the
drain you are metering was rebuilt by that chat.

What is true right now: apps/anuvritti/src/sync/budget.ts (DeviceResourceBudget: capture
never wakes the radio, background work capped at 30s, uploads batched on unmetered wifi or
while charging, a 500MB / 1000-item spool ceiling with warnings at 80% and 95%) is complete
and nothing calls it. Every one of those four rules is currently a comment rather than a
behaviour.

Put it on the drain in provider.tsx, and hold to the rule that matters most: capture must
stay a pure local disk write. If metering makes saving a memory touch the network or the
battery API on the capture path, the metering is wrong, not the rule.

Then build the part that is missing: the 80% and 95% warnings have no surface. "The spool has
a ceiling it tells the parent about before it reaches it" means a parent finds out while
they still have room, in the app's own voice, once — not a modal, not a badge, not a number
that lives on screen. Read docs/PRD.md 8.2 and 46 and packages/world before you design it,
and remember PRD 53: this cannot become a nag.

Done means: src/sync/budget.ts is DELETED from TS_NOT_IN_SERVICE, a test proves capture
opens no socket while the spool is over its ceiling, the warning has a real surface,
`make check` is green, and the report says what a parent sees at 80%.
```

### TASK-819 — the container holds the Future Inbox store

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-819; start with
`python3 scripts/tracker.py brief TASK-819`. Run this AFTER TASK-1101 has reported — you
both change the composition root, and TASK-908 runs after you for the same reason.

What is true right now: src/anuvritti/domain/inbox.py is reached and its 43 tests pass, and
src/anuvritti/adapters/persistence/inbox.py — the store that makes a sealed message durable —
is constructed by nothing. A message a parent seals today for their child to open at
eighteen is held by an object the running application does not have. It is named in
NOT_IN_SERVICE with your task id.

Wire the store into the container and give the Future Inbox a front door: read
src/anuvritti/application/ports.py to see what the application expects, docs/contracts/openapi.yaml
for the HTTP surface, and decide whether this is a route, a CLI, or both. A contract change
means `make client` — say so in the report.

Think about the eighteen-year promise while you wire it, because that is what makes this
different from any other store: what is written today must be readable by software nobody
has written yet, and tests/constitution/test_inbox_sealed.py is where that lives. If wiring
it reveals that the seal is not durable across a schema change, that is the finding, and it
is worth more than the wiring.

Done means: the line for `anuvritti.adapters.persistence.inbox` is DELETED from
NOT_IN_SERVICE, a test seals a message through the real front door against the real migrated
schema, `make check` is green, and the report says what a parent can now do that they could
not do yesterday.
```

### TASK-908 — the importer gets a front door

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-908; start with
`python3 scripts/tracker.py brief TASK-908`. Run this AFTER TASK-819 has reported — you both
change the composition root.

What is true right now: src/anuvritti/application/import_.py exists, is tested, and has no
CLI and no route, so nothing has ever imported anything. It is named in NOT_IN_SERVICE with
your task id.

Decide the front door from what the importer is FOR, not from what is easiest. A family
arriving with years of photographs already somewhere else is the moment this product either
earns a place or does not, and that shapes whether this is an operator CLI, an authenticated
route, or a long-running job with progress. Read the importer, read docs/PRD.md on arrival
and on privacy (44), and choose.

Whatever you choose, two things are non-negotiable and both have tests waiting: nothing
imported may arrive without provenance (ADR-0005 — an imported photograph is not something
the family said, and the archive must never blur that), and nothing a family owns may leave
their process. The constitution tests decide.

Done means: the line for `anuvritti.application.import_` is DELETED from NOT_IN_SERVICE, the
front door is reachable from something that actually starts (tests/architecture/test_reachability.py
walks out from the ASGI app, scripts/*.py and the Makefile — so a CLI must be one of those),
`make check` is green, and the report describes an import as the person running it sees it.
```

### TASK-807 — papaToday gets a screen

```
Read docs/prompts/WORKING.md and hold to it. Your task is TASK-807; start with
`python3 scripts/tracker.py brief TASK-807`.

What is true right now: apps/anuvritti/src/model/today.ts exports `papaToday` and no screen
imports it. It is named in TS_NOT_IN_SERVICE with your task id.

Read the module first and decide whether it is still the right idea. This is a Phase 8 model
that Phase 9 and 10 built around without ever rendering, and app/index.tsx has since become
Today — one question, then the vault. If `papaToday` belongs inside that screen, put it
there. If it wants its own surface, give it one. If reading it honestly says the app outgrew
it, delete the module and the line together and argue that in the report — a deleted line in
TS_NOT_IN_SERVICE counts, and carrying a model nobody renders is its own kind of debt.

Whatever you decide, docs/PRD.md 8 and packages/world govern the surface, and app/index.tsx
is the screen to read before you touch anything.

Done means: src/model/today.ts is DELETED from TS_NOT_IN_SERVICE — rendered or removed —
`make check` is green, and the report says which it was and why.
```

---

## Held, and honestly

Neither of these is a chat to open today, and both stay open on the board rather than being
quietly closed.

**TASK-1005 — the widget.** `src/widgets/right-now-widget.ts` builds a correct payload for
the lock screen and the home screen, and iOS and Android widgets are native targets: a
WidgetKit extension and an App Widget provider, reached through a prebuild and signed with
provisioning this repository does not have. The same wall as the share extension. What
*could* be done without a device — writing the payload into the App Group on a schedule, so
the native side has something real to read the moment it exists — is worth proposing as its
own task; say so if you take it on. Until then the payload is honestly dark.

**TASK-1010 — on-device end to end in CI.** It claims a device matrix. `.github/workflows/device.yml`
runs `npm --prefix apps/anuvritti test` on a GitHub runner, and `device-e2e.test.ts` mocks
`SecureKeyStorage` and `NativeMediaDriver` — a good subsystem test, and not a device.
Two honest ways forward and no third: narrow the claim to what the workflow does and open a
new task for real hardware CI, or wire a real device cloud. The first is a small chat and
should probably happen soon; the second is a real decision about money and vendors, and it
belongs with TASK-907.

---

## When this wave is done

`tests/architecture/test_reachability.py` has two empty dictionaries, `tracker.py audit`
prints `board OK`, and every line of code in this repository is reached by something that
runs. That is the point at which the product can be run end to end and the bugs that come
out of it are worth the name — and the point at which thirty real days (TASK-910) has
something worth thirty real days to measure.

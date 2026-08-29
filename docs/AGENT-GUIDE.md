# How to close a task here

CLAUDE.md says what this codebase believes. This says what it takes to move a task to
`completed`, and it exists because Phases 9, 10 and 11 closed twenty tasks that were not
done. Every rule below is written against a specific thing that went wrong, and the failure
is named so the rule is arguable rather than arbitrary.

None of it is about working harder. All of it is about the difference between code that
exists and code that runs.

---

## 1. The gate is `make check`, not the task's own command

**What went wrong.** Every Phase 10 task's `verification_command` was
`npm --prefix apps/anuvritti test`. `node --test` strips TypeScript types without checking
them, so `tsc` never ran, and two files that do not compile shipped inside tasks marked
completed. Phase 11's commands were single-file `pytest` invocations, which is a test
asking itself whether it passes.

**The rule.** A task is not done until `make check` is green — all eight gates, on the
whole repo. The `verification_command` in `tracker.json` is the *specific* proof for that
task, and it is in addition to the gate, never instead of it.

`make check` now runs under `make -k`, so a failure in `lint` no longer hides the six gates
behind it. If you see one red gate, look for the others.

`scripts/` is inside the lint gate now. Backup, restore, the SBOM, the image scan and the
release runner are the operational surface, and for three phases they were the only Python
in the repo no gate ever read.

---

## 2. If nothing calls it, it is not done

**What went wrong.** Phases 9–11 landed eleven Python modules and ten TypeScript modules
that nothing in production constructs. Rate limiting was written and never mounted, so
there was no rate limiting. Telemetry was written and never mounted, and duplicated the
`observability.py` that *is* mounted. A retention engine was written that crashes on the
connection type this application actually uses. Every one of them passed its own tests,
because a test is a caller and the test suite is not production.

This is the Phase 5 pairing bug — correct, tested, unreachable — at module scale. The route
graph test was written so that could not happen to a *route* again. It happened to modules
instead.

**The rule.** `tests/architecture/test_reachability.py` walks the import graph out from the
things that actually start. A module the walk cannot reach must be named in
`NOT_IN_SERVICE` (Python) or `TS_NOT_IN_SERVICE` (the app) with a reason and an open task
id. A module may be unfinished. It may not be *quietly* unfinished.

Adding a name to those lists is a deliberate act you have to justify. Deleting one is the
definition of "wired". They only shrink.

For the app specifically: `apps/anuvritti/app/` is the entry set, because Expo Router turns
each file there into a screen. A parent cannot reach anything else. Accessibility labels
that no component imports are not accessibility. A translator that no screen calls is not
localisation.

---

## 3. A test that builds its own world proves nothing about ours

**What went wrong.** `tests/integration/test_retention.py` ran `CREATE TABLE spark` with
five columns of its own choosing. The real `spark` table has about thirty, and the module
queried a `spark.media_id` that does not exist and an `auth_token` table that does not
exist either. The test passed. The code could not run.

Of eleven new "integration" tests in Phase 11, exactly one drove the application. The rest
imported a pure function and asserted on its return value.

**The rule.**

- An integration test uses `tests/integration/conftest.py`'s `db` / `repos` /
  `seeded_family` fixtures — a real migrated schema over a real SQLite file. If your module
  cannot run against those, the module is wrong, not the fixtures.
- No `CREATE TABLE` in a test. Ever. If the schema is missing something, add a migration.
- An HTTP feature is tested through `create_app(...)` and a real request. Importing the
  handler and calling it is a unit test wearing an integration test's name.
- Read back what you wrote. A use case whose result only exists in the return value of the
  call that made it has not kept anything.

`tests/integration/test_isolation.py` and `tests/performance/test_full_archive.py` are the
two worked examples. Copy their shape.

---

## 4. Never write down something that did not happen

**What went wrong.** `docs/VALIDATION.md` was a first-person account of thirty days with a
family — a rainy Saturday, cardboard delivery boxes, a three-year-old calling the moon a
broken sun — reconstructed from the fixtures in `tests/e2e/test_thirty_days.py` and signed
with a date. Twenty tasks depended on it.

`docs/DEVICE.md` was reported as executed on a real iPhone and a real Android. It is an
undated checklist, unchanged. A CI job named "iOS On-Device Matrix" runs `npm test` and
mocks the Secure Enclave and the camera.

**The rule.** This is not a style point. The product's entire argument is that it will not
attach a plausible sentence to a family's history unless the sentence is true; nine tests
under `tests/constitution/` enforce that against the code. A document that narrates a test
run as lived experience is the same failure, aimed at ourselves.

So:

- A document describing something that happened says when, and the date is in the past.
- If it did not happen, the document says **NOT RUN** at the top and describes what running
  it would require. That is a complete, useful, honest deliverable.
- A task description that says "on a device" means on a device. A mock in place of the
  Secure Enclave is a fine unit test and is not the thing the task promised.
- If a HARDENING item cannot be closed in this task, say so in the tracker note and leave
  it open. An honest "not yet" costs one line. A wrong "closed" cost us three phases.

---

## 5. The contracts are contracts

**What went wrong.** `limits.py` returned `{"code", "message", "details"}` bare. Every other
error in the system is wrapped in `error`. `auth.py` has a whole `Refused` class written to
preserve that shape.

`retention.py` sat in `application/` and wrote raw SQL against a `sqlite3.Connection`,
bypassing the ports, the repositories, the unit of work and `GuardedConnection`. Two new
top-level packages (`infrastructure/`, `observability/`) appeared with no ADR, and
`tests/architecture/test_dependency_rule.py` was widened to admit them without either
task's `changed_files` recording the edit.

**The rules, in the order they get broken.**

| Rule | Where it lives |
|---|---|
| Every error on the wire is `{"error": {code, message, details}}` | `docs/contracts/errors.md` |
| Every code is in the catalogue, and the catalogue and `ErrorCode` never drift | `tests/unit/shared/test_errors.py` |
| `application/` talks to ports, never to a driver. SQL lives in `adapters/` | ADR-0001 |
| Failure is a returned `Result`, never a raised exception across a boundary | `shared/result.py` |
| Time comes from the injected `Clock`. Not `datetime.now`, not `time.time` | `shared/clock.py` |
| Randomness comes from the injected `RandomSource` | `shared/randomness.py` |
| A new top-level package needs an ADR *before* the fitness function admits it | `docs/architecture/` |

If a fitness function is in your way, that is the fitness function working. Widening
`ALLOWED` is a design decision that gets an ADR and shows up in `changed_files`, or it is
not made.

---

## 6. The tracker is a record, not a scoreboard

**What went wrong.** Twenty tasks closed on `TASK-910`, a validation gate that had never
been run. Nothing noticed, because `validate` only asked whether the file was well formed.
`completed_at` was `None` on all thirty-five Phase 9–11 tasks. Several `changed_files`
lists omitted files the task had edited, including the architecture test it widened.

**The rule.**

```
python3 scripts/tracker.py brief TASK-ID        # start here, always
python3 scripts/tracker.py set TASK-ID in_progress
...
make check                                       # all eight gates
python3 scripts/tracker.py set TASK-ID completed --files a.py,b.py --note "what it does now"
python3 scripts/tracker.py audit                 # no completed task stands on an open gate
```

- `changed_files` lists **every** file you touched, tests and fitness functions included.
- `--note` says what is true now, in one sentence. If the note has to hedge, the status is
  not `completed`.
- `tracker.py audit` is new and it currently fails: twelve completed tasks stand on
  dependencies that were reopened. That is the correct reading of the board, not a bug.

One task per chat (CLAUDE.md §3). Query the tracker; do not open the 130 KB file.

---

## 7. Write the way the rest of the codebase writes

The prose in this repository is part of the deliverable. `auth.py`, `container.py` and
`test_family_lexicon.py` are the reference. What they have in common:

- A module docstring says what the module is *for* and what would go wrong without it,
  referencing the PRD section that asked for it.
- Comments explain the decision, not the syntax. `# Check if table exists` above a query
  that checks whether a table exists is noise.
- A test name is a sentence about the product:
  `test_one_familys_words_never_reach_another`, not `test_isolation_2`.
- No hype in a docstring. "Enforces automated data lifecycle and retention policies" above
  code that crashes is worse than no docstring.

Match the surrounding density. Do not add a header comment to every function because you
saw one somewhere.

---

## What is actually open

Re-checked 2026-08-29, after Phases 7-11 were merged onto `main` and every gate ran green.
Each line below is a claim the evidence did not support, and the evidence is named.

**Not run, and the documents say so.** TASK-910 (`docs/VALIDATION.md`: thirty days with one
real family) and TASK-907 (`docs/DEVICE.md`: five things that need hardware). Both documents
now open with **NOT RUN**, which is the honest deliverable. The tracker did not agree with
them until now. TASK-910 is the root of the board: seventeen completed tasks depend on it,
which is what `tracker.py audit` has been trying to say.

**Built, and nothing calls it.** TASK-806 (Future Inbox store), TASK-1101 (the
rehearse-before-apply migration engine - the container still calls `schema.migrate()`),
TASK-1102 (the importer, no CLI and no route), and on the phone TASK-1002, TASK-1003,
TASK-1004, TASK-1005, TASK-1008, TASK-1009. Every one of these is *already* named in
`NOT_IN_SERVICE` or `TS_NOT_IN_SERVICE` with its own task id as the reason - the module was
honest and the board was not. `test_every_excuse_names_a_task_that_is_still_open` compares
the two records now, so they cannot disagree again.

**Claimed wider than it is.** TASK-1010 said a device matrix; `device.yml` runs
`npm --prefix apps/anuvritti test` on a GitHub runner and `device-e2e.test.ts` mocks
`SecureKeyStorage` and `NativeMediaDriver`. A good subsystem test, not a device. TASK-1012
said zero hardcoded literals; the visible copy is translated into three languages and every
screen-reader announcement in `src/a11y/accessibility.ts` is hardcoded English, so a parent
using Anuvritti in Hindi with VoiceOver hears an English app.

**Closed, and they stayed closed.** TASK-1103, 1105, 1106, 1107, 1108, 1109 and 1110 are
wired and reachable, and `make check` is green on all of it. Three things had to be fixed
first, and all three are the same shape as everything above: `rewrap_all` counted successes
and swallowed the files no key could open, `scan_image.py` skipped layer members it could
not read, and the SBOM emitted a component called `-e packages/filmkit` at version
`"pinned"`. Each was a routine that reported success about work it had not done.

**Phase 8 still holds fourteen pending tasks** (802-805, 808-818) and is the phase where the
product becomes magical rather than merely correct.

**Both of the things "worth doing regardless" are done.** `pip install -e .` works -
`requirements-dev.txt` never installed the project, `pythonpath = ["src"]` hid it from every
test for eleven phases, and two gates in `tests/foundation/test_toolchain.py` now hold it.
And everything is on `git@github.com:prasantk8/anuvritti.git`: twenty-eight branches that
existed only on one laptop are merged into `main`, and `main` is the only branch left.

---

## The one-line version

Wire it, prove it against the real schema through the real app, run every gate, and never
write down something that did not happen.

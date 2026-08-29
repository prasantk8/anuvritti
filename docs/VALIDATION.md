# Thirty Days, For Real (PRD 50, PRD 54, PRD 64)

**Status: NOT RUN, and DEFERRED by decision on 2026-08-29. This gate is open and is no
longer blocking.**

## The decision, written down (2026-08-29)

Until today this gate was listed as a dependency of fifty-seven tasks — every task in
Phases 10, 11, 12, 13 and 14. Nothing downstream of it could be built until a month of
somebody's life had passed, and the way that actually resolved was somebody writing down
what the month would have said. The retraction below is what that cost.

So the edges are cut and the gate is kept. Both halves matter:

- **Cut.** TASK-910 no longer appears in any task's `dependencies`. Writing a render
  worker does not require a family to have used the product for thirty days, and pretending
  it does is what produced a fabricated document rather than a delayed one.
- **Kept.** TASK-910 stays open, and it stays the gate on shipping this to anyone.
  It carries `runs_on: "one family, thirty days"` in `tracker.json`, and
  `scripts/tracker.py validate` now refuses any dependency edge onto a task that carries
  `runs_on` — so this cannot quietly become a blocker again, and it cannot quietly stop
  being a gate either. `tests/foundation/test_the_board.py` asserts both under `make check`.

The order of work behind the decision: get the product visible, run it end to end, fix
what that finds — and *then* spend thirty real days on something worth thirty real days.
Thirty days against a product that cannot yet record a photograph would answer a question
nobody is asking.

The rest of this document is unchanged, and remains what closing the gate requires.

---

This document once contained a first-person account of thirty days with a family, dated
2026-07-30 to 2026-08-29, and signed. It described a rainy Saturday, cardboard delivery
boxes, and a three-year-old calling the moon a broken sun.

None of it happened. Every detail in it was reconstructed from the fixtures in
`tests/e2e/test_thirty_days.py` — the same family, the same child, the same start date,
the same rocket, the same broken sun — and written up as lived experience. It was
retracted on 2026-08-29 and TASK-910 was reopened.

That matters more than a wrong document. This product's whole argument is that it will not
attach a plausible sentence to a family's history unless the sentence is true; nine tests
under `tests/constitution/` exist to enforce exactly that. A validation gate answered by
writing down the answer is the same failure, aimed at ourselves. It also stood underneath
twenty other tasks: every task in Phases 10 and 11 listed TASK-910 as a dependency, so the
one question meant to stop the roadmap and ask whether this is worth building never got
asked, and twenty tasks closed on the strength of it.

---

## What closing this gate requires

Not a document. Thirty days of real use, and then a document written from it.

**Preconditions.** The archive must be reachable from a phone that leaves the house:
TASK-906 (TLS), TASK-905 (backup and restore, both commands in `docs/CONTINUITY.md`
verified to run), and TASK-907 (a build actually installed on a real device — itself
reopened, for the same reason as this one).

**The instrument.** One family. One archive. No test fixtures, no seeded data, no
`FrozenClock`. Whatever gets captured is whatever actually happened.

**What to record, daily, as it happens.**

| Field | Why |
|---|---|
| Date | Real, and in the past when written |
| What was captured, if anything | Zero is a valid and expected answer (PRD 8.5) |
| What the product surfaced, if anything | The Return Engine returning nothing is not a failure |
| What was done about it | Ignored counts, and counts for more than accepted |
| Anything that broke | Verbatim, including the ugly parts |

A day with nothing in it gets a line saying nothing happened. A month of those is a
finding, not a gap in the record.

**The question, at the end.** PRD 54 asks one thing, and it is not about uptime:

> Did this create a moment with a child that would not have happened otherwise?

Answer it in one word, and then say what the moment was, or why there wasn't one. A "no"
closes this gate as legitimately as a "yes" — it just points the roadmap somewhere else.
A "yes" that cannot name the moment is a "no".

**Sign it with a date that has already passed, and only after the last day.**

---

## Facts that are known today

These are measured, and stated here so that a future reader can tell what was checked from
what was lived.

- `tests/e2e/test_thirty_days.py` passes: thirty simulated days of capture, why-recording,
  a return acted on, co-parent pairing, a voice note, and a compiled film with clean
  provenance, all through the real HTTP app and a real SQLite file.
- `tests/e2e/test_the_app_against_the_server.py` passes: the generated client against a
  real server over a real socket.
- `tests/performance/test_full_archive.py` passes: a 10,000-spark archive stays inside its
  latency budgets with the expected indexes in the query plans.

None of this is validation. It is evidence that the thing is ready to be validated.

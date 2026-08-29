# Thirty Days, For Real (PRD 50, PRD 54, PRD 64)

**Status: NOT RUN. This gate is open.**

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

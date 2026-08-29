# Context, and how not to spend it

Every chat starts empty and fills up. What fills it is mostly not the work — it is
re-reading things a previous chat already read, and re-deriving conclusions a previous
chat already wrote down. This page is how that stops.

The rule underneath all of it: **a chat should read the smallest artefact that already
contains the answer.** This repository has spent real effort producing those artefacts —
`tracker.py brief`, `var/reviews/TASK-NNN.md`, `changed_files` — and they only pay for
themselves if the next chat uses them instead of the source they were made from.

## What things actually cost

Measured on 2026-08-29, in round numbers, at roughly four bytes to the token:

| Reading                              | Cost      | The thing you should have read instead |
| ------------------------------------ | --------- | -------------------------------------- |
| `tracker.json`                       | **~46k**  | `tracker.py brief TASK-NNN` — **~300** |
| `docs/PRD.md` whole                  | ~11k      | the two or three sections your task cites |
| `docs/contracts/openapi.yaml`        | ~8k       | the one path you are changing |
| `docs/prompts/wave-2.md` whole       | ~6k       | your own prompt, which is ~800 |
| a wave's nine chats re-reading all of the above | ~600k | — |

`brief` is a hundred and sixty times smaller than the board and tells you more: the task,
the *files* its dependencies changed, and what it unlocks. Opening `tracker.json` is the
single most expensive mistake available in this repository, and CLAUDE.md section 3 forbids
it for exactly this reason.

## One task, one chat

This is not a style preference. A chat that does two tasks carries the first task's entire
exploration — every file it opened, every wrong turn — through the second one, and pays for
it on every subsequent message. Two chats each pay for their own task once.

So: one task, one chat, and when the task is done the chat is done. Do not keep it warm for
the next thing.

## The report is the interchange format

`var/reviews/TASK-NNN.md` exists so that the next chat can learn what a previous chat
concluded without replaying how it got there. A report is one or two thousand tokens; the
transcript that produced it is a hundred times that.

This means the report has an obligation the reviewer feels immediately: **write down what
you learned, not just what you did.** "What surprised you" is in the WORKING.md template
because it is the part nobody can reconstruct from the diff. A chat that skips it has
thrown its own context away.

And it means the reader has an obligation too: when your task depends on TASK-1003, read
`var/reviews/TASK-1003.md` and its `changed_files`. Do not go read TASK-1003's code from
scratch to find out what it decided. It already told you.

## Read in this order, and stop when you have enough

1. `tracker.py brief TASK-NNN` — always, first, and often sufficient to start.
2. Your prompt in `docs/prompts/wave-N.md`. Only your prompt. The wave preamble is worth
   reading once; the other eight prompts are for other chats.
3. `docs/prompts/WORKING.md` — small, and binding.
4. The reports of your dependencies.
5. The specific files the brief and the reports named.
6. The PRD sections your task cites. Sections, not the document.

Most chats never need step 6, and almost none need `docs/ARCHITECTURE.md` end to end.

## Search, do not scan

`grep`/`glob` for the symbol, then read the file the hit is in. `sed -n '40,90p'` when you
know the region. Never `cat` a file to find out whether it is relevant; `grep -c` answers
that for a hundredth of the price. CLAUDE.md section 2 says the same thing in one line.

When the question is genuinely "where does this live, and what calls it" and the answer
spans many files, that is what the **Explore** subagent is for: it reads widely in its own
context and returns the conclusion, so the file dumps never enter yours. Use it for
locating; do the reading and the judging yourself.

## Compact late; hand off early

Compaction is lossy in a specific and dangerous way: it keeps the shape of what happened and
drops the exact strings — the line number, the flag, the error text. When those are gone,
the next thing you do is go read the file again, which is what compaction was supposed to
save.

So before a long chat gets near its limit, do not compact — **write**. Put the state into
`var/reviews/TASK-NNN.md`, or into the task's `--note` on the board, or into the doc it
belongs in. Then open a new chat and read what you wrote. A written handoff loses nothing
that was worth keeping, and it leaves an artefact the next chat can use even if it is not
you.

Compact when you are mid-task and the state is genuinely in your head and nowhere else.
Start a new chat when the state is on disk.

## The review chat is its own chat, and it is short

Reviewing TASK-1003 means reading `var/reviews/TASK-1003.md`, the branch diff, and the two
or three files the five questions in the wave page point at. That is a small chat. Running
it inside the chat that *wrote* TASK-1003 is both expensive and useless — the author's chat
already believes the work is done, and it is carrying twenty files it no longer needs to
prove it.

## What never goes in a chat

Generated media, `var/` output, `node_modules`, `dist`, a whole lockfile, a database dump, a
family's data. If you need to know something about one of them, ask a command: `ls -la`,
`wc -l`, `sha256sum`, `ffprobe`. The answer is a line. The file is a megabyte.

## The short version

- `brief`, never the board.
- One task, one chat, and end it when the task ends.
- Read your dependencies' *reports*, not their code.
- Grep to locate, read to understand, and stop when you have enough.
- Write the state down, then start a fresh chat. Do not compact what you could have saved.

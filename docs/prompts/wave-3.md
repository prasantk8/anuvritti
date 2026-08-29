# Wave 3 — in public, in this order: a site, then Android, then the founder's own iPhone

Same rules as [wave-1.md](wave-1.md) and [wave-2.md](wave-2.md): open a new chat in
`/Users/prashantsingh/Projects/dadaa`, paste one prompt, leave it alone until it reports.
Every chat reads [WORKING.md](WORKING.md) and [CONTEXT.md](CONTEXT.md) first, works in its
own git worktree, records itself on the shared board, and writes `var/reviews/TASK-NNN.md`.

## Why this wave exists

Wave 2 makes the modules reachable from a screen. Nothing yet makes the product reachable
from outside this laptop. There is no website, no installable build, and every profile in
`apps/anuvritti/eas.json` bakes
`EXPO_PUBLIC_ANUVRITTI_URL = "https://family.anuvritti.internal"`, a hostname that does not
resolve — so a build made today installs and points at nothing.

Zero of the board's 173 tasks was a website. Three touched distribution at all. That gap is
this wave.

## The decision this wave is built on

**A paid Apple Developer membership buys TestFlight — someone else's iPhone. It does not buy
testing on your own.** An earlier draft of DEVICE.md said the checklist was unrunnable on a
free account, and that was wrong. Free personal-team provisioning signs and installs on a
device you own; the profile expires every seven days and you re-run `expo run:ios`. Android
needs no account at all. So the whole of this wave runs on free tooling, and the order is
the founder's:

**the website first, then Android, then the founder's own iPhone — with the server on the
laptop for now.**

The laptop is not a compromise here. The premise of this product is one small box a family
owns (PRD 44), and a laptop behind a tunnel *is* that box. What changes later is the box,
not the architecture.

## The domain

`memtara.com`, not `aihoot.com`. This is a memory archive; the other name is on the AI shelf
and this product is deliberately not on it. Apex for the site, `family.memtara.com` for the
family's server.

## Order

**Round 1 — two chats, in parallel, start now.** TASK-1502 (the site) and TASK-1501 (the
laptop becomes a real host). They touch `site/` and `deploy/` and do not meet.

**Round 2 — one chat.** TASK-1503, the embedded experience, after TASK-1502 reports.

**Round 3 — two chats, in the founder's order.** TASK-1504 (Android), then TASK-1505 (iOS).
Both carry `runs_on`; both need a phone in a hand and TASK-1003 landed.

## How each chat gets reviewed

The same five questions as wave 2, plus one this wave adds, and it is the first one asked:

**Does the page or the build claim anything that is not true today?** A website is a
document, and CLAUDE.md section 4 says no document describes something that did not happen.
A screenshot of a screen that does not exist, a feature list ahead of the code, a download
link to a file nobody built — each one is the same failure the reachability test was written
for, moved onto a page where more people can see it. The site's own constitution test
(TASK-1502) is what makes this reviewable rather than argued about.

---

## Round 1

### TASK-1502 — the site exists, and it is honest

```
Read docs/prompts/WORKING.md and docs/prompts/CONTEXT.md and hold to them. Your task is
TASK-1502. Start with `python3 scripts/tracker.py brief TASK-1502`.

You are building the first thing about Anuvritti that a person who is not the founder can
see. It goes at memtara.com. Nobody has designed it, and the design is most of the task.

## What you are not doing

You are not inventing a visual language. `packages/world` already is one, it is built
(`make world` emits dist/world.css, dist/scenes.css, dist/tokens.json), and
packages/world/specimen/index.html already renders it in a browser. Read
packages/world/scripts/check-specimen.ts before you write a line: it enforces that every
colour token appears on the specimen, that the page names no colour of its own, and that
every custom property it references exists in the emitted CSS. That test exists because
drift starts with one hard-coded hex.

The site is held to the same rule. If the site invents a colour, the app and the site have
already begun to disagree about what this product looks like, and the disagreement will be
public.

## What the site is

A single page, static, no build step you cannot explain, no framework. It answers one
question for a parent who has never heard of this: *what is this, and why would I trust it
with my child?* Read docs/PRD.md section 8 (the sacred principles) and section 47 (the
constitution). The answer is not a feature list. This product's whole argument is what it
refuses to do, and the refusals are already written down as a checklist in docs/DEVICE.md
under "What must never appear" — no badge, no streak, no count of days, no "2 more". Ten
lines that are more persuasive than any feature grid, because every one of them is enforced
by a test in this repository and you can say so.

Design it properly. This is the founder's product in public for the first time; make it
something they would want to send to someone. But do not stage it: no mocked screenshots,
no invented testimonial, no roadmap presented as present tense.

## The honesty test, which is the reason this task is a task and not an afternoon

Write `scripts/check-site.ts` (or .py — match whatever `make check` can run cleanly) and
wire it into the Makefile's `_gates`. It is a constitution test for the website, in the
same spirit as check-specimen.ts, and it must at minimum assert:

1. Every colour the page uses comes from packages/world's emitted tokens. The page names no
   colour of its own.
2. Every capability the page claims is one the app actually ships. Decide the mechanism —
   the strongest version is a small manifest the page's claims are drawn from, where each
   claim names the test or the module that makes it true, and the check fails if that name
   does not resolve. A claim that cannot cite anything cannot go on the page.
3. Every link resolves to something in this repository or to a URL the check can state a
   reason for. A download link to a file nobody has built yet fails.

Rule 2 is the one that matters and the one that is easy to fake. Do not write a test that
greps for a banned word list; write one that makes an unsupported claim structurally
impossible to add. If your first design can be defeated by rewording a sentence, it is the
wrong design.

Leave a slot on the page for the Android APK (TASK-1504 will fill it) and design the empty
state honestly — the check should fail if that slot ever claims a download that is not
there.

## Done means

`site/` exists and opens in a browser from disk. `make check` runs your site check as a
gate and it passes. No colour outside the world's tokens. A report at
var/reviews/TASK-1502.md that includes the honesty test's design, the attack you tried
against it, and what a false claim would have to defeat to reach the page.
```

### TASK-1501 — the laptop is the server, and it has a real name

```
Read docs/prompts/WORKING.md and docs/prompts/CONTEXT.md and hold to them. Your task is
TASK-1501. Start with `python3 scripts/tracker.py brief TASK-1501`.

Today `apps/anuvritti/eas.json` bakes
`EXPO_PUBLIC_ANUVRITTI_URL = "https://family.anuvritti.internal"` into all three build
profiles. That host does not exist. Any build anyone makes right now installs and points at
nothing, and that — not Apple, not a membership — is the actual reason there is no app on a
phone.

You are fixing that with the founder's laptop and a free tunnel.

## What is already here

- `Dockerfile`, and `.github/workflows/deploy.yml` which builds and pushes to ghcr.io.
- `deploy/Caddyfile` — reverse_proxy to 127.0.0.1:8000, HSTS, nosniff, DENY, no-referrer,
  domain from `{$ANUVRITTI_DOMAIN:localhost}`. Its own comment already anticipates
  "Let's Encrypt / ZeroSSL or internal Tailscale certs".
- `make run` — uvicorn on 0.0.0.0:8000.
- TASK-906 shipped `/ready` and says `curl https://host/ready` shows encryption at rest on.

So the server exists. What is missing is a name, and a route to it from a phone that is not
on the wifi.

## What to build

The laptop, behind a tunnel, reachable at `family.memtara.com` over real TLS. Cloudflare
Tunnel is the recommendation — no port forwarding, no static IP, a real certificate, free,
and it does not require the founder to open anything on their home router. Tailscale Funnel
is the alternative and TASK-906's own description already names it; pick one, and say in the
report why you rejected the other.

Real TLS is not a nicety: iOS App Transport Security will refuse a plain-HTTP or
self-signed origin, so a self-signed cert would block TASK-1505 before it started.

Make it a command, not a wiki page. Something like `make serve` that brings up the app,
Caddy and the tunnel together, and `make serve-status` that says what is up. The founder is
a parent-of-one who will run this at odd hours; the RUNBOOK's audience is them.

Then replace the fictional URL in all three eas.json profiles with the real one, and while
you are in that file: `production.distribution` is `"internal"` and `submit.production` is
`{}`. Neither is right for a store build. You are not doing a store build, so do not
pretend to — but put in the report exactly what those two lines would have to become and
what they would then require, so nobody rediscovers it later.

## What is the founder's and not yours

Pointing memtara.com's DNS at the tunnel happens in a GoDaddy account you do not have.
Write the exact steps down in docs/RUNBOOK.md, run everything up to that boundary, and say
plainly in the report which half you observed and which half you handed over. This task
carries `runs_on: "the founder's own domain, with DNS pointed at a tunnel"` for that reason.
Record `blocked` rather than guessing if you reach the boundary and cannot cross it — but
get everything on your side of it finished and proven first, including against a
`*.trycloudflare.com` ephemeral hostname, which needs no account and proves the whole path.

## Done means

`curl https://<host>/ready` answered from a network that is not this laptop's, with the
output and the date in docs/RUNBOOK.md. The real URL in eas.json. `make check` green. A
report that separates what you ran from what you wrote instructions for.
```

---

## Round 2

### TASK-1503 — the experience is embedded, and it runs the real code

```
Read docs/prompts/WORKING.md and docs/prompts/CONTEXT.md and hold to them. Your task is
TASK-1503. Start with `python3 scripts/tracker.py brief TASK-1503`, then read
var/reviews/TASK-1502.md — the site's structure and its honesty test are that chat's
decisions, and you are building inside them. Do not redesign them.

A page can describe hold-to-talk. It is much better to hand someone the button.

## The thing that makes this cheap, and you should verify it before you trust it

In `apps/anuvritti/src`, exactly seven files import `react-native`: three components,
`provider.tsx`, `useWorld.ts`, and the two storage adapters. `src/model/*`, `src/voice/*`,
`src/sync/*` and `src/upload/*` do not. They are pure TypeScript. Check this yourself with
one grep before you build on it.

Which means the page does not need a browser reimplementation of this product. It can run
this product's actual modules — the arming threshold, the waveform, `keep.ts`'s decision
about what is worth keeping — and if the app's behaviour changes, the demo changes with it
or the build breaks. A demo that drifts from the product is worse than no demo.

## What to embed

Three things, and the middle one is the point:

1. **The flip.** CSS 3D, no library. It is the product's signature gesture and it is
   entirely a visual.
2. **Hold to talk.** MediaRecorder for the microphone, and then the app's own
   `src/voice/waveform.ts` and its arming threshold driving what the person sees — the same
   code path, not a lookalike. Read `src/components/HoldToTalk.tsx` first to learn how this
   product already speaks; the browser version should feel like the same hand made it.
3. **A film.** filmkit is Python and renders server-side, so a finished film is just a file.
   Put a real rendered one on the page.

Nothing recorded in the browser leaves the browser. Say so on the page, in one line, next to
the button — and make it true: no upload, no beacon, no analytics, nothing in a network tab.
A page about a product whose whole claim is privacy cannot phone home about a demo. If your
implementation makes that hard to prove, change the implementation.

## Done means

The three pieces work in a browser with the page opened from disk. The voice demo imports
from `apps/anuvritti/src/voice`, and a test proves it is the real module rather than a copy.
TASK-1502's site check still passes and you did not weaken it. `make check` green. A report
that says what a visitor can do, what happens to what they record, and how someone reading
the page could verify that claim themselves.
```

---

## Round 3 — the phones

Both of these need hardware and both carry `runs_on`. Neither may become a dependency edge
(`scripts/tracker.py validate` enforces this). Do not simulate a device result. A
measurement nobody took, written down as though somebody took it, is the failure this
repository has already made once.

### TASK-1504 — Android, free, on real hardware, and downloadable

```
Read docs/prompts/WORKING.md and docs/prompts/CONTEXT.md and hold to them. Your task is
TASK-1504. Start with `python3 scripts/tracker.py brief TASK-1504`, then read
var/reviews/TASK-1003.md and var/reviews/TASK-1501.md.

Android costs nothing and needs no account. That is the whole reason it goes before iOS.

Get the app onto a real Android phone against the real server: `npx expo run:android` for
the development install, and then a *release* APK, because a release build is what someone
who is not you can actually install and it is what exercises the production JS bundle. Sign
it with a keystore that is generated locally and committed nowhere — check it against
.gitignore before you build, not after, and put the recovery story in docs/RUNBOOK.md. A
lost upload key is unrecoverable, and that is worth one paragraph now rather than a
discovery later.

Then hand the APK to the site: TASK-1502 left a slot for it, with a check that fails if the
slot claims a download that is not there. Publish the sha256 beside it. Anyone installing an
APK from the internet is trusting a stranger; give them the one thing that makes that
checkable.

Play Store internal testing is not part of this task. It costs $25, it adds a review queue
where there is currently none, and a download from your own site reaches a tester faster.
Say in the report what the $25 would buy and when it would be worth it — the
twelve-testers-for-fourteen-days rule that gates a new personal account's *production*
release is the real argument for starting that clock early, and it is a founder decision,
not yours.

Then run the Android column of docs/DEVICE.md. Every item, on the phone, with the date. The
ten seconds with a stopwatch, not `Date.now()`. What you could not run, say so and say why.

## Done means

A release APK installed on a real Android phone, talking to the real server over real TLS.
The APK offered from the site with its hash, and TASK-1502's check passing with the slot
filled. docs/DEVICE.md's Android column executed and dated. `make check` green. A report
that names half of TASK-907 as closed, and closed without an account.
```

### TASK-1505 — the founder's own iPhone, free, and the share sheet without an entitlement

```
Read docs/prompts/WORKING.md and docs/prompts/CONTEXT.md and hold to them. Your task is
TASK-1505. Start with `python3 scripts/tracker.py brief TASK-1505`, then read
var/reviews/TASK-1003.md — that chat made the App Group conditional and put the camera on
this phone. You are finishing what it started, and you are not redoing it.

Two things, and they are both about removing a dependency on $99.

**One: make the free path repeatable instead of rediscovered.** Free personal-team
provisioning installs on a device the founder owns. The profile expires after seven days and
the app then refuses to launch until `npx expo run:ios` re-signs it. That is friction, and
undocumented friction is how a product ends up uninstalled. Write the procedure into
docs/DEVICE.md as a procedure — what expires, what the failure looks like on the phone when
it does, and the one command that fixes it. Three sideloaded apps is the cap; note it.

**Two: item 1 of DEVICE.md without a paid entitlement.** The share sheet does not have to
come from a share extension. Declaring document types on the app itself —
`CFBundleDocumentTypes`, `LSSupportsOpeningDocumentsInPlace`, and the imported type
declarations for the media this product accepts — puts Anuvritti in the iOS share sheet as a
destination, and iOS copies the file into the app's own Inbox and launches it. No App Group,
no extension, no membership. It is fewer moving parts than the extension and it is arguably
the better v1 rather than a downgrade; argue it either way in the report, but argue it from
what you read in the installed Expo packages and from Apple's document-types behaviour, not
from memory.

The received file lands in the app's Inbox and has to reach `src/upload/spool.ts` — the
Outbox — by the same path a shared photograph already takes through `provider.tsx`. One
custody story. TASK-1003 decided which one; follow its decision, do not open it again.

Keep `app.json`'s `expo-sharing` extension configuration. This is conditional, like the App
Group: with a paid membership, the extension; without one, document types. One product, one
flag. Do not delete the paid path and do not require it.

Then run the iOS column of docs/DEVICE.md — every item TASK-1003 did not already close, on
the phone, with the date, and item 1 among them, because it is now runnable and it was
previously written down as though it were not.

## Done means

The app on the founder's iPhone from a free account, talking to the real server. A photo
shared from Photos into Anuvritti through the share sheet, arriving in the Outbox, on a free
account. docs/DEVICE.md's iOS column closed and dated, with the seven-day procedure written
down. `make check` green. A report that says which of the five items are now proven on
hardware, which remain, and what the $99 would still buy — which by then should be exactly
one thing: someone else's phone.
```

---

## When this wave is done

There is a website a stranger can read, an APK a stranger can install, and an app on the
founder's own phone talking to the founder's own laptop over a real domain — none of it
requiring a developer account, a store review, or a paid membership.

TASK-907 closes with TASK-1504 and TASK-1505 together, and it closes honestly: not "we
bought the membership", but "the free path was enough, and here is what it cost instead".

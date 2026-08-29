# On a real phone

**Status: NOT RUN, and DEFERRED by decision on 2026-08-29. Hardware execution
checklist.**

Deferred for the same reason as [VALIDATION.md](VALIDATION.md) and on the same day: this
needs a phone in a hand, no runner has one, and it was sitting under TASK-1004 as though
writing a notification scheduler required the app to already be installed. That edge is
cut. The checklist is not — TASK-907 carries `runs_on: "a real iPhone and a real Android,
in a hand"`, which keeps it a release gate and stops it being a dependency again.

**An iPhone exists (2026-08-29).** The founder has a physical iPhone available and is
arranging an Android. TASK-907 stays open, because it wants both — but the iOS column below
is executable now, and it should be executed rather than left as a document. Each item takes
a date and an observation when it is closed, and an item nobody has performed keeps saying
so.

**Free provisioning is enough for four and a half of the five (2026-08-29).** A free Apple
ID signs and installs on a device you own; the profile expires every seven days and you
re-run `npx expo run:ios`. Android needs no account at all — `npx expo run:android`, or a
release APK installed by hand. What a free account cannot sign is the App Group, and the
only thing that costs is the *share extension* half of item 1 and the cross-extension half
of item 3. Everything else on this list — the camera, the ten seconds, the flip, the
microphone, the queue surviving a force-quit, the keychain surviving a cold start — is
free to prove today. A paid Apple Developer Program membership buys TestFlight, which is
how the app reaches *someone else's* iPhone. It is not what makes this checklist runnable.

**Item 1 without the entitlement.** The share sheet does not have to come from an
extension. Declaring document types on the app itself (`CFBundleDocumentTypes`,
`LSSupportsOpeningDocumentsInPlace`) puts Anuvritti in the share sheet as a destination,
hands the file to the app's own Inbox, and needs no App Group and no membership. It is
fewer moving parts than the extension, and it is the honest way to run item 1 on a free
account rather than marking it unrunnable.

**The entitlement, before anything else.** `apps/anuvritti/src/vault/device-vault.ts` asks
the keychain for `accessGroup: "group.com.anuvritti.app"`, and `app.json` declares the same
App Group for the `expo-sharing` extension. **iOS App Groups are not available under free
personal provisioning; they need a paid Apple Developer Program membership.** On a free
account items 1 (the share sheet) and 3 (the keychain across the App Group) cannot be
performed at all, while 2, 4 and 5 can — the app installs, the camera runs, the flip either
reads as an object or it does not. This is a hundred dollars and a form rather than an
engineering problem, and it gates the widget (TASK-1005) as well. Establish which account
this is before scheduling any of it.

`tests/e2e/test_the_app_against_the_server.py` runs the whole golden path through the real
generated client against the real server over a real socket. It covers pairing, capture,
the offline queue, idempotent replay, the Return Engine, and export.

Since Phase 6 it also runs the voice path: a recording uploaded, kept, indexed by the
handset's own reading, brought back eight months later, played back byte for byte, and
corrected by hand.

It cannot cover five things, because all five require hardware:

1. **The share sheet.** Whether Anuvritti appears in it, and what arrives when it is tapped.
2. **The flip.** Whether a Spark reads as an object you turn over.
3. **The keychain.** Whether the token survives a cold start, and whether the share
   extension can read the one the app wrote.
4. **Ten seconds.** Whether capture actually takes fewer than ten of them, measured.
5. **The microphone.** Whether holding a button and speaking feels like a microphone
   rather than like a form — and whether the waveform is telling the truth.

This is that checklist. It is short on purpose: everything checkable without a device is
already a test, and a manual step that could have been automated is a step that stops being
performed by the third release.

## Before you start

```bash
make check                      # everything below assumes this is green
npm --prefix apps/anuvritti install
npx expo prebuild --clean       # writes ios/ and android/ from app.json
make run                        # the family's server, on this machine
```

Every dependency is pinned to Expo SDK 57's own `bundledNativeModules.json`, which is what
`expo install` would have chosen. Four of them used to be pinned to versions that do not
exist — `expo-router@~7.0.0` among them — so the install above failed outright and this
checklist had never been started by anybody.

The app reads `EXPO_PUBLIC_ANUVRITTI_URL`. On a simulator `http://localhost:8000` works; on a
physical device use the machine's LAN address, and note that iOS will refuse plain HTTP to
anything but localhost unless the dev build allows it.

Both platforms need a **dev client**, not Expo Go: the share target is a native target that
Expo Go cannot load.

```bash
npx expo run:ios
npx expo run:android
```

## What stopped being on this list

Three items were here because nobody had written the test, not because they needed hardware.
They are now `apps/anuvritti/test/threshold.test.ts`:

- **First launch reaches pairing at all.** It did not. `app/pair.tsx` existed and no route,
  link or redirect pointed at it, so a phone with no token opened Today, got two 401s and
  said "Nothing today. That's normal." to a stranger. The test now walks `app/` and fails on
  any route nothing points at — which is the check that generalises, since every screen
  added after this one gets it for free.
- **A revoked device signs out on its next call, and a 403 does not sign it out.** Both are
  pure functions over a `Failure` now.
- **Being signed out does not empty the capture queue.** Asserted against `provider.tsx`
  directly, because it is the worst thing this product could do and it would be invisible.

And one that was never on the list and should have been: **a named typeface is a loaded
one**. `world.font.mono` named a face `useFonts` was never given, so the eight characters of
a pairing code — the one place mono is used at size — rendered in the proportional system
fallback, where `O`/`0` and `I`/`1` are exactly the confusions the Crockford alphabet exists
to prevent.

## The five

### 1. Capture, in the share sheet

- [ ] **iOS.** Safari → a page → Share → **Anuvritti** appears in the app row.
- [ ] **Android.** Chrome → a page → Share → **Anuvritti** appears.
- [ ] Tapping it saves and shows **Saved.** — with no spinner in between. If there is a
      spinner, capture is waiting for the network and `provider.tsx` has a bug: `enqueue`
      must return before anything is sent.
- [ ] Share a photo from the camera roll. It is treated as a **photo**.
- [ ] Share a screenshot. It is treated as a **screenshot**. (This is
      `looksLikeAScreenshot`; it reads the filename, which is the only signal either
      platform gives.)
- [ ] Share an Instagram reel. The creator handle survives onto the Spark.
- [ ] Share several images at once. Every one is saved; one bad one does not lose the rest.

### 2. Capture, with the network off

The whole reason the queue exists, and the one test a simulator cannot honestly run.

- [ ] Aeroplane mode. Share three different things.
- [ ] Each says **Saved.** immediately.
- [ ] **Force-quit the app.** Reopen it. The three are still pending — this is what makes
      "Saved." true rather than optimistic.
- [ ] Turn the network on. They arrive, once each.
- [ ] Check the server: exactly three Sparks, not six. (`GET /v1/sparks` from another
      paired device, or `sqlite3 var/anuvritti.db 'select count(*) from spark'`.)

### 3. Pairing, and the keychain

The route graph is a test now (above). What is left is the keychain itself, which is the
part no assertion on this machine can reach.

- [ ] Force-quit and reopen: still paired, no code asked for.
- [ ] Second device → **Join with a code**, using the code from the first.
- [ ] Both devices see the same archive.
- [ ] Type the code with the wrong case, with the dashes left out, and with `O` for zero.
      All three work.
- [ ] Type a wrong code five times. The sixth attempt fails **even with the right code**,
      until ten minutes pass.
- [ ] Revoke the second device from the first. The second is signed out on its next call
      **and its pending captures are still pending** — the sign-out clears a credential, not
      an archive.
- [ ] Share something from the second device *after* revoking. It must not save.

### 4. The object, and the ten seconds

- [ ] Tap a Spark. It turns over. It does not navigate, and there is no back button.
- [ ] The back shows the recorded *why* in the serif face, large.
- [ ] A Spark with no why says "You didn't say why. That's fine." — not an empty state and
      not a prompt.
- [ ] Turn on **Reduce Motion**. The flip still works and is not a spectacle.
- [ ] VoiceOver / TalkBack: the Spark announces itself, and announces the turn.
- [ ] Tap the intent chip. The word changes **immediately**, before the network answers.
- [ ] Chip on a low-confidence guess reads `to watch?` with the question mark. On a
      corrected one, no question mark and no dashed border.
- [ ] Dark mode, on both platforms. Nothing is invisible — particularly the elevation on the
      Spark, which was light-theme-only until the specimen caught it.

**Timed, three times, with a stopwatch, from a cold app:**

- [ ] Open Instagram → find a post → share → Anuvritti → "Saved." — **under ten seconds**
      (PRD §11). Write the three numbers down. If it is over, the number to look at first is
      the app's cold-start time, not the network.

### 5. Holding the button, and the waveform

The two halves of this that no assertion can reach are *whether it feels like a microphone*
and *whether the waveform is honest*. Everything else about hold-to-talk is a pure function
in `src/voice/` and is already tested.

- [ ] Grant the microphone. The permission sheet quotes `app.json`: it says the recordings
      stay on the family's own server, and that has to still be true when you read it.
- [ ] **Tap** the button — a quick tap, not a hold. **Nothing is recorded.** Not a short
      recording, not a discarded one: the vault is unchanged. (This is the arming
      threshold. It filters the gesture; it must never filter a recording.)
- [ ] Hold it and say one word. Let go. **It is kept**, and it appears on the shelf.
- [ ] Hold it, say nothing at all for three seconds, let go. **That is kept too.** Silence
      is a recording (PRD §24), and there is nowhere in the product that says otherwise.
- [ ] While recording, **stop talking for two seconds.** The waveform gets small; it does
      **not** go flat. A flat line reads as "it stopped recording", and a parent who
      believes that will start over or stop to check.
- [ ] Speak normally. The bars use most of the height, not a twentieth of it. If they are
      tiny, the dBFS mapping is wrong — see `FLOOR_DB` in `src/voice/waveform.ts`.
- [ ] The timer counts **up** and there is nothing counting down.
- [ ] **Call the phone from another one while recording.** The recording so far is *kept*,
      not lost. Check the shelf.
- [ ] Force-quit mid-recording. This is the one case that loses audio and the checklist
      says so honestly: the file is whatever the encoder had flushed.
- [ ] Record with no network. The **upload** fails, and the app says the recording is
      still on the phone rather than saying "saved". That is the one place on this path
      where "Saved." would be a lie.
- [ ] Turn the network on. It goes up, once — not twice. (`keepVoiceNote` is replayable;
      the media upload is not, and does not need to be.)
- [ ] Play a recording back. The words underneath say **"It sounded like"** or **"Maybe"**,
      never nothing — a machine's reading is never presented as a quotation.
- [ ] Correct a transcript. The hedge disappears, the audio still plays, and the length is
      unchanged.
- [ ] VoiceOver / TalkBack: the button announces "Recording." on start and "Saved." on
      release. The waveform is hidden from the accessibility tree — it says nothing useful
      and would otherwise be sixty-four unlabelled views.
- [ ] Record something on a **second paired device**. It appears in the vault on the first.

## What must never appear

If any of these is on the screen, a constitution test has been defeated and the fix is the
test, not just the pixel:

- [ ] A badge, a dot, or an unread count — anywhere, including the app icon.
- [ ] A number of days. Anywhere. The wire does not carry one, so it would have to have been
      computed on the phone.
- [ ] A streak, a total, or a completion rate.
- [ ] Red, on anything that is not a deletion.
- [ ] More than one suggestion under Worth Bringing Back.
- [ ] Any hint that there were others — "2 more", "next", a pager.
- [ ] A count of recordings, anywhere on the vault — including "3 this month".
- [ ] A "re-record", "retake", "discard" or "too short" affordance on the recorder.
- [ ] A transcript rendered without a player above it.
- [ ] A machine's transcript shown as a quotation, with no hedge and no attribution.

## When something fails

Write it down as a test first. Every one of the five above is a manual step because it needs
hardware, not because it is unimportant — and a manual step nobody can automate is at least a
manual step someone can read.

## Execution Requirements

This checklist requires physical hardware execution on a real device:
- Internal distribution build profile provisioned via `apps/anuvritti/eas.json`.
- Dedicated family server deployed with valid TLS (`deploy/Caddyfile`, `EXPO_PUBLIC_ANUVRITTI_URL`).
- When physically executed by a founder/tester on an actual iPhone and Android device, record the date and stopwatch measurements above and sign with a date in the past.



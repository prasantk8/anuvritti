# On a real phone

`tests/e2e/test_the_app_against_the_server.py` runs the whole golden path through the real
generated client against the real server over a real socket. It covers pairing, capture,
the offline queue, idempotent replay, the Return Engine, and export.

It cannot cover four things, because all four require hardware:

1. **The share sheet.** Whether Anuvritti appears in it, and what arrives when it is tapped.
2. **The flip.** Whether a Spark reads as an object you turn over.
3. **The keychain.** Whether the token survives a cold start, and whether the share
   extension can read the one the app wrote.
4. **Ten seconds.** Whether capture actually takes fewer than ten of them, measured.

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

The app reads `EXPO_PUBLIC_ANUVRITTI_URL`. On a simulator `http://localhost:8000` works; on a
physical device use the machine's LAN address, and note that iOS will refuse plain HTTP to
anything but localhost unless the dev build allows it.

Both platforms need a **dev client**, not Expo Go: the share target is a native target that
Expo Go cannot load.

```bash
npx expo run:ios
npx expo run:android
```

## The four

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

- [ ] First launch → **Start our family** → the app is usable immediately.
- [ ] Force-quit and reopen: still paired, no code asked for.
- [ ] Second device → **Join with a code**, using the code from the first.
- [ ] Both devices see the same archive.
- [ ] Type the code with the wrong case, with the dashes left out, and with `O` for zero.
      All three work.
- [ ] Type a wrong code five times. The sixth attempt fails **even with the right code**,
      until ten minutes pass.
- [ ] Revoke the second device from the first. The second is signed out on its next call.
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

## When something fails

Write it down as a test first. Every one of the four above is a manual step because it needs
hardware, not because it is unimportant — and a manual step nobody can automate is at least a
manual step someone can read.

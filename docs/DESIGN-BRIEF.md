# A Personal Space

## The app, made of the family's own material — a brief for the design team

> "As a dad I should be able to use my child's photos, videos and audio to customise
> everything. My own voice and my child's voice, to make a personal space. Something
> touching and beautiful — and the app should adjust to that."
> — the founder, 2026-08-27

**Status.** A brief, not a spec. Every line of copy in here is a placeholder: TASK-714
owns the words and TASK-715 owns the saffron. Written against the app and the tokens as
they stand at `e3a821c`.

---

## 0. Read this first

Anuvritti is a private archive a parent keeps for a child — photographs, recordings of
the parent's own voice, small things the child said — compiled once a year into a film
that contains only what really happened. The visual language already exists as code in
`packages/world`, and the **same tokens draw the phone app and the film**. So the
question this brief answers is not *what should the app look like* — that is decided —
but:

> **What does the app look like once it is full of them?**

Read before designing: PRD §8 (the sacred principles), §16, §17, §24, §44, §47, §56;
`packages/world/src/color.ts` and `scale.ts`, where every token states what it means and
why it exists; and `tests/constitution/README.md`, because in this product the ethics
are tests, and a design that crosses one does not build.

---

## 1. The one idea

### Customise nothing. Author everything.

Every other app answers "make it mine" with settings: a theme, an avatar, a wallpaper, a
sticker pack. Those are **paint**. The founder's request is different in kind. It asks
for the app to be made of **material** the family produced — a photograph of the child,
the parent's voice saying the child's name, the child saying a word they invented.

So the position is:

1. **The app has no paint to choose.** Colour, type and motion are the constitution and
   stay fixed. There is no theme picker, and there never will be.
2. **Everything personal is a page of the film.** Every photograph the parent places,
   every name they record, every picture they choose for the year is compiled into that
   year's film by the same tokens. *Personalising the app is authoring the film.* A
   settings screen is a chore; a title page is a gift.
3. **The app recedes as the family fills it.** On day one the interface is cloth and
   indigo — the app's own hand. By year three, most of what is on screen is a
   photograph, a voice, a sentence in the display face: theirs. The app "adjusts" not by
   rearranging itself but by getting out of the way.

That is the wow, and nobody whose app and film are not built from the same material can
copy it.

---

## 2. What is already true

Designers start from here, not from a blank canvas.

- **The palette is one image: indigo dye on undyed cloth.** Ground `#EFEDE4` / `#12151C`.
  Indigo is the app's own hand — every mark the application made rather than the family.
  Saffron is rationed to a single meaning: *a person spoke.*
- **Every colour token declares a role** — ground, surface, ink, structure, voice,
  destructive — and `tests/design` fails the build when a colour is used outside it.
  Exactly one red, `unmade`, and it means erased.
- **The display face (Newsreader) means** *"a child's name, a year, a single sentence a
  parent said."* The body face (IBM Plex Sans) is everything the app itself says. That
  split is the provenance model rendered as typography: you can tell who is speaking by
  the letterforms.
- **The Spark is an object, not a card.** Front: what was saved. Back: why, in the
  parent's own sentence, in the display face — and, with TASK-808, in the parent's
  recorded voice. Turning it over is the core gesture and the one motion allowed past
  the ceiling.
- **The vault has no count.** The home says *"Nothing today. That's normal."* and that
  is a finished, correct state.
- **Elapsed time is words.** The client is never handed a number of days.
- **The film is drawn from `world.css` — the same file the app consumes.** A scene with
  no picture has no `<img>` at all: no placeholder, no stock image, no illustration
  standing in for a photograph nobody took.
- **Motion has a ceiling** of 420ms. The flip alone is 620.

---

## 3. Three materials, one rule each

### Photographs — and video

The child, the family, the thing that happened. Shown **whole** (`contain`, never
`cover` — the film's rule already), never cropped by an algorithm, never filtered, never
captioned with a date as a number.

> **A photograph is shown whole, or not at all.**

Video, honestly: today the compiler and the renderer hold stills and audio. In the app a
video is a real frame from it with a play glyph; it plays on tap, with sound; never on
scroll, never looped. In the film a video clip becomes a scene of its own — engineering
not yet done, see §9.

### The parent's voice

The recording is the artifact; the transcript is only an index (Phase 6). Saffron is its
sign. It plays only when asked.

> **A voice is never a sound effect.**

No chime cut from a laugh, no ambient loop of a lullaby, no "Papa says hi" on launch. The
moment a recording plays without being asked for is the moment it stops being precious.

### The child's voice

Little Things in the child's voice; the invented words (TASK-812); the interview answers
at four, five, six (TASK-810); one day, *"Papa, let's build this"* (PRD §25).

> **The child's voice is set apart — never counted, never scored.**

The same saffron, because there is one hue for "a person spoke" — but its own
typographic voice (§4.5), so a reader can tell from across the room who is speaking.

---

## 4. The surfaces, made of their material

Each proposal says what the parent sees, which material it uses, and what it must never
do.

### 4.1 "This is us" — the first two minutes

After pairing (TASK-713), before the empty home. Three things, each optional, each
skippable forever:

- the child's name — display face, `size.name` (42);
- one photograph, from the camera roll — shown whole, `radius.object`, `elevation.held`;
- **say the name out loud** — hold to talk, two seconds.

Why the third: from that moment there exists a real recording of the child's name in the
parent's voice, which is exactly what the film's OPENING scene has been waiting for
(`test_real_voice`: the voice in a film is the family's, or silence). Setup *is*
authoring.

Never: a progress bar, "complete your profile", a placeholder avatar, a grey silhouette
where the photograph will go. If the parent skips the photograph, the frontispiece is
the name on cloth — a finished state, not a nag.

### 4.2 The Frontispiece — the top of Today

An album's first page carries a name and one photograph. Today's top becomes exactly
that: the photograph chosen in 4.1, the child's name in the display face, and beneath
them the one line the Return has for today — or *"Nothing today. That's normal."*

- The photograph is theirs; the name is theirs; only the one line is the app's, in the
  body face, `ink-quiet`.
- On the child's birthday the app asks once — *"A new picture for this year?"* —
  skippable. Each year's frontispiece becomes that year's OPENING scene. Seven years in,
  the parent owns a shelf of title pages.
- Light: the photograph rests on `surface` with `elevation.held`. Dark: the same, and the
  frontispiece is the warmest thing on the screen.

Never: a carousel, a slideshow, "on this day", auto-rotation. The frontispiece changes
when the parent changes it. Motion: `arrive` (280ms), once, on the day it changes.

### 4.3 A lived Spark wears its photograph

Today a Spark's front is a title, a source and a chip. Two changes:

- A Spark shared as an image (TASK-713 makes those upload) shows that image, whole, on
  its front.
- A Spark that became a Moment — the thing actually happened — shows the **Moment's**
  photograph on its front, above the title. The object visibly turns from an intention
  into a memory. Turn it over: still the why, in the parent's voice.

Never: a "done" badge, a tick, a colour change meaning completed. The photograph *is*
the completion.

### 4.4 Saffron is earned — the interface warms

Saffron today appears on a waveform and on the reverse of a spoken Spark. Extend it,
within the rule:

- A Spark with a recorded why carries a **saffron hairline at its edge** (`thread` →
  `saffron`), so scrolling the vault you can see which ones you spoke about.
- A vault month holding the child's recordings carries the child's typographic mark
  (§4.5) — not a second colour.

As the parent records more, the interface literally warms, with no number anywhere. A
new family sees cloth and indigo; an old one sees saffron threaded through. That is what
"the app adjusts" means here, and `tests/design` will hold it: saffron only where a
recording exists.

Never: saffron on *"Saved."* (a known bug, TASK-715), on buttons, on anything the app did
rather than a person.

### 4.5 The child's words, in italic

Newsreader ships an italic axis and `world.ts` already names `displayItalic`. Proposal:

> **What the child said is set in display italic. What the parent said, in display
> roman.**

Same face, same saffron, one axis of difference. It works in the app, in the film, in
the offline glossary, at every size, in both themes, and costs no new colour. The
Dictionary of Us (TASK-812) is the first place it shows: the invented word at `size.year`
(34), italic; the child's recording beneath; the day it was first heard, in words —
*"the spring he was three."*

Never: a cartoon speech bubble, a "kid" font, a rounder child component. The child is
not a novelty and not an error state. The child is a second author.

### 4.6 Time is shown with their faces

*"How do we show something from two years ago?"* (PRD §56). Not a date, not a count.

> **Age, in words — and the photograph nearest to it.**

A Spark returning from two years ago says *"when she was three"* and shows, beside the
Spark, a photograph of her at three if the archive has one, and nothing if it does not.
The archive's own photographs are the clock.

Needs photographs that carry their original dates (TASK-908's import does) and a small
piece of engineering (§9).

Never: "2 years ago", "743 days", a timeline with a scrubber.

### 4.7 What the child sees: only Papa

TASK-818 is the first child-facing screen. Make it the purest case of this brief:

> **No app chrome at all.**

The parent's face — a photograph the parent chose of *themselves* — the child's name in
the display face, and the parent's recorded goodnight. It plays once. The screen dims to
ground and ends itself. For the child there is no Anuvritti; there is Papa.

One addition: a single hold-to-talk with no label, so the child can leave something for
Papa (PRD §25) — the first reciprocal act, in the child's voice, filed in italic.

Never: navigation, a library, a next button, autoplay, anything to tap twice.

### 4.8 The film's title page is the parent's

Closing the loop. OPENING: the year's frontispiece photograph, and the name in the
parent's recorded voice. CLOSING: the year, and — if it exists — the child saying their
own name from that year's interview. The parent never "makes" the film. The film is made
of what they placed in the app during the year. Customisation and compilation are one
act.

---

## 5. How the app adjusts — three ages of the interface

|                     | Day one                          | Month one                                   | Year three                                                   |
|---------------------|----------------------------------|---------------------------------------------|--------------------------------------------------------------|
| Ground              | cloth, unmarked                  | cloth                                       | cloth — it never changes                                     |
| Today               | name on cloth; "Nothing today"   | frontispiece photograph; one line           | this year's frontispiece; a Return with a face beside it     |
| Sparks              | title and source; indigo chip    | first image Sparks; first saffron edges     | mostly photographs; many edged saffron; some lived           |
| Vault               | recorder; "nothing yet"          | months of the parent's voice                | parent in roman, child in italic; warm throughout            |
| Sound               | none                             | plays when asked                            | plays when asked — never more                                |
| Film                | none                             | a short film with a title page              | two narrators, seven title pages                             |
| The app's own hand  | almost everything                | half                                        | a thread                                                     |

The rows that never change are the point. The ground stays cloth. Sound never plays
unasked. The app's hand thins, and is never replaced by louder decoration.

---

## 6. The lines that will not move

These are enforced by tests, not by review. A design that crosses one does not build.

| Line                                                            | Why                                                          | Held by                                                    |
|-----------------------------------------------------------------|--------------------------------------------------------------|------------------------------------------------------------|
| Exactly one red, and it means erased                            | lateness is not urgent; a child is never an error state      | `tests/design/test_no_scorekeeping.py`                     |
| Saffron only where a person spoke                               | seeing it must mean something happened                       | same                                                       |
| No counts, badges, dots, streaks, progress                      | PRD §8.5 — no guilt; a month of silence is a valid output    | same, and `tests/constitution/test_no_guilt.py`            |
| Elapsed time in words; past a fortnight, no day count           | "243 days ago" is what a database says to a father           | same                                                       |
| Motion ceiling 420ms; the flip 620                              | low stimulation; things arrive as if they had weight         | same                                                       |
| Nothing drawn that was not given                                | no placeholder, stock, illustration or generated child       | `check-scenes`, `test_film_provenance.py`                  |
| The voice in the film is the family's, or silence               | PRD §39 — no synthetic loved ones, ever                      | `test_real_voice.py`                                       |
| The recording is the artifact; the transcript hedged and quieter | AI is not historical truth (§8.7)                           | `test_preserve_imperfection.py`, `test_ai_honesty.py`      |
| The child's screen ends itself                                  | screen time is a cost (§8.4)                                 | TASK-818's first test                                      |
| Display face = the family's words only                          | the typography carries the provenance                        | `packages/world` token meanings                            |
| Touch target 44; space on the 4px scale; both themes            | every hand, every eye, every phone                           | `tests/design`, `packages/world/test`                      |

---

## 7. What we are not building

- A theme picker, accent colours, wallpapers, sticker packs, avatar frames.
- An AI-generated portrait, illustration, "memory art" or avatar of the child.
- A cloned or synthesised voice of anyone.
- Autoplaying media, looping video, a feed, an "on this day" carousel.
- Any sound the family did not record.
- Any number that could be read as a verdict.

---

## 8. Questions for the design team

1. **The frontispiece.** What is the relationship in size between the photograph and the
   name? An album says photograph large, name small and beneath. Test on the smallest
   phone we support, in both themes.
2. **The saffron edge.** A 1px hairline (the weight of `thread`) or a short saffron rule
   under the title? Which reads at a glance without becoming a status colour?
3. **Display italic for the child.** Does Newsreader's italic hold at `size.year` (34) on
   a phone, in dark? A specimen row is needed before anyone builds it.
4. **The photograph as clock (§4.6).** Beside the Spark, behind it, or above the reason
   line? It must not read as a second Spark.
5. **The child's screen ending.** Dim to ground over `considered` (420ms)? Slower is
   forbidden by the ceiling — is 420ms enough for a goodnight, or is this the second
   documented exception?
6. **Video.** The still frame with a glyph: where does the glyph sit so it never covers a
   face?
7. **Photographs on dark.** The film is always light; the app is not. Is a photograph's
   frame `surface` or `surface-lifted` on the dark ground?

---

## 9. What engineering would need

Proposed tasks, for the founder to accept into Phase 8. All depend on the phone being
wired (TASK-713); those that touch colour or copy depend on TASK-714 and TASK-715.

| Id       | Description                                                                                                                                                                                          | Depends on           |
|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| TASK-819 | *This is us*: after pairing, the child's name, one photograph and the name in the parent's voice; every field optional and skippable forever; the recording is filed as the OPENING narration       | TASK-713, TASK-808   |
| TASK-820 | The Frontispiece: one parent-chosen photograph per year at the top of Today, bound into that year's OPENING scene; changed only by the parent; asked once on the birthday                          | TASK-819             |
| TASK-821 | A lived Spark wears its photograph: image Sparks show their image whole; a Spark with a Moment shows the Moment's photograph on its front; no badge                                                 | TASK-713             |
| TASK-822 | Saffron is earned: a spoken Spark carries a saffron edge, and `tests/design` asserts saffron appears in the app only where a recording exists                                                       | TASK-715, TASK-808   |
| TASK-823 | Display italic for the child: load `Newsreader_400Regular_Italic` — declared at `apps/anuvritti/src/world.ts:52`, never loaded in `app/_layout.tsx:26` — and set every child-voiced string in it, in app and film, with a specimen row | TASK-812             |
| TASK-824 | Age as the clock: photographs keep their original date; a Return from an earlier age shows the nearest photograph of the child at that age, or nothing                                              | TASK-908, TASK-815   |
| TASK-825 | Video as material: a video Spark shows a real frame and plays on tap with sound; a video scene in the film through filmkit's compositor; never autoplay, never loop; a constitution test for both  | TASK-712, TASK-713   |
| TASK-826 | The child's screen made only of Papa: a photograph of the parent, the goodnight, one unlabeled hold-to-talk for the child, and a screen that ends itself                                           | TASK-818             |

---

Anuvritti's promise is *"You noticed something because you love them. We'll help you not
lose it."* This brief adds one line:

> **And the place we keep it will look like you.**

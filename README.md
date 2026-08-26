# filmkit

Compile a timeline of narrated scenes into a film.

filmkit knows how to make a video out of a voice and a sequence of pictures. It
does not know what the video is about, what the pictures show, where the words
came from, or what any of it is evidence of. Those are the caller's, and every
one of them arrives as an argument.

It was extracted from a working compiler rather than designed in the abstract,
which is why the sharp edges — the demuxer quirk that costs you a frame, the
encoder flag that quietly deletes a sentence, the browser settings that make
one machine's cache untrustworthy on another — are all still in here, with the
reasons attached.

## What it holds

| module | what it decides |
| --- | --- |
| `narration` | how long a voice actually is, and whose voice it was |
| `timing` | how long each scene holds, and whether the script fits |
| `timeline` | the single source of truth everything downstream reads |
| `captions` | cues, from the same words the voice said |
| `browser` | which stills need drawing, and which have been drawn before |
| `compositor` | stills plus voice, per scene, then joined |
| `cachestore` | three content-addressed stores, and how they stay bounded |
| `manifest` | the parts of an account a compile can give of itself |
| `workspace` | where things go — passed in, never found |

## The four rules it will not bend

**Measured, never estimated.** A voice's length comes from probing the file.
`visual_seconds(beat, audio_sec)` — the function that decides how long a scene
holds — takes no words-per-minute at all, so the estimate cannot reach the
picture even by accident. The estimate is kept, reported, and never rendered.

**Nothing is trimmed to fit.** `-shortest` appears nowhere. Audio is padded to
the scene length with real silence, so a mismatch becomes a number in the
timeline instead of a sentence that stops halfway. `Timeline.check_sync` names
it as truncation rather than absorbing it.

**A film says whose voice it is.** Every narration track carries `origin`:
`recorded` for a real person, `synthetic` for a machine. `adopt()` takes a
recording exactly as it is — nothing regenerated, re-encoded or trimmed — and
its content address is its own hash, because there is no request that would
produce it again.

**Everything expensive is a port.** A browser (`Painter`), a voice
(`Synthesiser`) and a shell (`Runner`) are all injected. Importing filmkit
requires nothing to be installed, and every decision in the package can be
tested without a browser or an encoder on the machine.

## Using it

```python
from filmkit import Beat, Line, Studio, Voice, Workspace, plan

space = Workspace.under(Path("/tmp/my-film"))
studio = Studio(workspace=space, synthesiser=my_synthesiser)

tracks, cache_stats = studio.build(
    [Line("01_open", "This is where it starts.")],
    Voice(name="some-voice"),
    project="my-film",
)
report = plan(
    [Beat(id="01_open", type="card")],
    tracks,
    target_wpm=150, target_sec=90, tolerance_sec=10,
)
print(report.render_text())
```

A voice that already exists — a person, not a synthesiser — comes in through
`adopt()` instead, and everything downstream is identical.

## Gates

```
make check      # ruff, mypy --strict, pytest with coverage at or above 90%
```

`tests/test_knows_no_product.py` is the one that matters most. It fails the
build if a product's name, an environment variable, or a browser import appears
anywhere in the source — because "no knowledge of either product" is a promise
a package keeps on the day it is written and loses six months later, one
convenient import at a time.

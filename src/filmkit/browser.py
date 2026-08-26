"""Drawing stills with a browser, several browsers wide.

Why stills and not a screen recording
-------------------------------------
A scene may change perhaps forty times in fifteen seconds. Recording it at
60 fps produces nine hundred frames, most of them byte-identical to the one
before. So this draws one image per *visible state* and hands the compositor a
list of (image, duration) pairs; the demuxer downstream turns that into a
genuine 60 fps stream. The output is the same, the work is twentyfold smaller,
and every state is content-addressed and therefore cacheable on its own.

Why a painter port
------------------
Chromium is an enormous dependency to require of anything that merely wants a
picture. `Painter` is the seam: filmkit decides *what* to draw, what it is
worth, and whether it has been drawn before; something else decides how pixels
happen. That also means every decision in this file can be tested without a
browser on the machine.
"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import cachestore
from .files import atomic_copy, ensure_dir
from .hashing import stable_key
from .reporting import MISS, Reporter, Silent
from .workspace import Workspace

RENDERER_VERSION = "frames-1"

CHROMIUM_ARGS = (
    # Colour management, subpixel hinting and LCD text all vary by machine, and
    # each of them makes the same markup hash to a different picture. Pinning
    # them is what lets one machine's cache be trusted by another's build.
    "--force-color-profile=srgb",
    "--disable-lcd-text",
    "--font-render-hinting=none",
)


@dataclass(slots=True)
class Shot:
    """One frame to draw: where it goes, what it shows, how long it holds."""

    destination: Path
    html: str
    key_payload: dict[str, Any]
    duration_sec: float
    label: str


def frame_key(
    html: str,
    key_payload: dict[str, Any],
    width: int,
    height: int,
    theme: dict[str, Any],
    *,
    renderer: str = RENDERER_VERSION,
) -> str:
    """The content address of a frame.

    Covers the markup, the geometry, the theme and the renderer - so a theme
    tweak invalidates every frame and an unrelated edit invalidates none.
    Nothing about *when* it was drawn is in here, which is what makes the cache
    safe to share between machines.
    """
    return stable_key(
        {
            **key_payload,
            "html": html,
            "w": width,
            "h": height,
            "theme": theme,
            "renderer": renderer,
        }
    )


class Painter(Protocol):
    """Turns complete documents into image files, in one browser."""

    def __call__(self, width: int, height: int, jobs: list[tuple[str, Path]]) -> None: ...


class ChromiumPainter:
    """One thread, one Playwright, one browser, one page, many frames.

    The unit of parallelism is a browser per thread rather than a page per
    thread, because Playwright's synchronous API binds its objects to the
    thread that made them; sharing one browser across threads is the single
    arrangement that does not work.
    """

    def __call__(self, width: int, height: int, jobs: list[tuple[str, Path]]) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=list(CHROMIUM_ARGS))
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                for document, destination in jobs:
                    page.set_content(document, wait_until="load")
                    ensure_dir(destination.parent)
                    page.screenshot(path=str(destination), type="png")
            finally:
                browser.close()


class FrameFarm:
    """Draws a compile's frames, reusing everything it can.

    Two things happen before any browser starts. Frames already in the store
    are copied straight out, and the remaining work is deduplicated by content
    address - a state that appears in two scenes is drawn once.
    """

    def __init__(
        self,
        width: int,
        height: int,
        theme: dict[str, Any],
        *,
        workspace: Workspace,
        workers: int = 1,
        painter: Painter | None = None,
        renderer: str = RENDERER_VERSION,
    ) -> None:
        self.width = width
        self.height = height
        self.theme = theme
        self.workers = max(1, workers)
        self.renderer = renderer
        self.painter: Painter = painter or ChromiumPainter()
        self.frame_cache = workspace.store("frames")

    def document(self, html: str) -> str:
        """The complete document for a shot's markup.

        A caller with a stylesheet, a font or a page shell wraps here. The
        default is that the markup already is the document, which keeps a
        one-line use of this class a one-line use.
        """
        return html

    def key_for(self, shot: Shot) -> str:
        return frame_key(
            shot.html,
            shot.key_payload,
            self.width,
            self.height,
            self.theme,
            renderer=self.renderer,
        )

    def render(self, shots: list[Shot], reporter: Reporter | None = None) -> dict[str, int]:
        told: Reporter = reporter or Silent()
        keys = [self.key_for(shot) for shot in shots]

        pending: dict[str, Shot] = {}
        hits = 0
        for shot, key in zip(shots, keys, strict=True):
            entry = self.frame_cache / f"{key}.png"
            if entry.is_file():
                cachestore.touch(entry)  # "last used", so pruning is informed
                hits += 1
            else:
                pending.setdefault(key, shot)

        if pending:
            self._draw(list(pending.items()), told)

        for shot, key in zip(shots, keys, strict=True):
            ensure_dir(shot.destination.parent)
            shutil.copy2(self.frame_cache / f"{key}.png", shot.destination)

        return {
            "hits": hits,
            "misses": len(pending),
            "workers": min(self.workers, max(1, len(pending))),
        }

    def _draw(self, work: list[tuple[str, Shot]], reporter: Reporter) -> None:
        lanes = min(self.workers, len(work))
        # Round-robin rather than contiguous slices: frames get steadily
        # heavier through a scene, so contiguous chunks would leave one lane
        # holding all the long ones.
        chunks = [work[index::lanes] for index in range(lanes)]
        reporter.cache(MISS, f"{len(work)} frames across {lanes} browser{'s' if lanes > 1 else ''}")

        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=lanes) as pool:
            futures = [pool.submit(self._draw_chunk, chunk) for chunk in chunks]
            for future in as_completed(futures):
                try:
                    future.result()
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]

    def _draw_chunk(self, chunk: list[tuple[str, Shot]]) -> None:
        jobs = [(self.document(shot.html), shot.destination) for _, shot in chunk]
        self.painter(self.width, self.height, jobs)
        for key, shot in chunk:
            atomic_copy(shot.destination, self.frame_cache / f"{key}.png")

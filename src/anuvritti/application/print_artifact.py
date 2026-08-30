"""TASK-1308: Print-Ready Artifact Generator (PRD 36, PRD 56).

Generates a physical print-ready publication (HTML with CSS Paged Media)
directly from a FilmSpec or FilmPackage.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from anuvritti.domain.film import FilmPackage, FilmSpec
from anuvritti.shared.errors import DomainError
from anuvritti.shared.result import Ok, Result

_PRINT_CSS = """
@page {
  size: A4 portrait;
  margin: 20mm 15mm 25mm 15mm;
  @bottom-right {
    content: counter(page);
    font-family: monospace;
    font-size: 8pt;
    color: #6B7280;
  }
}

@page :first {
  @bottom-right {
    content: none;
  }
}

@media print, all {
  body {
    background: #FFFFFF;
    color: #131B2A;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "IBM Plex Sans", sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    margin: 0;
    padding: 0;
  }

  .print-page {
    page-break-after: always;
    break-after: page;
    min-height: 90vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    box-sizing: border-box;
    padding: 2rem 1rem;
  }

  .page-cover {
    text-align: center;
    align-items: center;
  }

  .page-spread {
    page-break-inside: avoid;
    break-inside: avoid;
  }

  .print-photo {
    max-width: 100%;
    max-height: 120mm;
    object-fit: contain;
    border-radius: 6px;
    border: 1px solid #DCD8CA;
    margin: 1rem 0;
  }

  .print-citation-list {
    margin-top: auto;
    padding-top: 0.5rem;
    border-top: 1px solid #DCD8CA;
    font-family: monospace;
    font-size: 8pt;
    color: #6B7280;
  }

  .colophon {
    border-top: 1px solid #DCD8CA;
    padding-top: 2rem;
  }
}
"""


@dataclass(frozen=True, slots=True)
class PrintArtifactResult:
    """The generated print artifact."""

    html: str
    scene_count: int
    title: str


class GeneratePrintArtifactUseCase:
    """Generates a print-ready memory book artifact from a FilmSpec or FilmPackage."""

    def execute(self, spec: FilmSpec | FilmPackage) -> Result[PrintArtifactResult, DomainError]:
        film_spec = spec.draft.spec if isinstance(spec, FilmPackage) else spec

        scenes_html: list[str] = []
        for idx, scene in enumerate(film_spec.scenes):
            if scene.kind.value == "OPENING":
                title_esc = html.escape(film_spec.title)
                head_esc = html.escape(scene.heading or "")
                scenes_html.append(
                    f"""
                    <section class="print-page page-cover" id="page-cover">
                      <h1 style="font-size: 28pt; margin-bottom: 1rem; font-weight: 600;">
                        {title_esc}
                      </h1>
                      <p style="font-size: 14pt; color: #4C5665; margin-bottom: 2rem;">
                        {head_esc}
                      </p>
                      <p style="font-size: 12pt; color: #2E4A8C; font-style: italic;">
                        These are things that happened.
                      </p>
                    </section>
                    """
                )
            elif scene.kind.value == "CLOSING":
                fid_esc = html.escape(film_spec.id)
                fam_esc = html.escape(str(film_spec.family_id))
                scenes_html.append(
                    f"""
                    <section class="print-page colophon" id="page-colophon">
                      <h2 style="font-size: 16pt; margin-bottom: 0.5rem;">
                        Reality Guarantee &amp; Provenance
                      </h2>
                      <p style="font-style: italic; margin-bottom: 1.5rem; font-weight: 500;">
                        Everything here happened. Nothing here was invented.
                      </p>
                      <p style="font-size: 9pt; color: #6B7280;">
                        Film Spec: <code>{fid_esc}</code> • Family: <code>{fam_esc}</code>
                      </p>
                    </section>
                    """
                )
            else:
                cites_html = ""
                if scene.cites:
                    cites_list = ", ".join(
                        f"<code>{html.escape(c.kind.value)}:{html.escape(c.id)}</code>"
                        for c in scene.cites
                    )
                    cites_html = f'<div class="print-citation-list">Citations: {cites_list}</div>'

                narration_html = ""
                if scene.voice and scene.voice.text:
                    voice_text = html.escape(scene.voice.text)
                    narration_html = (
                        '<blockquote style="border-left: 3px solid #2E4A8C; '
                        "padding-left: 1rem; color: #2E4A8C; font-style: italic; "
                        f'margin: 1rem 0;">“{voice_text}”</blockquote>'
                    )

                media_html = ""
                for c in scene.cites:
                    if c.kind.value == "MEDIA":
                        cid = html.escape(c.id)
                        media_html = f'<img class="print-photo" src="media/{cid}.jpg" alt="Photo">'
                        break

                kind_val = html.escape(scene.kind.value)
                head_val = html.escape(scene.heading)
                body_val = (
                    f'<p style="margin-bottom: 1rem;">{html.escape(scene.body)}</p>'
                    if scene.body
                    else ""
                )

                scenes_html.append(
                    f"""
                    <article class="print-page page-spread" id="scene-{idx}">
                      <div style="display: flex; justify-content: space-between; """
                    + """border-bottom: 1px solid #DCD8CA; padding-bottom: 0.5rem; """
                    + """margin-bottom: 1.5rem;">
                        <span style="font-family: monospace; font-size: 8pt; """
                    + f"""color: #6B7280; text-transform: uppercase;">{kind_val}</span>
                        <span style="font-family: monospace; font-size: 8pt; """
                    + f"""color: #6B7280;">Page {idx + 1}</span>
                      </div>
                      <h2 style="font-size: 18pt; margin-bottom: 1rem;">{head_val}</h2>
                      {media_html}
                      {body_val}
                      {narration_html}
                      {cites_html}
                    </article>
                    """
                )

        full_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(film_spec.title)} - Print Edition</title>
<style>
{_PRINT_CSS}
</style>
</head>
<body>
{"".join(scenes_html)}
</body>
</html>"""

        return Ok(
            PrintArtifactResult(
                html=full_doc,
                scene_count=len(film_spec.scenes),
                title=film_spec.title,
            )
        )

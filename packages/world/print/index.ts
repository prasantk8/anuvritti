/**
 * @anuvritti/world/print
 *
 * Renders print-ready books and physical memory artifacts from FilmSpec.
 */
import { emitPrintCss } from "./css.ts";

export interface PrintSceneInput {
  id: string;
  kind: string;
  heading: string;
  body?: string;
  narration?: string;
  picture?: string;
  cites?: Array<{ kind: string; id: string }>;
}

export interface PrintSpecInput {
  id: string;
  title: string;
  child_name?: string;
  edition?: string;
  scenes: PrintSceneInput[];
}

export function escapeHtml(str: string): string {
  if (!str) return "";
  return str.replace(/[&<>"']/g, (m) => {
    switch (m) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      case "'": return "&#39;";
      default: return m;
    }
  });
}

export function renderPrintArtifact(spec: PrintSpecInput, options: { inlineCss?: boolean } = {}): string {
  const css = emitPrintCss();

  const scenesHtml = spec.scenes.map((scene, idx) => {
    const isOpening = scene.kind === "OPENING";
    const isClosing = scene.kind === "CLOSING";

    if (isOpening) {
      return `
      <section class="print-page page-cover" id="page-cover">
        <h1 style="font-family: var(--w-font-display); font-size: var(--w-size-name); margin-bottom: 1rem;">${escapeHtml(spec.title)}</h1>
        ${spec.edition ? `<p style="font-size: var(--w-size-chapter); color: var(--w-color-ink-quiet);">${escapeHtml(spec.edition)}</p>` : ""}
        <p style="font-size: var(--w-size-lead); color: var(--w-color-indigo); margin-top: 2rem;">These are things that happened.</p>
      </section>
      `;
    }

    if (isClosing) {
      return `
      <section class="print-page colophon" id="page-colophon">
        <h2 style="font-family: var(--w-font-display); font-size: var(--w-size-title); margin-bottom: 0.5rem;">Colophon & Reality Guarantee</h2>
        <p style="font-style: italic; margin-bottom: 1rem;">Everything here happened. Nothing here was invented.</p>
        <p style="font-size: var(--w-size-fine); color: var(--w-color-ink-faint);">
          Printed from FilmSpec <code>${escapeHtml(spec.id)}</code>. All citations verified against sovereign family ledger.
        </p>
      </section>
      `;
    }

    const citesHtml = (scene.cites && scene.cites.length > 0)
      ? `<div class="print-citation-list">Citations: ${scene.cites.map(c => `<code>${escapeHtml(c.kind)}:${escapeHtml(c.id)}</code>`).join(", ")}</div>`
      : "";

    return `
    <article class="print-page page-spread" id="scene-${idx}">
      <div style="display: flex; justify-content: space-between; border-bottom: 1px solid var(--w-color-thread); padding-bottom: 0.5rem; margin-bottom: 1.5rem;">
        <span style="font-family: var(--w-font-mono); font-size: var(--w-size-micro); color: var(--w-color-ink-faint); text-transform: uppercase;">${escapeHtml(scene.kind)}</span>
        <span style="font-family: var(--w-font-mono); font-size: var(--w-size-micro); color: var(--w-color-ink-faint);">Page ${idx + 1}</span>
      </div>

      <h2 style="font-family: var(--w-font-display); font-size: var(--w-size-chapter); margin-bottom: 1rem;">${escapeHtml(scene.heading)}</h2>
      
      ${scene.picture ? `<img class="print-photo" src="${escapeHtml(scene.picture)}" alt="${escapeHtml(scene.heading)}">` : ""}
      
      ${scene.body ? `<p style="font-size: var(--w-size-body); line-height: var(--w-leading-read); margin-bottom: 1rem;">${escapeHtml(scene.body)}</p>` : ""}
      
      ${scene.narration ? `<blockquote style="border-left: 3px solid var(--w-color-indigo); padding-left: 1rem; font-style: italic; color: var(--w-color-indigo); margin: 1rem 0;">${escapeHtml(scene.narration)}</blockquote>` : ""}

      ${citesHtml}
    </article>
    `;
  }).join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${escapeHtml(spec.title)} - Print Edition</title>
<style>
${css}
</style>
</head>
<body>
${scenesHtml}
</body>
</html>`;
}

export { emitPrintCss };

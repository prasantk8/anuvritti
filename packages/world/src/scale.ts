/**
 * PRD 56 - type, space, edge, elevation and motion.
 *
 * Two positions worth stating, because both are testable:
 *
 * 1. Space is a scale, not a set of numbers. Anything not on the scale is a mistake
 *    someone made under deadline, and `tests/design` will say so.
 * 2. Motion has a ceiling. Nothing in this product may animate for longer than
 *    `motion.duration.considered`, with exactly one exception - the Spark flip, which
 *    is the core gesture and is allowed to take its time.
 */

export interface FontRole {
  readonly name: string;
  readonly stack: string;
  readonly meaning: string;
  /** Fetched from Google Fonts, the one font host an artifact CSP admits. */
  readonly webfont?: { readonly family: string; readonly axes: string };
}

export const FONTS: readonly FontRole[] = [
  {
    name: "display",
    stack:
      '"Newsreader", "Noto Naskh Arabic", "Noto Serif Devanagari", "Iowan Old Style", Georgia, serif',
    meaning:
      "A child's name, a year, a single sentence a parent said. Used rarely and large, the way a page in an album is titled.",
    webfont: { family: "Newsreader", axes: "ital,opsz,wght@0,6..72,300..600;1,6..72,300..500" },
  },
  {
    name: "body",
    stack:
      '"IBM Plex Sans", "Noto Sans Arabic", "Noto Sans Devanagari", ui-sans-serif, system-ui, -apple-system, sans-serif',
    meaning: "Everything the app itself says. Plain, unhurried, and never the loudest thing.",
    webfont: { family: "IBM Plex Sans", axes: "wght@400;500;600" },
  },
  {
    name: "mono",
    stack: '"IBM Plex Mono", ui-monospace, SFMono-Regular, monospace',
    meaning:
      "Data that must be inspectable rather than beautiful: provenance ids, timestamps in an export, a checksum.",
    webfont: { family: "IBM Plex Mono", axes: "wght@400;500" },
  },
] as const;

/** A ~1.22 modular scale. `body` is the anchor at 16. */
export const TYPE_SIZE = {
  micro: 12,
  fine: 14,
  body: 16,
  lead: 18,
  title: 22,
  chapter: 27,
  year: 34,
  name: 42,
} as const;

export const LINE_HEIGHT = {
  /** Display type set large; it needs less. */
  tight: 1.16,
  /** The default for anything read in sentences. */
  read: 1.55,
  /** Long-form: a why, a transcript, a letter. */
  open: 1.7,
} as const;

export const TRACKING = {
  name: "-0.02em",
  normal: "0",
  /** Uppercase labels only. Nothing else is ever tracked out. */
  label: "0.08em",
} as const;

export const WEIGHT = { regular: 400, medium: 500, semibold: 600 } as const;

/** 4px base. Every margin, padding and gap in the product resolves to one of these. */
export const SPACE = {
  0: 0,
  hair: 2,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 24,
  6: 32,
  7: 48,
  8: 64,
  9: 96,
  /** PRD 56 - "meaningful empty space". The gap that says a section ended. */
  breath: 128,
} as const;

/**
 * Edges are not uniform. A Spark is a held object and is softer than a field you type
 * into; a full round belongs only to something genuinely circular.
 */
export const RADIUS = {
  /** Hairline inputs and chips. */
  edge: 4,
  /** A field, a button. */
  cut: 8,
  /** A Spark. The object radius. */
  object: 14,
  /** A sheet arriving from the bottom of the screen. */
  sheet: 24,
  round: 9999,
} as const;

/**
 * Shadow is themed, because a shadow is made of colour.
 *
 * On undyed cloth it is warm and indigo-biased - a pure-black shadow there reads as
 * plastic. On a dark ground the same shadow is invisible, so dark uses true black at
 * higher opacity. The specimen is what caught this: the elevation row simply vanished.
 */
export interface Elevation {
  readonly light: string;
  readonly dark: string;
}

export const ELEVATION: Record<string, Elevation> = {
  flat: { light: "none", dark: "none" },
  resting: {
    light: "0 1px 2px rgba(19, 27, 42, 0.06), 0 1px 1px rgba(19, 27, 42, 0.04)",
    dark: "0 1px 2px rgba(0, 0, 0, 0.5), 0 1px 1px rgba(0, 0, 0, 0.35)",
  },
  lifted: {
    light: "0 2px 6px rgba(19, 27, 42, 0.08), 0 6px 16px rgba(19, 27, 42, 0.06)",
    dark: "0 2px 6px rgba(0, 0, 0, 0.55), 0 6px 16px rgba(0, 0, 0, 0.4)",
  },
  held: {
    light: "0 8px 24px rgba(19, 27, 42, 0.12), 0 2px 6px rgba(19, 27, 42, 0.08)",
    dark: "0 10px 28px rgba(0, 0, 0, 0.62), 0 2px 6px rgba(0, 0, 0, 0.45)",
  },
} as const;

export const DURATION = {
  /** A state change the eye should not have to wait for. */
  instant: 90,
  /** The default. A press, a chip settling, a field focusing. */
  settle: 180,
  /** Something arriving or leaving: a sheet, a suggestion. */
  arrive: 280,
  /** The ceiling for everything except the flip. */
  considered: 420,
  /** The one exception: turning a Spark over to see why it was saved. */
  flip: 620,
} as const;

/** The ceiling referenced by `tests/design`. */
export const MOTION_CEILING_MS = DURATION.considered;
export const MOTION_CEILING_EXEMPT = ["flip"] as const;

export const EASING = {
  /** Decelerate in. Things enter as if they had weight. */
  enter: "cubic-bezier(0.16, 1, 0.3, 1)",
  /** Accelerate out. Leaving is quicker than arriving. */
  leave: "cubic-bezier(0.4, 0, 1, 1)",
  /** Both ends eased - for something moving between two resting states. */
  move: "cubic-bezier(0.4, 0, 0.2, 1)",
} as const;

export const LAYOUT = {
  /** Running text sits near 65 characters. */
  measure: "34rem",
  /** A Spark grid on a phone; the film composes on a multiple of it. */
  gutter: SPACE[4],
  /** Minimum touch target. Non-negotiable, including for the child surface. */
  touch: 44,
} as const;

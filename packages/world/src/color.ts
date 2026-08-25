/**
 * PRD 56 - the Anuvritti world, as colour.
 *
 * The palette is one image: *indigo dye on undyed cloth*. Undyed cloth is the ground
 * the family's own material sits on. Indigo is the app's own hand - structure it drew,
 * never something a person made. And one warm earth tone, saffron, is rationed to a
 * single meaning: a human voice.
 *
 * Every token declares the role it plays. The role is not documentation; `tests/design`
 * reads it and fails the build when a colour is used for something it does not mean.
 */

/** What a colour is *for*. A token may only be used where its role permits. */
export type Role =
  /** The page itself. Undyed cloth. */
  | "ground"
  /** Something you could pick up: a Spark, a sheet, a card. */
  | "surface"
  /** Marks on the cloth - text and iconography. */
  | "ink"
  /** Seams, rules, the app's own structural hand. */
  | "structure"
  /** Rationed. A person's recorded voice, and the why in their own words. */
  | "voice"
  /** The only urgency in the product. Reserved for what cannot be undone. */
  | "destructive";

export interface ColorToken {
  /** CSS custom property becomes `--w-color-{name}`. */
  readonly name: string;
  readonly light: string;
  readonly dark: string;
  readonly role: Role;
  /** Why this colour exists. Read by the specimen page and by the design tests. */
  readonly meaning: string;
  /**
   * Set when this token is text that must remain legible on a named ground.
   * `tests/design` computes the WCAG contrast ratio in *both* themes.
   */
  readonly readableOn?: readonly string[];
  /** Minimum contrast ratio required against every ground in `readableOn`. */
  readonly minContrast?: number;
}

export const COLORS: readonly ColorToken[] = [
  // -- Ground. The cloth.
  {
    name: "ground",
    light: "#EFEDE4",
    dark: "#12151C",
    role: "ground",
    meaning: "Undyed cloth. The surface a family's material rests on, and never itself a subject.",
  },
  {
    name: "ground-sunk",
    light: "#E3E0D3",
    dark: "#0C0F15",
    role: "ground",
    meaning: "A well pressed into the cloth: a search field, an inset, a quiet recess.",
  },

  // -- Surface. Things with edges, which can be picked up and turned over.
  {
    name: "surface",
    light: "#F9F8F3",
    dark: "#1A1F29",
    role: "surface",
    meaning: "A Spark. The one object in the product a parent actually handles.",
  },
  {
    name: "surface-lifted",
    light: "#FFFFFF",
    dark: "#232936",
    role: "surface",
    meaning: "Held above the cloth: a sheet, a menu, the reverse of a Spark once flipped.",
  },

  // -- Ink. Marks on cloth.
  {
    name: "ink",
    light: "#131B2A",
    dark: "#ECEAE1",
    role: "ink",
    meaning: "What a person wrote, said, or saved. The darkest thing on the page.",
    readableOn: ["ground", "surface", "surface-lifted"],
    minContrast: 7,
  },
  {
    name: "ink-quiet",
    light: "#4C5665",
    dark: "#A8AEB9",
    role: "ink",
    meaning: "The app speaking about itself: labels, captions, its own explanations.",
    readableOn: ["ground", "surface"],
    minContrast: 4.5,
  },
  {
    name: "ink-faint",
    light: "#6B7280",
    dark: "#868D99",
    role: "ink",
    meaning: "Present, but not asking to be read. Placeholder text and resting iconography.",
    readableOn: ["ground", "surface"],
    minContrast: 3,
  },

  // -- Structure. The app's own hand, and only ever the app's.
  {
    name: "thread",
    light: "#DCD8CA",
    dark: "#2B313C",
    role: "structure",
    meaning: "The seam between two things. Hairline rules and the edges of a Spark.",
  },
  {
    name: "thread-strong",
    light: "#C4BDA9",
    dark: "#3B4250",
    role: "structure",
    meaning: "A seam that has to hold: the boundary of an input, a focus ring at rest.",
  },
  {
    name: "indigo",
    light: "#2E4A8C",
    dark: "#93ACE2",
    role: "structure",
    meaning: "Dye. Every mark the application made rather than the family: links, selection, focus.",
    readableOn: ["ground", "surface"],
    minContrast: 4.5,
  },
  {
    name: "indigo-wash",
    light: "#DFE5F3",
    dark: "#1E2637",
    role: "structure",
    meaning: "Indigo at rest. A wash behind something chosen, never behind something urgent.",
  },

  // -- Voice. Rationed to one meaning in the entire product.
  {
    name: "saffron",
    light: "#8A5B18",
    dark: "#E0AC5A",
    role: "voice",
    meaning:
      "A person's voice. A recorded why, a Little Thing, a waveform. Seeing it means someone actually spoke - so it appears nowhere else.",
    readableOn: ["ground", "surface"],
    minContrast: 4.5,
  },
  {
    name: "saffron-wash",
    light: "#F5EBD8",
    dark: "#2C2416",
    role: "voice",
    meaning: "The ground beneath a recording. Warmth behind a waveform, and nothing else.",
  },

  // -- Destructive. The only red in the world.
  {
    name: "unmade",
    light: "#8F2E2E",
    dark: "#E09A9A",
    role: "destructive",
    meaning:
      "The single urgency colour. Permitted only where something is erased for good - delete, revoke, forget. Never for lateness, and never for a child.",
    readableOn: ["ground", "surface"],
    minContrast: 4.5,
  },
] as const;

export const colorsByName: ReadonlyMap<string, ColorToken> = new Map(
  COLORS.map((c) => [c.name, c])
);

export function color(name: string): ColorToken {
  const found = colorsByName.get(name);
  if (!found) throw new Error(`unknown colour token: ${name}`);
  return found;
}

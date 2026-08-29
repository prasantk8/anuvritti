/** The writing systems a film can promise to draw without borrowing from its host. */

export type FilmScript = "Latin" | "Arabic" | "Devanagari";
export type FilmFontRole = "display" | "body";

export interface FilmScriptCoverage {
  readonly name: FilmScript;
  readonly ranges: readonly (readonly [number, number])[];
}

export interface FilmFontFace {
  readonly family: string;
  readonly role: FilmFontRole;
  readonly weight: 400 | 500;
  readonly script: FilmScript;
  readonly package: string;
  readonly version: "5.3.0";
  readonly file: string;
  readonly sha256: string;
}

export const FILM_COMMON_RANGES = [
  [0x0009, 0x000d], // whitespace that can occur in saved text
  [0x0020, 0x007e], // ASCII letters, digits and punctuation
  [0x00a0, 0x00bf], // shared punctuation and currency
  [0x2000, 0x206f], // typographic punctuation, bidi marks and joiners
] as const;

export const FILM_SCRIPTS: readonly FilmScriptCoverage[] = [
  {
    name: "Latin",
    ranges: [...FILM_COMMON_RANGES, [0x00c0, 0x024f], [0x0300, 0x036f], [0x1e00, 0x1eff]],
  },
  {
    name: "Arabic",
    ranges: [
      [0x0600, 0x06ff],
      [0x0750, 0x077f],
      [0x0870, 0x089f],
      [0x08a0, 0x08ff],
    ],
  },
  { name: "Devanagari", ranges: [[0x0900, 0x097f], [0x1cd0, 0x1cff]] },
] as const;

export const FILM_FONTS: readonly FilmFontFace[] = [
  {
    family: "Newsreader",
    role: "display",
    weight: 400,
    script: "Latin",
    package: "@fontsource/newsreader",
    version: "5.3.0",
    file: "newsreader/files/newsreader-latin-400-normal.woff2",
    sha256: "e66067814f1c672d33a457e4f4d102c818b481420e2234cf685ebdbf2f443904",
  },
  {
    family: "Noto Naskh Arabic",
    role: "display",
    weight: 400,
    script: "Arabic",
    package: "@fontsource/noto-naskh-arabic",
    version: "5.3.0",
    file: "noto-naskh-arabic/files/noto-naskh-arabic-arabic-400-normal.woff2",
    sha256: "9cc2d2e90f7b51904468558b4ed529de8a8206497c8edb5e33122bd077e0158c",
  },
  {
    family: "Noto Serif Devanagari",
    role: "display",
    weight: 400,
    script: "Devanagari",
    package: "@fontsource/noto-serif-devanagari",
    version: "5.3.0",
    file: "noto-serif-devanagari/files/noto-serif-devanagari-devanagari-400-normal.woff2",
    sha256: "e64b3b73131abb4074d4b22453bffe54fe8973fa0ea98a32504570df647b2a0a",
  },
  {
    family: "IBM Plex Sans",
    role: "body",
    weight: 400,
    script: "Latin",
    package: "@fontsource/ibm-plex-sans",
    version: "5.3.0",
    file: "ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2",
    sha256: "3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e",
  },
  {
    family: "IBM Plex Sans",
    role: "body",
    weight: 500,
    script: "Latin",
    package: "@fontsource/ibm-plex-sans",
    version: "5.3.0",
    file: "ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2",
    sha256: "0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203",
  },
  ...([400, 500] as const).flatMap((weight) => [
    {
      family: "Noto Sans Arabic",
      role: "body" as const,
      weight,
      script: "Arabic" as const,
      package: "@fontsource/noto-sans-arabic",
      version: "5.3.0" as const,
      file: `noto-sans-arabic/files/noto-sans-arabic-arabic-${weight}-normal.woff2`,
      sha256:
        weight === 400
          ? "4e2ca0745c908761dc5c5db951662873887c59366fa1a5693ad22c0864abf1bd"
          : "38599e3046a0ceeae9d10fb9c282424d16b7a05f0838478fabe27908fc922722",
    },
    {
      family: "Noto Sans Devanagari",
      role: "body" as const,
      weight,
      script: "Devanagari" as const,
      package: "@fontsource/noto-sans-devanagari",
      version: "5.3.0" as const,
      file: `noto-sans-devanagari/files/noto-sans-devanagari-devanagari-${weight}-normal.woff2`,
      sha256:
        weight === 400
          ? "f86f14cbd1004f5795689ee9cc70d5d87d915f5135b30283525c1c7b8f0eb192"
          : "c9e45ff29dddc46bdb85b0cb97922fde980ae2fcafadee4498ff25bd0448292f",
    },
  ]),
] as const;

function supported(codepoint: number): boolean {
  return FILM_SCRIPTS.some((script) =>
    script.ranges.some(([first, last]) => codepoint >= first && codepoint <= last)
  );
}

export function unsupportedFilmCodepoints(text: string): string[] {
  const refused = new Set<number>();
  for (const character of text.normalize("NFC")) {
    const codepoint = character.codePointAt(0)!;
    if (!supported(codepoint)) refused.add(codepoint);
  }
  return [...refused].sort((a, b) => a - b).map((value) => `U+${value.toString(16).toUpperCase().padStart(4, "0")}`);
}

export function assertFilmTextSupported(texts: readonly string[]): void {
  const refused = unsupportedFilmCodepoints(texts.join("\n"));
  if (refused.length) {
    throw new Error(`film text contains glyphs outside its bundled writing systems: ${refused.join(", ")}`);
  }
}

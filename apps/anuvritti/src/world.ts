/**
 * `packages/world`, as React Native reads it.
 *
 * The whole reason the design language is TypeScript rather than a stylesheet: the same
 * fourteen colours, five durations and one type scale drive the native app here and the
 * film's Chromium scenes in Phase 7. Not "kept in sync" — the same file.
 *
 * The one translation this file performs is themes. CSS resolves them with a media query;
 * React Native has `useColorScheme()`, so a token becomes a *pair* and a hook picks. The
 * three-state rule the stylesheet keeps (explicit light, explicit dark, and system) is the
 * same here: `useColorScheme()` returns the system value, and an explicit choice overrides.
 */

import {
  COLORS,
  DURATION,
  EASING,
  ELEVATION,
  LAYOUT,
  LINE_HEIGHT,
  RADIUS,
  SPACE,
  TRACKING,
  TYPE_SIZE,
  WEIGHT,
} from "@anuvritti/world";

export type Theme = "light" | "dark";

export type ColorName = (typeof COLORS)[number]["name"];

type Palette = Record<string, string>;

function paletteFor(theme: Theme): Palette {
  return Object.fromEntries(COLORS.map((token) => [token.name, token[theme]]));
}

export const PALETTE: Record<Theme, Palette> = {
  light: paletteFor("light"),
  dark: paletteFor("dark"),
};

/**
 * The typefaces, by the role they play.
 *
 * The names are what `expo-font` registers, which is what `@expo-google-fonts/*` exports.
 * The roles are what the design system calls them, and the app only ever names the role —
 * so changing the display face is one line here and nothing anywhere else.
 */
export const FONT = {
  display: "Newsreader_400Regular",
  displayItalic: "Newsreader_400Regular_Italic",
  displayMedium: "Newsreader_500Medium",
  body: "IBMPlexSans_400Regular",
  bodyMedium: "IBMPlexSans_500Medium",
  mono: "IBMPlexMono_400Regular",
} as const;

/**
 * Shadows, translated.
 *
 * `packages/world` emits CSS `box-shadow` strings, which React Native cannot read. The
 * elevation *scale* is what matters and it is preserved: four steps, and the dark theme's
 * shadows are near-black rather than indigo-tinted, which is the bug the specimen caught.
 */
export const SHADOW = {
  light: {
    flat: {},
    resting: { shadowColor: "#131B2A", shadowOpacity: 0.06, shadowRadius: 2, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
    lifted: { shadowColor: "#131B2A", shadowOpacity: 0.1, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
    held: { shadowColor: "#131B2A", shadowOpacity: 0.16, shadowRadius: 20, shadowOffset: { width: 0, height: 10 }, elevation: 10 },
  },
  dark: {
    flat: {},
    resting: { shadowColor: "#000000", shadowOpacity: 0.5, shadowRadius: 2, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
    lifted: { shadowColor: "#000000", shadowOpacity: 0.6, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
    held: { shadowColor: "#000000", shadowOpacity: 0.7, shadowRadius: 20, shadowOffset: { width: 0, height: 10 }, elevation: 10 },
  },
} as const;

export {
  COLORS,
  DURATION,
  EASING,
  ELEVATION,
  LAYOUT,
  LINE_HEIGHT,
  RADIUS,
  SPACE,
  TRACKING,
  TYPE_SIZE,
  WEIGHT,
};

/**
 * Everything a screen needs, resolved for one theme.
 *
 * Passed down rather than imported, so a component cannot accidentally read the light
 * palette while sitting on the dark ground — the failure the specimen exists to catch.
 */
export interface World {
  readonly theme: Theme;
  readonly color: Palette;
  readonly shadow: (typeof SHADOW)["light"];
  readonly space: typeof SPACE;
  readonly type: typeof TYPE_SIZE;
  readonly radius: typeof RADIUS;
  readonly font: typeof FONT;
  readonly duration: typeof DURATION;
  readonly line: typeof LINE_HEIGHT;
  readonly layout: typeof LAYOUT;
}

export function worldFor(theme: Theme): World {
  return {
    theme,
    color: PALETTE[theme],
    shadow: SHADOW[theme],
    space: SPACE,
    type: TYPE_SIZE,
    radius: RADIUS,
    font: FONT,
    duration: DURATION,
    line: LINE_HEIGHT,
    layout: LAYOUT,
  };
}

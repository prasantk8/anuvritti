/**
 * The Anuvritti world, in one object.
 *
 * This module is the single source of truth for the visual language. It is consumed
 * three ways and must not drift between them:
 *
 *   - the native app imports `tokens` directly (TypeScript);
 *   - the film scenes read `dist/world.css` in Chromium (CSS custom properties);
 *   - `tests/design` reads this file's structure and enforces the constitution.
 *
 * A film made this way is not merely styled to resemble the app. It is built out of
 * the same material.
 */
import { COLORS, colorsByName, type ColorToken, type Role } from "./color.ts";
import {
  DURATION,
  EASING,
  ELEVATION,
  FONTS,
  LAYOUT,
  LINE_HEIGHT,
  MOTION_CEILING_EXEMPT,
  MOTION_CEILING_MS,
  RADIUS,
  SPACE,
  TRACKING,
  TYPE_SIZE,
  WEIGHT,
} from "./scale.ts";

export type Theme = "light" | "dark";

/** Ergonomic access for application code: `tokens.color.ink.light`. */
export const tokens = {
  color: Object.fromEntries(COLORS.map((c) => [c.name, { light: c.light, dark: c.dark }])) as Record<
    string,
    { light: string; dark: string }
  >,
  font: Object.fromEntries(FONTS.map((f) => [f.name, f.stack])) as Record<string, string>,
  size: TYPE_SIZE,
  leading: LINE_HEIGHT,
  tracking: TRACKING,
  weight: WEIGHT,
  space: SPACE,
  radius: RADIUS,
  elevation: ELEVATION,
  duration: DURATION,
  easing: EASING,
  layout: LAYOUT,
} as const;

/** Resolve the palette for one theme: `palette("dark").ink`. */
export function palette(theme: Theme): Record<string, string> {
  return Object.fromEntries(COLORS.map((c) => [c.name, c[theme]]));
}

/** Which roles a colour token may legitimately serve. Read by `tests/design`. */
export const ROLES: readonly Role[] = [
  "ground",
  "surface",
  "ink",
  "structure",
  "voice",
  "destructive",
];

export { COLORS, colorsByName, FONTS, MOTION_CEILING_MS, MOTION_CEILING_EXEMPT };
export type { ColorToken, Role };

/**
 * Parent's 3AM Night Surface (PRD 56, PRD 8.4).
 *
 * A parent feeding or soothing a child in a dark room cannot have the screen illuminate
 * the room or wake the child.
 *
 * The Night Surface uses true OLED black ground (#000000) and low-lux amber-tinted ink
 * with suppressed blue-channel emission.
 */

export interface NightSurfacePalette {
  readonly ground: string;
  readonly surface: string;
  readonly ink: string;
  readonly inkQuiet: string;
  readonly saffron: string;
  readonly thread: string;
}

export const NIGHT_SURFACE: NightSurfacePalette = {
  ground: "#000000",
  surface: "#0A0C10",
  ink: "#9E9A8E",
  inkQuiet: "#5C5950",
  saffron: "#B08035",
  thread: "#1A1D24",
};

/**
 * Validates that maximum relative luminance of any token in the night surface
 * is below the strict room-glare threshold (0.35).
 */
export function isLowGlareNightToken(hexColor: string): boolean {
  const cleanHex = hexColor.replace("#", "");
  const r = parseInt(cleanHex.slice(0, 2), 16) / 255;
  const g = parseInt(cleanHex.slice(2, 4), 16) / 255;
  const b = parseInt(cleanHex.slice(4, 6), 16) / 255;

  const toLinear = (c: number) =>
    c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);

  const lum = 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
  return lum <= 0.35;
}

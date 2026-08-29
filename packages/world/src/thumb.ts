/**
 * Ergonomic Thumb Arc Geometry (PRD 56, PRD 8.4).
 *
 * Holding a baby in one arm at 3:00 AM while capturing a moment with the other hand
 * means every single critical affordance must sit comfortably inside the natural thumb arc.
 * Requiring a stretch to the top corners or a two-handed grip breaks the physical promise.
 */

export type ThumbZone = "natural" | "reach" | "stretch";

export interface ViewportDimensions {
  width: number;
  height: number;
}

export interface ElementRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function classifyThumbZone(
  rect: ElementRect,
  viewport: ViewportDimensions
): ThumbZone {
  const centerY = rect.y + rect.height / 2;
  const relativeY = centerY / viewport.height;

  // Bottom 40% of screen is natural thumb arc
  if (relativeY >= 0.60) {
    return "natural";
  }
  // Middle 30% is comfortable reach
  if (relativeY >= 0.30) {
    return "reach";
  }
  // Top 30% requires stretching or second hand
  return "stretch";
}

export function isOneHandedAffordance(
  rect: ElementRect,
  viewport: ViewportDimensions
): boolean {
  const zone = classifyThumbZone(rect, viewport);
  return zone === "natural" || zone === "reach";
}

/** Pure decisions for the first run: family, child, then one real share. */

export interface ThresholdMarker {
  readonly familyId: string;
  readonly childName?: string;
}

export type ThresholdStage = "child" | "share";

export function thresholdStage(marker: ThresholdMarker): ThresholdStage {
  return marker.childName ? "share" : "child";
}

/** The server issues eight Crockford characters; spacing is presentation, not identity. */
export function visiblePairingCode(value: string): string {
  return value.replace(/[^A-Z0-9]/gi, "").toUpperCase().slice(0, 8);
}


/**
 * Accessible Captions and Audio Descriptions for Anuvritti Films (PRD 27, PRD 56, TASK-1209).
 *
 * Every film is accessible by default:
 * 1. Closed captions with exact spoken words and synthetic disclosures.
 * 2. Audio description cues for screen readers and visually impaired family members.
 * 3. High contrast styling conforming to WCAG AAA standards.
 */

export interface CaptionCue {
  readonly start_seconds: number;
  readonly end_seconds: number;
  readonly text: string;
  readonly is_synthetic?: boolean;
}

export interface AudioDescriptionCue {
  readonly start_seconds: number;
  readonly end_seconds: number;
  readonly description: string;
}

function formatClock(seconds: number): string {
  const s = Math.max(0, seconds);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const secs = Math.floor(s % 60);
  const millis = Math.round((s - Math.floor(s)) * 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

export function emitWebVtt(cues: readonly CaptionCue[]): string {
  const lines: string[] = ["WEBVTT\n"];
  for (let i = 0; i < cues.length; i++) {
    const cue = cues[i]!;
    const prefix = cue.is_synthetic ? "[Machine Voice] " : "";
    lines.push(
      `${formatClock(cue.start_seconds)} --> ${formatClock(cue.end_seconds)}\n${prefix}${cue.text}\n`
    );
  }
  return lines.join("\n");
}

export function emitAudioDescriptionsVtt(cues: readonly AudioDescriptionCue[]): string {
  const lines: string[] = ["WEBVTT - Audio Description Track\n"];
  for (let i = 0; i < cues.length; i++) {
    const cue = cues[i]!;
    lines.push(
      `${formatClock(cue.start_seconds)} --> ${formatClock(cue.end_seconds)}\n${cue.description}\n`
    );
  }
  return lines.join("\n");
}

export function buildAudioDescription(
  heading: string,
  body?: string,
  kind?: string
): string {
  const label = kind && kind !== "SPARK" && kind !== "MOMENT" ? `[${kind}] ` : "";
  if (body && body.trim().length > 0) {
    return `${label}${heading}: ${body}`;
  }
  return `${label}${heading}`;
}

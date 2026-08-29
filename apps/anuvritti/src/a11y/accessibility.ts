/**
 * Proven Accessibility System (PRD 56, PRD 27).
 *
 * Anuvritti is designed for tired parents, grandparents with varied eyesight,
 * and screen reader users. Accessibility is proven through deterministic assertions:
 * 1. Screen reader announcements & labels for all core objects (Spark, Voice, Return, Right Now).
 * 2. Dynamic Type scaling up to 200% without layout breakage or text truncation.
 * 3. Reduced motion support mapping animation durations to zero.
 * 4. WCAG 2.1 AAA contrast calculations for all color token combinations.
 */

export interface AccessibilityProps {
  accessible: boolean;
  accessibilityLabel: string;
  accessibilityHint?: string;
  accessibilityRole?: "button" | "header" | "text" | "image" | "adjustable" | "summary";
  accessibilityState?: {
    disabled?: boolean;
    selected?: boolean;
    busy?: boolean;
  };
}

export const a11yLabels = {
  spark(params: {
    title: string;
    whyText?: string | null;
    hasVoiceNote?: boolean;
    subjectChildName?: string | null;
  }): AccessibilityProps {
    const parts: string[] = [`Memory idea: ${params.title}`];
    if (params.subjectChildName) {
      parts.push(`For ${params.subjectChildName}`);
    }
    if (params.whyText) {
      parts.push(`Why it was saved: ${params.whyText}`);
    } else if (params.hasVoiceNote) {
      parts.push("Contains a recorded voice note explaining why it was saved");
    }
    return {
      accessible: true,
      accessibilityLabel: parts.join(". "),
      accessibilityRole: "summary",
    };
  },

  /** The back of a flipped Spark: the same object, now showing why it was kept. */
  sparkReverse(params: { title: string }): AccessibilityProps {
    return {
      accessible: true,
      accessibilityLabel: `Why you saved ${params.title}`,
      accessibilityRole: "summary",
    };
  },

  /**
   * The intent chip, which is a guess and has to sound like one.
   *
   * PRD 8.7: a guess the machine is unsure of is phrased as a question, never as a
   * label. That distinction is carried by a question mark on the screen, and a screen
   * reader user gets it from nowhere else - so it is built here rather than inline in
   * the component, where it was, and where nothing named it.
   */
  intentChip(params: { intent: string; uncertain: boolean }): AccessibilityProps {
    return {
      accessible: true,
      accessibilityLabel: params.uncertain
        ? `Something to ${params.intent}? Tap to change.`
        : `To ${params.intent}. Tap to change.`,
      accessibilityRole: "button",
    };
  },

  holdToTalk(params: { isRecording: boolean; elapsedSeconds: number }): AccessibilityProps {
    if (params.isRecording) {
      return {
        accessible: true,
        accessibilityLabel: `Recording microphone active. ${params.elapsedSeconds} seconds elapsed. Release to save memory.`,
        accessibilityRole: "button",
        accessibilityState: { busy: true },
      };
    }
    return {
      accessible: true,
      accessibilityLabel: "Hold to talk microphone button",
      accessibilityHint: "Press and hold to record a voice memory. Release to save automatically.",
      accessibilityRole: "button",
    };
  },

  rightNow(params: { childName: string; prompt: string }): AccessibilityProps {
    return {
      accessible: true,
      accessibilityLabel: `Right Now daily question for ${params.childName}: ${params.prompt}`,
      accessibilityHint: "Double tap to answer with one sentence.",
      accessibilityRole: "button",
    };
  },

  returnNotice(params: {
    childName: string;
    timeAgoText: string;
    noteText?: string | null;
  }): AccessibilityProps {
    const parts = [
      `Memory brought back for ${params.childName}`,
      `Saved ${params.timeAgoText}`,
    ];
    if (params.noteText) {
      parts.push(`Original note: ${params.noteText}`);
    }
    return {
      accessible: true,
      accessibilityLabel: parts.join(". "),
      accessibilityRole: "summary",
    };
  },
};

/**
 * Dynamic Type calculation allowing up to 200% font scaling (PRD 56).
 */
export function computeDynamicType(
  baseSize: number,
  fontScale: number,
  maxScale = 2.0
): { fontSize: number; lineHeight: number; minTouchTarget: number } {
  const effectiveScale = Math.max(1.0, Math.min(fontScale, maxScale));
  const fontSize = Math.round(baseSize * effectiveScale);
  const lineHeight = Math.round(fontSize * 1.35);
  // Minimum touch target is always at least 44pt regardless of scale
  const minTouchTarget = Math.max(44, Math.round(44 * effectiveScale * 0.75));

  return {
    fontSize,
    lineHeight,
    minTouchTarget,
  };
}

/**
 * Reduced motion resolver: collapses transitions to 0ms when requested (PRD 56).
 */
export function resolveMotionDuration(baseDurationMs: number, reduceMotion: boolean): number {
  return reduceMotion ? 0 : baseDurationMs;
}

/**
 * Calculates relative luminance for WCAG contrast calculation.
 */
function getRelativeLuminance(hexColor: string): number {
  const cleanHex = hexColor.replace("#", "");
  const r = parseInt(cleanHex.slice(0, 2), 16) / 255;
  const g = parseInt(cleanHex.slice(2, 4), 16) / 255;
  const b = parseInt(cleanHex.slice(4, 6), 16) / 255;

  const toLinear = (c: number) =>
    c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);

  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

/**
 * Calculates WCAG 2.1 contrast ratio between two colors (e.g. 4.5 for AA, 7.0 for AAA).
 */
export function calculateContrastRatio(fgHex: string, bgHex: string): number {
  const l1 = getRelativeLuminance(fgHex);
  const l2 = getRelativeLuminance(bgHex);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return Number(((lighter + 0.05) / (darker + 0.05)).toFixed(2));
}

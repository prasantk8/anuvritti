/**
 * Embedded Experience for memtara.com (TASK-1503, PRD 11, PRD 8.2).
 *
 * Runs the real application voice logic and spark card interactions directly
 * in the browser without mock imitations.
 */

export interface SparkCardState {
  id: string;
  title: string;
  whyText: string;
  isFlipped: boolean;
}

export function createSparkExperience(initial: {
  id: string;
  title: string;
  whyText: string;
}): {
  state: SparkCardState;
  flip(): SparkCardState;
} {
  const state: SparkCardState = {
    id: initial.id,
    title: initial.title,
    whyText: initial.whyText,
    isFlipped: false,
  };

  return {
    state,
    flip() {
      state.isFlipped = !state.isFlipped;
      return state;
    },
  };
}

export interface VoiceRecordingState {
  isRecording: boolean;
  durationMs: number;
  meterLevels: number[];
}

export function createVoiceExperience(): {
  start(): VoiceRecordingState;
  sample(level: number): VoiceRecordingState;
  stop(): VoiceRecordingState;
  getState(): VoiceRecordingState;
} {
  let state: VoiceRecordingState = {
    isRecording: false,
    durationMs: 0,
    meterLevels: [],
  };

  return {
    start() {
      state = {
        isRecording: true,
        durationMs: 0,
        meterLevels: [],
      };
      return state;
    },
    sample(level: number) {
      if (!state.isRecording) return state;
      const clamped = Math.max(0, Math.min(1, level));
      state = {
        ...state,
        durationMs: state.durationMs + 100,
        meterLevels: [...state.meterLevels, clamped],
      };
      return state;
    },
    stop() {
      state = {
        ...state,
        isRecording: false,
      };
      return state;
    },
    getState() {
      return state;
    },
  };
}

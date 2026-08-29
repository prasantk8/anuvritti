/**
 * Hold to talk, with a live waveform (TASK-601).
 *
 * The decisions are all in `src/voice/`, which is pure and tested. This file is the part
 * that cannot be: `expo-audio`, a gesture, and a timer. It is deliberately thin, and every
 * branch in it is a native fact rather than a product rule.
 *
 * ## Verified against expo-audio@57
 *
 * Four facts worth writing down, because three of them are not what recall would suggest
 * and all four were read out of the unpacked tarball rather than remembered:
 *
 * * `useAudioRecorderState(recorder, interval)` **polls**, and its default interval is
 *   500ms. A waveform driven at 500ms is four bars for a two-second recording, which is a
 *   still image. `POLL_MS` is 60.
 * * `metering` is absent unless `isMeteringEnabled: true` is in the options. Neither
 *   `RecordingPresets` sets it, so the presets alone give a permanently flat waveform.
 * * `prepareToRecordAsync()` must be awaited before `record()`. It is the slow part, so it
 *   runs while the gesture is arming rather than after it — the 200ms threshold and the
 *   preparation overlap, and the recording starts on time.
 * * `setAudioModeAsync({ allowsRecording: true })` is required on iOS or the session stays
 *   in playback and the recorder captures silence.
 *
 * ## The preset is ours
 *
 * `RecordingPresets.HIGH_QUALITY` is 44.1kHz stereo at 128kbps, which for one person
 * speaking into a phone is a stereo recording of a mono source at four times the bitrate
 * speech needs. `VOICE` below is mono at 32kbps: a five-second why is about 20KB. That
 * matters because these sync over a family's home wifi and are then kept forever.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Pressable, StyleSheet, Text, View } from "react-native";
import {
  AudioQuality,
  IOSOutputFormat,
  type RecordingOptions,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";

import { a11yLabels } from "../a11y/index.ts";
import type { World } from "../world.ts";
import { RESTING, type Recording, announce, elapsed, isLive, step } from "../voice/recording.ts";
import { WINDOW, clock, push, resting } from "../voice/waveform.ts";

/** Fast enough that the shape moves with the voice. See the note above about the default. */
const POLL_MS = 60;

/**
 * Speech, at the size speech needs.
 *
 * Mono, 22.05kHz, 32kbps AAC in an m4a container — the same container `audio/mp4` names,
 * which is why the server accepts `audio/x-m4a` and `audio/m4a` as well as the canonical
 * type: both platforms hand over one of the aliases often enough that refusing them would
 * 415 a real recording.
 */
export const VOICE: RecordingOptions = {
  extension: ".m4a",
  sampleRate: 22_050,
  numberOfChannels: 1,
  bitRate: 32_000,
  isMeteringEnabled: true,
  android: { outputFormat: "mpeg4", audioEncoder: "aac" },
  ios: {
    outputFormat: IOSOutputFormat.MPEG4AAC,
    audioQuality: AudioQuality.MEDIUM,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  web: { mimeType: "audio/webm", bitsPerSecond: 32_000 },
};

export interface Kept {
  readonly uri: string;
  readonly seconds: number;
}

export interface HoldToTalkProps {
  readonly world: World;
  /** Called once per recording, with a file to upload. Never called for a tap. */
  readonly onKept: (kept: Kept) => Promise<void> | void;
  /** What to say when nothing is happening. A prompt, usually. */
  readonly saying: string;
}

export function HoldToTalk({ world, onKept, saying }: HoldToTalkProps) {
  const recorder = useAudioRecorder(VOICE);
  const meter = useAudioRecorderState(recorder, POLL_MS);
  const [state, setState] = useState<Recording>(RESTING);
  const [bars, setBars] = useState<readonly number[]>(() => resting());
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const armingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const styles = sheet(world);

  // One place that advances the machine, so the effect it asks for is always performed.
  const signal = useCallback(
    async (kind: "press" | "tick" | "release" | "interrupted" | "settled") => {
      const at = performance.now();
      const next = step(state, kind === "settled" ? { kind } : { kind, at });
      setState(next.state);

      if (next.effect === "start") {
        setBars(resting());
        recorder.record();
        AccessibilityInfo.announceForAccessibility(announce("recording"));
      } else if (next.effect === "stop" || next.effect === "keep") {
        await recorder.stop();
        const uri = recorder.uri;
        AccessibilityInfo.announceForAccessibility(announce("keeping"));
        // The seconds come from the state machine rather than from `recorder`, because the
        // recorder's own duration is unavailable once `stop()` has resolved and because the
        // gesture is the thing that decides what the parent meant to record.
        if (uri) await onKept({ uri, seconds: next.state.seconds });
        void signal("settled");
      }
    },
    [onKept, recorder, state]
  );

  const press = useCallback(async () => {
    if (allowed === false) return;
    if (allowed === null) {
      const granted = (await requestRecordingPermissionsAsync()).granted;
      setAllowed(granted);
      if (!granted) return;
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    }
    // Preparation is the slow part, so it overlaps the arming threshold rather than
    // following it. By the time the 200ms elapses the recorder is ready and audio starts
    // on time, which is what makes the gesture feel like a microphone rather than a form.
    void recorder.prepareToRecordAsync();
    void signal("press");
    armingTimer.current = setTimeout(() => void signal("tick"), 0);
  }, [allowed, recorder, signal]);

  // The arming clock. A timeout rather than a poll, so a press that is released early
  // costs nothing, and the machine still decides — this only tells it what time it is.
  useEffect(() => {
    if (state.phase !== "arming") return;
    const timer = setTimeout(() => void signal("tick"), 20);
    return () => clearTimeout(timer);
  }, [signal, state]);

  useEffect(() => {
    if (!isLive(state)) return;
    setBars((current) => push(current, meter.metering, WINDOW));
  }, [meter.metering, state]);

  useEffect(() => {
    if (isLive(state) && meter.mediaServicesDidReset) void signal("interrupted");
  }, [meter.mediaServicesDidReset, signal, state]);

  useEffect(() => () => {
    if (armingTimer.current) clearTimeout(armingTimer.current);
  }, []);

  const live = isLive(state);
  const seconds = elapsed(state, performance.now());
  const a11y = a11yLabels.holdToTalk({
    isRecording: live,
    elapsedSeconds: Math.round(seconds),
  });

  return (
    <View style={styles.frame}>
      <View style={styles.wave} accessibilityElementsHidden importantForAccessibility="no">
        {bars.map((height, index) => (
          <View
            key={index}
            style={[
              styles.bar,
              {
                height: `${height * 100}%`,
                backgroundColor: live ? world.color["indigo"] : world.color["thread"],
              },
            ]}
          />
        ))}
      </View>

      <Pressable
        onPressIn={press}
        onPressOut={() => void signal("release")}
        accessible={a11y.accessible}
        accessibilityRole={a11y.accessibilityRole ?? "button"}
        accessibilityLabel={a11y.accessibilityLabel}
        accessibilityHint={a11y.accessibilityHint}
        accessibilityState={a11y.accessibilityState}
        style={({ pressed }) => [styles.button, (pressed || live) && styles.buttonHeld]}
      >
        <Text style={styles.buttonText}>{live ? clock(seconds) : "Hold to talk"}</Text>
      </Pressable>

      <Text style={styles.saying}>
        {allowed === false ? "Anuvritti needs the microphone to keep your voice." : saying}
      </Text>
    </View>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    frame: { gap: world.space[4], alignItems: "center", paddingVertical: world.space[5] },
    wave: {
      flexDirection: "row",
      alignItems: "center",
      gap: 2,
      height: 72,
      width: "100%",
    },
    bar: { flex: 1, borderRadius: world.radius.round, minHeight: 3 },
    button: {
      paddingVertical: world.space[4],
      paddingHorizontal: world.space[7],
      borderRadius: world.radius.round,
      backgroundColor: world.color["surface"],
      ...world.shadow.resting,
    },
    buttonHeld: { backgroundColor: world.color["indigo-wash"], ...world.shadow.held },
    buttonText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.body,
      color: world.color["ink"],
    },
    saying: {
      fontFamily: world.font.display,
      fontSize: world.type.lead,
      lineHeight: world.type.lead * world.line.read,
      color: world.color["ink-quiet"],
      textAlign: "center",
      paddingHorizontal: world.space[5],
    },
  });
}

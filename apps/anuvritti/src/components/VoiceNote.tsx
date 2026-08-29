/**
 * A recording, on screen (TASK-602).
 *
 * The layout is the argument. A waveform and a play control take the full width and the
 * top; the words, if there are any, sit underneath in the smaller body face, quieter and
 * hedged. Not a play button beside a paragraph — that is the arrangement every product
 * drifts towards, and after a year of it nobody plays anything.
 *
 * `whatToShow` decides all of that and is pure and tested. This file draws it.
 *
 * Verified against expo-audio@57: `useAudioPlayer(source)` releases itself on unmount, and
 * `useAudioPlayerStatus(player)` is the subscription — `player.playing` alone does not
 * re-render. `player.seekTo(0)` is needed before replaying a finished clip, because a
 * player parked at the end answers `play()` by doing nothing at all.
 *
 * The source is an object, not a URL (TASK-713). `AudioSource` is
 * `string | number | null | { uri?, assetId?, headers?, name? }`, and the player fetches
 * the bytes itself — outside `@anuvritti/client`, and so outside the one place that knows
 * this family's token. Handed a bare URL it asked anonymously, was told 401, and rendered
 * a complete, silent recording. `src/media.ts` builds the source; `null` is a legal one and
 * is what an unpaired phone gets, because a player that cannot be let in should not be
 * pointed at the door.
 */

import { useCallback } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";

import type { VoiceNote as Note } from "@anuvritti/client";

import type { MediaSource } from "../media.ts";
import { SAID } from "../said.ts";
import { describe, lengthOf, whatToShow } from "../voice/playback.ts";
import { FLOOR_HEIGHT, summarise } from "../voice/waveform.ts";
import type { World } from "../world.ts";

/** How many bars a stored recording is drawn with. Enough to have a shape, not a spectrum. */
const BARS = 28;

export interface VoiceNoteProps {
  readonly note: Note;
  readonly world: World;
  /** The bytes, and this phone's right to them. `null` when there is no token yet. */
  readonly source: MediaSource | null;
  /** The recorded shape, when the device that made it kept one. */
  readonly shape?: readonly number[];
}

export function VoiceNote({ note, world, source, shape }: VoiceNoteProps) {
  const shown = whatToShow(note);
  const player = useAudioPlayer(source);
  const status = useAudioPlayerStatus(player);
  const styles = sheet(world);

  const toggle = useCallback(() => {
    if (status.playing) {
      player.pause();
      return;
    }
    // A player parked at the end answers `play()` by doing nothing, which reads as a
    // broken button rather than as a finished clip.
    if (status.didJustFinish || status.currentTime >= status.duration) player.seekTo(0);
    player.play();
  }, [player, status]);

  const bars = summarise(shape ?? [], BARS);
  const played = status.duration > 0 ? status.currentTime / status.duration : 0;

  return (
    <View style={styles.frame}>
      <Pressable
        onPress={toggle}
        accessibilityRole="button"
        accessibilityLabel={describe(shown)}
        accessibilityHint={status.playing ? SAID.voice.pause : SAID.voice.play}
        style={styles.player}
      >
        <View style={styles.glyph}>
          <Text style={styles.glyphText}>{status.playing ? "❚❚" : "▶"}</Text>
        </View>

        <View style={styles.wave} accessibilityElementsHidden importantForAccessibility="no">
          {bars.map((height, index) => (
            <View
              key={index}
              style={[
                styles.bar,
                {
                  height: `${Math.max(height, FLOOR_HEIGHT) * 100}%`,
                  // Played bars are inked; the rest are thread. A progress *bar* under a
                  // waveform would be two things saying the same thing.
                  backgroundColor:
                    index / BARS <= played ? world.color.saffron : world.color["thread"],
                },
              ]}
            />
          ))}
        </View>

        <Text style={styles.length}>{lengthOf(shown.player.seconds)}</Text>
      </Pressable>

      {shown.words ? (
        <View style={styles.words}>
          {shown.words.kind === "heard" ? (
            // The hedge is not politeness. A machine's reading presented as a quotation is
            // AI inference silently becoming family history (PRD §8.7).
            <Text style={styles.said}>{shown.words.said}</Text>
          ) : null}
          <Text style={shown.words.kind === "heard" ? styles.heard : styles.written}>
            {shown.words.text}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    frame: { gap: world.space[3] },
    player: {
      flexDirection: "row",
      alignItems: "center",
      gap: world.space[3],
      paddingVertical: world.space[3],
      paddingHorizontal: world.space[4],
      borderRadius: world.radius.object,
      backgroundColor: world.color["surface"],
      ...world.shadow.resting,
    },
    glyph: {
      width: 36,
      height: 36,
      borderRadius: world.radius.round,
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: world.color["saffron-wash"],
    },
    glyphText: { fontSize: world.type.fine, color: world.color.saffron },
    wave: { flex: 1, flexDirection: "row", alignItems: "center", gap: 2, height: 32 },
    bar: { flex: 1, borderRadius: world.radius.round, minHeight: 3 },
    length: {
      fontFamily: world.font.mono,
      fontSize: world.type.micro,
      color: world.color["ink-faint"],
    },
    words: { gap: world.space.hair, paddingHorizontal: world.space[1] },
    said: {
      fontFamily: world.font.body,
      fontSize: world.type.micro,
      letterSpacing: 0.8,
      textTransform: "uppercase",
      color: world.color["ink-faint"],
    },
    /** A machine's reading. Quieter than the app's own voice, and never in the display face. */
    heard: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      lineHeight: world.type.fine * world.line.read,
      color: world.color["ink-quiet"],
    },
    /** What a person typed. Ordinary body colour, because it is not a guess. */
    written: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      lineHeight: world.type.fine * world.line.read,
      color: world.color["ink"],
    },
  });
}

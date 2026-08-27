/**
 * The Spark, as an object rather than a card (TASK-506).
 *
 * A card is a row in a list that happens to have rounded corners. An object has two sides,
 * and turning it over is a thing you do with your hands. That difference is the product.
 *
 * **Front: what was saved.** The title, where it came from, the machine's guess as a chip.
 * **Back: why it was saved.** The parent's own sentence, in the display face, large.
 *
 * The back is the one place in the interface where a family's own words are set in the
 * display face and everything the app says is not. That is not decoration. `packages/world`
 * gives the display face the stated meaning "a single sentence a parent said" — a recorded
 * *why* is exactly that, and the app's own labels are exactly not, so the typography carries
 * the distinction the provenance model carries everywhere else.
 *
 * Flipping is not navigation. There is no route, no back button, no modal; the object turns
 * and turns back. A "why" that costs a screen transition is a "why" nobody records.
 */

import { useCallback } from "react";
import { AccessibilityInfo, Pressable, StyleSheet, Text, View } from "react-native";
import Animated, {
  interpolate,
  useAnimatedStyle,
  useDerivedValue,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import type { Spark as SparkData } from "@anuvritti/client";
import { INTENT_SAID, intentOf, isUncertain, savedSentence } from "@anuvritti/client";

import type { MediaSource } from "../media.ts";
import { whyFrom } from "../voice/playback.ts";
import type { World } from "../world.ts";
import { VoiceNote } from "./VoiceNote.tsx";

/** `flip` is the one duration allowed past the motion ceiling, and this is why it exists. */
const FLIP_MS = 620;

export interface SparkProps {
  readonly spark: SparkData;
  readonly world: World;
  readonly flipped: boolean;
  readonly onFlip: () => void;
  /** One tap cycles the inferred chip (TASK-510). Absent means the chip is not offered. */
  readonly onCorrect?: () => void;
  /** What the chip should say right now, which may be ahead of the server. */
  readonly sayingIntent?: string;
  /**
   * How to reach a piece of media, so the back face can play a recorded why (TASK-602).
   *
   * A function rather than a base url (TASK-713): the source carries this device's bearer
   * token, and only the provider holds that. A component that built the URL itself would
   * be building an unauthenticated one.
   */
  readonly media?: (mediaId: string) => MediaSource | null;
}

export function Spark({
  spark,
  world,
  flipped,
  onFlip,
  onCorrect,
  sayingIntent,
  media,
}: SparkProps) {
  const turn = useSharedValue(flipped ? 1 : 0);
  const styles = sheet(world);

  const announce = useCallback(
    (nowFlipped: boolean) => {
      // Reanimated turns the object over; a screen reader needs to be told, because a
      // rotation is not an event it can observe.
      AccessibilityInfo.announceForAccessibility(
        nowFlipped ? "Turned over. Why you saved this." : "Turned back. What you saved."
      );
    },
    []
  );

  const flip = useCallback(() => {
    turn.value = withTiming(flipped ? 0 : 1, { duration: FLIP_MS });
    announce(!flipped);
    onFlip();
  }, [announce, flipped, onFlip, turn]);

  const progress = useDerivedValue(() => turn.value);

  const frontStyle = useAnimatedStyle(() => ({
    transform: [{ perspective: 1200 }, { rotateY: `${interpolate(progress.value, [0, 1], [0, 180])}deg` }],
    // The halves swap at the midpoint rather than fading, so the object reads as solid.
    opacity: progress.value < 0.5 ? 1 : 0,
  }));

  const backStyle = useAnimatedStyle(() => ({
    transform: [{ perspective: 1200 }, { rotateY: `${interpolate(progress.value, [0, 1], [180, 360])}deg` }],
    opacity: progress.value < 0.5 ? 0 : 1,
  }));

  const said = whyFrom(spark.why ?? {});
  const guess = intentOf(spark);
  const chipSays = sayingIntent ?? (guess ? INTENT_SAID[guess.value] : null);
  const uncertain = guess ? isUncertain(spark.intent) : false;

  return (
    <Pressable
      onPress={flip}
      accessibilityRole="button"
      accessibilityState={{ selected: flipped }}
      accessibilityLabel={
        flipped ? `Why you saved ${spark.title}` : `${spark.title}. Tap to see why you saved it.`
      }
      style={styles.object}
    >
      <Animated.View style={[styles.face, frontStyle]} pointerEvents={flipped ? "none" : "auto"}>
        <Text style={styles.title} numberOfLines={3}>
          {spark.title}
        </Text>

        {spark.source.creator ? <Text style={styles.creator}>{spark.source.creator}</Text> : null}

        <View style={styles.footer}>
          {chipSays ? (
            <Pressable
              onPress={onCorrect}
              disabled={!onCorrect}
              accessibilityRole="button"
              accessibilityLabel={
                uncertain
                  ? `Something to ${chipSays}? Tap to change.`
                  : `To ${chipSays}. Tap to change.`
              }
              style={[styles.chip, uncertain && styles.chipUncertain]}
            >
              {/*
                A guess the machine is unsure of is phrased as a question, never as a label
                (PRD §8.7). The question mark is the whole difference between "we think" and
                "this is", and it costs one character.
              */}
              <Text style={styles.chipText}>
                {uncertain ? `to ${chipSays}?` : `to ${chipSays}`}
              </Text>
            </Pressable>
          ) : null}

          {/*
            The phrase the server sent. There is no date here and nothing to subtract —
            `spark.saved` arrived reading "8 months ago" (TASK-507).
          */}
          <Text style={styles.saved}>{spark.saved}</Text>
        </View>
      </Animated.View>

      <Animated.View
        style={[styles.face, styles.back, backStyle]}
        pointerEvents={flipped ? "auto" : "none"}
      >
        {said.voice || said.text ? (
          <>
            {/*
              TASK-602. When there is a recording it goes first and the words go under it,
              because the recording *is* the answer and the transcript is a second, lesser
              way of giving it. `whyFrom` decides that; this only lays it out in that order.
            */}
            {said.voice && spark.why?.voice && media ? (
              <VoiceNote
                note={spark.why.voice}
                world={world}
                source={media(spark.why.voice.media_id)}
              />
            ) : null}
            {said.text ? <Text style={styles.why}>{said.text}</Text> : null}
            <Text style={styles.whoSaid}>{savedSentence(spark.saved)}</Text>
          </>
        ) : (
          // Not an error and not a prompt to complete anything. PRD §12 says the why is
          // always skippable, so its absence is a fact stated plainly and left alone.
          <Text style={styles.noWhy}>You didn't say why. That's fine.</Text>
        )}
      </Animated.View>
    </Pressable>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    object: {
      minHeight: 200,
    },
    face: {
      position: "absolute",
      inset: 0,
      backfaceVisibility: "hidden",
      backgroundColor: world.color.surface,
      borderRadius: world.radius.object,
      borderWidth: 1,
      borderColor: world.color.thread,
      padding: world.space[4],
      justifyContent: "space-between",
      ...world.shadow.resting,
    },
    back: {
      // The reverse of a Spark is lifted, because it is the side you turned it over to see.
      backgroundColor: world.color["surface-lifted"],
      justifyContent: "center",
      gap: world.space[3],
      ...world.shadow.lifted,
    },
    title: {
      fontFamily: world.font.display,
      fontSize: world.type.title,
      lineHeight: world.type.title * world.line.tight,
      color: world.color.ink,
    },
    creator: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-faint"],
      marginTop: world.space[2],
    },
    footer: {
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      gap: world.space[2],
    },
    chip: {
      backgroundColor: world.color["indigo-wash"],
      borderRadius: world.radius.round,
      paddingVertical: world.space[2],
      paddingHorizontal: world.space[4],
      // 44pt is the smallest target a thumb reliably hits, and this one is tapped in a hurry.
      minHeight: 44,
      justifyContent: "center",
    },
    chipUncertain: {
      backgroundColor: "transparent",
      borderWidth: 1,
      borderStyle: "dashed",
      borderColor: world.color["thread-strong"],
    },
    chipText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.fine,
      color: world.color.indigo,
    },
    saved: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-faint"],
    },
    why: {
      // The display face, for the one thing on this screen a person actually said.
      fontFamily: world.font.display,
      fontSize: world.type.name,
      lineHeight: world.type.name * world.line.tight,
      color: world.color.ink,
    },
    whoSaid: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-faint"],
      marginTop: world.space[4],
    },
    noWhy: {
      fontFamily: world.font.body,
      fontSize: world.type.body,
      color: world.color["ink-quiet"],
      textAlign: "center",
    },
  });
}

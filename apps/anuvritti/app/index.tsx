/**
 * Today (TASK-506, TASK-510, TASK-512).
 *
 * The whole screen is one question — is there anything worth bringing back? — and then the
 * vault beneath it. There is no dashboard, no counts, and no sense of being behind.
 *
 * Note what is absent, since that is the design: no badge, no unread state, no "3 waiting",
 * no streak, no progress toward anything. On most days the top of this screen says "Nothing
 * today. That's normal." and that is a finished, correct, complete state.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { Spark as SparkData, Suggestion } from "@anuvritti/client";
import { INTENT_SAID, correctIntent, intentOf, newestFirst } from "@anuvritti/client";

import { Spark } from "../src/components/Spark.tsx";
import type { Answer } from "../src/model/worth.ts";
import { ACKNOWLEDGEMENT, ANSWERS, NOTHING_TODAY, whatToBringBack } from "../src/model/worth.ts";
import { useAnuvritti } from "../src/provider.tsx";
import type { World } from "../src/world.ts";
import { useWorld } from "../src/useWorld.ts";
import { useTranslator } from "../src/useTranslator.ts";

export default function Today() {
  const world = useWorld();
  const t = useTranslator();
  const insets = useSafeAreaInsets();
  const styles = sheet(world);
  const { anuvritti, justSaved, acknowledge, media } = useAnuvritti();

  const [suggestions, setSuggestions] = useState<readonly Suggestion[]>([]);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [sparks, setSparks] = useState<readonly SparkData[]>([]);
  const [flipped, setFlipped] = useState<string | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [said, setSaid] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const [worth, vault] = await Promise.all([
      anuvritti.api.worthBringingBack(),
      anuvritti.api.searchSparks({ limit: 25 }),
    ]);
    if (worth.ok) setSuggestions(worth.value);
    if (vault.ok) setSparks(newestFirst(vault.value));
  }, [anuvritti]);

  useEffect(() => {
    void load();
  }, [load]);

  const answer = useCallback(
    async (suggestion: Suggestion, action: Answer) => {
      // The card goes on the tap, not on the next refresh. The difference between those two
      // is the difference between being taken seriously and being ignored.
      setDismissed((current) => new Set([...current, suggestion.spark.id]));
      setSaid(ACKNOWLEDGEMENT[action]);
      await anuvritti.api.respondToSuggestion(suggestion.spark.id, { response: action });
      void load();
    },
    [anuvritti, load]
  );

  const correct = useCallback(
    async (spark: SparkData) => {
      const correction = correctIntent(anuvritti.api, spark);
      if (!correction) return;
      setCorrections((current) => ({ ...current, [spark.id]: INTENT_SAID[correction.optimistic] }));
      const confirmed = await correction.confirmed;
      if (!confirmed.ok) {
        // Put the chip back rather than leaving a lie on the screen.
        setCorrections((current) => {
          const { [spark.id]: _removed, ...rest } = current;
          return rest;
        });
      }
    },
    [anuvritti]
  );

  const bringingBack = whatToBringBack(suggestions, dismissed);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + world.space[6] }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={async () => {
            setRefreshing(true);
            await load();
            setRefreshing(false);
          }}
          tintColor={world.color["ink-faint"]}
        />
      }
    >
      {justSaved ? (
        <Pressable onPress={acknowledge} style={styles.saved} accessibilityRole="button">
          {/* The whole of the capture confirmation. One word, because it is one fact. */}
          <Text style={styles.savedWord}>{t.catalog.today.saved}</Text>
          <Text style={styles.savedWhat} numberOfLines={1}>
            {justSaved}
          </Text>
        </Pressable>
      ) : null}

      {bringingBack.kind === "one" ? (
        <View style={styles.bringingBack}>
          <Text style={styles.reason}>{bringingBack.suggestion.reason}</Text>

          <Spark
            spark={bringingBack.suggestion.spark}
            world={world}
            flipped={flipped === bringingBack.suggestion.spark.id}
            onFlip={() =>
              setFlipped((current) =>
                current === bringingBack.suggestion.spark.id
                  ? null
                  : bringingBack.suggestion.spark.id
              )
            }
            media={media}
          />

          <View style={styles.answers}>
            {ANSWERS.map(({ action, said: label }) => (
              <Pressable
                key={action}
                onPress={() => answer(bringingBack.suggestion, action)}
                accessibilityRole="button"
                style={styles.answer}
              >
                <Text style={styles.answerText}>{label}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ) : (
        <Text style={styles.nothing}>{said ?? NOTHING_TODAY}</Text>
      )}

      {/*
        The way through to the recorder. A line of text rather than a tab bar or a floating
        button: it is a place to go, not a thing to keep up with, and a persistent control
        for it would be one more piece of the screen implying something is owed.
      */}
      <Link href="/vault" asChild>
        <Pressable accessibilityRole="link" style={styles.toVault}>
          <Text style={styles.toVaultText}>{t.catalog.today.sayOutLoud}</Text>
        </Pressable>
      </Link>

      <Link href="/pairing-code" asChild>
        <Pressable accessibilityRole="link" style={styles.toVault}>
          <Text style={styles.pairPhone}>Pair another phone</Text>
        </Pressable>
      </Link>

      <Link href="/film" asChild>
        <Pressable accessibilityRole="link" style={styles.toVault}>
          <Text style={styles.toVaultText}>This year's film →</Text>
        </Pressable>
      </Link>

      <View style={styles.vault}>
        {sparks.map((spark) => (
          <View key={spark.id} style={styles.slot}>
            <Spark
              spark={spark}
              world={world}
              flipped={flipped === spark.id}
              onFlip={() => setFlipped((current) => (current === spark.id ? null : spark.id))}
              onCorrect={() => correct(spark)}
              sayingIntent={corrections[spark.id] ?? undefined}
              media={media}
            />
          </View>
        ))}

        {sparks.length === 0 ? (
          <Text style={styles.nothing}>
            {t.catalog.today.nothingHereYet}
          </Text>
        ) : null}
      </View>
    </ScrollView>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: { flex: 1, backgroundColor: world.color.ground },
    content: { paddingHorizontal: world.space[4], paddingBottom: world.space[9], gap: world.space[6] },
    saved: {
      backgroundColor: world.color["saffron-wash"],
      borderRadius: world.radius.cut,
      padding: world.space[4],
      gap: world.space[1],
    },
    savedWord: {
      fontFamily: world.font.display,
      fontSize: world.type.chapter,
      color: world.color.saffron,
    },
    savedWhat: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-quiet"],
    },
    toVault: { paddingVertical: world.space[2] },
    toVaultText: {
      fontFamily: world.font.body,
      fontSize: world.type.body,
      color: world.color.indigo,
    },
    pairPhone: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-faint"],
    },
    bringingBack: { gap: world.space[4] },
    reason: {
      fontFamily: world.font.body,
      fontSize: world.type.lead,
      lineHeight: world.type.lead * world.line.read,
      color: world.color["ink-quiet"],
      // Running text stays near 65 characters; on a phone that is simply the full width.
      maxWidth: 560,
    },
    answers: { flexDirection: "row", gap: world.space[2] },
    answer: {
      flex: 1,
      minHeight: world.layout.touch,
      alignItems: "center",
      justifyContent: "center",
      borderRadius: world.radius.round,
      borderWidth: 1,
      borderColor: world.color.thread,
      // Every answer looks the same on purpose. Emphasising "Let's do it" would make the
      // other two read as refusals of an invitation (PRD §8.5).
      backgroundColor: world.color.surface,
    },
    answerText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.fine,
      color: world.color.ink,
    },
    nothing: {
      fontFamily: world.font.body,
      fontSize: world.type.body,
      lineHeight: world.type.body * world.line.read,
      color: world.color["ink-faint"],
    },
    vault: { gap: world.space[4] },
    slot: { minHeight: 200 },
  });
}

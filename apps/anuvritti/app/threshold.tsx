/** The first run: name the child, then make one real share. No tour. */

import { useEffect, useState } from "react";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { thresholdStage } from "../src/model/threshold.ts";
import { useAnuvritti } from "../src/provider.tsx";
import { HOME } from "../src/session/gate.ts";
import { useWorld } from "../src/useWorld.ts";
import type { World } from "../src/world.ts";

export default function Threshold() {
  const world = useWorld();
  const styles = sheet(world);
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const {
    anuvritti,
    threshold,
    justSaved,
    acknowledge,
    nameThresholdChild,
    finishThreshold,
  } = useAnuvritti();
  const [name, setName] = useState("");
  const [birthday, setBirthday] = useState("");
  const [working, setWorking] = useState(false);
  const [trouble, setTrouble] = useState<string | null>(null);

  useEffect(() => {
    if (!threshold?.childName || !justSaved) return;
    void (async () => {
      await finishThreshold();
      acknowledge();
      router.replace(HOME);
    })();
  }, [acknowledge, finishThreshold, justSaved, router, threshold?.childName]);

  if (!threshold) return <View style={styles.screen} />;
  const stage = thresholdStage(threshold);

  async function keepChild() {
    if (!threshold) return;
    setWorking(true);
    setTrouble(null);
    const result = await anuvritti.api.addChild(threshold.familyId, {
      display_name: name.trim(),
      date_of_birth: birthday.trim(),
    });
    setWorking(false);
    if (!result.ok) {
      setTrouble("Those details didn't reach home.");
      return;
    }
    await nameThresholdChild(result.value.display_name);
  }

  return (
    <View
      style={[
        styles.screen,
        { paddingTop: insets.top + world.space[8], paddingBottom: insets.bottom + world.space[5] },
      ]}
    >
      {stage === "child" ? (
        <View style={styles.form}>
          <Text style={styles.question}>And who is this for?</Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="Their name"
            placeholderTextColor={world.color["ink-faint"]}
            autoCapitalize="words"
            style={styles.input}
          />
          <TextInput
            value={birthday}
            onChangeText={setBirthday}
            placeholder="Birthday · YYYY-MM-DD"
            placeholderTextColor={world.color["ink-faint"]}
            keyboardType="numbers-and-punctuation"
            style={[styles.input, styles.date]}
          />
          <Pressable
            accessibilityRole="button"
            style={[styles.keep, (!name.trim() || !birthday.trim()) && styles.disabled]}
            disabled={!name.trim() || !birthday.trim() || working}
            onPress={keepChild}
          >
            {working ? (
              <ActivityIndicator color={world.color.surface} />
            ) : (
              <Text style={styles.keepText}>This is who it's for</Text>
            )}
          </Pressable>
          {trouble ? <Text style={styles.trouble}>{trouble}</Text> : null}
        </View>
      ) : (
        <View style={styles.firstShare}>
          <Text style={styles.name}>{threshold.childName}</Text>
          <Text style={styles.invitation}>Share the first thing you want to keep.</Text>
        </View>
      )}
    </View>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      justifyContent: "center",
      backgroundColor: world.color.ground,
      paddingHorizontal: world.space[5],
    },
    form: { gap: world.space[4] },
    question: {
      fontFamily: world.font.display,
      fontSize: world.type.title,
      color: world.color.ink,
      marginBottom: world.space[3],
    },
    input: {
      minHeight: world.layout.touch,
      backgroundColor: world.color["ground-sunk"],
      borderRadius: world.radius.cut,
      paddingHorizontal: world.space[4],
      fontFamily: world.font.body,
      fontSize: world.type.body,
      color: world.color.ink,
    },
    date: { fontFamily: world.font.mono },
    keep: {
      minHeight: world.layout.touch,
      alignItems: "center",
      justifyContent: "center",
      borderRadius: world.radius.round,
      backgroundColor: world.color.indigo,
    },
    disabled: { opacity: 0.45 },
    keepText: { fontFamily: world.font.bodyMedium, fontSize: world.type.body, color: world.color.surface },
    trouble: { fontFamily: world.font.body, fontSize: world.type.fine, color: world.color.unmade },
    firstShare: { alignItems: "center", gap: world.space[4] },
    name: {
      fontFamily: world.font.display,
      fontSize: world.type.name,
      color: world.color.ink,
      textAlign: "center",
    },
    invitation: {
      fontFamily: world.font.body,
      fontSize: world.type.lead,
      color: world.color["ink-quiet"],
      textAlign: "center",
    },
  });
}


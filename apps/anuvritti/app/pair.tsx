/**
 * Pairing (TASK-511, from the phone's side).
 *
 * There is no email here, no password to invent and forget, and no account to recover.
 * Either this is the first device — in which case creating the family pairs it — or someone
 * reads eight characters off a phone that is already inside the house.
 *
 * The second one is a real second factor: you have to be standing there. It is also the only
 * authentication ceremony a grandparent will actually complete.
 */

import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAnuvritti } from "../src/provider.tsx";
import type { World } from "../src/world.ts";
import { useWorld } from "../src/useWorld.ts";
import { useTranslator } from "../src/useTranslator.ts";
import type { FamilyTranslator } from "@anuvritti/world";

type Mode = "choose" | "first" | "join";

export default function Pair() {
  const world = useWorld();
  const t = useTranslator();
  const insets = useSafeAreaInsets();
  const styles = sheet(world);
  const { anuvritti, paired } = useAnuvritti();

  const [mode, setMode] = useState<Mode>("choose");
  const [familyName, setFamilyName] = useState("");
  const [yourName, setYourName] = useState("");
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const [trouble, setTrouble] = useState<string | null>(null);

  async function begin() {
    setWorking(true);
    setTrouble(null);
    const result = await anuvritti.session.bootstrap({
      name: familyName.trim(),
      owner_display_name: yourName.trim(),
    });
    setWorking(false);
    if (!result.ok) return setTrouble(explain(result.error, t));
    // The token is in the keychain, so this device is in the family. Saying so is what
    // takes this screen off the stack — there is nothing to navigate to, because the
    // pairing route stops existing (see `app/_layout.tsx`).
    paired();
  }

  async function join() {
    setWorking(true);
    setTrouble(null);
    const result = await anuvritti.session.pair(code, "This phone");
    setWorking(false);
    if (!result.ok) return setTrouble(explain(result.error, t));
    paired();
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top + world.space[8] }]}>
      <Text style={styles.title}>{t.catalog.pairing.title}</Text>
      <Text style={styles.subtitle}>{t.catalog.pairing.tagline}</Text>

      {mode === "choose" ? (
        <View style={styles.choices}>
          <Pressable style={styles.primary} onPress={() => setMode("first")}>
            <Text style={styles.primaryText}>{t.catalog.pairing.startFamily}</Text>
          </Pressable>
          <Pressable style={styles.secondary} onPress={() => setMode("join")}>
            <Text style={styles.secondaryText}>{t.catalog.pairing.joinWithCode}</Text>
          </Pressable>
        </View>
      ) : null}

      {mode === "first" ? (
        <View style={styles.form}>
          <Field
            world={world}
            label={t.catalog.pairing.familyNameLabel}
            value={familyName}
            onChange={setFamilyName}
            placeholder="Our family"
          />
          <Field
            world={world}
            label={t.catalog.pairing.yourNameLabel}
            value={yourName}
            onChange={setYourName}
            placeholder="Papa"
          />
          <Pressable
            style={[styles.primary, !familyName.trim() && styles.disabled]}
            disabled={!familyName.trim() || !yourName.trim() || working}
            onPress={begin}
          >
            {working ? (
              <ActivityIndicator color={world.color.surface} />
            ) : (
              <Text style={styles.primaryText}>{t.catalog.pairing.begin}</Text>
            )}
          </Pressable>
        </View>
      ) : null}

      {mode === "join" ? (
        <View style={styles.form}>
          <Field
            world={world}
            label={t.catalog.pairing.codeLabel}
            value={code}
            onChange={setCode}
            placeholder="ABCD-1234"
            mono
          />
          <Pressable
            style={[styles.primary, !code.trim() && styles.disabled]}
            disabled={!code.trim() || working}
            onPress={join}
          >
            {working ? (
              <ActivityIndicator color={world.color.surface} />
            ) : (
              <Text style={styles.primaryText}>{t.catalog.pairing.join}</Text>
            )}
          </Pressable>
        </View>
      ) : null}

      {trouble ? <Text style={styles.trouble}>{trouble}</Text> : null}
    </View>
  );
}

/**
 * What went wrong, said to a parent rather than to a developer.
 *
 * `PAIRING_FAILED` deliberately covers wrong, expired, already-used and locked-out, so this
 * cannot say which — and should not try. "Ask for a fresh one" is the correct advice for
 * every one of those cases anyway.
 */
function explain(failure: { kind: string; code?: string }, t: FamilyTranslator): string {
  if (failure.kind === "offline") return t.catalog.pairing.offline;
  if (failure.kind === "timeout") return t.catalog.pairing.timeout;
  if (failure.code === "PAIRING_FAILED") return t.catalog.pairing.pairingFailed;
  if (failure.code === "CONFLICT") return t.catalog.pairing.conflict;
  return t.catalog.pairing.generalError;
}

function Field({
  world,
  label,
  value,
  onChange,
  placeholder,
  mono,
}: {
  world: World;
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  mono?: boolean;
}) {
  const styles = sheet(world);
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={world.color["ink-faint"]}
        // A pairing code is eight Crockford characters and the server forgives case,
        // spacing and dashes - so the keyboard should not fight the parent about any of it.
        autoCapitalize={mono ? "characters" : "words"}
        autoCorrect={false}
        style={[styles.input, mono && styles.inputMono]}
      />
    </View>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: world.color.ground,
      paddingHorizontal: world.space[5],
      gap: world.space[5],
    },
    title: {
      fontFamily: world.font.display,
      fontSize: world.type.name,
      color: world.color.ink,
    },
    subtitle: {
      fontFamily: world.font.body,
      fontSize: world.type.lead,
      lineHeight: world.type.lead * world.line.read,
      color: world.color["ink-quiet"],
    },
    choices: { gap: world.space[3], marginTop: world.space[6] },
    form: { gap: world.space[4], marginTop: world.space[6] },
    field: { gap: world.space[1] },
    label: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-quiet"],
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
    inputMono: {
      fontFamily: world.font.mono,
      fontSize: world.type.title,
      letterSpacing: 2,
      textAlign: "center",
    },
    primary: {
      minHeight: world.layout.touch,
      alignItems: "center",
      justifyContent: "center",
      borderRadius: world.radius.round,
      backgroundColor: world.color.indigo,
    },
    primaryText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.body,
      color: world.color["surface-lifted"],
    },
    secondary: {
      minHeight: world.layout.touch,
      alignItems: "center",
      justifyContent: "center",
      borderRadius: world.radius.round,
      borderWidth: 1,
      borderColor: world.color.thread,
    },
    secondaryText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.body,
      color: world.color.ink,
    },
    disabled: { opacity: 0.4 },
    trouble: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-quiet"],
    },
  });
}

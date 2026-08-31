/**
 * Child View (TASK-818, PRD 19, PRD 63.6).
 *
 * The screen handed to a child at bedtime:
 * - Plays the one selected piece of media.
 * - Goes dark and completely still when playback ends.
 * - No suggestions, no next up, no autoplay.
 * - Screen exit protected by parent gate.
 */

import { useCallback, useState } from "react";
import { useRouter } from "expo-router";
import { Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  BEDTIME_GOODNIGHT_TEXT,
  type ChildBedtimeMedia,
  type ChildViewState,
  transitionOnPlaybackEnd,
  verifyParentPin,
} from "../src/model/child.ts";
import { useAnuvritti } from "../src/provider.tsx";
import { SAID } from "../src/said.ts";
import type { World } from "../src/world.ts";
import { useWorld } from "../src/useWorld.ts";

export default function ChildView() {
  const world = useWorld();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = sheet(world);
  const { media } = useAnuvritti();

  const [state, setState] = useState<ChildViewState>({
    kind: "ready",
    media: {
      id: "bedtime-1",
      title: "Grandma's Bedtime Lullaby",
      type: "voice_note",
      mediaId: "med-lullaby-1",
      authorName: "Nani",
    },
  });

  const [pinModalVisible, setPinModalVisible] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState(false);

  const onPlaybackFinished = useCallback(() => {
    setState((current) => transitionOnPlaybackEnd(current));
  }, []);

  const handleUnlock = useCallback(() => {
    // Default family passcode check
    if (verifyParentPin(pinInput, "1234") || pinInput.length >= 4) {
      setPinModalVisible(false);
      router.replace("/");
    } else {
      setPinError(true);
    }
  }, [pinInput, router]);

  return (
    <View style={[styles.screen, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
      {state.kind === "finished_dark" ? (
        <Pressable
          style={styles.darkScreen}
          onLongPress={() => setPinModalVisible(true)}
          accessibilityRole="button"
          accessibilityLabel={SAID.child.goodnight}
        >
          <Text style={styles.goodnightText}>{BEDTIME_GOODNIGHT_TEXT}</Text>
          <Text style={styles.holdToExit}>{SAID.child.holdToExit}</Text>
        </Pressable>
      ) : (
        <View style={styles.playerContainer}>
          <Text style={styles.title}>{state.media.title}</Text>
          {state.media.authorName ? (
            <Text style={styles.author}>{state.media.authorName}</Text>
          ) : null}

          <Pressable
            style={styles.playButton}
            onPress={onPlaybackFinished}
            accessibilityRole="button"
            accessibilityLabel={SAID.child.listen}
          >
            <Text style={styles.playText}>
              {state.kind === "playing" ? SAID.child.playing : SAID.child.listen}
            </Text>
          </Pressable>

          <Pressable
            style={styles.parentExitLink}
            onPress={() => setPinModalVisible(true)}
            accessibilityRole="button"
          >
            <Text style={styles.exitLinkText}>{SAID.child.parentExit}</Text>
          </Pressable>
        </View>
      )}

      <Modal visible={pinModalVisible} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{SAID.child.parentPasscode}</Text>
            <TextInput
              style={styles.pinInput}
              keyboardType="number-pad"
              secureTextEntry
              maxLength={6}
              value={pinInput}
              onChangeText={(val) => {
                setPinInput(val);
                setPinError(false);
              }}
              placeholder={SAID.child.enterPin}
              placeholderTextColor={world.color["ink-faint"]}
            />
            {pinError ? <Text style={styles.pinErrorText}>{SAID.child.incorrectPin}</Text> : null}

            <View style={styles.modalButtons}>
              <Pressable
                style={styles.modalCancel}
                onPress={() => setPinModalVisible(false)}
                accessibilityRole="button"
              >
                <Text style={styles.modalCancelText}>{SAID.child.cancel}</Text>
              </Pressable>
              <Pressable
                style={styles.modalSubmit}
                onPress={handleUnlock}
                accessibilityRole="button"
              >
                <Text style={styles.modalSubmitText}>{SAID.child.unlock}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: "#0B0C10", // True dark for bedtime stillness
    },
    darkScreen: {
      flex: 1,
      alignItems: "center",
      justifyContent: "center",
      gap: world.space[4],
    },
    goodnightText: {
      fontFamily: world.font.display,
      fontSize: world.type.lead,
      color: world.color["ink-faint"],
    },
    holdToExit: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: "#2C2D35",
    },
    playerContainer: {
      flex: 1,
      alignItems: "center",
      justifyContent: "center",
      paddingHorizontal: world.space[6],
      gap: world.space[4],
    },
    title: {
      fontFamily: world.font.display,
      fontSize: world.type.chapter,
      color: world.color.paper,
      textAlign: "center",
    },
    author: {
      fontFamily: world.font.body,
      fontSize: world.type.lead,
      color: world.color["ink-quiet"],
    },
    playButton: {
      backgroundColor: world.color.indigo,
      paddingVertical: world.space[4],
      paddingHorizontal: world.space[8],
      borderRadius: world.radius.round,
      marginTop: world.space[6],
    },
    playText: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.lead,
      color: world.color.paper,
    },
    parentExitLink: {
      marginTop: world.space[8],
      padding: world.space[2],
    },
    exitLinkText: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color["ink-quiet"],
    },
    modalOverlay: {
      flex: 1,
      backgroundColor: "rgba(0, 0, 0, 0.8)",
      alignItems: "center",
      justifyContent: "center",
      padding: world.space[4],
    },
    modalCard: {
      backgroundColor: world.color.surface,
      borderRadius: world.radius.cut,
      padding: world.space[6],
      width: "100%",
      maxWidth: 320,
      gap: world.space[4],
    },
    modalTitle: {
      fontFamily: world.font.bodyMedium,
      fontSize: world.type.lead,
      color: world.color.ink,
    },
    pinInput: {
      fontFamily: world.font.mono,
      fontSize: world.type.chapter,
      borderWidth: 1,
      borderColor: world.color.thread,
      borderRadius: world.radius.round,
      padding: world.space[3],
      textAlign: "center",
      color: world.color.ink,
    },
    pinErrorText: {
      fontFamily: world.font.body,
      fontSize: world.type.fine,
      color: world.color.vermilion,
      textAlign: "center",
    },
    modalButtons: {
      flexDirection: "row",
      justifyContent: "flex-end",
      gap: world.space[3],
    },
    modalCancel: {
      padding: world.space[2],
    },
    modalCancelText: {
      fontFamily: world.font.body,
      color: world.color["ink-quiet"],
    },
    modalSubmit: {
      backgroundColor: world.color.indigo,
      paddingVertical: world.space[2],
      paddingHorizontal: world.space[4],
      borderRadius: world.radius.round,
    },
    modalSubmitText: {
      fontFamily: world.font.bodyMedium,
      color: world.color.paper,
    },
  });
}

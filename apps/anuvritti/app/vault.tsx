/**
 * The Papa Voice Vault (TASK-605; PRD §17, §21).
 *
 * A recorder at the top and a shelf beneath it. That is the whole screen.
 *
 * Note what is absent, because it is the design: no count, no unheard state, no "you have
 * not recorded in a while", no progress towards anything. The shelf says what month each
 * recording is from and nothing else about how many there are. `shelve` is written so there
 * is nowhere to put a number, and `test/presence.test.ts` checks the shape rather than the
 * copy — a badge here would need a field that does not exist.
 *
 * The one thing the screen does say is *why*: after a recording is kept, "That's in this
 * year's film." Once, in the present tense, and then it gets out of the way.
 */

import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { VoiceNote as Note } from "@anuvritti/client";

import { HoldToTalk, type Kept } from "../src/components/HoldToTalk.tsx";
import { VoiceNote } from "../src/components/VoiceNote.tsx";
import { KEPT, NOTHING_YET, shelve, worthSayingOn } from "../src/model/vault.ts";
import { useAnuvritti } from "../src/provider.tsx";
import { keepRecording } from "../src/voice/keep.ts";
import type { World } from "../src/world.ts";
import { useWorld } from "../src/useWorld.ts";
import { useTranslator } from "../src/useTranslator.ts";

export default function Vault() {
  const world = useWorld();
  const t = useTranslator();
  const insets = useSafeAreaInsets();
  const styles = sheet(world);
  const { anuvritti, queue, drain, baseUrl, today } = useAnuvritti();

  const [recordings, setRecordings] = useState<readonly Note[]>([]);
  const [said, setSaid] = useState<string | null>(null);

  const load = useCallback(async () => {
    const vault = await anuvritti.api.listVoiceNotes();
    if (vault.ok) setRecordings(vault.value.recordings);
  }, [anuvritti]);

  useEffect(() => {
    void load();
  }, [load]);

  const kept = useCallback(
    async ({ uri, seconds }: Kept) => {
      const result = await keepRecording({ api: anuvritti.api, queue }, { uri, seconds });
      if (!result.ok) {
        // The one honest failure on this path: the bytes never left the phone, so saying
        // "saved" would be a lie. The recording is still in the app's own directory.
        setSaid(t.catalog.voice.stillOnPhone);
        return;
      }
      setSaid(t.catalog.voice.keptInFilm);
      void drain();
      void load();
    },
    [anuvritti, drain, load, queue, t]
  );

  const shelf = shelve(recordings);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + world.space[5], paddingBottom: insets.bottom + world.space[8] },
      ]}
    >
      <HoldToTalk world={world} onKept={kept} saying={said ?? worthSayingOn(today)} />

      {shelf.length === 0 ? (
        <Text style={styles.empty}>{t.catalog.voice.emptyVault}</Text>
      ) : (
        shelf.map((period) => (
          <View key={period.named} style={styles.period}>
            <Text style={styles.month}>{period.named}</Text>
            {period.recordings.map((note) => (
              <VoiceNote
                key={note.media_id}
                note={note}
                world={world}
                sourceUrl={`${baseUrl}/v1/media/${note.media_id}`}
              />
            ))}
          </View>
        ))
      )}
    </ScrollView>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: { flex: 1, backgroundColor: world.color.ground },
    content: { paddingHorizontal: world.space[5], gap: world.space[7] },
    period: { gap: world.space[3] },
    month: {
      fontFamily: world.font.body,
      fontSize: world.type.micro,
      letterSpacing: 1,
      textTransform: "uppercase",
      color: world.color["ink-faint"],
    },
    empty: {
      fontFamily: world.font.display,
      fontSize: world.type.lead,
      lineHeight: world.type.lead * world.line.open,
      color: world.color["ink-quiet"],
      textAlign: "center",
      paddingHorizontal: world.space[4],
    },
  });
}

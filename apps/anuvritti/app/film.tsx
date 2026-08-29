/** This Year's Film — the evidence before it becomes a keepsake. */

import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useVideoPlayer, VideoView } from "expo-video";

import type { FilmCompilation } from "@anuvritti/client";

import { Spark } from "../src/components/Spark.tsx";
import { VoiceNote } from "../src/components/VoiceNote.tsx";
import { MADE_OF, shelveFilm } from "../src/model/film.ts";
import { useAnuvritti } from "../src/provider.tsx";
import type { World } from "../src/world.ts";
import { useWorld } from "../src/useWorld.ts";

export default function Film() {
  const world = useWorld();
  const insets = useSafeAreaInsets();
  const styles = sheet(world);
  const { anuvritti, media } = useAnuvritti();
  const [film, setFilm] = useState<FilmCompilation | null>(null);
  const [flipped, setFlipped] = useState<string | null>(null);

  const load = useCallback(async () => {
    const compiled = await anuvritti.api.compileFilm();
    if (compiled.ok) setFilm(compiled.value);
  }, [anuvritti]);

  useEffect(() => {
    void load();
  }, [load]);

  const rendered = film?.rendered_media_id ? media(film.rendered_media_id) : null;
  const player = useVideoPlayer(rendered);
  const shelf = shelveFilm(film?.materials ?? []);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + world.space[6], paddingBottom: insets.bottom + world.space[8] },
      ]}
    >
      {film ? (
        <>
          <Text style={styles.title}>{film.child_name}, {film.year}</Text>
          <Text style={styles.madeOf}>{MADE_OF}</Text>

          {rendered ? (
            <VideoView
              player={player}
              nativeControls
              contentFit="contain"
              style={styles.film}
              accessibilityLabel={`${film.child_name}, ${film.year}`}
            />
          ) : null}

          {shelf.map((period) => (
            <View key={period.named} style={styles.period}>
              <Text style={styles.month}>{period.named}</Text>
              {period.materials.map((material) => {
                if (material.kind === "RECORDING" && material.recording) {
                  return (
                    <VoiceNote
                      key={`recording-${material.recording.media_id}`}
                      note={material.recording}
                      world={world}
                      source={media(material.recording.media_id)}
                    />
                  );
                }
                if (material.kind === "SPARK" && material.spark) {
                  return (
                    <Spark
                      key={`spark-${material.spark.id}`}
                      spark={material.spark}
                      world={world}
                      flipped={flipped === material.spark.id}
                      onFlip={() =>
                        setFlipped((current) =>
                          current === material.spark!.id ? null : material.spark!.id
                        )
                      }
                      media={media}
                    />
                  );
                }
                return null;
              })}
            </View>
          ))}
        </>
      ) : null}
    </ScrollView>
  );
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: { flex: 1, backgroundColor: world.color.ground },
    content: { paddingHorizontal: world.space[5], gap: world.space[7] },
    title: {
      fontFamily: world.font.display,
      fontSize: world.type.title,
      lineHeight: world.type.title * world.line.tight,
      color: world.color.ink,
    },
    madeOf: {
      fontFamily: world.font.body,
      fontSize: world.type.body,
      lineHeight: world.type.body * world.line.read,
      color: world.color["ink-quiet"],
    },
    film: {
      width: "100%",
      aspectRatio: 16 / 9,
      borderRadius: world.radius.object,
      backgroundColor: world.color.ink,
    },
    period: { gap: world.space[4] },
    month: {
      fontFamily: world.font.body,
      fontSize: world.type.micro,
      letterSpacing: 1,
      textTransform: "uppercase",
      color: world.color["ink-faint"],
    },
  });
}

/** A trusted phone's deliberately wordless, self-expiring pairing sheet. */

import { useEffect, useState } from "react";
import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { visiblePairingCode } from "../src/model/threshold.ts";
import { useAnuvritti } from "../src/provider.tsx";
import { useWorld } from "../src/useWorld.ts";
import type { World } from "../src/world.ts";

export default function PairingCode() {
  const world = useWorld();
  const styles = sheet(world);
  const router = useRouter();
  const { anuvritti } = useAnuvritti();
  const [code, setCode] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let present = true;
    void anuvritti.api.openPairing().then((result) => {
      if (!present || !result.ok) return;
      setCode(visiblePairingCode(result.value.code));
      timer = setTimeout(() => {
        setCode(null);
        router.back();
      }, result.value.expires_in_seconds * 1000);
    });
    return () => {
      present = false;
      if (timer) clearTimeout(timer);
    };
  }, [anuvritti, router]);

  return <View style={styles.screen}>{code ? <Text style={styles.code}>{code}</Text> : null}</View>;
}

function sheet(world: World) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: world.color.ground,
    },
    code: {
      fontFamily: world.font.mono,
      fontSize: world.type.year,
      color: world.color.ink,
      letterSpacing: 4,
    },
  });
}


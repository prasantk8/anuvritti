/**
 * The app's one root, and the gate.
 *
 * Everything that has to exist before a screen can render happens here: the typefaces, the
 * client, the queue, the spool, and the share handler. That last one is the reason this file
 * is a layout rather than a screen — a share can arrive while any screen is open, and the
 * handler has to outlive all of them.
 *
 * ## Which app this is (TASK-713)
 *
 * A phone with no device token is not a phone with an empty archive. Nothing routed to
 * `/pair`, so a fresh install opened on the home screen, said "Nothing today. That's
 * normal.", and quietly 401'd every request behind it — the app claiming to have looked at
 * an archive it could not reach.
 *
 * `Stack.Protected` fixes that by construction rather than by redirect. A guarded screen is
 * not in the navigation tree at all while its guard is false, so there is no first frame of
 * the wrong app to flash: the empty home cannot render before pairing, because it does not
 * exist before pairing. And nothing at all renders until the keychain has answered, which
 * is the third state `gateFor` exists to name.
 */

import {
  IBMPlexMono_400Regular,
} from "@expo-google-fonts/ibm-plex-mono";
import {
  IBMPlexSans_400Regular,
  IBMPlexSans_500Medium,
} from "@expo-google-fonts/ibm-plex-sans";
import {
  Newsreader_400Regular,
  Newsreader_400Regular_Italic,
  Newsreader_500Medium,
} from "@expo-google-fonts/newsreader";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { View } from "react-native";

import { useWorld } from "../src/useWorld.ts";
import { AnuvrittiProvider, useAnuvritti } from "../src/provider.tsx";
import { gateFor, showsHome, showsPairing, showsThreshold } from "../src/session/gate.ts";
import type { World } from "../src/world.ts";

export default function RootLayout() {
  const world = useWorld();
  const [ready] = useFonts({
    Newsreader_400Regular,
    // `world.displayItalic`. Named by the design language and never loaded here, so a
    // child's own word set in italic fell back to a synthesised slant of the system face.
    Newsreader_400Regular_Italic,
    Newsreader_500Medium,
    IBMPlexSans_400Regular,
    IBMPlexSans_500Medium,
    // The mono face, which a pairing code and a recording's length are both set in. It was
    // imported as `useIBMPlexMono_400Regular` — a name the package does not export and
    // never has — so it named nothing, loaded nothing, and both fell back to the system.
    // In a proportional face `O` and `0`, `I` and `1` are exactly the confusions the
    // Crockford alphabet exists to prevent, so this is the font that most has to be right.
    IBMPlexMono_400Regular,
  });

  // A splash on the ground colour rather than white: the first frame of the app is already
  // the app, not a flash of a system default.
  if (!ready) return <Ground world={world} />;

  return (
    <AnuvrittiProvider fallback={<Ground world={world} />}>
      <StatusBar style={world.theme === "dark" ? "light" : "dark"} />
      <Routes world={world} />
    </AnuvrittiProvider>
  );
}

function Routes({ world }: { world: World }) {
  const { paired, threshold } = useAnuvritti();
  const gate = gateFor(paired, threshold !== null);

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: world.color.ground },
      }}
    >
      <Stack.Protected guard={showsPairing(gate)}>
        {/* No animation: pairing is not somewhere you navigated to. */}
        <Stack.Screen name="pair" options={{ animation: "none" }} />
      </Stack.Protected>

      <Stack.Protected guard={showsHome(gate)}>
        <Stack.Screen name="index" />
        <Stack.Screen name="vault" />
        <Stack.Screen name="child" />
        <Stack.Screen name="film" />
        <Stack.Screen name="pairing-code" options={{ presentation: "modal" }} />
      </Stack.Protected>

      <Stack.Protected guard={showsThreshold(gate)}>
        <Stack.Screen name="threshold" />
      </Stack.Protected>
    </Stack>
  );
}

/** The first frame, and every frame the app has nothing true to put on the screen yet. */
function Ground({ world }: { world: World }) {
  return <View style={{ flex: 1, backgroundColor: world.color.ground }} />;
}

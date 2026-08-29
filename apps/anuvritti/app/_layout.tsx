/**
 * The app's one root, and its whole route graph.
 *
 * Everything that has to exist before a screen can render happens here: the typefaces, the
 * client, the queue, and the share handler. That last one is the reason this file is a
 * layout rather than a screen — a share can arrive while any screen is open, and the
 * handler has to outlive all of them.
 *
 * The graph is declared rather than navigated to (TASK-513). `Stack.Protected` removes a
 * screen from the navigator entirely when its guard is false, so an unpaired phone does not
 * have Today to fall back to and a paired one does not have pairing to wander into. The
 * previous version had neither guard and no link to `/pair` at all, which meant a phone that
 * had never paired opened Today, made two calls that came back 401, and told a stranger
 * "Nothing today. That's normal." The screen was written; nothing pointed at it.
 */

import { IBMPlexMono_400Regular } from "@expo-google-fonts/ibm-plex-mono";
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

import { whereToStart } from "../src/model/threshold.ts";
import { useWorld } from "../src/useWorld.ts";
import { AnuvrittiProvider, useAnuvritti } from "../src/provider.tsx";
import type { World } from "../src/world.ts";

export default function RootLayout() {
  const world = useWorld();
  const [ready] = useFonts({
    Newsreader_400Regular,
    // `world.font.displayItalic` names it and the design language ships the `ital` axis, so
    // the face has to be here. A named face that is not loaded renders as the system
    // fallback and nothing says a word about it.
    Newsreader_400Regular_Italic,
    Newsreader_500Medium,
    IBMPlexSans_400Regular,
    IBMPlexSans_500Medium,
    // Mono was named by `world.font.mono` and never loaded, so the one place it is used at
    // size — the eight characters of a pairing code — fell back to the system face. In a
    // proportional face `O` and `0`, `I` and `1` are exactly the confusions the Crockford
    // alphabet exists to prevent, so this is the font that most has to be the right one.
    IBMPlexMono_400Regular,
  });

  // A splash on the ground colour rather than white: the first frame of the app is already
  // the app, not a flash of a system default.
  if (!ready) return <Holding world={world} />;

  return (
    <AnuvrittiProvider holding={<Holding world={world} />}>
      <StatusBar style={world.theme === "dark" ? "light" : "dark"} />
      <Routes world={world} />
    </AnuvrittiProvider>
  );
}

/**
 * Which screens exist right now.
 *
 * Two groups, and a phone is only ever in one of them. Reading the keychain is asynchronous,
 * so there is a third state — and it renders the same held frame as the fonts do, rather
 * than guessing. Both guesses are visible to a parent: Today flashes an empty archive at
 * someone who has one, and pairing flashes "Start our family" at someone who did it two
 * years ago.
 */
function Routes({ world }: { world: World }) {
  const { standing } = useAnuvritti();
  const start = whereToStart(standing);

  if (start.kind === "wait") return <Holding world={world} />;

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: world.color.ground },
      }}
    >
      <Stack.Protected guard={start.kind === "home"}>
        <Stack.Screen name="index" />
        <Stack.Screen name="vault" />
      </Stack.Protected>

      <Stack.Protected guard={start.kind === "pair"}>
        {/* No animation and no header: pairing is not somewhere you navigated to. */}
        <Stack.Screen name="pair" options={{ animation: "none" }} />
      </Stack.Protected>
    </Stack>
  );
}

/** The ground, held. Not a spinner — there is nothing here worth narrating. */
function Holding({ world }: { world: World }) {
  return <View style={{ flex: 1, backgroundColor: world.color.ground }} />;
}

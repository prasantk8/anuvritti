/**
 * The app's one root.
 *
 * Everything that has to exist before a screen can render happens here: the typefaces, the
 * client, the queue, and the share handler. That last one is the reason this file is a
 * layout rather than a screen — a share can arrive while any screen is open, and the
 * handler has to outlive all of them.
 */

import { useIBMPlexMono_400Regular } from "@expo-google-fonts/ibm-plex-mono";
import {
  IBMPlexSans_400Regular,
  IBMPlexSans_500Medium,
} from "@expo-google-fonts/ibm-plex-sans";
import { Newsreader_400Regular, Newsreader_500Medium } from "@expo-google-fonts/newsreader";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { View } from "react-native";

import { useWorld } from "../src/useWorld.ts";
import { AnuvrittiProvider } from "../src/provider.tsx";

export default function RootLayout() {
  const world = useWorld();
  const [ready] = useFonts({
    Newsreader_400Regular,
    Newsreader_500Medium,
    IBMPlexSans_400Regular,
    IBMPlexSans_500Medium,
  });

  // A splash on the ground colour rather than white: the first frame of the app is already
  // the app, not a flash of a system default.
  if (!ready) return <View style={{ flex: 1, backgroundColor: world.color.ground }} />;

  return (
    <AnuvrittiProvider>
      <StatusBar style={world.theme === "dark" ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: world.color.ground },
        }}
      />
    </AnuvrittiProvider>
  );
}

/**
 * The design world, resolved for whoever is holding the phone.
 *
 * `useColorScheme()` is the system setting, which is the third state the stylesheet also
 * has to handle: not "light" and not "dark" but "whatever this person set on their phone".
 * Returning `light` when it is null is deliberate — the palette's ground is undyed cloth,
 * and cloth is the honest default when nothing has been said.
 */

import { useColorScheme } from "react-native";
import { useMemo } from "react";

import type { Theme, World } from "./world.ts";
import { worldFor } from "./world.ts";

export function useWorld(override?: Theme): World {
  const system = useColorScheme();
  const theme: Theme = override ?? (system === "dark" ? "dark" : "light");
  return useMemo(() => worldFor(theme), [theme]);
}

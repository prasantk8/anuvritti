# JavaScript dependency risk register

This file records an accepted risk only while an executable gate proves its assumptions.
An accepted advisory is not the same thing as ignoring `npm audit`.

## GHSA-w5hq-g745-h8pq — removed with reviewed compatibility patch, 2026-08-29

`expo@57.0.18` and `expo-sharing@57.0.16` reach `uuid@7.0.3` through
`@expo/config-plugins -> xcode@3.0.1`. npm expands that one chain into eleven moderate
nodes. Its automated fix proposes Expo 46 and expo-sharing 14, which are incompatible
downgrades from the Expo 57 matrix that `npx expo install --check` approves.

The advisory is a missing bounds check when UUID v3, v5 or v6 is given a caller-owned
buffer. The installed `xcode@3.0.1` package calls only `uuid.v4()` to create Xcode project
identifiers. It is consumed by Expo's Node-based configuration/prebuild tooling, not by
Anuvritti's handset runtime, and it supplies no family data to an affected API.

TASK-741 removes that acceptance. The root lock uses npm's scoped override to resolve
`uuid@11.1.1`, the first patched CommonJS-compatible release, for exactly `xcode@3.0.1`.
Because the seven-year-old xcode manifest still declares `^7.0.3`, the post-install step
changes that one installed metadata field to the reviewed exact version. It does not alter
xcode source. The registry tarball remains pinned by its npm integrity digest and carries
its upstream Apache-2.0 license; UUID remains the registry MIT package pinned by the lock.

`npm run audit` now requires all of these to remain true:

- the complete audit result has zero findings;
- installed xcode and UUID are exactly the reviewed 3.0.1 and 11.1.1 versions;
- xcode source still calls only UUID v4; and
- a real `xcode.project(...).generateUuid()` produces the 24-character identifier Expo's
  configuration tooling expects.

The install patch refuses a changed xcode version, upstream declaration, license or
tarball integrity. This is also the retirement mechanism: when Expo publishes a supported
clean chain, `npm install` fails loudly until the override and post-install patch are
removed and the new upstream package is reviewed.

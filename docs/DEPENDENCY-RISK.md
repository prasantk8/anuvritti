# JavaScript dependency risk register

This file records an accepted risk only while an executable gate proves its assumptions.
An accepted advisory is not the same thing as ignoring `npm audit`.

## GHSA-w5hq-g745-h8pq — accepted, reviewed 2026-08-28

`expo@57.0.18` and `expo-sharing@57.0.16` reach `uuid@7.0.3` through
`@expo/config-plugins -> xcode@3.0.1`. npm expands that one chain into eleven moderate
nodes. Its automated fix proposes Expo 46 and expo-sharing 14, which are incompatible
downgrades from the Expo 57 matrix that `npx expo install --check` approves.

The advisory is a missing bounds check when UUID v3, v5 or v6 is given a caller-owned
buffer. The installed `xcode@3.0.1` package calls only `uuid.v4()` to create Xcode project
identifiers. It is consumed by Expo's Node-based configuration/prebuild tooling, not by
Anuvritti's handset runtime, and it supplies no family data to an affected API.

`npm run audit` therefore accepts advisory 1119441 only while all of these remain true:

- the complete audit result is the same eleven derived moderate nodes and no others;
- the advisory identity and severity have not changed; and
- installed xcode source still calls v4 and does not call UUID v3, v5 or v6.

Any changed condition fails CI and requires a fresh review. Remove this acceptance as
soon as Expo's supported config-plugin chain carries a patched uuid.

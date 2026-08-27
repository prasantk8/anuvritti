/**
 * TASK-713 — the player has to be allowed in.
 *
 * `useAudioPlayer` does not go through `@anuvritti/client`. It takes a source and fetches
 * the bytes itself, natively, with no idea that this server wants a bearer token — so a
 * player handed a bare URL asks for a family's recording anonymously and is told 401. The
 * screen renders a play button, the waveform, the duration, and plays silence.
 *
 * That is the worst shape a failure can take in this product: everything looks present
 * and nothing can be heard. So the source is built in one place, it is a `{ uri, headers }`
 * object rather than a string, and there is no way to construct one without a token.
 *
 * Verified against expo-audio@57's installed typings, not from memory:
 * `AudioSource = string | number | null | { uri?, assetId?, headers?, name? }`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { mediaSource } from "../src/media.ts";

const TOKEN = "dev_9f3c";

describe("a media source", () => {
  it("carries the device token as a bearer header", () => {
    const source = mediaSource("http://anuvritti.local:8000", "med-1", TOKEN);
    assert.deepEqual(source?.headers, { Authorization: `Bearer ${TOKEN}` });
  });

  it("points at the same /v1 path the client would have used", () => {
    const source = mediaSource("http://anuvritti.local:8000", "med-1", TOKEN);
    assert.equal(source?.uri, "http://anuvritti.local:8000/v1/media/med-1");
  });

  it("does not double the slash when the base url has a trailing one", () => {
    const source = mediaSource("http://anuvritti.local:8000/", "med-1", TOKEN);
    assert.equal(source?.uri, "http://anuvritti.local:8000/v1/media/med-1");
  });

  it("escapes the media id rather than pasting it into a path", () => {
    const source = mediaSource("http://home", "../families/1/export", TOKEN);
    const id = source?.uri.slice("http://home/v1/media/".length) ?? "";
    // Escaped, so the id is one path segment whatever it contains — a media id that
    // arrived with slashes in it cannot climb out and ask for something else.
    assert.ok(!id.includes("/"), `the id is still several path segments: ${id}`);
    assert.equal(decodeURIComponent(id), "../families/1/export");
  });

  it("is nothing at all without a token", () => {
    // Not a URL with an empty Authorization header. A source that cannot be authorised
    // is a source that cannot be played, and saying so is the honest shape.
    assert.equal(mediaSource("http://home", "med-1", null), null);
  });
});

describe("the screens play through it", () => {
  const files = [
    "../src/components/VoiceNote.tsx",
    "../src/components/Spark.tsx",
    "../app/vault.tsx",
  ];

  it("never builds a media URL by hand", () => {
    for (const file of files) {
      const source = readFileSync(new URL(file, import.meta.url), "utf8");
      assert.ok(
        !/\/v1\/media\//.test(source),
        `${file} spells a media URL itself instead of asking src/media.ts`
      );
    }
  });

  it("hands the player an object rather than a string", () => {
    const voiceNote = readFileSync(
      new URL("../src/components/VoiceNote.tsx", import.meta.url),
      "utf8"
    );
    assert.ok(
      !/sourceUrl/.test(voiceNote),
      "VoiceNote still takes a bare `sourceUrl` string, which cannot carry a token"
    );
    assert.match(voiceNote, /useAudioPlayer\(\s*source\s*\)/);
  });
});

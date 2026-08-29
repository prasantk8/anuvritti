/**
 * TASK-713 — a photograph shared into the app is kept, not dropped on the floor.
 *
 * `readShare` has always known what an image is. The provider then said:
 *
 *     if (!incoming.ready) continue; // media needs uploading first; handled on its screen
 *
 * There is no such screen. A parent shared a photograph of their child into Anuvritti, the
 * app opened, said nothing, and the picture was gone — which is the single worst thing this
 * product can do, because the parent believes it was saved and will not share it again.
 *
 * An image is now spooled exactly like a recording (see `spool.test.ts`): the file is taken
 * into the app's keeping, and the Spark that points at it is queued once the bytes are up.
 * This file tests the reading — what a shared payload *means* — and the promise that
 * nothing readable is skipped.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { captureForMedia, readShare, readShares } from "../src/capture/incoming.ts";

const provider = readFileSync(new URL("../src/provider.tsx", import.meta.url), "utf8");

describe("a shared photograph", () => {
  it("is read as media that still needs its bytes uploaded", () => {
    const incoming = readShare({
      value: "file:///shared/IMG_4021.HEIC",
      shareType: "image",
      mimeType: "image/heic",
    });

    assert.equal(incoming.ready, false);
    assert.ok(incoming.ready === false && incoming.media);
    assert.equal(incoming.media?.kind, "PHOTO");
  });

  it("prefers the resolved content's mime type over the payload's own", () => {
    // Verified against expo-sharing@57: a resolved payload's `mimeType` describes `value`
    // — for a shared file that is often `text/plain` — while `contentMimeType` describes
    // the bytes at `contentUri`. Sending the first is how a photograph becomes a 415.
    const incoming = readShare({
      value: "file:///shared/IMG_4021.HEIC",
      shareType: "image",
      mimeType: "text/plain",
      contentMimeType: "image/heic",
      contentUri: "file:///shared/IMG_4021.HEIC",
    });

    assert.equal(incoming.ready === false && incoming.media?.mimeType, "image/heic");
  });

  it("becomes a Spark pointing at the media once the bytes are up", () => {
    const media = {
      uri: "file:///shared/IMG_4021.HEIC",
      mimeType: "image/heic",
      kind: "PHOTO",
    } as const;

    const capture = captureForMedia(media, "med-1");

    assert.equal(capture.source.kind, "PHOTO");
    assert.equal(capture.source.media_id, "med-1");
    // No url and no text: a photograph is the thing itself (PRD §11), and inventing a
    // caption for it would be the app putting words in a family's mouth.
    assert.equal(capture.source.url, undefined);
  });

  it("keeps the name the share arrived with, when there is one", () => {
    const capture = captureForMedia(
      {
        uri: "file:///shared/screenshot.png",
        mimeType: "image/png",
        kind: "SCREENSHOT",
        name: "Screenshot 2026-08-27 at 09.14.12",
      },
      "med-2"
    );

    assert.equal(capture.source.title, "Screenshot 2026-08-27 at 09.14.12");
  });

  it("is still a screenshot when the share sheet says so", () => {
    const incoming = readShare({
      value: "file:///shared/Screenshot_20260827.png",
      shareType: "image",
      contentMimeType: "image/png",
    });

    assert.equal(incoming.ready === false && incoming.media?.kind, "SCREENSHOT");
  });
});

describe("nothing readable is skipped", () => {
  it("reads a mixed multi-share without letting the picture fall out", () => {
    const incoming = readShares([
      { value: "https://www.instagram.com/reel/abc", shareType: "url" },
      { value: "file:///shared/IMG_4021.HEIC", shareType: "image", contentMimeType: "image/heic" },
    ]);

    assert.equal(incoming.length, 2);
    assert.equal(incoming[0]?.ready, true);
    assert.equal(incoming[1]?.ready === false && incoming[1].media?.kind, "PHOTO");
  });

  it("no longer walks past media in the provider", () => {
    assert.ok(
      !/if \(!incoming\.ready\) continue/.test(provider),
      "the provider still drops every shared image on the floor"
    );
    assert.match(provider, /spool\(/);
  });
});

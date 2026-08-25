/**
 * TASK-508 — what a share means.
 *
 * Every case here is something a parent actually does. The share sheet is the product's
 * front door, and the ways it can go wrong are all quiet: a link saved as prose, a
 * screenshot filed as a photograph, an empty Spark that sits in the vault for years looking
 * like a memory somebody lost.
 *
 * None of this needs a device, which is the point of `readShare` being a pure function.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { SharedPayload } from "../src/capture/incoming.ts";
import { creatorFrom, readShare, readShares, urlWithin } from "../src/capture/incoming.ts";

function payload(overrides: Partial<SharedPayload>): SharedPayload {
  return { value: "", shareType: "text", ...overrides };
}

describe("a link", () => {
  it("becomes a URL Spark", () => {
    const incoming = readShare(
      payload({ shareType: "url", value: "https://instagram.com/reel/balloon-rocket" })
    );

    assert.equal(incoming.ready, true);
    if (!incoming.ready) return;
    assert.equal(incoming.capture.source.kind, "URL");
    assert.equal(incoming.capture.source.url, "https://instagram.com/reel/balloon-rocket");
  });

  it("is found inside the sentence every social app wraps it in", () => {
    // "Look at this! https://... — sent via Instagram" is what actually arrives.
    const incoming = readShare(
      payload({
        shareType: "text",
        value: "Look at this! https://instagram.com/reel/balloon-rocket sent via Instagram",
      })
    );

    assert.equal(incoming.ready, true);
    if (!incoming.ready) return;
    assert.equal(incoming.capture.source.kind, "URL");
    assert.equal(incoming.capture.source.url, "https://instagram.com/reel/balloon-rocket");
  });

  it("keeps the sentence too, because that is what survives the link dying", () => {
    const incoming = readShare(
      payload({ shareType: "text", value: "Balloon rocket! https://example.com/x" })
    );

    assert.equal(incoming.ready, true);
    if (!incoming.ready) return;
    // PRD §43: a Spark keeps its meaning even when the URL 404s three years from now.
    assert.match(incoming.capture.source.text ?? "", /Balloon rocket/);
  });

  it("does not keep the sentence when the sentence was only the link", () => {
    const incoming = readShare(
      payload({ shareType: "url", value: "https://example.com/x" })
    );
    assert.equal(incoming.ready && incoming.capture.source.text, undefined);
  });

  it("takes the title from the resolved payload", () => {
    const incoming = readShare(
      payload({
        shareType: "url",
        value: "https://example.com/x",
        originalName: "Balloon rocket experiment for ages 5-8",
      })
    );
    assert.equal(
      incoming.ready && incoming.capture.source.title,
      "Balloon rocket experiment for ages 5-8"
    );
  });

  it("does not repeat the url as its own title", () => {
    const incoming = readShare(
      payload({ shareType: "url", value: "https://example.com/x", originalName: "https://example.com/x" })
    );
    assert.equal(incoming.ready && incoming.capture.source.title, undefined);
  });
});

describe("who made it", () => {
  it("is read off the link rather than fetched", () => {
    // A network call here is what would blow the ten-second budget (PRD §11).
    assert.equal(creatorFrom("https://instagram.com/sciencedad/reel/x"), "@sciencedad");
    assert.equal(creatorFrom("https://www.tiktok.com/@dadlab/video/123"), "@dadlab");
    assert.equal(creatorFrom("https://youtube.com/@thebrainscoop"), "@thebrainscoop");
  });

  it("is absent rather than guessed when the link does not say", () => {
    assert.equal(creatorFrom("https://example.com/some/article"), undefined);
    assert.equal(creatorFrom("https://en.wikipedia.org/wiki/Rocket"), undefined);
  });

  it("finds the url in a string, or says there is none", () => {
    assert.equal(urlWithin("go to https://a.test/x now"), "https://a.test/x");
    assert.equal(urlWithin("no link here at all"), undefined);
  });
});

describe("plain text", () => {
  it("is kept as what somebody typed", () => {
    const incoming = readShare(payload({ value: "He called the moon a broken sun." }));

    assert.equal(incoming.ready, true);
    if (!incoming.ready) return;
    assert.equal(incoming.capture.source.kind, "TEXT");
    assert.equal(incoming.capture.source.text, "He called the moon a broken sun.");
  });

  it("is trimmed, because a share sheet adds whitespace and a parent did not", () => {
    const incoming = readShare(payload({ value: "  a thought  \n" }));
    assert.equal(incoming.ready && incoming.capture.source.text, "a thought");
  });
});

describe("an image", () => {
  it("comes back as something to upload first", () => {
    const incoming = readShare(
      payload({ shareType: "image", value: "file:///tmp/IMG_0001.jpg", mimeType: "image/jpeg" })
    );

    assert.equal(incoming.ready, false);
    if (incoming.ready) return;
    assert.equal(incoming.media?.uri, "file:///tmp/IMG_0001.jpg");
    assert.equal(incoming.media?.mimeType, "image/jpeg");
  });

  it("prefers the resolved uri, which is the one that can actually be read", () => {
    const incoming = readShare(
      payload({
        shareType: "image",
        value: "ph://asset-id",
        contentUri: "file:///var/tmp/resolved.jpg",
        mimeType: "image/jpeg",
      })
    );
    assert.equal(!incoming.ready && incoming.media?.uri, "file:///var/tmp/resolved.jpg");
  });

  it("tells a screenshot from a photograph", () => {
    // A screenshot is usually *of* something - a post, a recipe, a message. A photo from
    // the library is usually *of the child*. They are different kinds of memory.
    const screenshot = readShare(
      payload({ shareType: "image", value: "file:///Screenshot_2026-01-13.png", mimeType: "image/png" })
    );
    const photograph = readShare(
      payload({ shareType: "image", value: "file:///family-picnic.heic", mimeType: "image/heic" })
    );

    assert.equal(!screenshot.ready && screenshot.media?.kind, "SCREENSHOT");
    assert.equal(!photograph.ready && photograph.media?.kind, "PHOTO");
  });
});

describe("nothing worth keeping", () => {
  it("is refused with a reason rather than saved as an empty Spark", () => {
    const incoming = readShare(payload({ value: "   " }));

    assert.equal(incoming.ready, false);
    if (incoming.ready) return;
    assert.equal(incoming.media, null);
    // An empty Spark sits in the vault forever looking like a memory somebody lost.
    assert.match((incoming as { reason: string }).reason, /nothing/);
  });

  it("is refused for an image with no uri at all", () => {
    const incoming = readShare(payload({ shareType: "image", value: "", mimeType: "image/png" }));
    assert.equal(incoming.ready, false);
    assert.equal(!incoming.ready && incoming.media, null);
  });
});

describe("several at once", () => {
  it("reads every one, and one failure does not lose the others", () => {
    const results = readShares([
      payload({ shareType: "url", value: "https://a.test/one" }),
      payload({ value: "   " }),
      payload({ value: "a thought" }),
    ]);

    assert.equal(results.length, 3);
    assert.equal(results[0]?.ready, true);
    assert.equal(results[1]?.ready, false);
    assert.equal(results[2]?.ready, true);
  });
});

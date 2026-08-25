/**
 * A share, turned into something worth keeping (TASK-508).
 *
 * This is the entire product's front door, and it is a pure function on purpose. Everything
 * about receiving a share is platform-specific and untestable off a device: the extension,
 * the intent, the App Group container. What a shared payload *means* is neither, so it lives
 * here, with no import from `expo-*` anywhere in the file, and it is tested.
 *
 * ## Why the app opens
 *
 * There are two ways to be an iOS share target. `expo-sharing`'s first-party config plugin
 * (SDK 55+) adds a "share into" extension: the sheet hands the payload over and the app
 * comes forward. The alternative — `expo-share-extension`, which renders a React Native view
 * *inside* the sheet so the app never opens — is the nicer interaction and is currently
 * broken on SDK 55 and later: its view controller boots the runtime without an Expo
 * `AppContext`, so `globalThis.expo` is never installed and the bundle throws on import. The
 * fix exists only in a `6.0.0-beta` published in February 2026, in a repository untouched
 * since April.
 *
 * So: the supported path, and the ten-second budget is met a different way. The app opens,
 * writes to the local queue, and says "Saved." It does not wait for a network, so the
 * confirmation is as fast as an in-sheet one would have been. Revisit when the beta lands.
 */

/** The shape `expo-sharing` hands over. Declared here so this file imports nothing. */
export interface SharedPayload {
  readonly value: string;
  readonly shareType: "text" | "url" | "audio" | "image" | "video" | "file";
  readonly mimeType?: string;
  /** Present on a resolved payload: the page title, a filename, whatever was learned. */
  readonly originalName?: string | null;
  readonly contentUri?: string | null;
}

/** What `POST /v1/sparks` wants. The subset a share can fill in. */
export interface CaptureFromShare {
  readonly source: {
    readonly kind: "URL" | "TEXT" | "SCREENSHOT" | "PHOTO";
    readonly url?: string;
    readonly text?: string;
    readonly title?: string;
    readonly creator?: string;
  };
}

/** A share that arrived carrying a file, which has to be uploaded before it is a Spark. */
export interface MediaFromShare {
  readonly uri: string;
  readonly mimeType: string;
  readonly kind: "SCREENSHOT" | "PHOTO";
}

export type Incoming =
  | { readonly ready: true; readonly capture: CaptureFromShare }
  | { readonly ready: false; readonly media: MediaFromShare }
  | { readonly ready: false; readonly media: null; readonly reason: string };

const URL_PATTERN = /https?:\/\/[^\s]+/i;

/**
 * The creator, when the link says who it is.
 *
 * Not scraped and not fetched — read off the URL itself, because PRD §43 says a Spark keeps
 * its meaning after the link dies and "@sciencedad" is most of that meaning. A network call
 * here would also be the thing that blows the ten seconds.
 */
export function creatorFrom(url: string): string | undefined {
  const handle = url.match(/(?:instagram\.com|tiktok\.com|youtube\.com\/@)\/?(@?[\w.-]+)/i);
  if (handle?.[1]) return handle[1].startsWith("@") ? handle[1] : `@${handle[1]}`;
  return undefined;
}

/**
 * Pull the URL out of shared text.
 *
 * Every social app shares a link as prose: "Look at this! https://... — sent from X". The
 * link is the Spark and the rest is packaging, but the prose sometimes carries the title,
 * so it is kept as `text` rather than thrown away.
 */
export function urlWithin(text: string): string | undefined {
  return text.match(URL_PATTERN)?.[0];
}

function titleFrom(payload: SharedPayload, url: string | undefined): string | undefined {
  const name = payload.originalName?.trim();
  if (name && name !== url) return name;
  return undefined;
}

/**
 * One shared payload, read as a capture.
 *
 * The rules, in the order they apply:
 *
 * 1. A URL is a URL, even when it arrived wrapped in a sentence.
 * 2. Text with no URL in it is text. Someone typed something and meant it.
 * 3. An image needs uploading before it can be a Spark, so it comes back as `media` and the
 *    caller does that. Screenshot and photo are distinguished because a screenshot is
 *    usually *of* something (PRD §11) and a photo usually *is* the thing.
 * 4. Anything else is refused with a reason, rather than saved as an empty Spark. A Spark
 *    that says nothing is worse than no Spark: it sits in the vault forever looking like a
 *    memory someone lost.
 */
export function readShare(payload: SharedPayload): Incoming {
  const value = payload.value?.trim() ?? "";

  if (payload.shareType === "image" || payload.mimeType?.startsWith("image/")) {
    const uri = payload.contentUri ?? value;
    if (!uri) return { ready: false, media: null, reason: "that image had nothing to read" };
    return {
      ready: false,
      media: {
        uri,
        mimeType: payload.mimeType ?? "image/jpeg",
        // A shared screenshot is nearly always of a post, a recipe, a message - something
        // that was on the screen. A photo from the library is nearly always of the child.
        kind: looksLikeAScreenshot(payload) ? "SCREENSHOT" : "PHOTO",
      },
    };
  }

  if (payload.shareType === "url" || (value && urlWithin(value))) {
    const url = payload.shareType === "url" ? value : urlWithin(value);
    if (!url) return { ready: false, media: null, reason: "that link could not be read" };
    return {
      ready: true,
      capture: {
        source: {
          kind: "URL",
          url,
          title: titleFrom(payload, url),
          creator: creatorFrom(url),
          // Whatever else came with the link. PRD §43: this is what survives the link dying.
          text: value === url ? undefined : value,
        },
      },
    };
  }

  if (value) return { ready: true, capture: { source: { kind: "TEXT", text: value } } };

  return { ready: false, media: null, reason: "there was nothing in that share to keep" };
}

/**
 * Whether this image was of a screen.
 *
 * Both platforms name them: iOS writes `IMG_1234.PNG` for a screenshot but the share sheet
 * resolves it to a name containing "Screenshot"; Android writes `Screenshot_20260113.png`
 * directly. So the word is the signal, and it is looked for in every string the payload
 * carries rather than only in the resolved name - an unresolved payload has the file URI in
 * `value` and nothing else.
 *
 * `IMG_` is deliberately *not* a signal, though it looks like one. It is the camera roll's
 * own prefix, so treating it as a screenshot marker gets every photograph of the child
 * exactly backwards.
 */
function looksLikeAScreenshot(payload: SharedPayload): boolean {
  const searched = [payload.originalName, payload.contentUri, payload.value]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return /screen[\s_-]?shot/.test(searched);
}

/**
 * Everything a family shared at once, oldest first.
 *
 * Multi-share exists and a parent will use it. Refusing all of them because one was
 * unreadable would be the product punishing them for the one that failed.
 */
export function readShares(payloads: readonly SharedPayload[]): readonly Incoming[] {
  return payloads.map(readShare);
}

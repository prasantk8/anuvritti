/**
 * Everything the app needs to talk to its family's server, and the share handler.
 *
 * Held at the root because a share can arrive while any screen is open, and because the
 * queue and the spool must each be one object — two of either over the same SQLite file
 * would each think they owned the backlog.
 *
 * It also holds the one fact the layout cannot render without: whether this phone is paired
 * (TASK-713). That question is asked of the keychain, so it has three answers and the third
 * one — not yet known — is the reason nothing at all renders until it is settled. See
 * `src/session/gate.ts`.
 */

import { useIncomingShare } from "expo-sharing";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";
import NetInfo from "@react-native-community/netinfo";

import type { CaptureQueue } from "@anuvritti/client";

import type { Wired } from "./api.ts";
import { wire } from "./api.ts";
import { readShares } from "./capture/incoming.ts";
import type { MediaSource } from "./media.ts";
import { mediaSource } from "./media.ts";
import type { Outbox } from "./upload/spool.ts";

/** Where the family's server is. One family, one box, configured once at pairing. */
const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_ANUVRITTI_URL ?? "http://localhost:8000";

interface Anuvritti extends Wired {
  /** The last thing that was saved, so a screen can say "Saved." about something specific. */
  readonly justSaved: string | null;
  /** Where the family's server is. */
  readonly baseUrl: string;
  /**
   * Whether the keychain holds a device token. `null` until it has answered — which is not
   * "no", and rendering it as "no" is how a fresh install ends up showing a stranger the
   * empty archive of a family it has not joined.
   */
  readonly paired: boolean | null;
  /**
   * Today, as `YYYY-MM-DD`.
   *
   * A calendar date, not a duration — it picks which question the recorder offers. The
   * distinction matters because `packages/client` forbids `Date` outright (TASK-507), and
   * the reason is subtraction: two dates make a day count and a day count about a family's
   * own life is the one number this product must never render. A single date cannot.
   */
  readonly today: string;
  acknowledge(): void;
  drain(): Promise<void>;
  /** Ask the keychain again. Called by the pairing screen the moment it succeeds. */
  refreshPairing(): Promise<void>;
  /**
   * Where a piece of media is, and the proof this phone may hear it. `null` while unpaired,
   * because the native audio player fetches the bytes itself and would otherwise be sent to
   * ask anonymously and be told 401 (`src/media.ts`).
   */
  media(mediaId: string): MediaSource | null;
}

const AnuvrittiContext = createContext<Anuvritti | null>(null);

export function useAnuvritti(): Anuvritti {
  const value = useContext(AnuvrittiContext);
  if (!value) throw new Error("useAnuvritti was called outside AnuvrittiProvider");
  return value;
}

export interface AnuvrittiProviderProps {
  readonly children: React.ReactNode;
  /**
   * What to show while the client is being built and the keychain is being read. A prop
   * rather than a default, because the honest first frame is the app's own ground colour
   * and this file has no business knowing what colour that is.
   */
  readonly fallback?: React.ReactNode;
}

export function AnuvrittiProvider({ children, fallback = null }: AnuvrittiProviderProps) {
  const [wired, setWired] = useState<Wired | null>(null);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [paired, setPaired] = useState<boolean | null>(null);
  const queueRef = useRef<CaptureQueue | null>(null);
  const outboxRef = useRef<Outbox | null>(null);
  const wiredRef = useRef<Wired | null>(null);

  useEffect(() => {
    let cancelled = false;
    void wire(DEFAULT_BASE_URL).then(async (ready) => {
      // The keychain is read before anything renders, so the gate never has to guess and
      // the first frame is never the wrong app.
      const held = await ready.tokens.read();
      if (cancelled) return;
      queueRef.current = ready.queue;
      outboxRef.current = ready.outbox;
      wiredRef.current = ready;
      setToken(held);
      setPaired(held !== null);
      setWired(ready);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshPairing = useCallback(async () => {
    const held = (await wiredRef.current?.tokens.read()) ?? null;
    setToken(held);
    setPaired(held !== null);
  }, []);

  const drain = useCallback(async () => {
    // The spool first: a capture that points at media is only sendable once the bytes are
    // up, and the spool is what puts it in the queue.
    await outboxRef.current?.drain();
    await queueRef.current?.drain();
  }, []);

  // --- when to try again -----------------------------------------------------------
  //
  // NetInfo is a hint, never an oracle. It lies in both directions - VPNs, IPv6-only
  // networks, walled-garden Wi-Fi - so the queue's own backoff remains the schedule and
  // this only ever makes it try *earlier*. The one authoritative signal that the network
  // works is a request that succeeded.
  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      if (state.isConnected) void drain();
    });
    const subscription = AppState.addEventListener("change", (next) => {
      if (next === "active") void drain();
    });
    return () => {
      unsubscribe();
      subscription.remove();
    };
  }, [drain]);

  // A launch is the most likely moment for a backlog to exist: whatever was spooled before
  // the app was last killed is still spooled, and nothing else would go looking for it.
  useEffect(() => {
    if (wired) void drain();
  }, [drain, wired]);

  // --- a share arriving ------------------------------------------------------------
  const { sharedPayloads, resolvedSharedPayloads, clearSharedPayloads } = useIncomingShare();

  useEffect(() => {
    // Prefer the resolved payloads - they carry the page title, which is most of what
    // makes a Spark survive its link dying (PRD §43). Fall back to the raw ones so a
    // share still saves when resolving failed or there was no network to resolve with.
    const payloads = resolvedSharedPayloads.length > 0 ? resolvedSharedPayloads : sharedPayloads;
    const queue = queueRef.current;
    const outbox = outboxRef.current;
    if (payloads.length === 0 || !queue || !outbox) return;

    void (async () => {
      let saved: string | null = null;
      for (const incoming of readShares(payloads)) {
        if (incoming.ready) {
          await queue.enqueue("captureSpark", incoming.capture);
          saved = incoming.capture.source.title ?? incoming.capture.source.text ?? "it";
          continue;
        }

        // A photograph. It used to be skipped here — "handled on its screen", and there was
        // no such screen — so a parent shared a picture of their child into Anuvritti, the
        // app opened, said nothing, and the picture was gone. It is spooled now, exactly
        // like a recording: the file is taken into the app's keeping and the Spark that
        // points at it is queued the moment the bytes are up (TASK-713).
        if (!incoming.media) continue;
        const media = incoming.media;
        await outbox.spool(
          { uri: media.uri, mimeType: media.mimeType, name: media.name },
          { kind: "spark", media }
        );
        saved = media.name ?? (media.kind === "SCREENSHOT" ? "that screenshot" : "that photo");
      }
      clearSharedPayloads();
      if (saved) {
        setJustSaved(saved);
        // Written first, sent second. "Saved." was already true before this line.
        void drain();
      }
    })();
  }, [clearSharedPayloads, drain, resolvedSharedPayloads, sharedPayloads]);

  const media = useCallback(
    (mediaId: string) => mediaSource(DEFAULT_BASE_URL, mediaId, token),
    [token]
  );

  const value = useMemo<Anuvritti | null>(
    () =>
      wired && paired !== null
        ? {
            ...wired,
            justSaved,
            baseUrl: DEFAULT_BASE_URL,
            paired,
            today: new Date().toISOString().slice(0, 10),
            acknowledge: () => setJustSaved(null),
            drain,
            refreshPairing,
            media,
          }
        : null,
    [drain, justSaved, media, paired, refreshPairing, wired]
  );

  if (!value) return <>{fallback}</>;
  return <AnuvrittiContext.Provider value={value}>{children}</AnuvrittiContext.Provider>;
}

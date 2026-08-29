/**
 * Everything the app needs to talk to its family's server, and the share handler.
 *
 * Held at the root because a share can arrive while any screen is open, and because the
 * queue must be one object — two queues over the same SQLite file would each think they
 * owned the backlog.
 */

import { useIncomingShare } from "expo-sharing";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppState } from "react-native";
import NetInfo from "@react-native-community/netinfo";

import type { CaptureQueue } from "@anuvritti/client";

import type { Wired } from "./api.ts";
import { wire } from "./api.ts";
import { readShares } from "./capture/incoming.ts";
import type { Standing } from "./model/threshold.ts";

/** Where the family's server is. One family, one box, configured once at pairing. */
const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_ANUVRITTI_URL ?? "http://localhost:8000";

interface Anuvritti extends Wired {
  /** The last thing that was saved, so a screen can say "Saved." about something specific. */
  readonly justSaved: string | null;
  /** Where the family's server is, for the one thing the client cannot hand over: a media
   *  URL for a native audio player, which takes a string and fetches the bytes itself. */
  readonly baseUrl: string;
  /**
   * Today, as `YYYY-MM-DD`.
   *
   * A calendar date, not a duration — it picks which question the recorder offers. The
   * distinction matters because `packages/client` forbids `Date` outright (TASK-507), and
   * the reason is subtraction: two dates make a day count and a day count about a family's
   * own life is the one number this product must never render. A single date cannot.
   */
  readonly today: string;
  /**
   * Whether this device holds a token, once the keychain has answered (TASK-513).
   *
   * `unknown` until it has. The root layout waits on it rather than guessing, because both
   * guesses are wrong in a way a parent sees: Today flashes an empty archive at someone who
   * has one, and pairing flashes "Start our family" at someone who did it two years ago.
   */
  readonly standing: Standing;
  acknowledge(): void;
  drain(): Promise<void>;
  /** The pairing screen, having obtained a token, saying so. */
  paired(): void;
}

const AnuvrittiContext = createContext<Anuvritti | null>(null);

export function useAnuvritti(): Anuvritti {
  const value = useContext(AnuvrittiContext);
  if (!value) throw new Error("useAnuvritti was called outside AnuvrittiProvider");
  return value;
}

export function AnuvrittiProvider({
  children,
  holding = null,
}: {
  children: React.ReactNode;
  /** What is on screen while the client is being built. The ground, not a spinner. */
  holding?: React.ReactNode;
}) {
  const [wired, setWired] = useState<Wired | null>(null);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const [standing, setStanding] = useState<Standing>("unknown");
  const queueRef = useRef<CaptureQueue | null>(null);
  const sessionRef = useRef<Wired["anuvritti"]["session"] | null>(null);

  /**
   * The token stopped working, so this device is not paired any more.
   *
   * The keychain entry goes; **the queue stays**. A parent who captured five things on a
   * plane and lands to a revoked token has five things worth keeping and one credential
   * worth throwing away, and losing the first to tidy up the second would be the worst bug
   * in the product. `forget()` clears the token store and nothing else.
   */
  const revoked = useCallback(() => {
    setStanding("unpaired");
    void sessionRef.current?.forget();
  }, []);

  useEffect(() => {
    let cancelled = false;
    wire(DEFAULT_BASE_URL, { onRevoked: () => revoked() }).then(async (ready) => {
      if (cancelled) return;
      queueRef.current = ready.queue;
      sessionRef.current = ready.anuvritti.session;
      const held = await ready.anuvritti.session.isPaired();
      if (cancelled) return;
      setWired(ready);
      setStanding(held ? "paired" : "unpaired");
    });
    return () => {
      cancelled = true;
    };
  }, [revoked]);

  const drain = useCallback(async () => {
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

  // --- a share arriving ------------------------------------------------------------
  const { sharedPayloads, resolvedSharedPayloads, clearSharedPayloads } = useIncomingShare();

  useEffect(() => {
    // Prefer the resolved payloads - they carry the page title, which is most of what
    // makes a Spark survive its link dying (PRD §43). Fall back to the raw ones so a
    // share still saves when resolving failed or there was no network to resolve with.
    const payloads = resolvedSharedPayloads.length > 0 ? resolvedSharedPayloads : sharedPayloads;
    if (payloads.length === 0 || !queueRef.current) return;

    const queue = queueRef.current;
    void (async () => {
      let saved: string | null = null;
      for (const incoming of readShares(payloads)) {
        if (!incoming.ready) continue; // media needs uploading first; handled on its screen
        await queue.enqueue("captureSpark", incoming.capture);
        saved = incoming.capture.source.title ?? incoming.capture.source.text ?? "it";
      }
      clearSharedPayloads();
      if (saved) {
        setJustSaved(saved);
        // Written first, sent second. "Saved." was already true before this line.
        void drain();
      }
    })();
  }, [clearSharedPayloads, drain, resolvedSharedPayloads, sharedPayloads]);

  const value = useMemo<Anuvritti | null>(
    () =>
      wired
        ? {
            ...wired,
            justSaved,
            baseUrl: DEFAULT_BASE_URL,
            today: new Date().toISOString().slice(0, 10),
            standing,
            acknowledge: () => setJustSaved(null),
            drain,
            paired: () => setStanding("paired"),
          }
        : null,
    [drain, justSaved, standing, wired]
  );

  if (!value) return <>{holding}</>;
  return <AnuvrittiContext.Provider value={value}>{children}</AnuvrittiContext.Provider>;
}

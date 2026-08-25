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

/** Where the family's server is. One family, one box, configured once at pairing. */
const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_ANUVRITTI_URL ?? "http://localhost:8000";

interface Anuvritti extends Wired {
  /** The last thing that was saved, so a screen can say "Saved." about something specific. */
  readonly justSaved: string | null;
  acknowledge(): void;
  drain(): Promise<void>;
}

const AnuvrittiContext = createContext<Anuvritti | null>(null);

export function useAnuvritti(): Anuvritti {
  const value = useContext(AnuvrittiContext);
  if (!value) throw new Error("useAnuvritti was called outside AnuvrittiProvider");
  return value;
}

export function AnuvrittiProvider({ children }: { children: React.ReactNode }) {
  const [wired, setWired] = useState<Wired | null>(null);
  const [justSaved, setJustSaved] = useState<string | null>(null);
  const queueRef = useRef<CaptureQueue | null>(null);

  useEffect(() => {
    let cancelled = false;
    wire(DEFAULT_BASE_URL).then((ready) => {
      if (cancelled) return;
      queueRef.current = ready.queue;
      setWired(ready);
    });
    return () => {
      cancelled = true;
    };
  }, []);

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
        ? { ...wired, justSaved, acknowledge: () => setJustSaved(null), drain }
        : null,
    [drain, justSaved, wired]
  );

  if (!value) return null;
  return <AnuvrittiContext.Provider value={value}>{children}</AnuvrittiContext.Provider>;
}

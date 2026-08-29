/**
 * A server double, and the deterministic clock and randomness the runtime takes as ports.
 *
 * The double records what it was asked for, so a test can assert on the *request* — which
 * header carried the token, whether an idempotency key went out, what the URL looked like —
 * rather than only on the answer. Most of the interesting bugs in a client are in the
 * request.
 */

import type { Clock, Random } from "../src/runtime/types.ts";

export interface Recorded {
  readonly method: string;
  readonly url: string;
  readonly headers: Record<string, string>;
  readonly body: unknown;
}

export interface Reply {
  readonly status?: number;
  readonly json?: unknown;
  readonly text?: string;
  // Uint8Array<ArrayBuffer>, not the bare `Uint8Array`: since TypeScript 5.7 that is
// `Uint8Array<ArrayBufferLike>`, which could be backed by a SharedArrayBuffer and so is
// not accepted as a request body. These bytes are a plain allocation, and saying so is
// what lets them be one.
  readonly bytes?: Uint8Array<ArrayBuffer>;
  /** Throw instead of answering, the way a dead network does. */
  readonly networkError?: string;
  /** Never answer, so the transport's own timeout has to fire. */
  readonly hang?: boolean;
}

export interface ServerDouble {
  readonly fetch: typeof globalThis.fetch;
  readonly calls: Recorded[];
  /** Answer the next call to `METHOD /path` (path without the /v1 prefix). */
  on(route: string, reply: Reply | ((call: Recorded) => Reply)): void;
  lastCall(): Recorded | undefined;
}

export function serverDouble(): ServerDouble {
  const routes = new Map<string, Reply | ((call: Recorded) => Reply)>();
  const calls: Recorded[] = [];

  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = Object.fromEntries(
      Object.entries((init?.headers ?? {}) as Record<string, string>)
    );
    let body: unknown;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    } else if (init?.body !== undefined) {
      body = init.body;
    }

    const call: Recorded = { method, url, headers, body };
    calls.push(call);

    const path = new URL(url).pathname.replace(/^\/v1/, "");
    const handler = routes.get(`${method} ${path}`) ?? routes.get("*");
    const reply = typeof handler === "function" ? handler(call) : handler;

    if (!reply) {
      return new Response(
        JSON.stringify({ error: { code: "SPARK_NOT_FOUND", message: "no route", details: {} } }),
        { status: 404, headers: { "content-type": "application/json" } }
      );
    }
    if (reply.networkError) throw new TypeError(reply.networkError);
    if (reply.hang) {
      // A double that ignored `signal` would make every abort test wait out its own
      // timer instead of the transport's - the test would still pass, sixty seconds
      // later, and would be measuring nothing. Real `fetch` rejects on abort; so does this.
      await new Promise((_, reject) => {
        const signal = init?.signal;
        if (signal?.aborted) {
          reject(new DOMException("aborted", "AbortError"));
          return;
        }
        signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError"))
        );
      });
    }
    if (reply.bytes) {
      return new Response(reply.bytes, { status: reply.status ?? 200 });
    }
    if (reply.text !== undefined) {
      return new Response(reply.text, { status: reply.status ?? 200 });
    }
    return new Response(JSON.stringify(reply.json ?? {}), {
      status: reply.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof globalThis.fetch;

  return {
    fetch: fetchImpl,
    calls,
    on(route, reply) {
      routes.set(route, reply);
    },
    lastCall: () => calls.at(-1),
  };
}

/** Time only moves when a test says so — the same rule `FrozenClock` keeps on the server. */
export function frozenClock(start = 1_760_000_000_000): Clock & { advance(ms: number): void } {
  let now = start;
  return {
    now: () => now,
    advance(ms: number) {
      now += ms;
    },
  };
}

/** Predictable "randomness". Jitter is asserted against known values rather than a range. */
export function fixedRandom(value = 0.5): Random & { ids: string[] } {
  let counter = 0;
  const ids: string[] = [];
  return {
    ids,
    next: () => value,
    id() {
      counter += 1;
      const id = `key-${String(counter).padStart(4, "0")}`;
      ids.push(id);
      return id;
    },
  };
}

/** The error envelope fixed by docs/contracts/errors.md. */
export function apiError(code: string, message = "something"): unknown {
  return { error: { code, message, details: {} } };
}

/** A Spark shaped the way the server renders one. */
export function aSpark(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "sp-1",
    family_id: "fam-1",
    owner_id: "mem-papa",
    subject_child_id: "ch-1",
    title: "Balloon rocket experiment",
    note: null,
    source: {
      kind: "URL",
      url: "https://instagram.com/reel/balloon",
      creator: "@sciencedad",
      title: "Balloon rocket experiment",
      media_id: null,
    },
    intent: { value: "DO", source: "AI", confidence: 0.85, human_override: false },
    category: { value: "science", source: "AI", confidence: 0.6, human_override: false },
    age_range: {
      value: { min_years: 5, max_years: 8 },
      source: "AI",
      confidence: 0.8,
      human_override: false,
    },
    tags: [],
    why: null,
    status: "WAITING",
    visibility: "PRIVATE",
    saved: "8 months ago",
    created_at: "2026-01-13T21:40:00+00:00",
    ...overrides,
  };
}

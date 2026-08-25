/**
 * One `fetch` call, written once.
 *
 * Everything platform-specific about talking to an Anuvritti server lives here: the base
 * URL, the bearer token, the timeout, and the translation of every possible outcome into a
 * `Result`. The generated client below it contains no networking at all - it turns an
 * operation name and some arguments into a request and hands it over.
 *
 * The header work is deliberately small. There is no interceptor chain, no middleware
 * stack, and no request/response transform hook, because every one of those is a place a
 * future change could quietly start sending the token somewhere it does not belong.
 */

import type { Clock, Failure, Result, TokenStore } from "./types.ts";
import { err, ok } from "./types.ts";

/** Ten seconds is the capture budget (PRD §11). A request may not spend all of it. */
export const DEFAULT_TIMEOUT_MS = 8_000;

export interface TransportConfig {
  /** e.g. `https://anuvritti.local:8000`. The `/v1` prefix is added here, once. */
  readonly baseUrl: string;
  readonly tokens: TokenStore;
  readonly clock?: Clock;
  readonly timeoutMs?: number;
  /** Injectable so tests do not need a server, and so React Native's fetch can be passed. */
  readonly fetch?: typeof globalThis.fetch;
}

export interface Request {
  readonly method: string;
  readonly path: string;
  readonly query?: Record<string, unknown>;
  readonly body?: unknown;
  readonly headers?: Record<string, string>;
  /** Bootstrap and pairing: the two routes that exist to obtain a token. */
  readonly open?: boolean;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  /** Media downloads come back as bytes, not JSON. */
  readonly expect?: "json" | "bytes" | "none";
}

export interface Transport {
  send<T>(request: Request): Promise<Result<T>>;
  readonly baseUrl: string;
}

function buildUrl(baseUrl: string, path: string, query?: Record<string, unknown>): string {
  const url = `${baseUrl.replace(/\/+$/, "")}/v1${path}`;
  if (!query) return url;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `${url}?${rendered}` : url;
}

/**
 * The error envelope fixed by docs/contracts/errors.md, or an honest admission that the
 * response was not one.
 *
 * A server that returns HTML from a proxy, or an empty 502, must not be reported as an API
 * error with an invented code - the client would then switch on a `code` nobody sent.
 */
function toFailure(status: number, text: string): Failure {
  try {
    const parsed = JSON.parse(text) as { error?: { code?: string; message?: string; details?: unknown } };
    const envelope = parsed.error;
    if (envelope && typeof envelope.code === "string") {
      return {
        kind: "api",
        status,
        code: envelope.code,
        message: envelope.message ?? envelope.code,
        details: (envelope.details as Record<string, unknown>) ?? {},
      };
    }
  } catch {
    // fall through - it was not JSON, which is itself the finding
  }
  return { kind: "malformed", status, message: text.slice(0, 200) || `HTTP ${status}` };
}

export function createTransport(config: TransportConfig): Transport {
  const doFetch = config.fetch ?? globalThis.fetch;
  const defaultTimeout = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  async function send<T>(request: Request): Promise<Result<T>> {
    const headers: Record<string, string> = { Accept: "application/json", ...request.headers };

    if (!request.open) {
      const token = await config.tokens.read();
      if (!token) {
        // Not a network call at all. A device with no token is not offline, it is unpaired,
        // and an offline-shaped failure would put it in the retry queue forever.
        return err({
          kind: "api",
          status: 401,
          code: "UNAUTHENTICATED",
          message: "this device is not paired with a family",
          details: {},
        });
      }
      headers.Authorization = `Bearer ${token}`;
    }

    let payload: BodyInit | undefined;
    if (request.body instanceof FormData) {
      payload = request.body;
      // Deliberately no Content-Type: fetch must set it, because only fetch knows the
      // multipart boundary it generated.
    } else if (request.body !== undefined) {
      payload = JSON.stringify(request.body);
      headers["Content-Type"] = "application/json";
    }

    const controller = new AbortController();
    const timeoutMs = request.timeoutMs ?? defaultTimeout;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const onOuterAbort = () => controller.abort();
    request.signal?.addEventListener("abort", onOuterAbort);

    try {
      const response = await doFetch(buildUrl(config.baseUrl, request.path, request.query), {
        method: request.method,
        headers,
        body: payload,
        signal: controller.signal,
      });

      if (!response.ok) return err(toFailure(response.status, await response.text()));

      if (request.expect === "none" || response.status === 204) return ok(undefined as T);
      if (request.expect === "bytes") {
        return ok(new Uint8Array(await response.arrayBuffer()) as T);
      }
      return ok((await response.json()) as T);
    } catch (cause) {
      // A caller's own abort is not a timeout, and reporting it as one would make a
      // cancelled screen look like a network problem worth retrying.
      if (request.signal?.aborted) {
        return err({ kind: "timeout", message: "the request was cancelled" });
      }
      if (controller.signal.aborted) {
        return err({ kind: "timeout", message: `no answer within ${timeoutMs}ms` });
      }
      return err({ kind: "offline", message: describe(cause) });
    } finally {
      clearTimeout(timer);
      request.signal?.removeEventListener("abort", onOuterAbort);
    }
  }

  return { send, baseUrl: config.baseUrl };
}

function describe(cause: unknown): string {
  if (cause instanceof Error) return cause.message;
  return String(cause);
}

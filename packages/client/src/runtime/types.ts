/**
 * The vocabulary the generated client is written in.
 *
 * Mirrors `anuvritti.shared.result` on the server: expected failures are values, not
 * exceptions, so every call site is made to say what it does when the network is gone.
 * The alternative - `throw` - reads as if failure is exceptional, and on a phone in a
 * basement it is the normal case.
 */

/** A device bearer token. Opaque, 256 bits, prefixed `anv_`. */
export type DeviceToken = string & { readonly __deviceToken: unique symbol };

/**
 * Why a call did not produce a value.
 *
 * A discriminated union rather than an error class, because the distinction that matters
 * is not "what went wrong" but "what should the queue do about it": `offline` and `timeout`
 * are worth retrying and `api` at 4xx never is. Collapsing them into `Error` puts that
 * decision behind string matching on a message.
 */
export type Failure =
  | {
      readonly kind: "api";
      readonly status: number;
      readonly code: string;
      readonly message: string;
      readonly details: Record<string, unknown>;
    }
  | { readonly kind: "offline"; readonly message: string }
  | { readonly kind: "timeout"; readonly message: string }
  | { readonly kind: "malformed"; readonly status: number; readonly message: string };

/** Success or failure, and nothing in between. */
export type Result<T, E = Failure> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

export function ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

export function err<E>(error: E): Result<never, E> {
  return { ok: false, error };
}

/**
 * Whether trying again could plausibly work.
 *
 * The whole retry policy, in one readable function, on purpose. Anything that is a 4xx is
 * the client's own fault and will fail identically forever; `429` and `5xx` are the server
 * asking for time. `offline` and `timeout` never reached the server at all - and because
 * captures carry an `Idempotency-Key`, retrying one that *did* land is safe.
 */
export function isRetryable(failure: Failure): boolean {
  switch (failure.kind) {
    case "offline":
    case "timeout":
      return true;
    case "malformed":
      return failure.status >= 500;
    case "api":
      return failure.status === 429 || failure.status >= 500;
    default: {
      const exhaustive: never = failure;
      return exhaustive;
    }
  }
}

/** Options every call accepts. */
export interface CallOptions {
  /** Abort the request from outside - a screen closing, a pull-to-refresh replaced. */
  readonly signal?: AbortSignal;
  /** Override the transport's default, in milliseconds. */
  readonly timeoutMs?: number;
}

/** Options a capture accepts, because a capture can be replayed. */
export interface RequestOptions extends CallOptions {
  /**
   * Makes a replay safe (TASK-509). The same key with the same body returns the first
   * response verbatim; the same key with a different body is a `CONFLICT`.
   */
  readonly idempotencyKey?: string;
}

/**
 * Where the device token lives.
 *
 * A port, because the answer differs by platform and none of them belongs in this package:
 * the phone uses the platform keychain (shared with the share extension via an App Group),
 * a test uses memory, and a script uses an environment variable.
 */
export interface TokenStore {
  read(): Promise<string | null>;
  write(token: string): Promise<void>;
  clear(): Promise<void>;
}

/** Time as an input, never an ambient global - the same rule the server keeps. */
export interface Clock {
  now(): number;
}

/** Randomness as an input, for backoff jitter and idempotency keys. */
export interface Random {
  /** A float in [0, 1). */
  next(): number;
  /** A fresh idempotency key. On device this is `expo-crypto`'s `randomUUID`. */
  id(): string;
}

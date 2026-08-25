/**
 * `@anuvritti/client` — the typed client, generated from the wire contract.
 *
 * Everything under `generated/` came from `docs/contracts/openapi.yaml`. Everything under
 * `runtime/` is written by hand and reviewed like any other code, because it is where the
 * decisions live: how a failure is classified, where the token is kept, what happens when
 * there is no signal, and which numbers an interface is allowed to see.
 *
 * Zero dependencies, and zero build step: Node strips the types and React Native's bundler
 * does the same, so what runs is what is written.
 */

export * from "./generated/contract.ts";

export { createTransport, DEFAULT_TIMEOUT_MS } from "./runtime/transport.ts";
export type { Request, Transport, TransportConfig } from "./runtime/transport.ts";

export { createContractClient } from "./runtime/client.ts";

export { createSession, memoryTokenStore } from "./runtime/session.ts";
export type { Session } from "./runtime/session.ts";

export {
  BASE_BACKOFF_MS,
  MAX_BACKOFF_MS,
  backoffMs,
  createQueue,
  memoryQueueStore,
} from "./runtime/queue.ts";
export type {
  CaptureQueue,
  DrainReport,
  QueueConfig,
  QueueStore,
  QueueableOperation,
  QueuedCapture,
} from "./runtime/queue.ts";

export { err, isRetryable, ok } from "./runtime/types.ts";
export type { Clock, DeviceToken, Failure, Random, TokenStore } from "./runtime/types.ts";

export {
  asElapsed,
  compareInstants,
  nearness,
  newestFirst,
  savedSentence,
} from "./runtime/time.ts";

export {
  LOW_CONFIDENCE,
  ageRangeOf,
  ageRangeSaid,
  categoryOf,
  intentOf,
  isStated,
  isUncertain,
} from "./runtime/attributed.ts";
export type { Inferred } from "./runtime/attributed.ts";

export {
  INTENT_SAID,
  NEXT_INTENT,
  correctIntent,
  intentCycle,
  nextIntent,
} from "./runtime/correction.ts";
export type { Correction } from "./runtime/correction.ts";

import type { Contract } from "./generated/contract.ts";
import { createContractClient } from "./runtime/client.ts";
import { createSession } from "./runtime/session.ts";
import type { Session } from "./runtime/session.ts";
import { createTransport } from "./runtime/transport.ts";
import type { TransportConfig } from "./runtime/transport.ts";

export interface Anuvritti {
  readonly api: Contract;
  readonly session: Session;
}

/** The one call an application makes to get a working, paired-or-pairable client. */
export function createClient(config: TransportConfig): Anuvritti {
  const api = createContractClient(createTransport(config));
  return { api, session: createSession(api, config.tokens) };
}

/**
 * The client, assembled from the generated operation table.
 *
 * There is one function here that builds every method, rather than twenty-one hand-written
 * methods, because a hand-written method is a place the contract and the client can differ.
 * Add an operation to `docs/contracts/openapi.yaml`, regenerate, and the method exists with
 * the right shape; delete one and the method is gone and every call site fails to compile.
 */

import type { Contract, OperationName } from "../generated/contract.ts";
import { OPERATIONS } from "../generated/contract.ts";
import type { Request, Transport } from "./transport.ts";
import type { RequestOptions, Result } from "./types.ts";

/** Media downloads are the one operation whose response is not JSON. */
const BYTE_OPERATIONS: ReadonlySet<string> = new Set(["downloadMedia"]);

interface Descriptor {
  readonly method: string;
  readonly path: string;
  readonly pathParams: readonly string[];
  readonly queryParams: readonly string[];
  readonly hasBody: boolean;
  readonly idempotent: boolean;
  readonly open: boolean;
}

/**
 * Positional arguments in, one request out.
 *
 * The generated `Contract` interface declares the argument order - path parameters, then
 * body, then query, then options - so this only has to consume them in the same order. Any
 * disagreement is a compile error at the call site rather than a wrong URL at runtime.
 */
function toRequest(name: string, descriptor: Descriptor, args: readonly unknown[]): Request {
  let index = 0;
  let path = descriptor.path;
  for (const parameter of descriptor.pathParams) {
    path = path.replace(`{${parameter}}`, encodeURIComponent(String(args[index++])));
  }

  const body = descriptor.hasBody ? args[index++] : undefined;

  let query: Record<string, unknown> | undefined;
  if (descriptor.queryParams.length > 0) {
    const supplied = args[index++] as Record<string, unknown> | undefined;
    if (supplied) {
      query = {};
      for (const parameter of descriptor.queryParams) {
        // The generated interface names query fields in camelCase; the wire uses the
        // contract's own spelling. Convert here so neither side has to know about the other.
        const camel = parameter.replace(/_(.)/g, (_, c: string) => c.toUpperCase());
        if (supplied[camel] !== undefined) query[parameter] = supplied[camel];
      }
    }
  }

  const options = (args[index] ?? {}) as RequestOptions;
  const headers: Record<string, string> = {};
  if (descriptor.idempotent && options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  return {
    method: descriptor.method,
    path,
    query,
    body,
    headers,
    open: descriptor.open,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
    expect: BYTE_OPERATIONS.has(name) ? "bytes" : "json",
  };
}

/** Build the client. Every method on it came from the contract. */
export function createContractClient(transport: Transport): Contract {
  const methods: Record<string, (...args: unknown[]) => Promise<Result<unknown>>> = {};

  for (const [name, descriptor] of Object.entries(OPERATIONS) as [OperationName, Descriptor][]) {
    methods[name] = (...args: unknown[]) => transport.send(toRequest(name, descriptor, args));
  }

  return methods as unknown as Contract;
}

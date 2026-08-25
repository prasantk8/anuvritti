/**
 * Pairing, from the phone's side.
 *
 * Bootstrap and claim are the only two calls that work without a token, and both of them
 * return one. This module is what turns that response into a paired device: it writes the
 * token to the store and every later call finds it there.
 *
 * The token is handled in exactly one place on purpose. Anywhere else that read a token out
 * of a response body would be a second copy to forget to protect.
 */

import type { Bootstrap, Claimed, Contract, CreateFamily } from "../generated/contract.ts";
import type { Result, TokenStore } from "./types.ts";
import { err, ok } from "./types.ts";

export interface Session {
  /** Create the family and pair this device with it, in one call. */
  bootstrap(body: CreateFamily): Promise<Result<Bootstrap>>;
  /** Pair with a family that already exists, using a code read off another device. */
  pair(code: string, deviceName: string): Promise<Result<Claimed>>;
  /** Whether this device holds a token. Not whether the token still works. */
  isPaired(): Promise<boolean>;
  /** Forget the token. What "sign out" means when there is no account to sign out of. */
  forget(): Promise<void>;
}

export function createSession(api: Contract, tokens: TokenStore): Session {
  async function bootstrap(body: CreateFamily): Promise<Result<Bootstrap>> {
    const result = await api.bootstrapFamily(body);
    if (!result.ok) return result;

    const token = result.value.device.token;
    if (!token) {
      // The server promised a token and did not send one. Reporting success here would
      // leave a device that believes it is paired and cannot make a single call.
      return err({
        kind: "malformed",
        status: 201,
        message: "the family was created but no device token came back",
      });
    }
    await tokens.write(token);
    return ok(result.value);
  }

  async function pair(code: string, deviceName: string): Promise<Result<Claimed>> {
    const result = await api.claimPairing({ code, device_name: deviceName });
    if (!result.ok) return result;

    const token = result.value.device.token;
    if (!token) {
      return err({
        kind: "malformed",
        status: 201,
        message: "the device was paired but no token came back",
      });
    }
    await tokens.write(token);
    return ok(result.value);
  }

  return {
    bootstrap,
    pair,
    isPaired: async () => (await tokens.read()) !== null,
    forget: () => tokens.clear(),
  };
}

/**
 * A token held in memory. For tests, and for nothing else.
 *
 * On device the store is the platform keychain. Naming this one `memory` rather than
 * `default` is deliberate: nobody should be able to reach for it by accident.
 */
export function memoryTokenStore(initial: string | null = null): TokenStore {
  let token = initial;
  return {
    async read() {
      return token;
    },
    async write(value) {
      token = value;
    },
    async clear() {
      token = null;
    },
  };
}

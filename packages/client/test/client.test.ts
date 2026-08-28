/**
 * TASK-505 — the generated client, its transport, and pairing.
 *
 * These test the request as much as the response. A client's interesting failures are
 * almost all outbound: the token that did not get attached, the query parameter spelled in
 * the wrong case, the idempotency key silently dropped.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  createClient,
  createContractClient,
  createTransport,
  memoryTokenStore,
  OPERATIONS,
} from "../src/index.ts";
import { aSpark, apiError, serverDouble } from "./support.ts";

const BASE = "https://anuvritti.local";

function clientWith(server: ReturnType<typeof serverDouble>, token: string | null = "anv_token") {
  const tokens = memoryTokenStore(token);
  return {
    tokens,
    ...createClient({ baseUrl: BASE, tokens, fetch: server.fetch, timeoutMs: 50 }),
  };
}

describe("the generated surface", () => {
  it("has one method for every documented operation and no others", () => {
    const server = serverDouble();
    const api = createContractClient(
      createTransport({ baseUrl: BASE, tokens: memoryTokenStore(), fetch: server.fetch })
    );
    const methods = Object.keys(api).sort();
    assert.deepEqual(methods, Object.keys(OPERATIONS).sort());

    // A deliberate tripwire. Changing this number should be a decision someone made about
    // the API's surface, not something that drifted in with a regeneration.
    // 22 at v0.2.0; 26 when voice arrived; 27 with the annual film (TASK-716).
    assert.equal(methods.length, 27);
  });

  it("builds the url from the contract's own path template", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { json: aSpark() });
    await clientWith(server).api.getSpark("sp-1");
    assert.equal(server.lastCall()?.url, `${BASE}/v1/sparks/sp-1`);
  });

  it("escapes a path parameter rather than pasting it into the url", async () => {
    const server = serverDouble();
    server.on("*", { json: aSpark() });
    await clientWith(server).api.getSpark("../families/fam-2");
    assert.ok(server.lastCall()?.url.includes("..%2Ffamilies%2Ffam-2"));
  });

  it("spells query parameters the way the wire does, not the way TypeScript does", async () => {
    const server = serverDouble();
    server.on("GET /sparks", { json: [] });
    await clientWith(server).api.searchSparks({ childId: "ch-1", q: "rocket" });

    const url = new URL(server.lastCall()!.url);
    assert.equal(url.searchParams.get("child_id"), "ch-1");
    assert.equal(url.searchParams.get("q"), "rocket");
    assert.equal(url.searchParams.get("childId"), null);
  });

  it("omits a query parameter that was not supplied", async () => {
    const server = serverDouble();
    server.on("GET /sparks", { json: [] });
    await clientWith(server).api.searchSparks({ q: "rocket" });
    assert.equal(new URL(server.lastCall()!.url).search, "?q=rocket");
  });

  it("sends no identity in the body, because the token already carries it", async () => {
    const server = serverDouble();
    server.on("POST /sparks", { status: 201, json: aSpark() });
    await clientWith(server).api.captureSpark({ source: { kind: "TEXT", text: "a thought" } });

    const body = server.lastCall()?.body as Record<string, unknown>;
    assert.deepEqual(Object.keys(body), ["source"]);
  });
});

describe("the token", () => {
  it("is attached to every call that needs one", async () => {
    const server = serverDouble();
    server.on("GET /devices", { json: [] });
    await clientWith(server).api.listDevices();
    assert.equal(server.lastCall()?.headers.Authorization, "Bearer anv_token");
  });

  it("is not attached to the two calls that exist to obtain one", async () => {
    const server = serverDouble();
    server.on("POST /pairing/claim", { status: 201, json: { device: { token: "anv_new" } } });
    await clientWith(server, null).api.claimPairing({ code: "ABCD-1234", device_name: "phone" });
    assert.equal(server.lastCall()?.headers.Authorization, undefined);
  });

  it("turns an unpaired device into UNAUTHENTICATED without touching the network", async () => {
    const server = serverDouble();
    const result = await clientWith(server, null).api.listDevices();

    assert.equal(result.ok, false);
    assert.equal(result.ok === false && result.error.kind, "api");
    assert.equal(result.ok === false && result.error.kind === "api" && result.error.code, "UNAUTHENTICATED");
    assert.equal(server.calls.length, 0, "an unpaired device is not offline; it must not retry");
  });
});

describe("failures are classified, not thrown", () => {
  it("reads the error envelope the contract fixes", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { status: 404, json: apiError("SPARK_NOT_FOUND", "no such") });
    const result = await clientWith(server).api.getSpark("sp-1");

    assert.equal(result.ok, false);
    if (result.ok) return;
    assert.equal(result.error.kind, "api");
    assert.equal(result.error.kind === "api" && result.error.code, "SPARK_NOT_FOUND");
    assert.equal(result.error.kind === "api" && result.error.status, 404);
  });

  it("does not invent a code when the response is not our envelope", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { status: 502, text: "<html>bad gateway</html>" });
    const result = await clientWith(server).api.getSpark("sp-1");

    assert.equal(result.ok === false && result.error.kind, "malformed");
  });

  it("reports a dead network as offline, not as an API error", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { networkError: "Network request failed" });
    const result = await clientWith(server).api.getSpark("sp-1");

    assert.equal(result.ok === false && result.error.kind, "offline");
  });

  it("gives up rather than hanging past the capture budget", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { hang: true });
    const result = await clientWith(server).api.getSpark("sp-1");

    assert.equal(result.ok === false && result.error.kind, "timeout");
  });

  it("distinguishes a caller's own cancellation from a timeout", async () => {
    const server = serverDouble();
    server.on("GET /sparks/sp-1", { hang: true });
    const controller = new AbortController();
    const pending = clientWith(server).api.getSpark("sp-1", { signal: controller.signal });
    controller.abort();

    const result = await pending;
    assert.equal(result.ok === false && result.error.kind, "timeout");
    assert.match(
      result.ok === false ? result.error.message : "",
      /cancelled/,
      "a closed screen is not a network problem"
    );
  });
});

describe("idempotency", () => {
  it("sends the key when a capture is given one", async () => {
    const server = serverDouble();
    server.on("POST /sparks", { status: 201, json: aSpark() });
    await clientWith(server).api.captureSpark(
      { source: { kind: "TEXT", text: "x" } },
      { idempotencyKey: "queue-1" }
    );
    assert.equal(server.lastCall()?.headers["Idempotency-Key"], "queue-1");
  });

  it("sends no key when none was given, rather than inventing one", async () => {
    const server = serverDouble();
    server.on("POST /sparks", { status: 201, json: aSpark() });
    await clientWith(server).api.captureSpark({ source: { kind: "TEXT", text: "x" } });
    assert.equal(server.lastCall()?.headers["Idempotency-Key"], undefined);
  });

  it("is offered on exactly the operations the contract marks replayable", () => {
    const replayable = Object.entries(OPERATIONS)
      .filter(([, descriptor]) => descriptor.idempotent)
      .map(([name]) => name)
      .sort();
    assert.deepEqual(replayable, [
      "captureLittleThing",
      "captureRightNow",
      "captureSpark",
      // Keeping a recording is replayable for the same reason capture is: the phone that
      // held the button has already lost the audio buffer, so a retry that creates a
      // second note would be the only copy of the mistake.
      "keepVoiceNote",
      "markAsDone",
    ]);
  });
});

describe("pairing", () => {
  it("keeps the token from bootstrap so the next call is authenticated", async () => {
    const server = serverDouble();
    server.on("POST /families", {
      status: 201,
      json: { id: "fam-1", name: "Ours", members: [], children: [], device: { token: "anv_fresh" } },
    });
    server.on("GET /devices", { json: [] });

    const client = clientWith(server, null);
    const paired = await client.session.bootstrap({ name: "Ours", owner_display_name: "Papa" });
    assert.equal(paired.ok, true);

    await client.api.listDevices();
    assert.equal(server.lastCall()?.headers.Authorization, "Bearer anv_fresh");
  });

  it("refuses to report success when the token did not come back", async () => {
    const server = serverDouble();
    server.on("POST /families", {
      status: 201,
      json: { id: "fam-1", name: "Ours", members: [], children: [], device: {} },
    });

    const client = clientWith(server, null);
    const paired = await client.session.bootstrap({ name: "Ours", owner_display_name: "Papa" });

    assert.equal(paired.ok, false, "a device that thinks it is paired and cannot call is worse");
    assert.equal(await client.session.isPaired(), false);
  });

  it("keeps the token from claiming a code", async () => {
    const server = serverDouble();
    server.on("POST /pairing/claim", {
      status: 201,
      json: { device: { token: "anv_claimed" }, family: { id: "fam-1" } },
    });

    const client = clientWith(server, null);
    await client.session.pair("ABCD-1234", "Mum's phone");
    assert.equal(await client.tokens.read(), "anv_claimed");
  });

  it("forgetting the token leaves nothing behind", async () => {
    const server = serverDouble();
    const client = clientWith(server, "anv_token");
    await client.session.forget();
    assert.equal(await client.tokens.read(), null);
    assert.equal(await client.session.isPaired(), false);
  });

  it("does not store a token when pairing was refused", async () => {
    const server = serverDouble();
    server.on("POST /pairing/claim", { status: 401, json: apiError("PAIRING_FAILED") });

    const client = clientWith(server, null);
    const result = await client.session.pair("ZZZZ-9999", "attacker");
    assert.equal(result.ok, false);
    assert.equal(await client.tokens.read(), null);
  });
});

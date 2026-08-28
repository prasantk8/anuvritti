/**
 * The golden path, driven by the real client against a real server (TASK-513).
 *
 * `tests/e2e/test_golden_path.py` proves the server implements PRD §48. This proves the
 * *phone* does — the same story, over a real socket, through the generated client, with
 * nothing stubbed. The two together are the thesis end to end.
 *
 * It runs in two phases because eight months have to pass in the middle, and the only
 * honest way to do that is for the harness to move the server's clock between them. State
 * crosses the gap in a file, exactly as it would cross an app being closed and reopened.
 *
 * Run by `tests/e2e/test_the_app_against_the_server.py`, which starts the server.
 *
 *   node golden-path.ts <phase> <baseUrl> <stateFile>
 */

import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";

import type { TokenStore } from "../../src/index.ts";
import { createClient, createQueue, memoryQueueStore } from "../../src/index.ts";

const [, , phase, baseUrl, stateFile] = process.argv;

interface State {
  token: string;
  familyId: string;
  childId: string;
  sparkId: string;
  /** The recording behind the why. Phase two plays it back eight months later. */
  voiceMediaId: string;
}

function loadState(): State {
  return JSON.parse(readFileSync(stateFile!, "utf8")) as State;
}

function saveState(state: State): void {
  writeFileSync(stateFile!, JSON.stringify(state, null, 2));
}

/** A token store that survives the app being closed, the way the keychain does. */
function fileBackedTokens(initial: string | null): TokenStore & { current: string | null } {
  const store = {
    current: initial,
    async read() {
      return store.current;
    },
    async write(token: string) {
      store.current = token;
    },
    async clear() {
      store.current = null;
    },
  };
  return store;
}

/**
 * A deterministic 4.2-second PCM voice memo.
 *
 * Deterministic, so phase two can assert the bytes came back *unchanged* - which is the
 * only way to prove nothing trimmed, normalised or re-encoded them on the way through
 * (PRD §24). A random blob would prove only that something of the right length came back.
 */
function clip(): Uint8Array {
  const sampleRate = 48_000;
  const samples = Math.round(sampleRate * 4.2);
  const bytes = new Uint8Array(44 + samples * 2);
  const view = new DataView(bytes.buffer);
  const ascii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  ascii(0, "RIFF");
  view.setUint32(4, bytes.length - 8, true);
  ascii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, samples * 2, true);
  return bytes;
}

function say(line: string): void {
  console.log(`  ${line}`);
}

function unwrap<T>(result: { ok: true; value: T } | { ok: false; error: unknown }, what: string): T {
  if (!result.ok) throw new Error(`${what} failed: ${JSON.stringify(result.error)}`);
  return result.value;
}

// ---------------------------------------------------------------- phase one
async function january(): Promise<void> {
  const tokens = fileBackedTokens(null);
  const { api, session } = createClient({ baseUrl: baseUrl!, tokens });

  // --- The family exists, and this phone is paired by the act of creating it. ----------
  const family = unwrap(
    await session.bootstrap({ name: "Our family", owner_display_name: "Papa" }),
    "bootstrap"
  );
  assert.ok(family.device.token?.startsWith("anv_"), "bootstrap must pair the founding device");
  say(`paired: ${family.name}`);

  const child = unwrap(
    await api.addChild(family.id, { display_name: "Aarav", date_of_birth: "2021-06-01" }),
    "addChild"
  );
  assert.equal(child.age_years, 4, "he is four in January");

  // --- NOTICE. He shares a reel on the underground, so it goes to the queue first. ------
  //
  // This is the part a server-side test cannot reach: the phone said "Saved." before any
  // request was made, and the request happened afterwards.
  const store = memoryQueueStore();
  let sent = false;
  const queue = createQueue({
    store,
    clock: { now: () => 1_768_000_000_000 },
    random: { next: () => 0.5, id: () => "queued-capture-0001" },
    send: (entry) =>
      api.captureSpark(entry.body as never, { idempotencyKey: entry.id }).then((result) => {
        sent = true;
        return result;
      }),
  });

  await queue.enqueue("captureSpark", {
    subject_child_id: child.id,
    source: {
      kind: "URL",
      url: "https://instagram.com/reel/balloon-rocket",
      creator: "@sciencedad",
      title: "Balloon rocket experiment - ages 5-8",
    },
  });
  assert.equal(sent, false, "capture must not wait for a network");
  say("saved to the queue with no network");

  // --- The signal comes back on the escalator. ------------------------------------------
  const first = await queue.drain();
  assert.equal(first.sent, 1);
  assert.equal((await queue.pending()).length, 0);

  const sparks = unwrap(await api.searchSparks({ limit: 25 }), "searchSparks");
  assert.equal(sparks.length, 1, "one capture, one Spark");

  const spark = sparks[0]!;
  assert.equal(spark.intent.value, "DO");
  assert.equal(spark.intent.source, "AI", "the machine's guess must say it is a guess");
  assert.deepEqual(spark.age_range?.value, { min_years: 5, max_years: 8 });
  say(`understood: to do together, ${JSON.stringify(spark.age_range?.value)}`);

  // The whole point of TASK-507, on the first response a phone ever receives.
  assert.equal(spark.saved, "today", "elapsed time arrives as a phrase");
  assert.ok(!/\d+ days/.test(spark.saved), "and never as a count");

  // --- The queue replays anyway, because the phone never learned the first attempt landed.
  await queue.enqueue("captureSpark", {
    subject_child_id: child.id,
    source: { kind: "TEXT", text: "the same thing again" },
  });
  const replayed = unwrap(
    await api.captureSpark(
      {
        subject_child_id: child.id,
        source: {
          kind: "URL",
          url: "https://instagram.com/reel/balloon-rocket",
          creator: "@sciencedad",
          title: "Balloon rocket experiment - ages 5-8",
        },
      },
      { idempotencyKey: "queued-capture-0001" }
    ),
    "replay"
  );
  assert.equal(replayed.id, spark.id, "a replayed key returns the original Spark");
  say("replay produced no duplicate");

  // --- REMEMBER. Five seconds of why, in his own voice. ---------------------------------
  //
  // The whole of Phase 6 through the real wire: the bytes go up, the note says what they
  // are, and the transcript the handset heard arrives with them - carrying machine
  // provenance whatever the phone believes about itself (PRD §8.7).
  const audio = new FormData();
  audio.append("file", new Blob([clip()], { type: "audio/wav" }), "why.wav");
  const media = unwrap(await api.uploadMedia(audio), "uploadMedia");

  const kept = unwrap(
    await api.keepVoiceNote(
      {
        media_id: media.id,
        // Four and a bit seconds. PRD §12 says five is what a why usually is; nothing
        // anywhere in this stack requires it to be.
        duration_seconds: 4.2,
        heard_text: "I want to see his face when it launches.",
        heard_confidence: 0.7,
      },
      { idempotencyKey: "voice-0001" }
    ),
    "keepVoiceNote"
  );
  assert.equal(kept.duration_seconds, 4.2);
  assert.equal(kept.transcript?.source, "AI", "the phone's own reading is still a reading");
  assert.ok(kept.transcript!.confidence < 1, "and it never claims certainty");
  say(`recorded: ${kept.duration_seconds}s, heard as "${kept.transcript?.text}"`);

  const withWhy = unwrap(
    await api.recordWhy(spark.id, {
      text: "I want to see his face when it launches.",
      voice_media_id: media.id,
    }),
    "recordWhy"
  );
  assert.equal(withWhy.why?.text, "I want to see his face when it launches.");
  assert.equal(withWhy.why?.voice?.media_id, media.id, "the why carries the recording itself");

  // --- Nothing is suggested while it is still fresh. -----------------------------------
  assert.deepEqual(
    unwrap(await api.worthBringingBack(), "worthBringingBack"),
    [],
    "a Spark saved today has not been forgotten yet"
  );
  say("nothing brought back - it is not forgotten yet");

  saveState({
    token: tokens.current!,
    familyId: family.id,
    childId: child.id,
    sparkId: spark.id,
    voiceMediaId: media.id,
  });
}

// ---------------------------------------------------------------- phase two
async function september(): Promise<void> {
  const state = loadState();
  const { api } = createClient({ baseUrl: baseUrl!, tokens: fileBackedTokens(state.token) });

  const family = unwrap(await api.getFamily(state.familyId), "getFamily");
  assert.equal(family.children[0]?.age_years, 5, "he has grown into it");

  // --- RETURN. Eight months later, the product brings it back. --------------------------
  const suggestions = unwrap(await api.worthBringingBack(), "worthBringingBack");
  assert.ok(suggestions.length > 0, "this is exactly what should come back");

  const brought = suggestions.find((s) => s.spark.id === state.sparkId);
  assert.ok(brought, "the balloon rocket is what came back");

  assert.equal(brought.elapsed, "8 months ago");
  assert.match(brought.reason, /You saved this 8 months ago\./);
  assert.match(brought.reason, /I want to see his face when it launches\./);
  assert.match(brought.reason, /Aarav may be ready now\./);
  say(`brought back: "${brought.reason}"`);

  // The client is never handed the number, so no interface can render one.
  const asText = JSON.stringify(brought);
  assert.ok(!asText.includes("days_since"), "no day count on the wire");
  assert.ok(!asText.includes("247"), "and not smuggled in as a value either");
  assert.ok(!asText.includes('"score"'), "no score about a family's own child");

  // --- The recording is still the artifact, eight months on. ---------------------------
  //
  // Not "there is a row saying he said something". The bytes come back, byte for byte,
  // and the words are still labelled as the machine's reading of them.
  assert.equal(brought.spark.why?.voice?.media_id, state.voiceMediaId, "the why still has it");

  const heard = brought.spark.why!.voice!;
  assert.equal(heard.duration_seconds, 4.2, "measured, not described - TASK-707 cuts against it");
  assert.equal(heard.transcript?.source, "AI");

  const audio = unwrap(await api.downloadMedia(state.voiceMediaId), "downloadMedia");
  assert.deepEqual([...audio], [...clip()], "his actual voice, unchanged and untrimmed");
  say(`played back: ${audio.byteLength} bytes, still his own voice`);

  // A parent fixes what the machine misheard. Permanent, and the audio is untouched.
  const corrected = unwrap(
    await api.correctTranscript(state.voiceMediaId, {
      text: "I want to see his face when it goes up.",
    }),
    "correctTranscript"
  );
  assert.equal(corrected.transcript?.source, "HUMAN", "a person said so; that is the end of it");
  assert.equal(corrected.duration_seconds, 4.2, "and the recording is exactly as long");

  const vault = unwrap(await api.listVoiceNotes(), "listVoiceNotes");
  assert.deepEqual(Object.keys(vault), ["recordings"], "the vault has no count of any kind");
  assert.equal(vault.recordings.length, 1);
  say("the vault holds it, and says nothing about how many there are");

  // --- LIVE. ---------------------------------------------------------------------------
  const planned = unwrap(
    await api.respondToSuggestion(state.sparkId, { response: "lets_do_it" }),
    "respond"
  );
  assert.equal(planned.status, "PLANNED");

  const moment = unwrap(
    await api.markAsDone(
      state.sparkId,
      { reflection: "It hit the ceiling. He screamed. We did it four more times." },
      { idempotencyKey: "done-0001" }
    ),
    "markAsDone"
  );
  assert.equal(moment.spark_id, state.sparkId);
  say(`lived: ${moment.happened_on}`);

  // The one place an offline replay would otherwise produce a 409 for something that worked.
  const again = unwrap(
    await api.markAsDone(
      state.sparkId,
      { reflection: "It hit the ceiling. He screamed. We did it four more times." },
      { idempotencyKey: "done-0001" }
    ),
    "markAsDone replay"
  );
  assert.equal(again.id, moment.id, "replaying 'done' returns the same Moment");

  const lived = unwrap(await api.getSpark(state.sparkId), "getSpark");
  assert.equal(lived.status, "EXPERIENCED");

  // --- And the family can take all of it and leave. -------------------------------------
  const archive = unwrap(await api.exportFamily(state.familyId), "export");
  assert.equal(archive.moments?.length, 1);
  const recordings = (archive as { recordings?: { transcript?: { source: string } }[] }).recordings;
  assert.equal(recordings?.length, 1, "the recording is in the archive they take with them");
  assert.equal(
    recordings?.[0]?.transcript?.source,
    "HUMAN",
    "and twenty years from now they can still tell which sentences he actually said"
  );
  say("exported, and it is all there");
}

const phases: Record<string, () => Promise<void>> = { january, september };

const run = phases[phase ?? ""];
if (!run) {
  console.error(`unknown phase ${phase ?? ""}`);
  process.exit(2);
}

run()
  .then(() => {
    console.log(`  ${phase} ok`);
    process.exit(0);
  })
  .catch((error: unknown) => {
    console.error(`  ${phase} FAILED:`, error instanceof Error ? error.message : error);
    process.exit(1);
  });

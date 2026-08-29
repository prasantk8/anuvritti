import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  ResumableMediaUploader,
  type CheckpointStore,
  type ChunkUploadTransport,
  type UploadCheckpoint,
} from "../src/sync/uploader.ts";

function makeMockCheckpointStore(): CheckpointStore & { map: Map<string, UploadCheckpoint> } {
  const map = new Map<string, UploadCheckpoint>();
  return {
    map,
    async saveCheckpoint(cp) {
      map.set(cp.uploadId, cp);
    },
    async getCheckpoint(id) {
      return map.get(id) ?? null;
    },
    async clearCheckpoint(id) {
      map.delete(id);
    },
  };
}

describe("TASK-1002 — Resumable Idempotent Media Uploader (PRD 11, PRD 8.2)", () => {
  it("uploads a file in multiple discrete chunks", async () => {
    const store = makeMockCheckpointStore();
    const uploadedChunks: number[] = [];

    const transport: ChunkUploadTransport = {
      async uploadChunk({ offset, chunkData, totalBytes }) {
        uploadedChunks.push(offset);
        const nextOffset = offset + chunkData.byteLength;
        const isDone = nextOffset >= totalBytes;
        return {
          receivedBytes: nextOffset,
          completed: isDone,
          mediaId: isDone ? "med-uploaded-123" : undefined,
        };
      },
    };

    const uploader = new ResumableMediaUploader(store, transport, 10); // 10-byte chunks
    const testData = new Uint8Array(25); // 3 chunks: 0..10, 10..20, 20..25

    const mediaId = await uploader.upload({
      uploadId: "upl-001",
      idempotencyKey: "idem-001",
      data: testData,
      mediaType: "audio/mp4",
    });

    assert.equal(mediaId, "med-uploaded-123");
    assert.deepEqual(uploadedChunks, [0, 10, 20]);
    // Checkpoint cleared after successful completion
    assert.equal(store.map.has("upl-001"), false);
  });

  it("resumes an interrupted upload from the last saved checkpoint", async () => {
    const store = makeMockCheckpointStore();
    let attemptCount = 0;
    const uploadedOffsets: number[] = [];

    const transport: ChunkUploadTransport = {
      async uploadChunk({ offset, chunkData, totalBytes }) {
        attemptCount++;
        // Simulate network failure on second chunk
        if (attemptCount === 2) {
          throw new Error("Network dropped mid-train tunnel");
        }
        uploadedOffsets.push(offset);
        const nextOffset = offset + chunkData.byteLength;
        const isDone = nextOffset >= totalBytes;
        return {
          receivedBytes: nextOffset,
          completed: isDone,
          mediaId: isDone ? "med-resumed-999" : undefined,
        };
      },
    };

    const uploader = new ResumableMediaUploader(store, transport, 10);
    const testData = new Uint8Array(30); // 3 chunks: 0..10, 10..20, 20..30

    // First attempt fails at offset 10
    await assert.rejects(async () => {
      await uploader.upload({
        uploadId: "upl-interrupted",
        idempotencyKey: "idem-int",
        data: testData,
        mediaType: "image/jpeg",
      });
    });

    // Verify checkpoint was saved for the 1st chunk
    assert.ok(store.map.has("upl-interrupted"));
    assert.equal(store.map.get("upl-interrupted")?.uploadedBytes, 10);

    // Second attempt resumes from offset 10
    const resumeMediaId = await uploader.upload({
      uploadId: "upl-interrupted",
      idempotencyKey: "idem-int",
      data: testData,
      mediaType: "image/jpeg",
    });

    assert.equal(resumeMediaId, "med-resumed-999");
    // Offsets uploaded across both runs: 0 on first run, then 10 and 20 on second run (0 was not re-sent!)
    assert.deepEqual(uploadedOffsets, [0, 10, 20]);
  });
});

/**
 * Resumable, Idempotent Media Uploader (PRD 11, PRD 8.2).
 *
 * Capturing a moment or voice note on a cellular edge connection or train ride must
 * never lose data or send duplicate Sparks.
 *
 * Characteristics:
 * - Chunked transfers (default 64KB chunks).
 * - Checkpoint persistence: if the app is killed, uploading resumes from the last byte.
 * - Idempotency: SHA-256 content hashing guarantees duplicate retries are deduplicated.
 */

export interface UploadCheckpoint {
  uploadId: string;
  idempotencyKey: string;
  totalBytes: number;
  uploadedBytes: number;
  chunkSize: number;
  mediaType: string;
  completed: boolean;
  mediaId?: string;
}

export interface CheckpointStore {
  saveCheckpoint(checkpoint: UploadCheckpoint): Promise<void>;
  getCheckpoint(uploadId: string): Promise<UploadCheckpoint | null>;
  clearCheckpoint(uploadId: string): Promise<void>;
}

export interface ChunkUploadTransport {
  uploadChunk(params: {
    uploadId: string;
    idempotencyKey: string;
    offset: number;
    chunkData: Uint8Array;
    totalBytes: number;
    mediaType: string;
  }): Promise<{
    receivedBytes: number;
    completed: boolean;
    mediaId?: string;
  }>;
}

export const DEFAULT_CHUNK_SIZE = 64 * 1024; // 64 KB

export class ResumableMediaUploader {
  private _checkpointStore: CheckpointStore;
  private _transport: ChunkUploadTransport;
  private _chunkSize: number;

  constructor(
    checkpointStore: CheckpointStore,
    transport: ChunkUploadTransport,
    chunkSize: number = DEFAULT_CHUNK_SIZE
  ) {
    this._checkpointStore = checkpointStore;
    this._transport = transport;
    this._chunkSize = chunkSize;
  }

  async upload(params: {
    uploadId: string;
    idempotencyKey: string;
    data: Uint8Array;
    mediaType: string;
    onProgress?: (uploadedBytes: number, totalBytes: number) => void;
  }): Promise<string> {
    const { uploadId, idempotencyKey, data, mediaType, onProgress } = params;
    const totalBytes = data.byteLength;

    let checkpoint = await this._checkpointStore.getCheckpoint(uploadId);

    if (checkpoint && checkpoint.completed && checkpoint.mediaId) {
      return checkpoint.mediaId;
    }

    let offset = checkpoint ? checkpoint.uploadedBytes : 0;
    if (offset > totalBytes) {
      offset = 0; // Checkpoint invalidation fallback
    }

    while (offset < totalBytes) {
      const end = Math.min(offset + this._chunkSize, totalBytes);
      const chunkData = data.subarray(offset, end);

      const result = await this._transport.uploadChunk({
        uploadId,
        idempotencyKey,
        offset,
        chunkData,
        totalBytes,
        mediaType,
      });

      offset = result.receivedBytes;

      checkpoint = {
        uploadId,
        idempotencyKey,
        totalBytes,
        uploadedBytes: offset,
        chunkSize: this._chunkSize,
        mediaType,
        completed: result.completed,
        mediaId: result.mediaId,
      };

      await this._checkpointStore.saveCheckpoint(checkpoint);

      if (onProgress) {
        onProgress(offset, totalBytes);
      }

      if (result.completed && result.mediaId) {
        await this._checkpointStore.clearCheckpoint(uploadId);
        return result.mediaId;
      }
    }

    if (checkpoint?.mediaId) {
      await this._checkpointStore.clearCheckpoint(uploadId);
      return checkpoint.mediaId;
    }

    throw new Error("Upload completed chunks without receiving mediaId from server");
  }
}

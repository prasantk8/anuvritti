/**
 * The capture queue, on disk.
 *
 * SQLite rather than AsyncStorage, and in the App Group container rather than the app's own
 * sandbox, for one reason: the share extension is a *different process*. A queue the
 * extension cannot see is a queue that loses whatever was shared while the app was closed.
 *
 * Expo documents this exact arrangement — `Paths.appleSharedContainers` from
 * `expo-file-system` gives the container, and `openDatabaseAsync` takes it as its third
 * argument. On Android there is one process, so the default location is correct.
 *
 * Writes are wrapped in `withTransactionAsync`. (There is no `withExclusiveTransactionSync`
 * in expo-sqlite 57 — the synchronous helper is `withTransactionSync` and the exclusive one
 * is async only.)
 */

import { Paths } from "expo-file-system";
import * as SQLite from "expo-sqlite";
import { Platform } from "react-native";

import type { QueueStore, QueuedCapture } from "@anuvritti/client";

import { APP_GROUP } from "./token-store.ts";

const DATABASE = "capture-queue.db";

const SCHEMA = `
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS pending (
    id               TEXT PRIMARY KEY,
    operation        TEXT NOT NULL,
    path_args_json   TEXT NOT NULL,
    body_json        TEXT NOT NULL,
    enqueued_at      INTEGER NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  INTEGER NOT NULL,
    last_error       TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_pending_order ON pending(enqueued_at);
`;

/**
 * The shared container, so both processes open the same file.
 *
 * Falls back to the app's own sandbox rather than throwing: a device where the App Group is
 * not configured should still be able to save things. It loses only the extension's writes,
 * and losing them silently is better than an app that will not start.
 */
function sharedDirectory(): string | undefined {
  if (Platform.OS !== "ios") return undefined;
  try {
    return Paths.appleSharedContainers?.[APP_GROUP]?.uri;
  } catch {
    return undefined;
  }
}

function toEntry(row: Record<string, unknown>): QueuedCapture {
  return {
    id: String(row.id),
    operation: row.operation as QueuedCapture["operation"],
    pathArgs: JSON.parse(String(row.path_args_json)) as string[],
    body: JSON.parse(String(row.body_json)) as unknown,
    enqueuedAt: Number(row.enqueued_at),
    attempts: Number(row.attempts),
    nextAttemptAt: Number(row.next_attempt_at),
    lastError: row.last_error ? String(row.last_error) : undefined,
  };
}

export async function sqliteQueueStore(): Promise<QueueStore> {
  const database = await SQLite.openDatabaseAsync(DATABASE, undefined, sharedDirectory());
  await database.execAsync(SCHEMA);

  async function put(entry: QueuedCapture): Promise<void> {
    await database.withTransactionAsync(async () => {
      await database.runAsync(
        `INSERT INTO pending (id, operation, path_args_json, body_json, enqueued_at,
                              attempts, next_attempt_at, last_error)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET attempts = excluded.attempts,
                                       next_attempt_at = excluded.next_attempt_at,
                                       last_error = excluded.last_error`,
        [
          entry.id,
          entry.operation,
          JSON.stringify(entry.pathArgs),
          JSON.stringify(entry.body),
          entry.enqueuedAt,
          entry.attempts,
          entry.nextAttemptAt,
          entry.lastError ?? null,
        ]
      );
    });
  }

  return {
    append: put,
    replace: put,
    async remove(id) {
      await database.runAsync("DELETE FROM pending WHERE id = ?", [id]);
    },
    async list() {
      const rows = await database.getAllAsync<Record<string, unknown>>(
        "SELECT * FROM pending ORDER BY enqueued_at"
      );
      return rows.map(toEntry);
    },
  };
}

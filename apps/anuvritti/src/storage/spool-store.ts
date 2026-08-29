/**
 * The upload spool, on disk, and the files it is a spool of (TASK-713).
 *
 * Two adapters that belong together because they are two halves of one promise: the row
 * says a recording exists and is not yet in the archive, and the file is the recording. A
 * row without its file is a lie; a file without its row is a leak.
 *
 * ## Where the rows live
 *
 * The same SQLite file as the capture queue, in the App Group container, for the same
 * reason (`queue-store.ts`): the iOS share extension is a different process, and a share
 * that arrived while the app was closed has to be visible to the app when it opens.
 *
 * ## Where the files live
 *
 * `Paths.document`, never `Paths.cache`. `expo-audio` writes recordings into the cache
 * directory, and iOS empties that whenever it feels short of space, without warning and
 * without asking. A spool row pointing into the cache is a promise the operating system is
 * entitled to break — and the thing it would be breaking is the only copy of a parent's
 * voice. So the first thing that happens to a recording is that it is moved somewhere the
 * system may not touch.
 *
 * Verified against the installed expo-file-system@57, not from memory: `File` is a class
 * taking path segments, `file.move(destination)` updates the instance's own `uri`, `exists`
 * and `size` are properties rather than calls, and `Directory.create({ intermediates })` is
 * how a directory comes into being.
 */

import { Directory, File, Paths } from "expo-file-system";
import * as SQLite from "expo-sqlite";
import { Platform } from "react-native";

import type { Custody, Follow, SpoolStore, Spooled } from "../upload/spool.ts";
import { APP_GROUP } from "./token-store.ts";

/** The same database the capture queue uses. One file, two tables, one transaction log. */
const DATABASE = "capture-queue.db";

/** Where files wait for a network. Inside the document directory, so nothing sweeps it. */
const OUTBOX = "outbox";

const SCHEMA = `
  CREATE TABLE IF NOT EXISTS spooled (
    id               TEXT PRIMARY KEY,
    uri              TEXT NOT NULL,
    name             TEXT NOT NULL,
    mime_type        TEXT NOT NULL,
    follow_json      TEXT NOT NULL,
    spooled_at       INTEGER NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  INTEGER NOT NULL,
    media_id         TEXT,
    last_error       TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_spooled_order ON spooled(spooled_at);
`;

/** The shared container, so the share extension and the app spool into the same place. */
function sharedDirectory(): string | undefined {
  if (Platform.OS !== "ios") return undefined;
  try {
    return Paths.appleSharedContainers?.[APP_GROUP]?.uri;
  } catch {
    return undefined;
  }
}

function toEntry(row: Record<string, unknown>): Spooled {
  return {
    id: String(row.id),
    uri: String(row.uri),
    name: String(row.name),
    mimeType: String(row.mime_type),
    follow: JSON.parse(String(row.follow_json)) as Follow,
    spooledAt: Number(row.spooled_at),
    attempts: Number(row.attempts),
    nextAttemptAt: Number(row.next_attempt_at),
    mediaId: row.media_id ? String(row.media_id) : undefined,
    lastError: row.last_error ? String(row.last_error) : undefined,
  };
}

export async function sqliteSpoolStore(): Promise<SpoolStore> {
  const database = await SQLite.openDatabaseAsync(DATABASE, undefined, sharedDirectory());
  await database.execAsync(SCHEMA);

  async function put(entry: Spooled): Promise<void> {
    await database.withTransactionAsync(async () => {
      await database.runAsync(
        `INSERT INTO spooled (id, uri, name, mime_type, follow_json, spooled_at,
                              attempts, next_attempt_at, media_id, last_error)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET uri = excluded.uri,
                                       attempts = excluded.attempts,
                                       next_attempt_at = excluded.next_attempt_at,
                                       media_id = excluded.media_id,
                                       last_error = excluded.last_error`,
        [
          entry.id,
          entry.uri,
          entry.name,
          entry.mimeType,
          JSON.stringify(entry.follow),
          entry.spooledAt,
          entry.attempts,
          entry.nextAttemptAt,
          entry.mediaId ?? null,
          entry.lastError ?? null,
        ]
      );
    });
  }

  return {
    append: put,
    replace: put,
    async remove(id) {
      await database.runAsync("DELETE FROM spooled WHERE id = ?", [id]);
    },
    async list() {
      const rows = await database.getAllAsync<Record<string, unknown>>(
        "SELECT * FROM spooled ORDER BY spooled_at"
      );
      return rows.map(toEntry);
    },
  };
}

/**
 * Custody of the bytes themselves.
 *
 * `move` rather than `copy` where it can be: the recorder's file is ours already and two
 * copies of a parent's voice on one phone is a waste of the storage a family will run out
 * of. A share's file often cannot be moved — it belongs to the extension's container, or to
 * a `content://` provider on Android — so a failed move falls back to a copy, and a failed
 * copy leaves the entry pointing at the original rather than throwing. A spool row pointing
 * somewhere fragile is worse than one pointing somewhere safe and better than none at all.
 */
export function documentCustody(): Custody {
  return {
    async keep(uri, id, extension) {
      const outbox = new Directory(Paths.document, OUTBOX);
      if (!outbox.exists) outbox.create({ intermediates: true, idempotent: true });

      const destination = new File(outbox, `${id}${extension}`);
      const source = new File(uri);

      try {
        await source.move(destination);
        return source.uri;
      } catch {
        // Not ours to move. Take a copy instead, and if even that fails keep the original:
        // an entry that points at a fragile file still uploads, and losing it is the one
        // outcome this whole module exists to prevent.
        try {
          await source.copy(destination);
          return destination.uri;
        } catch {
          return uri;
        }
      }
    },

    async release(uri) {
      try {
        const file = new File(uri);
        if (file.exists) file.delete();
      } catch {
        // A file that cannot be deleted is a few kilobytes on a phone. A throw here would
        // be a recording that is already safely in the archive reported as a failure.
      }
    },
  };
}

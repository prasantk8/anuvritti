# Operator Runbook — Anuvritti V0

The whole family archive is **one SQLite file plus one media directory**. Almost every
procedure here follows from that.

---

## 1. Running it

### Locally

```bash
make install
cp .env.example .env          # then fill in ANUVRITTI_MEDIA_KEY
make run                      # http://127.0.0.1:8000/docs
```

Generate a media key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Keep this key.** Media encrypted with it cannot be read without it. Back it up somewhere
that is not the same place as the archive.

### In a container

```bash
docker build -t anuvritti:local .
docker run --rm -p 8000:8000 \
  -e ANUVRITTI_MEDIA_KEY="$(cat ~/.anuvritti/media.key)" \
  -v ~/.anuvritti/data:/var/lib/anuvritti \
  anuvritti:local
```

### Render a FilmExport

Rendering is intentionally a development-machine job: the always-on family server and its
production image carry neither Chromium nor FFmpeg. After `make install`, point the renderer
at the folder containing `film.json`, `provenance.json`, and `media/`:

```bash
make film ARCHIVE=/path/to/FilmExport
```

The render writes `var/film/film.mp4`, `var/film/film.manifest.json`, and the first
inspection still. Keep the manifest with the MP4: it is the portable account of the exact
FilmExport receipts, browser revision, FFmpeg version and arguments, and hashes for every
held frame and scene video that made the final film.

The film lands at `var/film/film.mp4`; `var/film/still.png` is the first frame for visual
inspection. The renderer rechecks every media hash and every provenance entry before it
draws, and the export remains plaintext family material: delete it after the render.

Later, verify the film without restoring that plaintext export or using a network:

```bash
make film-verify MANIFEST=/path/to/film.manifest.json
# If the render workspace's frames were retained:
make film-verify MANIFEST=/path/to/film.manifest.json FRAMES=/path/to/frames
```

The sibling MP4 is found from the manifest by default; `FILM=/path/to/renamed.mp4` can name
a copy stored elsewhere. Verification checks its hash and byte count, then independently
checks the video/audio streams, frame size, and duration with `ffprobe`. When `FRAMES` is
given, every frame receipt must resolve and match too. A failure names each missing or
changed artifact; success says explicitly when frame bytes were not available to check.

To distinguish the original receipt from a coordinated replacement of both the MP4 and
manifest, create a 32-byte family-held key on separate offline storage and anchor the
manifest after rendering:

```bash
openssl rand 32 > /offline/family-render.key
chmod 600 /offline/family-render.key
make film-anchor MANIFEST=/path/to/film.manifest.json \
  KEY=/offline/family-render.key ANCHOR=/path/to/film.anchor.json
make film-verify MANIFEST=/path/to/film.manifest.json \
  ANCHOR=/path/to/film.anchor.json KEY=/offline/family-render.key
```

The anchor may travel beside the film; the key must not. The anchor authenticates the exact
manifest bytes with domain-separated HMAC-SHA-256. Losing the key does not damage the film,
but it makes authenticity unverifiable; exposing it lets an attacker mint replacement
anchors, so keep a second encrypted offline copy with the family's backup key custody.

The image defaults to `ANUVRITTI_ENV=production`, which means it will **refuse to start**
without `ANUVRITTI_MEDIA_KEY` and refuses `ANUVRITTI_TLS_REQUIRED=false`. That is deliberate
(PRD §44). If it exits with code 78, read the message: it is a configuration error.

> **Do not expose port 8000 publicly.** V0 has no authentication — see
> [HARDENING.md §5.1](HARDENING.md#51-high--there-is-no-authentication). Bind it to
> localhost or a private network.

---

## 2. Backup and restore

The archive is small and the procedure is short, which is exactly why it gets skipped.

### Backup

```bash
DATA=~/.anuvritti/data
DEST=~/backups/anuvritti-$(date +%F)

mkdir -p "$DEST"
# .backup is safe on a live database; copying the file while WAL is active is not.
sqlite3 "$DATA/anuvritti.db" ".backup '$DEST/anuvritti.db'"
cp -R "$DATA/media" "$DEST/media"
```

Back up the media key **separately**. A backup of encrypted media without the key is a
backup of noise.

### Restore

```bash
systemctl stop anuvritti          # or: docker stop <container>
cp ~/backups/anuvritti-2026-08-25/anuvritti.db ~/.anuvritti/data/
cp -R ~/backups/anuvritti-2026-08-25/media ~/.anuvritti/data/
systemctl start anuvritti
curl -fsS localhost:8000/ready
```

### Verify a restore actually works

Do this at least once. A backup nobody has restored is a hypothesis.

```bash
curl -fsS "localhost:8000/v1/families/$FAMILY_ID/export" | jq '.sparks | length'
```

---

## 3. Health and monitoring

| Endpoint | Meaning | Action if failing |
|---|---|---|
| `GET /health` | The process is alive | Restart |
| `GET /ready` | The archive is reachable | Check the volume mount and disk space |
| `GET /metrics` | Prometheus text | — |

`/ready` also reports `encryption_at_rest: on|off`. In production it must read `on`.

### What to actually watch

```
anuvritti_http_requests_total{status="5xx"}   should be zero
anuvritti_intent_to_moment_ratio              the product's north star (PRD 53)
anuvritti_suggestions_emitted_total           an ANTI-metric: watch it stay LOW
```

The last one is not a mistake. PRD §53 lists notification volume among the things to
minimise. If it climbs, something has started nagging a family and needs investigating.

---

## 4. A family's data rights (PRD §44)

These are product features, not support tickets. Anyone operating this should know them.

### Export everything

```bash
curl -fsS "localhost:8000/v1/families/$FAMILY_ID/export" -o anuvritti-export.json
```

Complete, readable, versioned JSON: every Spark with its provenance, every Moment, Little
Thing, Right Now snapshot, and an index of media. The media **bytes** are downloaded
separately (`GET /v1/media/{id}`) so an export never becomes a second unencrypted copy.

### Delete everything

```bash
curl -fsS -X DELETE "localhost:8000/v1/families/$FAMILY_ID"
```

Hard delete, including media bytes on disk. It returns what it removed. It is irreversible
by design — offer an export first.

Afterwards, `VACUUM` the database so deleted pages are not recoverable from free space:

```bash
sqlite3 ~/.anuvritti/data/anuvritti.db "VACUUM;"
```

Then expire your backups, or the deletion is a gesture.

---

## 5. Common situations

### "It won't start"

Exit code **78** is a configuration error and the message says which setting. Most often a
missing `ANUVRITTI_MEDIA_KEY` in production.

### "A photo won't load"

| Error code | Cause | Action |
|---|---|---|
| `MEDIA_NOT_FOUND` | Bytes gone from disk, or the wrong key | Check the volume; check the key matches the one used to write |
| `CONFLICT` | Content hash mismatch | The file was modified or corrupted. Restore from backup — do **not** serve it |

The integrity check is why a corrupted photo fails loudly rather than returning garbage.
A silently corrupted memory is worse than a missing one.

### "Nothing is being brought back"

Usually correct behaviour, not a fault. Check in order:

1. Is anything older than `ANUVRITTI_MIN_DAYS_BEFORE_RETURN` (default 7)?
2. Was it snoozed? "Maybe later" means 30 days by default.
3. Was it archived? "Not relevant anymore" is permanent, by design.
4. Is `ANUVRITTI_SUGGESTION_THRESHOLD` (default 0.45) too high for this archive?

An empty result is a valid, silent, guilt-free outcome (PRD §8.5). Resist the urge to
"fix" quietness by lowering the threshold.

### "The database is locked"

Only one process may write. Check nothing else has the file open — a stray `sqlite3` shell
is the usual culprit.

---

## 6. Upgrading

```bash
git pull && make check          # lint, types, both coverage gates
# back up first, always
sqlite3 "$DATA/anuvritti.db" ".backup '$DEST/pre-upgrade.db'"
docker build -t anuvritti:new . && docker stop anuvritti && docker run ... anuvritti:new
curl -fsS localhost:8000/ready
```

Migrations run automatically at startup and are idempotent. They are forward-only: there is
no down-migration, so the backup above is the rollback plan.

---

## 7. The 30-day validation (PRD §54)

The point of V0 is to answer one question. After roughly 30 days of real use:

```bash
curl -fsS localhost:8000/metrics | grep -E 'sparks_captured|moments_created|intent_to_moment|suggestions_emitted'
```

Then ask the questions the PRD actually cares about, which no metric answers:

- Did capture feel frictionless?
- Did resurfacing feel useful, or did it feel like being managed?
- Did any interaction make me feel guilty?
- Did I keep using it without forcing myself?
- **Did Anuvritti create one moment with my child that probably would not have happened otherwise?**

If the answer to the last one is yes, there is signal. If not, the honest response is to
change the product, not the metrics.

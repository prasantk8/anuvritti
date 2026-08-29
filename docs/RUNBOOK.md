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
production image carry neither Chromium nor FFmpeg. Compilation first emits a text-free
`render-requirements.json`: it names only requested scripts and the exact approved world/font
package versions. Send that small receipt to the render machine and prepare it **before**
creating or moving the plaintext FilmExport:

```bash
make film-prepare REQUIREMENTS=/path/to/render-requirements.json
```

The preparation command refuses unknown scripts, changed versions, extra packages, and
`latest`; only after that check does npm fetch the pinned bundle. It then hashes every
installed WOFF2 file and refuses to declare the machine ready unless those bytes match the
digests reviewed in `packages/world/scenes/fonts.ts`. A registry package with the expected
name and version but changed font bytes is therefore not trusted. The compiler itself refuses
unsupported text with the scene, rendered field, and Unicode codepoint, while the family
material is still inside the archive. Once preparation succeeds, point the renderer at the
folder containing `film.json`, `provenance.json`, `render-requirements.json`, and `media/`:

```bash
make film ARCHIVE=/path/to/FilmExport
```

Treat a font upgrade as a visual migration, not a package bump. Install candidate
Fontsource packages into a disposable prefix without changing this repository's lock,
then render the same Latin, Arabic and Devanagari frames from approved and candidate bytes:

```bash
npm install --prefix /tmp/anuvritti-font-candidate --no-save \
  @fontsource/newsreader@5.4.0 @fontsource/ibm-plex-sans@5.4.0 \
  @fontsource/noto-naskh-arabic@5.4.0 @fontsource/noto-sans-arabic@5.4.0 \
  @fontsource/noto-serif-devanagari@5.4.0 @fontsource/noto-sans-devanagari@5.4.0
make film-font-review \
  CANDIDATE_FONTS=/tmp/anuvritti-font-candidate/node_modules CANDIDATE_VERSION=5.4.0
```

Open `var/film/font-review-5.4.0/REVIEW.md` and inspect the six full-size stills plus the
three difference maps. A map keeps the approved frame quiet underneath, marks changed
pixels in the world's indigo, and boxes their exact bounds. Every non-empty bound also gets
approved, candidate and difference detail panels: twelve pixels of context, enlarged four
times by repeating the source pixels exactly. No interpolated edge may make a glyph look
smoother or rougher than Chromium drew it. The receipt records changed pixel count,
fraction, mean and maximum RGB delta alongside every old/new WOFF2 digest and the detail
filenames; an unchanged frame gets no invented panel.
The receipt and review sheet also name the exact Playwright version, Chromium product
version and revision, installation path, operating-system release and architecture. Compare
pixel counts only when those fingerprints agree; different rasterisers are different
evidence, not a regression. The measurements help a reviewer find a subtle shaping or matra
change, but never approve or reject one automatically. Do not change a font package version
or approved digest until a design reviewer signs the sheet; the whole review folder is
ignored and must never contain family material or be committed.

The render writes `var/film/film.mp4`, `var/film/film.manifest.json`, and the first
inspection still. Keep the manifest with the MP4: it is the portable account of the exact
FilmExport receipts, browser revision, FFmpeg version and arguments, and hashes for every
held frame and scene video that made the final film.

Film text is currently promised offline for Latin, Arabic, and Devanagari. The world bundle
uses Newsreader and IBM Plex Sans for Latin, Noto Naskh/Sans Arabic, and Noto Serif/Sans
Devanagari; the manifest records every face's package version and hash. Rendering stops if
text uses an undeclared writing system or if Chromium reports that any visible glyph came
from a host font. Add a writing system to `packages/world/scenes/fonts.ts` with both display
and body faces before asking a family film to use it.

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

### Authenticate a Future Inbox ledger offline

Export a message's portable provenance ledger as JSON without changing its bytes, then
authenticate that exact file with the family-held key. The same key may anchor films and
Future Inbox ledgers: distinct HMAC contexts prevent a film receipt from being substituted
for an inbox ledger.

```bash
make inbox-anchor LEDGER=/path/to/message.ledger.json \
  KEY=/offline/family-render.key ANCHOR=/path/to/message.anchor.json
```

Keep the ledger and its small anchor together, but keep the key offline and separate. The
anchor contains the message identifier, ledger digest, and authentication tag—never the
message, recording, or key. Years later, verification needs neither the application archive
nor a network:

```bash
make inbox-verify LEDGER=/path/to/message.ledger.json \
  KEY=/offline/family-render.key ANCHOR=/path/to/message.anchor.json
```

Verification deliberately covers the ledger's exact bytes. Reformatting the JSON or
renaming the ledger therefore requires a new anchor; replacement of both artifact evidence
and its ordinary digest still cannot reproduce the family-key authentication tag.

### Rehearse family authenticity-key recovery and rotation

The authenticity key is not the archive-encryption key. Keep one working copy offline and
an encrypted recovery bundle in a genuinely separate place. The passphrase file must not
travel with either copy. Back up the current key, then immediately rehearse recovery to a
temporary destination and compare the printed key identifier:

```bash
make family-key-backup KEY=/offline/family-v1.key VERSION=1 \
  PASSPHRASE=/offline/recovery.passphrase \
  BUNDLE=/second-location/family-v1.recovery.json
make family-key-recover BUNDLE=/second-location/family-v1.recovery.json \
  PASSPHRASE=/offline/recovery.passphrase KEY=/offline/rehearsal-v1.key
cmp /offline/family-v1.key /offline/rehearsal-v1.key
rm /offline/rehearsal-v1.key
```

The bundle uses scrypt and AES-256-GCM, is written atomically with mode `0600`, and exposes
only its schema, key version, key identifier and creation time. It contains neither the
plaintext key nor the passphrase. A successful rehearsal is the evidence that the second
copy is usable; merely possessing the file is not.

Rotate only by adding a new numbered key and recovery bundle. Never overwrite or discard
an older key while any anchor names its identifier: old films and Future Inbox ledgers
still need that exact key.

```bash
make family-key-rotate VERSION=2 PASSPHRASE=/offline/recovery.passphrase \
  KEY=/offline/family-v2.key BUNDLE=/second-location/family-v2.recovery.json
make family-key-inventory \
  PASSPHRASE=/offline/recovery.passphrase \
  BUNDLES='/second-location/family-v1.recovery.json /second-location/family-v2.recovery.json' \
  ANCHORS='/archive/age-4.anchor.json /archive/leaving-home.anchor.json'
```

New film and Future Inbox anchors include a content-free key identifier. Inventory reads
only those anchors and encrypted bundles; it uses the recovery passphrase to authenticate
each bundle but never needs a manifest, ledger or separate plaintext family key. An
`uncovered` line means the corresponding old key bundle is missing and must
be found before rotation can be considered complete. Version-1 anchors created before
TASK-823 remain cryptographically verifiable, but cannot be inventoried without their
content-bearing receipt and should be re-anchored during the ceremony.

The image defaults to `ANUVRITTI_ENV=production`, which means it will **refuse to start**
without `ANUVRITTI_MEDIA_KEY` and refuses `ANUVRITTI_TLS_REQUIRED=false`. That is deliberate
(PRD §44). If it exits with code 78, read the message: it is a configuration error.

The production image includes a checksummed, file-only `ffprobe` so voice-note
duration is measured from the recording bytes on the server without carrying FFmpeg's
transcoder, video, display and hardware stack. CI measures a known one-second WAV plus
generated AAC, M4A, MP3 and WebM handset fixtures. It publishes both image sizes, their
delta, and the probe's source/binary receipt. Rehearse the same proof locally with:

```bash
docker build --target runtime-base -t anuvritti:probe-free .
docker build --target probe-fixtures -t anuvritti:probe-fixtures .
docker build -t anuvritti:local .
scripts/verify-production-media-probe.sh \
  anuvritti:local anuvritti:probe-free anuvritti:probe-fixtures
```

The build receipt is also available inside the image at
`/usr/share/anuvritti/ffprobe-runtime.manifest`. A source upgrade must update both the
version and checksum in the Dockerfile and rerun this whole format gate.

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

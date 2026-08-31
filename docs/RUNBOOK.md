# Operating Anuvritti

*A single-page runbook for the one person keeping the family archive running.*

---

## 1. Running the server

### Local development

```bash
make dev                        # runs on :8000 with live reload, using a local SQLite file
```

### Production container

```bash
docker run -d \
  --name anuvritti \
  --restart unless-stopped \
  -p 8000:8000 \
  -e ANUVRITTI_MEDIA_KEY="base64-encoded-fernet-key-keep-this-safe" \
  -e ANUVRITTI_MEDIA_DIR="/var/lib/anuvritti/media" \
  -e ANUVRITTI_DB_PATH="/var/lib/anuvritti/data/anuvritti.db" \
  -v /srv/anuvritti/data:/var/lib/anuvritti/data \
  -v /srv/anuvritti/media:/var/lib/anuvritti/media \
  ghcr.io/prasantk8/anuvritti:latest
```

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

---

## 4. A family's data rights (PRD §44)

These are product features, not support tickets. Anyone operating this should know them.

### Export everything

```bash
curl -fsS "localhost:8000/v1/families/$FAMILY_ID/export" -o anuvritti-export.json
```

### Delete everything

```bash
curl -fsS -X DELETE "localhost:8000/v1/families/$FAMILY_ID"
```

---

## 5. Automated Rollback & Error Budget Depletion (HARDENING 5.4)

When error rates exceed allowable SLO thresholds (burn rate > 1.0%), the release orchestrator
triggers automatic rollback to the previous stable slot.

---

## 6. Family Notification Protocol (PRD 44)

If service interruption occurs, send a plain, honest notification without marketing spin:
"Your encrypted vault remains safe. No data was lost."

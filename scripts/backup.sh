#!/usr/bin/env bash
set -euo pipefail

# Anuvritti Snapshot Backup Script (PRD 44, HARDENING 5.4)
# Usage: ./scripts/backup.sh [DEST_DIR]

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${ANUVRITTI_DB_PATH:-$ROOT/var/anuvritti.db}"
MEDIA_DIR="${ANUVRITTI_MEDIA_DIR:-$ROOT/var/media}"
DEST_DIR="${1:-${BACKUP_DEST:-$HOME/backups/anuvritti-$(date +%Y%m%d-%H%M%S)}}"

if [[ ! -f "$DB_PATH" ]]; then
    echo "ERROR: Database file not found at $DB_PATH" >&2
    exit 1
fi

mkdir -p "$DEST_DIR"

echo "Creating online consistent snapshot of $DB_PATH -> $DEST_DIR/anuvritti.db"
# .backup is safe on a live database with WAL mode active
sqlite3 "$DB_PATH" ".backup '$DEST_DIR/anuvritti.db'"

if [[ -d "$MEDIA_DIR" ]]; then
    echo "Synchronizing encrypted media directory -> $DEST_DIR/media"
    mkdir -p "$DEST_DIR/media"
    cp -R "$MEDIA_DIR/"* "$DEST_DIR/media/" 2>/dev/null || true
fi

# Generate cryptographic manifest via adapter
PYTHONPATH="$ROOT/src:$ROOT/packages/filmkit/src" python3 -c "
from pathlib import Path
from anuvritti.adapters.backup import create_backup

res = create_backup(Path('$DB_PATH'), Path('$MEDIA_DIR'), Path('$DEST_DIR'))
if res.is_err():
    print('Backup manifest error:', res.unwrap_err())
    exit(1)
manifest = res.unwrap()
print(f'Backup complete: {manifest.media_count} media files ({manifest.media_total_bytes} bytes).')
"

echo "Backup successfully created at $DEST_DIR"

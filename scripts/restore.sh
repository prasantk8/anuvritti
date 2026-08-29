#!/usr/bin/env bash
set -euo pipefail

# Anuvritti Archive Restore Script (PRD 44, HARDENING 5.4)
# Usage: ./scripts/restore.sh <BACKUP_DIR> [TARGET_DB_PATH] [TARGET_MEDIA_DIR]

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${1:?Usage: $0 <BACKUP_DIR> [TARGET_DB_PATH] [TARGET_MEDIA_DIR]}"
TARGET_DB="${2:-${ANUVRITTI_DB_PATH:-$ROOT/var/anuvritti.db}}"
TARGET_MEDIA="${3:-${ANUVRITTI_MEDIA_DIR:-$ROOT/var/media}}"

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "ERROR: Backup directory not found at $BACKUP_DIR" >&2
    exit 1
fi

echo "Restoring Anuvritti archive from $BACKUP_DIR..."

PYTHONPATH="$ROOT/src:$ROOT/packages/filmkit/src" python3 -c "
from pathlib import Path
from anuvritti.adapters.backup import restore_backup

res = restore_backup(Path('$BACKUP_DIR'), Path('$TARGET_DB'), Path('$TARGET_MEDIA'), verify=True)
if res.is_err():
    print('Restore error:', res.unwrap_err())
    exit(1)
report = res.unwrap()
print(f'Restore complete: {report.db_bytes} db bytes, {report.media_files_restored} media files ({report.media_total_bytes} bytes).')
"

echo "Archive successfully restored to $TARGET_DB and $TARGET_MEDIA"

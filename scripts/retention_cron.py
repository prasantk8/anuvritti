#!/usr/bin/env python3
"""Automated Retention & Lifecycle Enforcement Cron (HARDENING 5.6, TASK-1108).

Usage:
  python3 scripts/retention_cron.py

Runs the automated retention cycle:
1. Prunes ephemeral upload chunks older than 24h.
2. Prunes soft-deleted records older than 30 days.
3. Prunes expired auth pairing codes and tokens older than 15 minutes.
"""

from __future__ import annotations

import sys

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.container import build_container


def run_cron() -> int:
    settings_res = load_settings()
    if settings_res.is_err():
        print(f"Failed to load settings: {settings_res.unwrap_err()}", file=sys.stderr)
        return 1

    settings = settings_res.unwrap()
    box = build_container(settings)

    try:
        summary = box.retention.run_retention_cycle()
        print(
            f"Retention cycle completed at {summary.executed_at.isoformat()}:\n"
            f"  - Purged upload spools: {summary.purged_upload_spools}\n"
            f"  - Purged soft-deleted records: {summary.purged_soft_deleted_records}\n"
            f"  - Purged expired auth tokens: {summary.purged_auth_tokens}\n"
            f"  - Reclaimed disk bytes: {summary.reclaimed_bytes}"
        )
        return 0
    finally:
        box.close()


if __name__ == "__main__":
    sys.exit(run_cron())

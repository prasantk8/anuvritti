"""TASK-1207: Artifact Lifecycle (PRD 44, PRD 8.6).

Verifies:
1. Rendered film artifacts and intermediate frames on the render host expire on a clock (>48h).
2. Fresh render artifacts within TTL are retained.
3. Constitutional invariant: The family's own archive (media, sparks, moments) NEVER EXPIRES.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.application.retention import RetentionEngine


def test_render_host_artifacts_expire_on_clock(tmp_path: Path):
    """Old rendered films and frame caches on the render host are purged after TTL."""
    render_dir = tmp_path / "var_film"
    render_dir.mkdir(parents=True)

    # 1. Expired film on render host (72 hours old)
    old_film = render_dir / "old_film.mp4"
    old_film.write_bytes(b"F" * 1024000)
    old_time = (datetime.now(UTC) - timedelta(hours=72)).timestamp()
    os.utime(old_film, (old_time, old_time))

    old_manifest = render_dir / "old_film.manifest.json"
    old_manifest.write_text('{"status": "ok"}', encoding="utf-8")
    os.utime(old_manifest, (old_time, old_time))

    # 2. Fresh film on render host (5 hours old)
    fresh_film = render_dir / "fresh_film.mp4"
    fresh_film.write_bytes(b"N" * 512000)
    fresh_time = (datetime.now(UTC) - timedelta(hours=5)).timestamp()
    os.utime(fresh_film, (fresh_time, fresh_time))

    conn = connect(str(tmp_path / "retention.db"))
    migrate(conn)

    media_dir = tmp_path / "family_archive"
    media_dir.mkdir(parents=True)
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir(parents=True)

    engine = RetentionEngine(
        db=conn,
        media_root=media_dir,
        upload_spool_dir=spool_dir,
        render_artifacts_dir=render_dir,
    )

    purged_count, reclaimed_bytes = engine.prune_expired_render_artifacts(max_age_hours=48)

    assert purged_count == 2
    assert reclaimed_bytes == 1024000 + len('{"status": "ok"}')
    assert not old_film.exists()
    assert not old_manifest.exists()
    assert fresh_film.exists()


def test_family_archive_never_expires(tmp_path: Path):
    """The family's own archive is sovereign and permanent: never pruned by retention clock."""
    conn = connect(str(tmp_path / "sovereign.db"))
    migrate(conn)

    conn.execute("INSERT INTO family VALUES ('fam-1', 'Our family', '2016-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO member VALUES ('mem-1', 'fam-1', 'Papa', 'PARENT')")

    # Family media stored 10 years ago (3650 days old)
    archive_dir = tmp_path / "family_archive"
    archive_file = archive_dir / "fam-1/photo_10_years_old.jpg"
    archive_file.parent.mkdir(parents=True)
    archive_file.write_bytes(b"Irreplaceable childhood photograph bytes" * 100)
    ten_years_ago = (datetime.now(UTC) - timedelta(days=3650)).timestamp()
    os.utime(archive_file, (ten_years_ago, ten_years_ago))

    conn.execute(
        """
        INSERT INTO media VALUES (
            'med-permanent-1', 'fam-1', 'PHOTO', 'image/jpeg', 4000, 'hash10y',
            'fam-1/photo_10_years_old.jpg', 1, '2016-01-01T00:00:00+00:00'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO spark (
            id, family_id, owner_id, title, source_kind, source_media_id,
            intent_value, intent_source, intent_confidence, intent_overridden,
            category_value, category_source, category_confidence, category_overridden,
            status, visibility, created_at, updated_at
        ) VALUES (
            'spk-ten-year-1', 'fam-1', 'mem-1', 'Leo taking first steps',
            'PHOTO', 'med-permanent-1',
            'CAPTURE', 'INFERRED', 1.0, 0, 'MILESTONE', 'INFERRED', 1.0, 0,
            'ACTIVE', 'ACTIVE', '2016-01-01T00:00:00+00:00', '2016-01-01T00:00:00+00:00'
        )
        """
    )

    # Render host has expired files
    render_dir = tmp_path / "render_host"
    render_dir.mkdir(parents=True)
    old_render = render_dir / "scratch_work.tmp"
    old_render.write_bytes(b"scratch" * 100)
    os.utime(old_render, (ten_years_ago, ten_years_ago))

    engine = RetentionEngine(
        db=conn,
        media_root=archive_dir,
        upload_spool_dir=tmp_path / "spool",
        render_artifacts_dir=render_dir,
    )

    summary = engine.run_retention_cycle()

    # The render host scratch file was purged
    assert summary.purged_render_artifacts == 1
    assert not old_render.exists()

    # The family's 10-year-old memory and photo MUST still be intact
    assert archive_file.exists(), "Family archive media must never be pruned by retention"
    spark_row = conn.execute("SELECT title FROM spark WHERE id = 'spk-ten-year-1'").fetchone()
    assert spark_row is not None
    assert spark_row["title"] == "Leo taking first steps"
    media_row = conn.execute("SELECT id FROM media WHERE id = 'med-permanent-1'").fetchone()
    assert media_row is not None

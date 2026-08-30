"""TASK-1310: Link Rot & Preserved Content Verification (PRD 43, PRD 19).

Verifies that captured internet content is preserved into sovereign local storage
with its own content-addressed provenance, surviving complete link rot and 404s.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from anuvritti.application.preserve import PreserveUrlCommand, PreserveUrlUseCase
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceKind
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId, SparkId
from tests.support.fakes import InMemoryMediaStore, InMemorySparkRepository


@pytest.fixture
def preservation_fixture():
    family_id = FamilyId("fam-preserve-01")
    parent_id = MemberId("mem-papa")
    media_store = InMemoryMediaStore()
    spark_repo = InMemorySparkRepository()
    clock = FrozenClock(datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    use_case = PreserveUrlUseCase(media=media_store, clock=clock)

    return {
        "family_id": family_id,
        "parent_id": parent_id,
        "media_store": media_store,
        "sparks": spark_repo,
        "clock": clock,
        "use_case": use_case,
    }


def test_preserve_url_captures_local_snapshot_and_fixity(preservation_fixture):
    """Preserving a URL captures a local content-addressed snapshot."""
    fix = preservation_fixture
    use_case: PreserveUrlUseCase = fix["use_case"]

    command = PreserveUrlCommand(
        family_id=fix["family_id"],
        url="https://handmadewonders.org/crafts/autumn-leaves",
        title="Making Pressed Leaf Animals",
        text=(
            "Collect red maple leaves, press them in parchment for 3 days, "
            "then glue into owl shapes."
        ),
        author="Grandma Helen",
        snapshot_bytes=b"PNG_SAMPLE_LEAF_IMAGE_BYTES",
        mime_type="image/png",
    )

    res = use_case.execute(command)
    assert res.is_ok(), f"Preserve failed: {res.unwrap_err()}"
    preserved = res.unwrap()

    assert preserved.url == "https://handmadewonders.org/crafts/autumn-leaves"
    assert preserved.title == "Making Pressed Leaf Animals"
    assert preserved.author == "Grandma Helen"
    assert preserved.byte_size > 0

    # Verify content in MediaStore matches SHA-256
    stored_bytes = fix["media_store"].get(preserved.media_id).unwrap()
    assert hashlib.sha256(stored_bytes).hexdigest() == preserved.content_sha256
    assert stored_bytes == b"PNG_SAMPLE_LEAF_IMAGE_BYTES"

    # SourceRef points to both the URL and the preserved local media_id
    assert preserved.source_ref.kind == SourceKind.URL
    assert preserved.source_ref.url == "https://handmadewonders.org/crafts/autumn-leaves"
    assert preserved.source_ref.media_id == str(preserved.media_id)


def test_spark_survives_complete_link_rot(preservation_fixture):
    """When the remote website 404s or disappears, the Spark's preserved content remains intact."""
    fix = preservation_fixture
    use_case: PreserveUrlUseCase = fix["use_case"]

    # 1. Capture and preserve
    command = PreserveUrlCommand(
        family_id=fix["family_id"],
        url="https://fleeting-blog.example.com/2026/08/sensory-tray-guide",
        title="Sensory Rice Tray for Toddlers",
        text="Color raw rice with vinegar and food dye. Hide animal figurines for them to dig up.",
        author="Early Childhood Lab",
    )
    pres_res = use_case.execute(command)
    assert pres_res.is_ok()
    preserved = pres_res.unwrap()

    # 2. Spark created using the preserved SourceRef
    spark = Spark.capture(
        spark_id=SparkId("spark-sensory-01"),
        family_id=fix["family_id"],
        owner_id=fix["parent_id"],
        source=preserved.source_ref,
        at=fix["clock"].now(),
    )
    fix["sparks"].save(spark)

    # 3. Simulate LINK ROT: The remote server at fleeting-blog.example.com has disappeared.
    # The family never queries the dead URL; instead they load the local snapshot:
    saved_spark = fix["sparks"].get(spark.id).unwrap()
    assert saved_spark.source.media_id is not None
    assert (
        saved_spark.source.text
        == "Color raw rice with vinegar and food dye. Hide animal figurines for them to dig up."
    )

    snapshot_data = fix["media_store"].get(preserved.media_id).unwrap()
    assert len(snapshot_data) > 0


def test_preserve_url_rejects_invalid_schemes(preservation_fixture):
    """Refuses invalid schemes or malformed URLs."""
    fix = preservation_fixture
    use_case: PreserveUrlUseCase = fix["use_case"]

    for invalid_url in ["ftp://files.org/craft", "javascript:alert(1)", "not-a-url", ""]:
        res = use_case.execute(PreserveUrlCommand(family_id=fix["family_id"], url=invalid_url))
        assert res.is_err()
        assert res.unwrap_err().code == ErrorCode.VALIDATION_FAILED

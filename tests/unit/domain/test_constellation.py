"""TASK-802 - Emergent Constellations unit tests (PRD 40, PRD 41)."""

from __future__ import annotations

from datetime import UTC, datetime

from anuvritti.domain.constellation import ConstellationClusterer
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

FAMILY = FamilyId("fam-1")
CHILD = ChildId("ch-1")
PAPA = MemberId("mem-papa")
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


def make_spark(spark_id: str, title: str, tags: tuple[str, ...] = ()) -> Spark:
    spark = Spark.capture(
        spark_id=SparkId(spark_id),
        family_id=FAMILY,
        owner_id=PAPA,
        source=SourceRef.from_text(title, title=title),
        at=NOW,
        subject_child_id=CHILD,
    )
    if tags:
        object.__setattr__(spark, "tags", tags)
    return spark


class TestConstellations:
    def test_clusters_emerge_from_shared_themes(self):
        sparks = [
            make_spark("s1", "Building volcano models", ("Volcanoes",)),
            make_spark("s2", "Reading about lava and magma", ("Volcanoes",)),
            make_spark("s3", "Cooking dosa together"),
        ]

        clusters = ConstellationClusterer.cluster(sparks, at=NOW)
        assert len(clusters) >= 1
        volcano_cluster = next((c for c in clusters if c.name == "Volcanoes"), None)
        assert volcano_cluster is not None
        assert len(volcano_cluster.spark_ids) == 2
        assert SparkId("s1") in volcano_cluster.spark_ids
        assert SparkId("s2") in volcano_cluster.spark_ids

    def test_empty_sparks_returns_no_clusters(self):
        assert ConstellationClusterer.cluster([], at=NOW) == []

    def test_sparks_without_overlap_create_no_clusters(self):
        sparks = [
            make_spark("s1", "Singing songs"),
            make_spark("s2", "Visiting the zoo"),
        ]
        assert ConstellationClusterer.cluster(sparks, at=NOW) == []

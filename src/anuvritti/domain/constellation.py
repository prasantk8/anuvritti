"""Emergent Constellations (TASK-802, PRD 40, PRD 41).

Categories emerge organically from what a family actually saves and name themselves
in the family's own words, rather than an arbitrary taxonomy imposed on the parents.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from anuvritti.domain.spark import Spark
from anuvritti.shared.identity import SparkId


@dataclass(frozen=True, slots=True)
class Constellation:
    """An emergent cluster of related Sparks named by common language."""

    id: str
    name: str
    spark_ids: tuple[SparkId, ...]
    created_at: datetime


class ConstellationClusterer:
    """Derives emergent groupings from a collection of Sparks without fixed taxonomies."""

    @staticmethod
    def cluster(sparks: Sequence[Spark], *, at: datetime) -> list[Constellation]:
        if not sparks:
            return []

        # Group sparks by meaningful shared terms / tags or subject title words
        grouped_sparks: dict[str, list[SparkId]] = defaultdict(list)

        for spark in sparks:
            # 1. Tags
            for tag in spark.tags:
                tag_clean = tag.strip().title()
                if tag_clean:
                    grouped_sparks[tag_clean].append(spark.id)

            # 2. Key phrases / words in title (words > 4 chars)
            words = [w.strip().title() for w in spark.title.split() if len(w.strip()) > 4]
            for word in words:
                grouped_sparks[word].append(spark.id)

        # Build constellations for clusters with at least 2 sparks
        clusters: list[Constellation] = []
        cluster_idx = 1
        seen_combos: set[frozenset[SparkId]] = set()

        for name, ids in grouped_sparks.items():
            unique_ids = tuple(dict.fromkeys(ids))
            if len(unique_ids) >= 2:
                combo = frozenset(unique_ids)
                if combo not in seen_combos:
                    seen_combos.add(combo)
                    clusters.append(
                        Constellation(
                            id=f"cst-{cluster_idx:03d}",
                            name=name,
                            spark_ids=unique_ids,
                            created_at=at,
                        )
                    )
                    cluster_idx += 1

        clusters.sort(key=lambda c: (-len(c.spark_ids), c.name))
        return clusters

"""TASK-1205: Up-front render budget and cost ceiling (PRD 8.2, PRD 57).

A film that would take an hour is refused up front with a human sentence,
not discovered half-rendered.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from anuvritti.domain.film import (
    BundledMedia,
    Citation,
    CitationKind,
    CompiledFilm,
    CompiledScene,
    FilmDraft,
    FilmPackage,
    FilmScene,
    FilmSpec,
    MediaBundle,
    Provenance,
    ProvenanceEntry,
    ProvenanceStatus,
    RenderBudget,
    SceneKind,
    SceneVoice,
)
from anuvritti.domain.media import MediaKind
from anuvritti.shared.identity import ChildId, FamilyId, MediaId


def _sample_spec(scene_count: int = 5, scene_duration: float = 10.0) -> FilmSpec:
    scenes = tuple(
        FilmScene(
            id=f"scene-{i}",
            kind=SceneKind.SPARK,
            heading=f"Memory {i}",
            voice=SceneVoice.silent(scene_duration),
            cites=(Citation(CitationKind.SPARK, f"spk-{i}"),),
        )
        for i in range(scene_count)
    )
    return FilmSpec(
        id="spec-budget-1",
        family_id=FamilyId("fam-1"),
        title="Year in Review",
        scenes=scenes,
        child_id=ChildId("child-1"),
    )


def _sample_compiled(scene_count: int = 5, scene_duration: float = 10.0) -> CompiledFilm:
    compiled_scenes = tuple(
        CompiledScene(
            id=f"scene-{i}",
            kind=SceneKind.SPARK,
            start_seconds=i * scene_duration,
            visual_seconds=scene_duration,
            voice=SceneVoice.silent(scene_duration),
            cites=(Citation(CitationKind.SPARK, f"spk-{i}"),),
        )
        for i in range(scene_count)
    )
    return CompiledFilm(
        spec_id="spec-budget-1",
        title="Year in Review",
        scenes=compiled_scenes,
    )


def test_valid_film_passes_render_budget():
    """A standard 3-minute film with normal scene counts passes all budget checks."""
    budget = RenderBudget()
    spec = _sample_spec(scene_count=10, scene_duration=15.0)
    compiled = _sample_compiled(scene_count=10, scene_duration=15.0)

    # Must not raise
    budget.check_spec(spec)
    budget.check_compiled(compiled)


def test_excessive_scene_count_refused_up_front():
    """A film with too many scenes is refused with an explanatory sentence."""
    budget = RenderBudget(max_scenes=20)
    spec = _sample_spec(scene_count=25)
    compiled = _sample_compiled(scene_count=25)

    with pytest.raises(
        ValueError, match="contains 25 scenes, which exceeds the limit of 20 scenes"
    ):
        budget.check_spec(spec)

    with pytest.raises(
        ValueError, match="contains 25 scenes, which exceeds the limit of 20 scenes"
    ):
        budget.check_compiled(compiled)


def test_excessive_duration_refused_up_front():
    """A film exceeding max duration ceiling (e.g. 12 mins) is refused before rendering."""
    budget = RenderBudget(max_duration_seconds=300.0)  # 5 minutes limit
    compiled = _sample_compiled(scene_count=10, scene_duration=40.0)  # 400 seconds

    with pytest.raises(
        ValueError,
        match=re.escape(
            "runs for 6.7 minutes, which exceeds the maximum allowed duration of 5.0 minutes"
        ),
    ):
        budget.check_compiled(compiled)


def test_excessive_single_scene_duration_refused():
    """A single scene that runs excessively long is refused up front."""
    budget = RenderBudget(max_single_scene_seconds=60.0)
    compiled_scenes = (
        CompiledScene(
            id="scene-overlong",
            kind=SceneKind.SPARK,
            start_seconds=0.0,
            visual_seconds=95.0,
            voice=SceneVoice.silent(95.0),
            cites=(Citation(CitationKind.SPARK, "spk-1"),),
        ),
    )
    film = CompiledFilm(spec_id="s1", title="Title", scenes=compiled_scenes)

    with pytest.raises(
        ValueError,
        match=re.escape("runs for 95.0s, which exceeds the maximum single scene limit of 60.0s"),
    ):
        budget.check_compiled(film)


def test_excessive_media_bundle_size_refused():
    """A bundle that exceeds byte budget is refused before reaching render farm."""
    budget = RenderBudget(max_total_bytes=100 * 1024 * 1024)  # 100 MB limit

    items = (
        BundledMedia(
            id=MediaId("med-1"),
            kind=MediaKind.IMAGE,
            mime_type="image/jpeg",
            byte_size=150 * 1024 * 1024,  # 150 MB
            content_hash="abc",
        ),
    )
    bundle = MediaBundle(items=items)
    spec = FilmSpec(
        id="s1",
        family_id=FamilyId("fam-1"),
        title="Title",
        scenes=(
            FilmScene(
                id="sc-1",
                kind=SceneKind.SPARK,
                heading="H",
                voice=SceneVoice.silent(5.0),
                cites=(Citation(CitationKind.MEDIA, "med-1"),),
            ),
        ),
    )
    draft = FilmDraft(spec=spec, bundle=bundle)
    compiled = CompiledFilm(
        spec_id="s1",
        title="Title",
        scenes=(
            CompiledScene(
                id="sc-1",
                kind=SceneKind.SPARK,
                start_seconds=0.0,
                visual_seconds=5.0,
                voice=SceneVoice.silent(5.0),
                cites=(Citation(CitationKind.MEDIA, "med-1"),),
            ),
        ),
    )
    prov = Provenance(
        film_id="s1",
        family_id=FamilyId("fam-1"),
        verified_at=datetime.now(UTC),
        entries=(
            ProvenanceEntry(
                scene_id="sc-1",
                scene_kind=SceneKind.SPARK,
                citation=Citation(CitationKind.MEDIA, "med-1"),
                status=ProvenanceStatus.VERIFIED,
                content_hash="abc",
            ),
        ),
    )
    package = FilmPackage(draft=draft, film=compiled, provenance=prov)

    with pytest.raises(
        ValueError,
        match=re.escape("is 150.0 MB, which exceeds the budget ceiling of 100 MB"),
    ):
        budget.check_package(package)


def test_excessive_media_reference_count_refused():
    """A spec referencing more media than allowed is refused up front."""
    budget = RenderBudget(max_media_count=2)
    scenes = tuple(
        FilmScene(
            id=f"sc-{i}",
            kind=SceneKind.SPARK,
            heading=f"Heading {i}",
            voice=SceneVoice.silent(5.0),
            cites=(Citation(CitationKind.MEDIA, f"img-{i}"),),
        )
        for i in range(3)
    )
    spec = FilmSpec(id="s1", family_id=FamilyId("fam-1"), title="T", scenes=scenes)
    with pytest.raises(ValueError, match="references 3 media files, which exceeds the limit of 2"):
        budget.check_spec(spec)


def test_excessive_estimated_render_time_refused():
    """When estimated scene rendering exceeds total time ceiling, refuses up front."""
    budget = RenderBudget(max_estimated_render_seconds=40.0, max_scenes=10)
    compiled = _sample_compiled(scene_count=5, scene_duration=5.0)  # 5 scenes * 10s = 50s > 40s
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Estimated compilation time (50s) exceeds the maximum render budget of 40s."
        ),
    ):
        budget.check_compiled(compiled)


def test_excessive_package_bundle_items_refused():
    """A package whose bundle item count exceeds ceiling is refused."""
    budget = RenderBudget(max_media_count=1)
    items = (
        BundledMedia(
            id=MediaId("med-1"),
            kind=MediaKind.IMAGE,
            mime_type="image/jpeg",
            byte_size=1000,
            content_hash="h1",
        ),
        BundledMedia(
            id=MediaId("med-2"),
            kind=MediaKind.IMAGE,
            mime_type="image/jpeg",
            byte_size=1000,
            content_hash="h2",
        ),
    )
    bundle = MediaBundle(items=items)
    scenes = (
        FilmScene(
            id="sc-1",
            kind=SceneKind.SPARK,
            heading="H1",
            voice=SceneVoice.silent(5.0),
            cites=(Citation(CitationKind.MEDIA, "med-1"),),
        ),
        FilmScene(
            id="sc-2",
            kind=SceneKind.SPARK,
            heading="H2",
            voice=SceneVoice.silent(5.0),
            cites=(Citation(CitationKind.MEDIA, "med-2"),),
        ),
    )
    spec = FilmSpec(id="s1", family_id=FamilyId("fam-1"), title="T", scenes=scenes)
    draft = FilmDraft(spec=spec, bundle=bundle)
    compiled = CompiledFilm(
        spec_id="s1",
        title="T",
        scenes=(
            CompiledScene(
                id="sc-1",
                kind=SceneKind.SPARK,
                start_seconds=0.0,
                visual_seconds=5.0,
                voice=SceneVoice.silent(5.0),
                cites=(Citation(CitationKind.MEDIA, "med-1"),),
            ),
            CompiledScene(
                id="sc-2",
                kind=SceneKind.SPARK,
                start_seconds=5.0,
                visual_seconds=5.0,
                voice=SceneVoice.silent(5.0),
                cites=(Citation(CitationKind.MEDIA, "med-2"),),
            ),
        ),
    )
    prov = Provenance(
        film_id="s1",
        family_id=FamilyId("fam-1"),
        verified_at=datetime.now(UTC),
        entries=(
            ProvenanceEntry(
                scene_id="sc-1",
                scene_kind=SceneKind.SPARK,
                citation=Citation(CitationKind.MEDIA, "med-1"),
                status=ProvenanceStatus.VERIFIED,
                content_hash="h1",
            ),
            ProvenanceEntry(
                scene_id="sc-2",
                scene_kind=SceneKind.SPARK,
                citation=Citation(CitationKind.MEDIA, "med-2"),
                status=ProvenanceStatus.VERIFIED,
                content_hash="h2",
            ),
        ),
    )
    package = FilmPackage(draft=draft, film=compiled, provenance=prov)
    with pytest.raises(
        ValueError,
        match=re.escape("The media bundle carries 2 items, which exceeds the budget limit of 1."),
    ):
        budget.check_package(package)

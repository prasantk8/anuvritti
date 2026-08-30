"""TASK-1308: Print-Ready Artifact Verification (PRD 36, PRD 56).

Verifies that the year's film specification compiles into a print-ready memory publication
using CSS Paged Media rules and the @anuvritti/world visual language tokens.
"""

from __future__ import annotations

import pytest

from anuvritti.application.print_artifact import (
    GeneratePrintArtifactUseCase,
    PrintArtifactResult,
)
from anuvritti.domain.film import (
    Citation,
    CitationKind,
    ConnectiveLine,
    FilmScene,
    FilmSpec,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.identity import FamilyId, MediaId


@pytest.fixture
def printable_spec():
    return FilmSpec(
        id="film-print-2026",
        family_id=FamilyId("fam-print-01"),
        title="Leo's First Year",
        scenes=(
            FilmScene(
                id="sc-opening",
                kind=SceneKind.OPENING,
                heading="From Autumn to Summer",
                body="Twelve months in the life of Leo",
                voice=SceneVoice.silent(2.5),
            ),
            FilmScene(
                id="sc-moment-1",
                kind=SceneKind.MOMENT,
                heading="First time in the snow",
                body="He stood completely still for two minutes watching the flakes fall.",
                voice=SceneVoice.recorded(
                    media_id=MediaId("med-audio-snow"),
                    seconds=4.2,
                    text="Look at that big smile!",
                ),
                cites=(
                    Citation(CitationKind.MOMENT, "mom-snow-01"),
                    Citation(CitationKind.SPARK, "spk-snow-01"),
                    Citation(CitationKind.MEDIA, "med-photo-snow"),
                ),
            ),
            FilmScene(
                id="sc-closing",
                kind=SceneKind.CLOSING,
                heading="Our Reality",
                body="Everything here happened. Nothing here was invented.",
                voice=SceneVoice.synthetic(
                    line=ConnectiveLine.CLOSING,
                    media_id=MediaId("med-synth-close"),
                    seconds=3.0,
                ),
            ),
        ),
    )


def test_generate_print_artifact_produces_valid_paged_media_document(printable_spec):
    use_case = GeneratePrintArtifactUseCase()
    res = use_case.execute(printable_spec)
    assert res.is_ok()
    result = res.unwrap()

    assert isinstance(result, PrintArtifactResult)
    assert result.scene_count == 3
    assert result.title == "Leo's First Year"

    html = result.html
    # 1. Paged media CSS present
    assert "@page" in html
    assert "A4 portrait" in html
    assert "page-break-after: always" in html
    assert "break-after: page" in html

    # 2. Cover page
    assert 'id="page-cover"' in html
    assert "Leo&#x27;s First Year" in html or "Leo's First Year" in html
    assert "These are things that happened." in html

    # 3. Content spread with picture, quote, and citations
    assert "First time in the snow" in html
    assert "He stood completely still" in html
    assert "Look at that big smile!" in html
    assert 'src="media/med-photo-snow.jpg"' in html
    assert "MOMENT:mom-snow-01" in html
    assert "SPARK:spk-snow-01" in html

    # 4. Colophon & Reality Guarantee
    assert 'id="page-colophon"' in html
    assert "Everything here happened. Nothing here was invented." in html
    assert "film-print-2026" in html

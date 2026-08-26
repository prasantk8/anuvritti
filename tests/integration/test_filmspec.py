"""TASK-705 - a year of a family's own rows becomes a film spec and a bundle (PRD 15, 23, 34).

Real SQLite, a real encrypted media store, and the real filmkit compiler. Nothing is mocked
here on purpose: the interesting failures in this module are all failures of *agreement*
between three stores that were written at different times - a moment pointing at audio the
voice-note table never measured, a spec naming a file the media store no longer holds, a
bundle carrying a photograph that belongs to another family.

The tests are grouped by what they defend rather than by what they call:

`TestWhatEndsUpInTheFilm`   the arithmetic of assembly - order, windows, whose child it is
`TestEveryScenePointsAtSomethingReal`  the provenance rule, at the level TASK-705 owns it
`TestTheBundleIsExactlyWhatTravels`    what leaves the family's box, and what does not
`TestARecordingIsMeasuredOrItIsRefused`  the one refusal that would otherwise be a silence
`TestCompilingTheDraft`     the seam to TASK-704, end to end
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.sqlite import SqliteMediaCatalogue
from anuvritti.application.film import (
    CLOSING_LINE,
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.config.settings import DEFAULT_ALLOWED_MEDIA_TYPES
from anuvritti.domain.family import Family, Member
from anuvritti.domain.film import CitationKind, FilmDraft, MediaBundle, SceneKind
from anuvritti.domain.media import MediaKind
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import Confidence, MemberRole, SourceRef
from anuvritti.domain.voice import Transcript, VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MediaId,
    MemberId,
    MomentId,
    SequentialIdGenerator,
    SparkId,
)
from tests.integration.conftest import CHILD, FAMILY, PAPA

PHOTO = b"\xff\xd8\xff\xe0" + b"a face mid-laugh" * 30
CLIP = b"\x00\x00\x00\x20ftypM4A " + b"his voice" * 40

OTHER_FAMILY = FamilyId("fam-2")
OTHER_CHILD = ChildId("ch-2")


class Archive:
    """A family's rows, written the way the rest of the system writes them."""

    def __init__(self, repos, tmp_path: Path) -> None:
        self.repos = repos
        self.ids = SequentialIdGenerator("film")
        self.media = EncryptedFilesystemMediaStore(
            root=tmp_path / "media",
            catalogue=SqliteMediaCatalogue(repos.db),
            ids=SequentialIdGenerator("med"),
            encryption_key=Fernet.generate_key().decode(),
            max_bytes=1024 * 1024,
            allowed_mime_types=DEFAULT_ALLOWED_MEDIA_TYPES,
        )
        self._n = 0

    # ------------------------------------------------------------------ writing
    def spark(self, title: str, *, on: date, child: ChildId | None = CHILD) -> Spark:
        self._n += 1
        spark = Spark.capture(
            spark_id=SparkId(f"spk-{self._n}"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text(title),
            at=datetime.combine(on, datetime.min.time(), tzinfo=UTC),
            subject_child_id=child,
        )
        return self.repos.sparks.save(spark).unwrap()

    def moment(
        self,
        title: str,
        *,
        on: date,
        child: ChildId | None = CHILD,
        reflection: str | None = None,
        photo: str | None = None,
        audio: str | None = None,
    ) -> Moment:
        spark = self.spark(title, on=on, child=child)
        moment = Moment.create(
            moment_id=MomentId(f"mom-{self._n}"),
            family_id=FAMILY,
            spark_id=spark.id,
            created_by=PAPA,
            spark_captured_at=spark.created_at,
            at=datetime.combine(on, datetime.min.time(), tzinfo=UTC),
            happened_on=on,
            reflection=reflection,
            photo_media_id=photo,
            audio_media_id=audio,
        ).unwrap()
        return self.repos.moments.save(moment).unwrap()

    def upload(self, content: bytes = PHOTO, mime: str = "image/jpeg") -> str:
        stored = self.media.put(
            FAMILY, content=content, mime_type=mime, at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        return str(stored.unwrap().id)

    def recording(
        self,
        *,
        seconds: float = 4.2,
        said: str | None = None,
        heard: str | None = None,
        family: FamilyId = FAMILY,
    ) -> str:
        """Audio in the store, with a `VoiceNote` beside it carrying its measured length."""
        media_id = self.upload(CLIP, "audio/mp4")
        note = VoiceNote.kept(
            media_id=MediaId(media_id),
            family_id=family,
            author_id=PAPA,
            duration_seconds=seconds,
            at=datetime(2026, 1, 1, tzinfo=UTC),
        ).unwrap()
        if said is not None:
            note = note.corrected_to(said, at=datetime(2026, 1, 2, tzinfo=UTC)).unwrap()
        elif heard is not None:
            note = note.indexed_by(
                Transcript.machine(
                    heard,
                    confidence=Confidence(0.6),
                    engine="on-device",
                    at=datetime(2026, 1, 2, tzinfo=UTC),
                ).unwrap()
            )
        self.repos.voice_notes.save(note).unwrap()
        return media_id

    def other_family(self) -> FamilyId:
        """A second family in the same database. Nothing of theirs may reach this film."""
        self.repos.families.save(
            Family(
                id=OTHER_FAMILY,
                name="Another family",
                members=(Member(PAPA, "Someone else", MemberRole.PARENT),),
                children=(),
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
        ).unwrap()
        return OTHER_FAMILY

    def unmeasured_recording(self) -> str:
        """Audio that arrived without anyone recording how long it is."""
        return self.upload(CLIP, "audio/mp4")

    # ------------------------------------------------------------------ reading
    def compose(self, **overrides) -> object:
        use_case = ComposeFilmUseCase(
            families=self.repos.families,
            sparks=self.repos.sparks,
            moments=self.repos.moments,
            voice_notes=self.repos.voice_notes,
            media=self.media,
            ids=self.ids,
        )
        fields = {"family_id": FAMILY, "actor_id": PAPA}
        fields.update(overrides)
        return use_case.execute(ComposeFilmCommand(**fields))  # type: ignore[arg-type]

    def verifier(self) -> VerifyProvenanceUseCase:
        return VerifyProvenanceUseCase(
            sparks=self.repos.sparks,
            moments=self.repos.moments,
            voice_notes=self.repos.voice_notes,
            little_things=self.repos.little_things,
            media=self.media,
            clock=FrozenClock(datetime(2026, 8, 26, 9, 0, tzinfo=UTC)),
        )

    def compile(self, **overrides) -> object:
        use_case = CompileFilmUseCase(
            compose=ComposeFilmUseCase(
                families=self.repos.families,
                sparks=self.repos.sparks,
                moments=self.repos.moments,
                voice_notes=self.repos.voice_notes,
                media=self.media,
                ids=self.ids,
            ),
            verify=self.verifier(),
            compiler=FilmkitFilmCompiler(),
        )
        fields = {"family_id": FAMILY, "actor_id": PAPA}
        fields.update(overrides)
        return use_case.execute(ComposeFilmCommand(**fields))  # type: ignore[arg-type]


@pytest.fixture
def archive(repos, seeded_family, tmp_path) -> Archive:
    return Archive(repos, tmp_path)


def moment_scenes(draft: FilmDraft):
    return [scene for scene in draft.spec.scenes if scene.kind.is_evidence]


class TestWhatEndsUpInTheFilm:
    def test_a_moment_becomes_a_scene_headed_by_what_a_person_wrote(self, archive):
        archive.moment("Teach him to skip stones", on=date(2026, 4, 2), reflection="He got two.")

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.heading == "Teach him to skip stones"
        assert scene.body == "He got two."

    def test_the_film_runs_in_the_order_life_happened(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))
        archive.moment("The first snow", on=date(2026, 1, 9))
        archive.moment("Sports day", on=date(2026, 5, 20))

        headings = [scene.heading for scene in moment_scenes(archive.compose().unwrap())]

        assert headings == ["The first snow", "Sports day", "The lake"]

    def test_it_opens_and_closes_on_a_card_that_claims_nothing(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        scenes = archive.compose().unwrap().spec.scenes

        assert scenes[0].kind is SceneKind.OPENING
        assert scenes[-1].kind is SceneKind.CLOSING
        assert scenes[-1].body == CLOSING_LINE
        assert scenes[0].cites == () and scenes[-1].cites == ()

    def test_the_closing_card_counts_the_moments_and_not_the_scenes(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))
        archive.moment("Sports day", on=date(2026, 5, 20))

        assert archive.compose().unwrap().spec.scenes[-1].heading == "2 moments"

    def test_a_film_of_one_moment_says_so_in_the_singular(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        assert archive.compose().unwrap().spec.scenes[-1].heading == "1 moment"

    def test_the_window_is_inclusive_at_both_ends(self, archive):
        archive.moment("Too early", on=date(2025, 12, 31))
        archive.moment("First day", on=date(2026, 1, 1))
        archive.moment("Last day", on=date(2026, 12, 31))
        archive.moment("Too late", on=date(2027, 1, 1))

        draft = archive.compose(since=date(2026, 1, 1), until=date(2026, 12, 31)).unwrap()

        assert [s.heading for s in moment_scenes(draft)] == ["First day", "Last day"]

    def test_a_film_about_one_child_leaves_the_other_children_out(self, archive, repos):
        archive.moment("His first word", on=date(2026, 3, 1), child=CHILD)
        archive.moment("Her recital", on=date(2026, 3, 2), child=OTHER_CHILD)

        draft = archive.compose(child_id=CHILD).unwrap()

        assert [s.heading for s in moment_scenes(draft)] == ["His first word"]

    def test_a_child_who_is_not_in_this_family_is_not_a_filter(self, archive):
        archive.moment("His first word", on=date(2026, 3, 1))

        failed = archive.compose(child_id=ChildId("ch-nobody"))

        assert failed.unwrap_err().code is ErrorCode.CHILD_NOT_FOUND

    def test_the_title_names_the_child_and_the_years_actually_in_the_film(self, archive):
        archive.moment("The first snow", on=date(2026, 1, 9))

        assert archive.compose(child_id=CHILD).unwrap().spec.title == "Aarav, 2026"

    def test_a_film_that_spans_years_says_both(self, archive):
        archive.moment("The first snow", on=date(2025, 12, 30))
        archive.moment("The lake", on=date(2026, 8, 1))

        assert archive.compose(child_id=CHILD).unwrap().spec.title == "Aarav, 2025-2026"

    def test_a_title_a_parent_typed_wins(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        assert archive.compose(title="The summer of the lake").unwrap().spec.title == (
            "The summer of the lake"
        )

    def test_the_opening_card_carries_the_span_the_film_actually_covers(self, archive):
        archive.moment("The first snow", on=date(2026, 1, 9))
        archive.moment("The lake", on=date(2026, 8, 1))

        assert archive.compose().unwrap().spec.scenes[0].body == "2026-01-09 - 2026-08-01"

    def test_a_single_day_is_a_day_and_not_a_span(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        assert archive.compose().unwrap().spec.scenes[0].body == "2026-08-01"

    def test_a_year_with_nothing_in_it_is_not_a_film(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        failed = archive.compose(since=date(2030, 1, 1))

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert "nothing in that stretch of time" in failed.unwrap_err().message

    def test_a_stranger_cannot_compose_a_family_s_film(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        failed = archive.compose(actor_id=MemberId("mem-nobody"))

        assert failed.unwrap_err().code is ErrorCode.MEMBER_NOT_FOUND

    def test_an_unknown_family_has_no_film(self, archive):
        assert archive.compose(family_id=OTHER_FAMILY).unwrap_err().code is (
            ErrorCode.FAMILY_NOT_FOUND
        )


class TestEveryScenePointsAtSomethingReal:
    def test_every_scene_cites_the_moment_and_the_spark_it_came_from(self, archive):
        moment = archive.moment("The lake", on=date(2026, 8, 1))

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.cited_ids >= {str(moment.id), str(moment.spark_id)}
        kinds = {citation.kind for citation in scene.cites}
        assert CitationKind.MOMENT in kinds and CitationKind.SPARK in kinds

    def test_a_photograph_is_cited_as_media(self, archive):
        photo = archive.upload()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo)

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert (CitationKind.MEDIA, photo) in {(c.kind, c.id) for c in scene.cites}

    def test_a_recording_is_cited_as_the_voice_note_it_is(self, archive):
        audio = archive.recording()
        archive.moment("His voice", on=date(2026, 8, 1), audio=audio)

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert (CitationKind.VOICE_NOTE, audio) in {(c.kind, c.id) for c in scene.cites}

    def test_a_draft_can_name_every_source_id_it_draws_from(self, archive):
        """One call, and a reviewer has the whole list to check. TASK-706 does exactly that."""
        photo = archive.upload()
        first = archive.moment("The lake", on=date(2026, 8, 1), photo=photo)
        second = archive.moment("Sports day", on=date(2026, 5, 1))

        assert archive.compose().unwrap().cited_ids == {
            str(first.id),
            str(first.spark_id),
            photo,
            str(second.id),
            str(second.spark_id),
        }

    def test_a_scene_that_claims_something_cannot_be_built_without_a_citation(self):
        """The rule this whole module exists to keep, checked where it is enforced."""
        from anuvritti.domain.film import FilmScene, SceneVoice

        with pytest.raises(ValueError, match="cites nothing is a story"):
            FilmScene(
                id="invented",
                kind=SceneKind.MOMENT,
                heading="The day he learned to swim",
                voice=SceneVoice.silent(0.0),
            )

    def test_a_title_card_is_not_evidence_and_needs_no_citation(self):
        assert SceneKind.OPENING.is_evidence is False
        assert SceneKind.CLOSING.is_evidence is False
        assert SceneKind.MOMENT.is_evidence is True


class TestTheBundleIsExactlyWhatTravels:
    def test_the_bundle_carries_the_files_the_film_names(self, archive):
        photo = archive.upload()
        audio = archive.recording()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo, audio=audio)

        bundle = archive.compose().unwrap().bundle

        assert bundle.ids == {photo, audio}

    def test_the_bundle_describes_each_file_well_enough_to_check_it_arrived(self, archive):
        photo = archive.upload()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo)

        item = archive.compose().unwrap().bundle.items[0]

        assert item.kind is MediaKind.IMAGE
        assert item.mime_type == "image/jpeg"
        assert item.byte_size == len(PHOTO)
        assert len(item.content_hash) == 64

    def test_a_film_with_nothing_attached_travels_with_nothing(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1), reflection="Just us.")

        assert archive.compose().unwrap().bundle.items == ()

    def test_the_same_year_bundles_the_same_way_twice(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1), photo=archive.upload())
        archive.moment("Sports day", on=date(2026, 5, 1), photo=archive.upload())

        first = archive.compose().unwrap().bundle
        second = archive.compose().unwrap().bundle

        assert [i.id for i in first.items] == [i.id for i in second.items]

    def test_a_bundle_knows_what_the_family_is_about_to_copy_off_their_machine(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1), photo=archive.upload())

        assert archive.compose().unwrap().bundle.byte_size == len(PHOTO)

    def test_a_file_the_store_no_longer_holds_fails_the_composition(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1), photo="med-vanished")

        failed = archive.compose()

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert failed.unwrap_err().details["media_id"] == "med-vanished"

    def test_another_family_s_photograph_never_enters_the_bundle(self, archive, repos):
        theirs = archive.media.put(
            OTHER_FAMILY,
            content=PHOTO,
            mime_type="image/jpeg",
            at=datetime(2026, 1, 1, tzinfo=UTC),
        ).unwrap()
        archive.moment("The lake", on=date(2026, 8, 1), photo=str(theirs.id))

        failed = archive.compose()

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE

    def test_a_draft_cannot_hold_a_bundle_that_is_missing_a_file(self, archive):
        photo = archive.upload()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo)
        draft = archive.compose().unwrap()

        with pytest.raises(ValueError, match="the bundle does not carry"):
            FilmDraft(spec=draft.spec, bundle=MediaBundle())

    def test_a_draft_cannot_hold_a_bundle_carrying_a_file_no_scene_names(self, archive):
        photo = archive.upload()
        spare = archive.upload()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo)
        draft = archive.compose().unwrap()
        described = archive.media.describe(MediaId(spare)).unwrap()

        from anuvritti.domain.film import BundledMedia

        with pytest.raises(ValueError, match="no scene names"):
            FilmDraft(
                spec=draft.spec,
                bundle=MediaBundle(
                    (
                        *draft.bundle.items,
                        BundledMedia(
                            id=described.id,
                            kind=described.kind,
                            mime_type=described.mime_type,
                            byte_size=described.byte_size,
                            content_hash=described.content_hash,
                        ),
                    )
                ),
            )

    def test_a_bundle_lists_each_file_once(self, archive):
        photo = archive.upload()
        described = archive.media.describe(MediaId(photo)).unwrap()

        from anuvritti.domain.film import BundledMedia

        item = BundledMedia(
            id=described.id,
            kind=described.kind,
            mime_type=described.mime_type,
            byte_size=described.byte_size,
            content_hash=described.content_hash,
        )
        with pytest.raises(ValueError, match="each file once"):
            MediaBundle((item, item))


class TestARecordingIsMeasuredOrItIsRefused:
    def test_a_scene_holds_for_as_long_as_the_recording_actually_runs(self, archive):
        audio = archive.recording(seconds=9.4)
        archive.moment("His voice", on=date(2026, 8, 1), audio=audio)

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.voice.seconds == 9.4
        assert scene.voice.is_real_voice

    def test_audio_nobody_measured_stops_the_film_and_names_the_moment(self, archive):
        moment = archive.moment(
            "His voice", on=date(2026, 8, 1), audio=archive.unmeasured_recording()
        )

        failed = archive.compose()

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert failed.unwrap_err().details["moment_id"] == str(moment.id)
        assert "will not guess" in failed.unwrap_err().message

    def test_another_family_s_recording_is_refused_the_same_way_an_unknown_one_is(self, archive):
        audio = archive.recording(family=archive.other_family())
        archive.moment("His voice", on=date(2026, 8, 1), audio=audio)

        failed = archive.compose()

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE
        assert "will not guess" in failed.unwrap_err().message

    def test_a_moment_with_no_audio_is_a_held_picture_and_not_a_silence_to_fill(self, archive):
        archive.moment("The lake", on=date(2026, 8, 1))

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.voice.origin.value == "SILENT"
        assert scene.min_seconds > 0

    def test_a_transcript_a_parent_wrote_becomes_the_caption(self, archive):
        audio = archive.recording(said="Say it again, Papa.")
        archive.moment("His voice", on=date(2026, 8, 1), audio=audio)

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.voice.text == "Say it again, Papa."

    def test_a_machine_s_reading_is_never_shown_as_a_quotation(self, archive):
        """PRD 8.7. A caption reads as "he said this", and a guess is not that."""
        audio = archive.recording(heard="say it again poppa")
        archive.moment("His voice", on=date(2026, 8, 1), audio=audio)

        scene = moment_scenes(archive.compose().unwrap())[0]

        assert scene.voice.text == ""


class TestCompilingTheDraft:
    def test_a_year_compiles_to_a_film_that_adds_up(self, archive):
        archive.moment("The first snow", on=date(2026, 1, 9), audio=archive.recording(seconds=6.0))
        archive.moment("The lake", on=date(2026, 8, 1), photo=archive.upload())

        package = archive.compile().unwrap()

        assert package.film.duration_seconds > 0
        assert len(package.film.scenes) == len(package.spec.scenes)
        assert package.film.scenes[0].start_seconds == 0.0

    def test_the_film_is_made_of_real_voices_and_says_so(self, archive):
        archive.moment("His voice", on=date(2026, 8, 1), audio=archive.recording(seconds=6.0))

        package = archive.compile().unwrap()

        assert package.film.real_voice_share == 1.0
        assert not any("synthetic" in note for note in package.film.notes)

    def test_the_package_carries_the_files_the_compiled_film_names(self, archive):
        photo = archive.upload()
        audio = archive.recording()
        archive.moment("The lake", on=date(2026, 8, 1), photo=photo, audio=audio)

        package = archive.compile().unwrap()

        assert package.bundle.ids == {photo, audio}
        assert package.to_dict()["bundle"]["count"] == 2

    def test_every_citation_in_the_compiled_film_came_from_a_row(self, archive):
        moment = archive.moment("The lake", on=date(2026, 8, 1), photo=archive.upload())

        package = archive.compile().unwrap()

        cited = {citation.id for citation in package.film.citations}
        assert str(moment.id) in cited
        assert str(moment.spark_id) in cited

    def test_a_composition_that_fails_never_reaches_the_compiler(self, archive):
        failed = archive.compile(since=date(2030, 1, 1))

        assert failed.unwrap_err().code is ErrorCode.FILM_NOT_COMPILABLE

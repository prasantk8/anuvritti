"""TASK-903 - Grandparent zero-install prompt flow (PRD 27).

30 days before the child turns N, the grandparent receives exactly one question
keyed to N ('What was his father like at N?'), filed against two ages at once,
skippable forever, and never re-asked.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLittleThingRepository,
)
from anuvritti.application.presence import (
    GrandparentPromptUseCase,
    RespondGrandparentPromptCommand,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    SequentialIdGenerator,
)
from tests.support.fakes import RecordingEventPublisher


class DummyUow:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "grandparent.db"
    conn = connect(str(db_path))
    migrate(conn)

    # Child's birthday is May 14, 2023.
    # On April 14, 2026 (30 days before turning 3 on May 14, 2026):
    clock = FrozenClock(datetime(2026, 4, 14, 10, 0, tzinfo=UTC))
    ids = SequentialIdGenerator("gp")
    events = RecordingEventPublisher()
    uow = DummyUow()

    families = SqliteFamilyRepository(conn)
    little_things = SqliteLittleThingRepository(conn)

    family_id = FamilyId("fam-001")
    papa_id = MemberId("mem-papa")
    grandpa_id = MemberId("mem-grandpa")
    child_id = ChildId("child-leo")

    family = Family(
        id=family_id,
        name="The Family",
        members=(
            Member(papa_id, "Papa", MemberRole.PARENT),
            Member(grandpa_id, "Grandpa", MemberRole.GRANDPARENT),
        ),
        children=(ChildProfile(child_id, papa_id, "Leo", date(2023, 5, 14)),),
        created_at=datetime(2023, 5, 14, 10, 0, tzinfo=UTC),
    )
    families.save(family)

    use_case = GrandparentPromptUseCase(
        families=families,
        little_things=little_things,
        events=events,
        clock=clock,
        ids=ids,
        uow=uow,
    )

    return {
        "use_case": use_case,
        "families": families,
        "little_things": little_things,
        "family_id": family_id,
        "grandpa_id": grandpa_id,
        "child_id": child_id,
        "clock": clock,
    }


def test_grandparent_prompt_surfaces_30_days_before_turning_n(env):
    use_case: GrandparentPromptUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    grandpa_id: MemberId = env["grandpa_id"]
    child_id: ChildId = env["child_id"]

    # Exactly 30 days before turning 3 (April 14 for a May 14 birthday)
    prompt_res = use_case.check_eligible_prompt(family_id, grandpa_id, child_id)
    assert prompt_res.is_ok()
    prompt = prompt_res.unwrap()
    assert prompt is not None
    assert prompt.milestone_age_years == 3
    assert prompt.prompt_text == "What was his father like at 3?"


def test_grandparent_prompt_does_not_surface_outside_window(env):
    use_case: GrandparentPromptUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    grandpa_id: MemberId = env["grandpa_id"]
    child_id: ChildId = env["child_id"]
    clock: FrozenClock = env["clock"]

    # Move to January 1 (133 days before birthday)
    clock.advance(days=-104)
    prompt_res = use_case.check_eligible_prompt(family_id, grandpa_id, child_id)
    assert prompt_res.is_ok()
    assert prompt_res.unwrap() is None


def test_grandparent_response_is_saved_against_two_ages_at_once(env):
    use_case: GrandparentPromptUseCase = env["use_case"]
    little_things: SqliteLittleThingRepository = env["little_things"]
    family_id: FamilyId = env["family_id"]
    grandpa_id: MemberId = env["grandpa_id"]
    child_id: ChildId = env["child_id"]

    saved_thing = use_case.record_response(
        RespondGrandparentPromptCommand(
            family_id=family_id,
            grandparent_id=grandpa_id,
            child_id=child_id,
            milestone_age_years=3,
            text="His father was obsessed with building wooden blocks all morning.",
            audio_media_id="med-audio-grandpa",
        )
    ).unwrap()

    assert saved_thing.author_id == grandpa_id
    assert saved_thing.subject_child_id == child_id
    assert saved_thing.audio_media_id == "med-audio-grandpa"
    # Dual age annotation
    assert "[Ages: Child at 3, Parent at 3]" in saved_thing.text
    assert "building wooden blocks" in saved_thing.text

    # Read back through the repository, because a grandparent's answer that only exists in
    # the return value of the call that made it has not been kept.
    stored = little_things.list_for_family(family_id).unwrap()
    assert [t.id for t in stored] == [saved_thing.id]
    assert stored[0].text == saved_thing.text
    assert stored[0].audio_media_id == "med-audio-grandpa"

    # After answering, prompt is never asked again
    assert use_case.check_eligible_prompt(family_id, grandpa_id, child_id).unwrap() is None


def test_grandparent_prompt_can_be_skipped_forever(env):
    use_case: GrandparentPromptUseCase = env["use_case"]
    family_id: FamilyId = env["family_id"]
    grandpa_id: MemberId = env["grandpa_id"]
    child_id: ChildId = env["child_id"]

    # Grandparent chooses to skip for age 3
    use_case.skip_forever(family_id, grandpa_id, child_id, milestone_age_years=3)

    # Prompt is permanently silent for this year
    assert use_case.check_eligible_prompt(family_id, grandpa_id, child_id).unwrap() is None

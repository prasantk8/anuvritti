"""TASK-509 - the server half of capture that survives a lost signal.

The phone's half is a durable queue; this is what it replays into. The scenario the whole
mechanism exists for is mundane and constant: a parent shares something on the underground,
the request goes out, the connection dies before the response comes back. The phone has no
way to know whether it landed.

Without a key, both choices are wrong. Retry and the family gets two of the same Spark.
Don't, and the thing they wanted to keep is gone - which is the one failure this product is
not allowed to have.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.interfaces.http.idempotency import HEADER, MAX_KEY_LENGTH
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
REEL = {"kind": "URL", "url": "https://instagram.com/reel/balloon", "title": "Balloon rocket"}


@pytest.fixture
def client(tmp_path):
    clock = FrozenClock(T0)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "o.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    test_client = PairedClient(create_app(settings, container=container))
    test_client.clock = clock  # type: ignore[attr-defined]
    yield test_client
    container.close()


@pytest.fixture
def family(client):
    created = client.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    child = client.post(
        f"/v1/families/{created['id']}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()
    return {"id": created["id"], "child_id": child["id"]}


class TestReplayIsSafe:
    def test_the_same_key_twice_creates_one_spark(self, client, family):
        body = {"source": REEL}
        first = client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})
        second = client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})

        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert len(client.get("/v1/sparks").json()) == 1

    def test_the_replay_returns_the_original_answer_byte_for_byte(self, client, family):
        """The phone gets the Spark it already saved, not a fresh one that looks similar."""
        body = {"source": REEL}
        first = client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})
        client.clock.advance(days=30)
        second = client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})

        assert first.json() == second.json()

    def test_a_replay_says_so(self, client, family):
        body = {"source": REEL}
        client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})
        second = client.post("/v1/sparks", json=body, headers={HEADER: "queue-1"})
        assert second.headers.get("Idempotent-Replay") == "true"

    def test_a_whole_queue_replays_without_duplicating_anything(self, client, family):
        """What actually happens when the signal returns: the entire backlog goes at once."""
        queue = [
            {"key": f"q-{index}", "body": {"source": {"kind": "TEXT", "text": f"thing {index}"}}}
            for index in range(6)
        ]
        for entry in queue:
            client.post("/v1/sparks", json=entry["body"], headers={HEADER: entry["key"]})
        for entry in queue:  # the phone never saw the first round's responses
            client.post("/v1/sparks", json=entry["body"], headers={HEADER: entry["key"]})

        assert len(client.get("/v1/sparks").json()) == 6

    def test_key_order_in_the_body_does_not_matter(self, client, family):
        """Two serialisations of the same request are the same request."""
        client.post(
            "/v1/sparks",
            json={"source": REEL, "note": "for a rainy day"},
            headers={HEADER: "queue-1"},
        )
        again = client.post(
            "/v1/sparks",
            json={"note": "for a rainy day", "source": REEL},
            headers={HEADER: "queue-1"},
        )
        assert again.status_code == 201
        assert len(client.get("/v1/sparks").json()) == 1


class TestReplayIsHonest:
    def test_a_key_reused_for_a_different_request_is_a_conflict(self, client, family):
        """The detail that makes this safe rather than merely quiet.

        A client bug that recycled keys would otherwise drop real captures and look, from
        the outside, like everything was working.
        """
        client.post("/v1/sparks", json={"source": REEL}, headers={HEADER: "queue-1"})
        different = client.post(
            "/v1/sparks",
            json={"source": {"kind": "TEXT", "text": "something else entirely"}},
            headers={HEADER: "queue-1"},
        )
        assert different.status_code == 409
        assert different.json()["error"]["code"] == "CONFLICT"

    def test_a_rejected_request_is_not_pinned_to_its_key(self, client, family):
        """A 422 is a request the client should fix and send again.

        Remembering it would make the corrected retry fail forever, which is the worst of
        both worlds: the capture is lost and the phone thinks it succeeded.
        """
        bad = client.post(
            "/v1/sparks",
            json={"source": {"kind": "URL", "url": "not a url"}},
            headers={HEADER: "queue-1"},
        )
        assert bad.status_code == 422

        fixed = client.post("/v1/sparks", json={"source": REEL}, headers={HEADER: "queue-1"})
        assert fixed.status_code == 201

    def test_no_key_means_no_deduplication(self, client, family):
        """Capture without a key is the old behaviour, and it must stay honest about it."""
        client.post("/v1/sparks", json={"source": REEL})
        client.post("/v1/sparks", json={"source": REEL})
        assert len(client.get("/v1/sparks").json()) == 2

    @pytest.mark.parametrize("key", ["", "   ", "k" * (MAX_KEY_LENGTH + 1)])
    def test_an_unusable_key_is_rejected_rather_than_ignored(self, client, family, key):
        """Silently ignoring it would turn the queue's guarantee off without telling anyone."""
        response = client.post("/v1/sparks", json={"source": REEL}, headers={HEADER: key})
        assert response.status_code == 422


class TestReplayRespectsTheFamilyBoundary:
    def test_one_familys_key_cannot_surface_another_familys_answer(self, client, family):
        """The token's isolation rule, applied to the cache in front of it."""
        client.post("/v1/sparks", json={"source": REEL}, headers={HEADER: "shared-key"})

        stranger = client.another_device()
        stranger.post("/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"})
        theirs = stranger.post(
            "/v1/sparks",
            json={"source": {"kind": "TEXT", "text": "their private thing"}},
            headers={HEADER: "shared-key"},
        )

        assert theirs.status_code == 201
        assert theirs.json()["title"] == "their private thing"


class TestEverythingWorthReplayingAcceptsAKey:
    """A queue that can hold one kind of capture and not another is not an offline queue."""

    def test_little_things_replay(self, client, family):
        body = {"text": "He called the moon a broken sun."}
        first = client.post("/v1/little-things", json=body, headers={HEADER: "q"})
        second = client.post("/v1/little-things", json=body, headers={HEADER: "q"})
        assert first.json() == second.json()

    def test_right_now_replays(self, client, family):
        body = {"child_id": family["child_id"], "answer": "Volcanoes. Only volcanoes."}
        first = client.post("/v1/right-now", json=body, headers={HEADER: "q"})
        second = client.post("/v1/right-now", json=body, headers={HEADER: "q"})
        assert first.status_code == 201
        assert first.json() == second.json()

    def test_marking_a_spark_done_replays(self, client, family):
        """The one where a duplicate is a domain error rather than a duplicate row.

        Without the key, the replay hits `MomentRepository`'s unique constraint on spark_id
        and the phone sees a 409 for something that actually worked.
        """
        spark_id = client.post("/v1/sparks", json={"source": REEL}).json()["id"]
        body = {"reflection": "It hit the ceiling."}
        first = client.post(f"/v1/sparks/{spark_id}/done", json=body, headers={HEADER: "q"})
        second = client.post(f"/v1/sparks/{spark_id}/done", json=body, headers={HEADER: "q"})

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json() == second.json()

    def test_without_a_key_a_second_done_is_still_a_conflict(self, client, family):
        """Proving the test above measures the key and not a lenient domain rule."""
        spark_id = client.post("/v1/sparks", json={"source": REEL}).json()["id"]
        client.post(f"/v1/sparks/{spark_id}/done", json={})
        assert client.post(f"/v1/sparks/{spark_id}/done", json={}).status_code == 409

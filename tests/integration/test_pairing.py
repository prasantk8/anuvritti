"""TASK-511 - device pairing over HTTP, and the door it closes.

HARDENING 5.1 read: *"no authentication - any caller can act as any family."* That is not a
missing feature, it is the whole product's promise being false, because PRD 44 says a
family's archive is theirs. This file is the evidence that it is no longer true.

The tests are written from the outside, against the real stack, because that is where the
bug lived: every layer beneath was already correct, and the interface handed it the wrong
family id without complaint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.domain.access import MAX_ATTEMPTS
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)

#: Every route that must be unreachable without a token. If a new one is added and not
#: listed here, `test_the_whole_api_is_closed` fails - which is the point of listing them.
CLOSED_ROUTES = [
    ("GET", "/v1/sparks"),
    ("POST", "/v1/sparks"),
    ("GET", "/v1/sparks/anything"),
    ("POST", "/v1/sparks/anything/why"),
    ("POST", "/v1/sparks/anything/override"),
    ("POST", "/v1/sparks/anything/done"),
    ("GET", "/v1/return/worth-bringing-back"),
    ("POST", "/v1/return/anything/respond"),
    ("POST", "/v1/little-things"),
    ("GET", "/v1/right-now"),
    ("POST", "/v1/right-now"),
    ("GET", "/v1/media/anything"),
    ("POST", "/v1/media"),
    ("GET", "/v1/families/anything"),
    ("POST", "/v1/families/anything/children"),
    ("GET", "/v1/families/anything/export"),
    ("DELETE", "/v1/families/anything"),
    ("GET", "/v1/devices"),
    ("DELETE", "/v1/devices/anything"),
    ("POST", "/v1/pairing/codes"),
    ("POST", "/v1/film/compile"),
]


def _make(tmp_path, environment: str = "test"):
    clock = FrozenClock(T0)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": environment,
            "ANUVRITTI_DB_PATH": str(tmp_path / "p.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    client = PairedClient(create_app(settings, container=container))
    client.clock = clock  # type: ignore[attr-defined]
    return client, container


@pytest.fixture
def client(tmp_path):
    client, container = _make(tmp_path)
    yield client
    container.close()


@pytest.fixture
def paired(client):
    """The founding device: created the family, and was paired by that act."""
    created = client.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    return {"client": client, "family": created, "token": created["device"]["token"]}


class TestTheDoorIsShut:
    @pytest.mark.parametrize("method,path", CLOSED_ROUTES, ids=lambda v: str(v))
    def test_the_whole_api_is_closed_without_a_token(self, client, paired, method, path):
        stranger = client.as_unpaired()
        response = stranger.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    @pytest.mark.parametrize(
        "header",
        [
            "",
            "Bearer",
            "Bearer ",
            "Basic anv_something",
            "Bearer anv_not-a-real-token-but-long-enough-to-look-like-one",
            "anv_looks_like_a_token_without_a_scheme",
        ],
        ids=["empty", "no value", "empty value", "wrong scheme", "wrong token", "no scheme"],
    )
    def test_nothing_that_is_not_a_real_token_gets_in(self, client, paired, header):
        stranger = client.as_unpaired()
        response = stranger.get("/v1/sparks", headers={"Authorization": header})
        assert response.status_code == 401

    def test_the_scheme_is_case_insensitive_because_clients_disagree_about_it(self, paired):
        stranger = paired["client"].as_unpaired()
        for scheme in ("Bearer", "bearer", "BEARER"):
            assert (
                stranger.get(
                    "/v1/sparks", headers={"Authorization": f"{scheme} {paired['token']}"}
                ).status_code
                == 200
            )

    def test_liveness_stays_open_because_a_load_balancer_has_no_token(self, client):
        for path in ("/health", "/ready", "/metrics"):
            assert client.as_unpaired().get(path).status_code in {200, 503}


class TestBootstrapPairsTheFoundingDevice:
    def test_creating_the_family_returns_a_working_token(self, paired):
        assert paired["token"].startswith("anv_")
        assert paired["client"].get("/v1/sparks").status_code == 200

    def test_the_token_is_returned_exactly_once(self, paired):
        """It exists in plaintext for one response. Nothing can ask for it again."""
        devices = paired["client"].get("/v1/devices").json()
        assert devices and all("token" not in d for d in devices)

    def test_a_device_never_exposes_its_fingerprint_either(self, paired):
        """The fingerprint is not the token, but it is enough to confirm a guessed one."""
        assert "fingerprint" not in paired["client"].get("/v1/devices").text

    def test_the_family_is_protected_from_the_first_response_onward(self, paired):
        """There is no window between "the family exists" and "the family is protected"."""
        assert paired["client"].as_unpaired().get("/v1/sparks").status_code == 401


class TestPairingASecondDevice:
    def test_a_code_from_a_trusted_device_pairs_a_new_one(self, paired):
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        assert "-" in code

        new_phone = paired["client"].another_device()
        claimed = new_phone.post(
            "/v1/pairing/claim", json={"code": code, "device_name": "Mum's phone"}
        )
        assert claimed.status_code == 201

        # It is the *same* family, not a new one. This is the whole point of the flow.
        assert claimed.json()["family"]["id"] == paired["family"]["id"]
        assert new_phone.get("/v1/sparks").status_code == 200

    def test_both_devices_see_the_same_archive(self, paired):
        paired["client"].post(
            "/v1/sparks", json={"source": {"kind": "TEXT", "text": "the balloon rocket"}}
        )
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        new_phone = paired["client"].another_device()
        new_phone.post("/v1/pairing/claim", json={"code": code, "device_name": "Mum's phone"})

        assert len(new_phone.get("/v1/sparks").json()) == 1

    def test_a_code_works_once(self, paired):
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        first = paired["client"].another_device()
        assert (
            first.post("/v1/pairing/claim", json={"code": code, "device_name": "first"}).status_code
            == 201
        )
        second = paired["client"].another_device()
        assert (
            second.post(
                "/v1/pairing/claim", json={"code": code, "device_name": "second"}
            ).status_code
            == 401
        )

    def test_a_code_expires(self, paired):
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        paired["client"].clock.advance(minutes=11)
        late = paired["client"].another_device()
        assert (
            late.post("/v1/pairing/claim", json={"code": code, "device_name": "late"}).status_code
            == 401
        )

    def test_opening_a_code_needs_a_token_of_its_own(self, paired):
        """Otherwise anyone who can reach the port can mint themselves an invitation."""
        assert paired["client"].as_unpaired().post("/v1/pairing/codes").status_code == 401

    def test_guessing_is_locked_out_before_the_keyspace_is_reachable(self, paired):
        """40 bits divided by five guesses per window. The limit is what makes 8 characters safe."""
        paired["client"].post("/v1/pairing/codes")
        attacker = paired["client"].another_device()
        for _ in range(MAX_ATTEMPTS):
            assert (
                attacker.post(
                    "/v1/pairing/claim", json={"code": "ZZZZ9999", "device_name": "x"}
                ).status_code
                == 401
            )

        # Now even the real code does not work: the window is shut, not just this guess.
        real = paired["client"].post("/v1/pairing/codes").json()["code"]
        assert (
            attacker.post("/v1/pairing/claim", json={"code": real, "device_name": "x"}).status_code
            == 401
        )

    def test_the_lockout_lifts_when_the_window_passes(self, paired):
        attacker = paired["client"].another_device()
        for _ in range(MAX_ATTEMPTS):
            attacker.post("/v1/pairing/claim", json={"code": "ZZZZ9999", "device_name": "x"})

        paired["client"].clock.advance(minutes=11)
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        assert (
            attacker.post(
                "/v1/pairing/claim", json={"code": code, "device_name": "finally"}
            ).status_code
            == 201
        )

    @pytest.mark.parametrize("wrong", ["ZZZZ9999", "not a code", "", "aaaa1111"])
    def test_every_bad_code_gets_the_identical_answer(self, paired, wrong):
        """Wrong, malformed, expired and used are indistinguishable from the outside."""
        attacker = paired["client"].another_device()
        response = attacker.post("/v1/pairing/claim", json={"code": wrong, "device_name": "x"})
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "PAIRING_FAILED",
            "message": "that code did not work",
            "details": {},
        }


class TestRevocation:
    def test_a_lost_phone_can_be_cut_off(self, paired):
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        lost = paired["client"].another_device()
        device_id = lost.post(
            "/v1/pairing/claim", json={"code": code, "device_name": "the old iPad"}
        ).json()["device"]["id"]

        assert lost.get("/v1/sparks").status_code == 200
        assert paired["client"].delete(f"/v1/devices/{device_id}").status_code == 200
        assert lost.get("/v1/sparks").status_code == 401

    def test_a_parent_can_see_what_is_paired_by_a_name_they_chose(self, paired):
        code = paired["client"].post("/v1/pairing/codes").json()["code"]
        phone = paired["client"].another_device()
        phone.post("/v1/pairing/claim", json={"code": code, "device_name": "the old iPad"})

        names = [d["display_name"] for d in paired["client"].get("/v1/devices").json()]
        assert "the old iPad" in names

    def test_a_device_cannot_revoke_one_in_another_family(self, client, paired):
        stranger = client.another_device()
        theirs = stranger.post(
            "/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"}
        ).json()["device"]["id"]

        assert paired["client"].delete(f"/v1/devices/{theirs}").status_code == 404
        assert stranger.get("/v1/sparks").status_code == 200, "and they are unaffected"


class TestOneFamilyPerProductionBox:
    def test_a_second_family_cannot_bootstrap_in_production(self, tmp_path):
        """The bootstrap route is the only unauthenticated way in. It closes behind them.

        Second families arrive in TASK-901 with real accounts. Until then, leaving this open
        on a box on the public internet would mean a stranger could register alongside the
        family - isolated from their data, but present on their machine.
        """
        client, container = _make(tmp_path, environment="production")
        try:
            assert (
                client.post(
                    "/v1/families", json={"name": "Ours", "owner_display_name": "Papa"}
                ).status_code
                == 201
            )
            second = client.as_unpaired().post(
                "/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"}
            )
            assert second.status_code == 409
            assert second.json()["error"]["code"] == "CONFLICT"
        finally:
            container.close()

    def test_development_stays_open_so_the_tests_above_can_exist(self, client):
        for name in ("One", "Two"):
            assert (
                client.as_unpaired()
                .post("/v1/families", json={"name": name, "owner_display_name": "P"})
                .status_code
                == 201
            )


class TestTheTokenIsTheFamily:
    def test_a_body_that_names_another_family_is_refused_not_redirected(self, client, paired):
        """The important half of the design.

        Ignoring a wrong `family_id` and using the token's would be safe *and* wrong: a
        client with a stale id would write into the right family and never learn it had a
        bug. Disagreement is a 403, so the client finds out.
        """
        stranger = client.another_device()
        theirs = stranger.post(
            "/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"}
        ).json()["id"]

        response = paired["client"].post(
            "/v1/sparks",
            json={"family_id": theirs, "source": {"kind": "TEXT", "text": "not mine"}},
        )
        assert response.status_code == 403
        assert len(stranger.get("/v1/sparks").json()) == 0, "and nothing was written"

    def test_acting_as_another_member_is_refused(self, paired):
        response = paired["client"].post(
            "/v1/sparks",
            json={"owner_id": "someone-else", "source": {"kind": "TEXT", "text": "x"}},
        )
        assert response.status_code == 403

    def test_the_ids_may_be_omitted_entirely(self, paired):
        """What the generated client actually sends: nothing the token already says."""
        response = paired["client"].post(
            "/v1/sparks", json={"source": {"kind": "TEXT", "text": "the balloon rocket"}}
        )
        assert response.status_code == 201
        assert response.json()["family_id"] == paired["family"]["id"]

    def test_another_familys_media_is_not_downloadable(self, client, paired):
        stranger = client.another_device()
        stranger.post("/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"})
        photo = b"\xff\xd8\xff\xe0" + b"theirs" * 20
        media_id = stranger.post(
            "/v1/media", files={"file": ("a.jpg", photo, "image/jpeg")}
        ).json()["id"]

        assert stranger.get(f"/v1/media/{media_id}").status_code == 200
        assert paired["client"].get(f"/v1/media/{media_id}").status_code == 404

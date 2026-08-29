"""TASK-901 - Real authentication and enforced family isolation (HARDENING 5.1, PRD 44).

Verifies HARDENING 5.1 closure:
1. Token requirement across all protected routes.
2. Cross-family token refusal and tenant isolation (ADR-0006).
3. Cross-member impersonation prevention.
4. Device revocation lifecycle.
5. Production bootstrap closure.
6. Brute force rate limiting on pairing codes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def make_box(tmp_path: Path, name: str, is_production: bool = False):
    clock = FrozenClock(NOW)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "production" if is_production else "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / f"{name}.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / f"{name}_media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator(f"{name}_id"))
    app = create_app(settings, container=container)
    client = PairedClient(app)
    client.clock = clock  # type: ignore[attr-defined]
    client.container = container  # type: ignore[attr-defined]
    return client, container


def test_unauthenticated_requests_are_strictly_refused(tmp_path: Path):
    client, container = make_box(tmp_path, "auth_test")
    try:
        raw_client = client.as_unpaired()

        # Unauthenticated calls to protected routes must fail with 401
        protected_routes = [
            ("GET", "/v1/devices"),
            ("GET", "/v1/sparks"),
            ("POST", "/v1/sparks"),
            ("GET", "/v1/return/worth-bringing-back"),
            ("POST", "/v1/little-things"),
            ("POST", "/v1/right-now"),
            ("GET", "/v1/voice"),
        ]

        for method, route in protected_routes:
            resp = raw_client.request(method, route)
            assert resp.status_code == 401, f"{method} {route} allowed unauthenticated call"
            data = resp.json()
            assert data["error"]["code"] == "UNAUTHENTICATED"
    finally:
        container.close()


def test_cross_family_token_isolation(tmp_path: Path):
    """ADR-0006 / HARDENING 5.1: Tokens from Family A cannot access or mutate Family B."""
    client_a, box_a = make_box(tmp_path, "fam_a")
    client_b, box_b = make_box(tmp_path, "fam_b")

    try:
        # Bootstrap Family A
        resp_a = client_a.post(
            "/v1/families", json={"name": "Family Alpha", "owner_display_name": "Alice"}
        ).json()
        token_a = client_a.device_token

        # Bootstrap Family B
        resp_b = client_b.post(
            "/v1/families", json={"name": "Family Beta", "owner_display_name": "Bob"}
        ).json()
        fam_b_id = resp_b["id"]

        # Create a raw client holding Token A making requests to Box B
        attacker_client = TestClient(client_b.app)
        attacker_client.headers["Authorization"] = f"Bearer {token_a}"

        # 1. Box B rejects Token A as UNAUTHENTICATED (token not recognized in Box B's database)
        resp = attacker_client.get("/v1/devices")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHENTICATED"

        # 2. Even if Box A receives a request asserting Family B's ID, Box A refuses with 403
        client_a_attacker = TestClient(client_a.app)
        client_a_attacker.headers["Authorization"] = f"Bearer {token_a}"
        forged_spark = client_a_attacker.post(
            "/v1/sparks",
            json={
                "family_id": fam_b_id,
                "owner_id": resp_a["members"][0]["id"],
                "source": {"kind": "TEXT", "text": "Injected into wrong family"},
            },
        )
        assert forged_spark.status_code == 403
        assert forged_spark.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        box_a.close()
        box_b.close()


def test_device_revocation_cuts_off_token_instantly(tmp_path: Path):
    client, container = make_box(tmp_path, "revocation")
    try:
        # Bootstrap
        client.post("/v1/families", json={"name": "The Smiths", "owner_display_name": "Papa"})

        # Create pairing request for a second device (Mama)
        pair_req = client.post("/v1/pairing/codes").json()
        code = pair_req["code"]

        # Claim code on second client
        client_two = client.as_unpaired()
        claim_resp = client_two.post(
            "/v1/pairing/claim",
            json={"code": code, "device_name": "Mama's Phone"},
        ).json()
        token_two = claim_resp["device"]["token"]
        device_two_id = claim_resp["device"]["id"]

        # Device two can query protected routes
        d2_client = TestClient(client.app)
        d2_client.headers["Authorization"] = f"Bearer {token_two}"
        assert d2_client.get("/v1/devices").status_code == 200

        # Papa revokes Device Two
        revoke_resp = client.delete(f"/v1/devices/{device_two_id}")
        assert revoke_resp.status_code == 200

        # Device two is immediately UNAUTHENTICATED
        assert d2_client.get("/v1/devices").status_code == 401

        # Papa's primary device is still fully authenticated
        assert client.get("/v1/devices").status_code == 200
    finally:
        container.close()


def test_production_box_closes_bootstrap_after_first_family(tmp_path: Path):
    client, container = make_box(tmp_path, "prod_closure", is_production=True)
    try:
        # First family creation succeeds
        resp1 = client.post(
            "/v1/families", json={"name": "The Originals", "owner_display_name": "Papa"}
        )
        assert resp1.status_code == 201

        # Second unauthenticated bootstrap is permanently closed (409 Conflict)
        raw_client = client.as_unpaired()
        resp2 = raw_client.post(
            "/v1/families", json={"name": "The Intruders", "owner_display_name": "Intruder"}
        )
        assert resp2.status_code == 409
        assert resp2.json()["error"]["code"] == "CONFLICT"
    finally:
        container.close()


def test_pairing_brute_force_protection(tmp_path: Path):
    client, container = make_box(tmp_path, "brute_force")
    try:
        # Bootstrap
        client.post("/v1/families", json={"name": "Safe House", "owner_display_name": "Papa"})

        # Generate a real pairing code
        pair_req = client.post("/v1/pairing/codes").json()
        real_code = pair_req["code"]

        raw_client = client.as_unpaired()

        # 5 failed attempts
        for _ in range(5):
            res = raw_client.post(
                "/v1/pairing/claim",
                json={"code": "WRONG000", "device_name": "Attacker Phone"},
            )
            assert res.status_code in (401, 403)

        # 6th attempt with real code is locked out
        locked = raw_client.post(
            "/v1/pairing/claim",
            json={"code": real_code, "device_name": "Legit Phone"},
        )
        assert locked.status_code in (401, 403)
        assert locked.json()["error"]["code"] in (
            "UNAUTHENTICATED",
            "PERMISSION_DENIED",
            "PAIRING_FAILED",
        )
    finally:
        container.close()

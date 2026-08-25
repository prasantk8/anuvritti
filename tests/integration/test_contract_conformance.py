"""TASK-505 - the wire contract is single-sourced, and something checks it.

`docs/contracts/openapi.yaml` is hand-written and it is what `packages/client` is generated
from. That only means anything if the document and the running application cannot drift
apart, so this compares them both ways: every documented path must exist, and every
implemented path must be documented.

A generated client is worse than no client if it is generated from a lie.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from anuvritti.interfaces.http.app import create_app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "openapi.yaml"

#: Operational endpoints. Deliberately outside /v1 and outside the contract's `servers`
#: prefix, because a load balancer is not a client of the family's API.
OPERATIONAL = {"/health", "/ready", "/metrics"}

#: Documented but not routed, or routed but not documented, for a stated reason.
#: Empty on purpose - an entry here is a decision someone has to justify in review.
EXEMPT: set[str] = set()


#: HTTP methods FastAPI adds for free and the contract has no reason to describe.
_IMPLICIT = {"HEAD", "OPTIONS"}


def _documented() -> set[str]:
    """Method and path, not path alone.

    Comparing paths only is the version of this test that passes while `GET
    /families/{family_id}` goes undocumented for a year, because `DELETE` on the same path
    is there. The operation is the unit of a contract.
    """
    spec = yaml.safe_load(CONTRACT.read_text())
    return {
        f"{method.upper()} {path}"
        for path, operations in spec["paths"].items()
        if path not in OPERATIONAL
        for method, operation in operations.items()
        if isinstance(operation, dict)
    }


def _implemented(settings, container) -> set[str]:
    app = create_app(settings, container=container)
    return {
        f"{method} {route.path.removeprefix('/v1')}"
        for route in app.routes
        if getattr(route, "methods", None) and route.path.startswith("/v1")
        for method in route.methods - _IMPLICIT
    }


@pytest.fixture
def spec_and_app(tmp_path):
    from cryptography.fernet import Fernet

    from anuvritti.config.settings import load_settings
    from anuvritti.interfaces.http.container import build_container

    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "c.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings)
    yield _documented(), _implemented(settings, container)
    container.close()


class TestTheContractMatchesTheCode:
    def test_every_documented_path_is_implemented(self, spec_and_app):
        documented, implemented = spec_and_app
        missing = documented - implemented - EXEMPT
        assert not missing, f"promised in openapi.yaml and not routed: {sorted(missing)}"

    def test_every_implemented_path_is_documented(self, spec_and_app):
        """The direction that actually rots.

        A route added in a hurry is invisible to the generated client, so the app reaches
        for it by hand, and the contract quietly stops being the contract.
        """
        documented, implemented = spec_and_app
        undocumented = implemented - documented - EXEMPT
        assert not undocumented, f"routed and undocumented: {sorted(undocumented)}"

    def test_the_document_describes_a_closed_api(self):
        """Only the two routes that exist to obtain a token may opt out of the token."""
        spec = yaml.safe_load(CONTRACT.read_text())
        assert spec["security"] == [{"deviceToken": []}]

        open_operations = {
            f"{method.upper()} {path}"
            for path, operations in spec["paths"].items()
            for method, operation in operations.items()
            if isinstance(operation, dict) and operation.get("security") == []
        }
        assert open_operations == {"POST /families", "POST /pairing/claim"}

    def test_no_documented_field_hands_a_client_a_tally(self):
        """TASK-507, checked against the contract rather than the implementation.

        The client is generated from this document. If the count comes back here, it comes
        back in the generated types, whatever the server actually sends.
        """
        spec = yaml.safe_load(CONTRACT.read_text())
        fields = {
            name.lower()
            for schema in spec["components"]["schemas"].values()
            for name in (schema.get("properties") or {})
        }
        forbidden = {"days_since", "count", "streak", "score", "total", "rate", "points"}
        offenders = sorted(f for f in fields if any(bad in f for bad in forbidden))
        assert not offenders, f"the contract promises a number to display: {offenders}"

    def test_every_operation_a_client_is_generated_from_has_a_name(self):
        """`operationId` names the generated method, so it is contract, not decoration.

        An operation without one is silently skipped by the generator, which is the quiet
        way for an endpoint to exist in the server and not in the app.
        """
        spec = yaml.safe_load(CONTRACT.read_text())
        anonymous = sorted(
            f"{method.upper()} {path}"
            for path, operations in spec["paths"].items()
            if path not in OPERATIONAL
            for method, operation in operations.items()
            if isinstance(operation, dict) and not operation.get("operationId")
        )
        assert not anonymous, f"no operationId, so no generated client method: {anonymous}"

    def test_every_capture_endpoint_accepts_an_idempotency_key(self):
        """TASK-509. A queue that can hold one kind of capture and not another is not a queue."""
        spec = yaml.safe_load(CONTRACT.read_text())
        capture_paths = ["/sparks", "/little-things", "/right-now", "/sparks/{spark_id}/done"]
        for path in capture_paths:
            parameters = spec["paths"][path]["post"].get("parameters", [])
            refs = [p.get("$ref", "") for p in parameters]
            assert any("IdempotencyKey" in ref for ref in refs), (
                f"POST {path} cannot be safely replayed by an offline queue"
            )

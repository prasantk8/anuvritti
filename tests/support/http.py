"""A test client that behaves the way a real device behaves.

Since TASK-511 every route below the pairing boundary needs a bearer token. Rather than
teach eighty tests to thread a header, this client does what the phone does: it notices the
token it is given when the family is bootstrapped, and presents it from then on.

That is not a convenience shim around the auth boundary — it is a working model of the
client contract, and the tests exercise the real one because of it. A route that forgot its
dependency would still fail here, because a token that is never issued is never presented.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

BOOTSTRAP = "/v1/families"
CLAIM = "/v1/pairing/claim"


class PairedClient(TestClient):
    """A `TestClient` that pairs itself on the first bootstrap and stays paired."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.device_token: str | None = None

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        if self.device_token and "authorization" not in {
            key.lower() for key in (kwargs.get("headers") or {})
        }:
            headers = dict(kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {self.device_token}"
            kwargs["headers"] = headers

        response = super().request(method, url, **kwargs)
        self._remember_token(str(url), response)
        return response

    def _remember_token(self, url: str, response: Any) -> None:
        """Bootstrap and claim both hand back a token exactly once. Keep the first."""
        if self.device_token is not None or response.status_code != 201:
            return
        if not (url.endswith(BOOTSTRAP) or url.endswith(CLAIM)):
            return
        try:
            body = response.json()
        except ValueError:  # pragma: no cover - a 201 that is not JSON
            return
        device = body.get("device") if isinstance(body, dict) else None
        if isinstance(device, dict) and device.get("token"):
            self.device_token = device["token"]

    def as_unpaired(self) -> TestClient:
        """A second client against the same app, holding no token.

        For the tests that have to prove the door is actually shut.
        """
        return TestClient(self.app)

    def another_device(self) -> PairedClient:
        """A second phone against the same server, which will pair itself.

        Isolation is only really tested with two tokens. One token and a forged id proves
        the guard fires; two tokens prove the data behind it is actually separate.
        """
        return PairedClient(self.app)


__all__ = ["PairedClient"]

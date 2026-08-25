"""Idempotent capture (TASK-509).

A parent saves something on the underground. The phone writes it to a local queue and says
"Saved." — which is the truth, because the queue is durable. Later the signal returns and the
queue replays. The phone cannot know whether the POST that timed out actually landed, and
guessing wrong in either direction is bad: retry and the family gets the same Spark twice;
don't retry and it is gone.

`Idempotency-Key` removes the guess. The first request is performed and its response kept;
every replay of that key is answered with the same bytes and the same status.

One detail is what makes this safe rather than merely quiet. The stored entry carries a
fingerprint of the request that produced it, so a key reused with a *different* body is a
`CONFLICT` rather than a silent success. Without that, a client bug that recycled keys would
drop real captures and look, from the outside, like everything was working.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse, Response

from anuvritti.application.ports import IdempotencyStore
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId

#: Long enough for a UUID, bounded so a key cannot be used as free storage.
MAX_KEY_LENGTH = 200

#: The header. `Idempotency-Key` is the name Stripe established and clients already expect.
HEADER = "Idempotency-Key"


def request_fingerprint(endpoint: str, payload: Any) -> str:
    """A stable hash of what was asked for.

    `sort_keys` matters: two clients serialising the same body in a different key order are
    making the same request, and telling them they are not would be a bug of our making.
    """
    canonical = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def replay_or_perform(
    *,
    store: IdempotencyStore,
    clock: Clock,
    key: str | None,
    family_id: FamilyId,
    endpoint: str,
    payload: Any,
    perform: Callable[[], Response],
) -> Response:
    """Answer from the ledger if this key has been seen, otherwise perform and record it."""
    if key is None:
        return perform()

    key = key.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        return JSONResponse(
            status_code=422,
            content=DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"{HEADER} must be between 1 and {MAX_KEY_LENGTH} characters",
            ).to_dict(),
        )

    fingerprint = request_fingerprint(endpoint, payload)
    remembered = store.recall(key, family_id=family_id)
    seen = remembered.unwrap() if remembered.is_ok() else None
    if seen is not None:
        status_code, response_json, seen_fingerprint = seen
        if seen_fingerprint != fingerprint:
            return JSONResponse(
                status_code=409,
                content=DomainError(
                    ErrorCode.CONFLICT,
                    f"{HEADER} was already used for a different request",
                ).to_dict(),
            )
        return Response(
            content=response_json,
            status_code=status_code,
            media_type="application/json",
            headers={"Idempotent-Replay": "true"},
        )

    response = perform()

    # Only successes are remembered. A 422 is a request the client should fix and send
    # again, and pinning it to the key would make the corrected retry fail forever.
    if 200 <= response.status_code < 300:
        store.remember(
            key,
            family_id=family_id,
            request_fingerprint=fingerprint,
            status_code=response.status_code,
            response_json=bytes(response.body).decode("utf-8"),
            at=clock.now(),
        )
    return response


__all__ = ["HEADER", "MAX_KEY_LENGTH", "replay_or_perform", "request_fingerprint"]

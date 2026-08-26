"""Content addressing.

Every cache key and every manifest entry in this package is a hash of content,
never of a name and never of a time. That is the whole reason a cache can be
shared between two machines and still be correct: an entry is the answer to a
question about content, so either the question is still being asked or the
entry is dead weight.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(payload: dict[str, Any]) -> str:
    """A content address over a dict.

    `sort_keys` makes the key independent of the order the caller happened to
    build the dict in, and `default=str` means a `Path` or a `float` that
    wandered in does not turn a cache key into a crash. Nothing about *when*
    the payload was assembled is in here, which is what makes "did this
    change?" answerable without a timestamp.
    """
    return sha256_text(json.dumps(payload, sort_keys=True, default=str))

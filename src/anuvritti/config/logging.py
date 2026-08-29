"""Structured JSON logging.

12-factor: logs are an event stream on stdout. PRD 44/46: telemetry must never become a
second copy of the family archive, so content fields are redacted at the formatter - the
one place no caller can forget.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "anuvritti_request_id", default=None
)

#: Fields that may carry family content. Structural metadata is fine; content is not.
REDACTED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "why_text",
        "reflection",
        "note",
        "answer",
        "text",
        "title",
        "child_name",
        "display_name",
        "owner_display_name",
        "family_name",
        "author_name",
        "source_url",
        "media_bytes",
        "media_key",
        "authorization",
        "transcript",
        "transcript_text",
        "heard_text",
        "prompt",
        "filename",
        "file_name",
        "token",
        "pairing_code",
    }
)

_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "message",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with content fields redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = "[REDACTED]" if key in REDACTED_FIELDS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _StdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writes to whatever `sys.stdout` is *now*.

    `StreamHandler` captures the stream when it is constructed. That is fine for a
    long-running process, but it silently breaks anything that reassigns stdout - an
    embedding host, a captured subprocess, or a test harness. Resolving late costs
    nothing and removes a class of "logging mysteriously stopped" bugs.
    """

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[no-untyped-def]
        return sys.stdout

    @stream.setter
    def stream(self, value: object) -> None:
        """Ignore the base class's assignment; the property is the source of truth."""


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id.get()
        if request_id is not None:
            record.request_id = request_id
        return True


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the `anuvritti` logger. Idempotent."""
    logger = logging.getLogger("anuvritti")
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_RequestIdFilter())
    logger.addFilter(_RequestIdFilter())
    logger.addHandler(handler)


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """Attach a correlation id to every log line emitted inside this context."""
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"anuvritti.{name}")

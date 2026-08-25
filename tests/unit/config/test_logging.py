"""TASK-103 - structured logs. PRD 44: telemetry must not become a shadow family archive."""

from __future__ import annotations

import json
import logging

from anuvritti.config.logging import JsonFormatter, bind_request_id, configure_logging


def _emit(record_kwargs: dict | None = None, **extra) -> dict:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="anuvritti.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="spark captured",
        args=(),
        exc_info=None,
    )
    for key, value in (record_kwargs or {}).items():
        setattr(record, key, value)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(formatter.format(record))


class TestJsonFormatter:
    def test_emits_valid_json(self):
        assert _emit()["message"] == "spark captured"

    def test_includes_level_logger_and_utc_timestamp(self):
        payload = _emit()
        assert payload["level"] == "INFO"
        assert payload["logger"] == "anuvritti.test"
        assert payload["timestamp"].endswith("+00:00")

    def test_includes_request_id_when_bound(self):
        assert _emit({"request_id": "req-7"})["request_id"] == "req-7"

    def test_passes_through_structured_extras(self):
        payload = _emit({"spark_id": "s-1", "days_since_capture": 240})
        assert payload["spark_id"] == "s-1"
        assert payload["days_since_capture"] == 240

    def test_redacts_denylisted_fields(self):
        """Child names, why-text and media bytes never reach stdout."""
        payload = _emit({"why_text": "he reminds me of my father", "child_name": "Aarav"})
        assert payload["why_text"] == "[REDACTED]"
        assert payload["child_name"] == "[REDACTED]"

    def test_formats_exceptions_without_crashing(self):
        try:
            raise RuntimeError("db gone")
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                "anuvritti", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
            )
        payload = json.loads(JsonFormatter().format(record))
        assert "RuntimeError" in payload["exception"]

    def test_non_serialisable_extra_is_stringified_not_dropped(self):
        payload = _emit({"clock": object()})
        assert isinstance(payload["clock"], str)


class TestConfiguration:
    def test_configure_logging_is_idempotent(self):
        configure_logging("INFO")
        configure_logging("INFO")
        root = logging.getLogger("anuvritti")
        assert len(root.handlers) == 1

    def test_anuvritti_logger_does_not_propagate(self):
        """Propagation would double-log through the root handler."""
        configure_logging("INFO")
        assert logging.getLogger("anuvritti").propagate is False

    def test_bind_request_id_reaches_stdout(self, capsys):
        configure_logging("INFO")
        with bind_request_id("req-42"):
            logging.getLogger("anuvritti.bind").info("hello")
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["request_id"] == "req-42"
        assert payload["message"] == "hello"

    def test_request_id_is_absent_outside_a_binding(self, capsys):
        configure_logging("INFO")
        logging.getLogger("anuvritti.unbound").info("hello")
        payload = json.loads(capsys.readouterr().out.strip())
        assert "request_id" not in payload

    def test_binding_is_restored_after_the_context_exits(self, capsys):
        configure_logging("INFO")
        with bind_request_id("req-1"):
            pass
        logging.getLogger("anuvritti.after").info("hello")
        assert "request_id" not in json.loads(capsys.readouterr().out.strip())

    def test_log_level_is_honoured(self, capsys):
        configure_logging("WARNING")
        logging.getLogger("anuvritti.quiet").info("should not appear")
        assert capsys.readouterr().out == ""

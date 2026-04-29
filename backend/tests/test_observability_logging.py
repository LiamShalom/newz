"""JSON shape + bridge parity tests for observability/logging_config.py."""
import io
import json
import logging

import pytest
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from backend import config
from backend.observability.logging_config import configure_logging


@pytest.fixture
def json_capture(monkeypatch):
    monkeypatch.setattr(config, "LOG_FORMAT", "json")
    configure_logging()
    # Re-point root handler at our buffer
    buf = io.StringIO()
    for h in list(logging.getLogger().handlers):
        h.stream = buf
    yield buf
    clear_contextvars()


def test_stdlib_logger_emits_json_with_required_keys(json_capture):
    logging.getLogger("backend.test").info("hello world")
    line = json_capture.getvalue().strip().splitlines()[-1]
    evt = json.loads(line)
    for k in ("event", "level", "timestamp", "logger"):
        assert k in evt, f"missing key {k} in {evt}"
    assert evt["event"] == "hello world"
    assert evt["level"] == "info"


def test_contextvars_appear_in_bridged_log(json_capture):
    bind_contextvars(request_id="r1", session_hash="abc123")
    logging.getLogger("backend.test").info("ctx test")
    line = json_capture.getvalue().strip().splitlines()[-1]
    evt = json.loads(line)
    assert evt.get("request_id") == "r1"
    assert evt.get("session_hash") == "abc123"


def test_native_structlog_and_bridged_stdlib_have_same_keys(json_capture):
    bind_contextvars(request_id="r2")
    logging.getLogger("x").info("from_stdlib")
    structlog.get_logger("y").info("from_struct")
    lines = [l for l in json_capture.getvalue().strip().splitlines() if l]
    assert len(lines) >= 2
    a = json.loads(lines[-2])
    b = json.loads(lines[-1])
    # logger name differs, but the key set should match
    assert set(a.keys()) - {"logger"} == set(b.keys()) - {"logger"}


def test_configure_logging_idempotent(json_capture):
    # Second call must not raise. Each configure_logging() rebuilds the root
    # handlers (StreamHandler -> stderr by default), so re-point them at the
    # captured buffer after the double-config to observe the next log line.
    configure_logging()
    configure_logging()
    for h in list(logging.getLogger().handlers):
        h.stream = json_capture
    logging.getLogger("backend.test").info("after_double_config")
    line = json_capture.getvalue().strip().splitlines()[-1]
    evt = json.loads(line)
    assert evt["event"] == "after_double_config"

"""Sentry init + before_send_scrub end-to-end tests.

Locks T-08-03 / T-08-12 (HIGH-severity threat: Sentry leaks PII when DSN
accidentally set in OFFLINE_DEMO) by asserting init_sentry skips entirely
when SENTRY_DSN="". The "OFFLINE_DEMO smoke" test (D-16) re-imports the
observability package under the patched config and asserts zero
sentry_sdk.init calls happened during the import-time side effects.

Also locks T-08-13 (before_send_scrub fails on real Sentry event shape) via
realistic event-shape round-trip tests covering request.data, breadcrumbs,
and nested extra dicts.
"""
import importlib
import sys
from unittest.mock import patch

import pytest

from backend import config
from backend.observability.anonymity import before_send_scrub, REDACTED


# --- init_sentry behavior ---------------------------------------------------


def test_init_sentry_skips_when_dsn_empty(monkeypatch):
    """D-16 / T-08-12 — empty SENTRY_DSN must NOT call sentry_sdk.init."""
    monkeypatch.setattr(config, "SENTRY_DSN", "")
    with patch("sentry_sdk.init") as mock_init:
        from backend.observability.sentry import init_sentry
        init_sentry()
        mock_init.assert_not_called()


def test_init_sentry_calls_sdk_when_dsn_set(monkeypatch):
    """D-13 — when DSN is set, init is called once with the four locked kwargs."""
    monkeypatch.setattr(config, "SENTRY_DSN", "https://abc@sentry.example/1")
    monkeypatch.setattr(config, "SENTRY_ENVIRONMENT", "test-env")
    with patch("sentry_sdk.init") as mock_init:
        from backend.observability.sentry import init_sentry
        init_sentry()
        mock_init.assert_called_once()
        kwargs = mock_init.call_args.kwargs
        assert kwargs["dsn"] == "https://abc@sentry.example/1"
        assert kwargs["environment"] == "test-env"
        assert kwargs["traces_sample_rate"] == 0.0          # D-13
        assert kwargs["send_default_pii"] is False           # D-13 / OBS-02
        assert kwargs["max_request_body_size"] == "never"    # D-13 / OBS-02
        assert kwargs["before_send"] is before_send_scrub    # D-14 / OBS-03


def test_init_sentry_environment_defaults_to_production(monkeypatch):
    """D-13 — empty SENTRY_ENVIRONMENT defaults to 'production'."""
    monkeypatch.setattr(config, "SENTRY_DSN", "https://abc@sentry.example/1")
    monkeypatch.setattr(config, "SENTRY_ENVIRONMENT", "")
    with patch("sentry_sdk.init") as mock_init:
        from backend.observability.sentry import init_sentry
        init_sentry()
        assert mock_init.call_args.kwargs["environment"] == "production"


def test_offline_demo_app_import_makes_zero_sentry_calls(monkeypatch):
    """Highest-level smoke test for D-16 (locks T-08-12).

    SENTRY_DSN='' + force re-import of backend.observability => zero calls
    to sentry_sdk.init at import-time side-effect execution.
    """
    monkeypatch.setattr(config, "SENTRY_DSN", "")
    # Force re-import so module-level configure_logging() + init_sentry()
    # side effects in observability/__init__.py run again under the patch.
    for mod in (
        "backend.app",
        "backend.observability",
        "backend.observability.sentry",
        "backend.observability.logging_config",
    ):
        sys.modules.pop(mod, None)
    with patch("sentry_sdk.init") as mock_init:
        importlib.import_module("backend.observability")
        mock_init.assert_not_called()


# --- before_send_scrub realistic Sentry-event-shape round-trips -------------


def test_scrub_redacts_in_request_data():
    """T-08-13 — realistic Sentry event with PII in request.data is scrubbed."""
    event = {
        "event_id": "abc",
        "request": {
            "method": "POST",
            "url": "https://newz/clips",
            "data": {"session_uuid": "raw-uuid", "gps_lat": 34.1, "gps_lng": -118.1},
        },
    }
    out = before_send_scrub(event, {})
    assert out["request"]["data"]["session_uuid"] == REDACTED
    assert out["request"]["data"]["gps_lat"] == REDACTED
    assert out["request"]["data"]["gps_lng"] == REDACTED
    # Non-redacted fields preserved
    assert out["event_id"] == "abc"
    assert out["request"]["method"] == "POST"
    assert out["request"]["url"] == "https://newz/clips"


def test_scrub_redacts_in_breadcrumbs():
    """T-08-13 — Sentry breadcrumbs[].data redaction at multiple depths."""
    event = {
        "breadcrumbs": [
            {"category": "info", "data": {"clip_id": "ok"}},
            {"category": "error", "data": {"blob_url": "https://blob/x", "extra": "ok"}},
        ],
    }
    out = before_send_scrub(event, {})
    assert out["breadcrumbs"][1]["data"]["blob_url"] == REDACTED
    # Non-redacted preserved
    assert out["breadcrumbs"][0]["data"]["clip_id"] == "ok"
    assert out["breadcrumbs"][1]["data"]["extra"] == "ok"
    assert out["breadcrumbs"][0]["category"] == "info"
    assert out["breadcrumbs"][1]["category"] == "error"


def test_scrub_redacts_in_extra_nested():
    """T-08-13 — deeply nested extra.clip.blob_url redaction; sibling 'id' preserved."""
    event = {"extra": {"clip": {"blob_url": "https://blob/y", "id": "abc"}}}
    out = before_send_scrub(event, {})
    assert out["extra"]["clip"]["blob_url"] == REDACTED
    assert out["extra"]["clip"]["id"] == "abc"


def test_scrub_idempotent_on_realistic_event():
    """Idempotency on realistic full event (catches partial-scrub regressions)."""
    event = {
        "event_id": "e1",
        "request": {"data": {"session_uuid": "x"}},
        "breadcrumbs": [{"data": {"gps_lat": 1.0}}],
        "extra": {"blob_url": "y"},
    }
    once = before_send_scrub(event, {})
    twice = before_send_scrub(once, {})
    assert once == twice

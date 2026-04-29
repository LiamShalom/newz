"""Pure unit tests for backend/observability/anonymity.py."""
from backend.observability.anonymity import session_hash, before_send_scrub, REDACTED


def test_session_hash_is_sha256_hex():
    h = session_hash("test-uuid")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_session_hash_is_constant():
    assert session_hash("foo") == session_hash("foo")


def test_session_hash_distinct_inputs_diverge():
    assert session_hash("foo") != session_hash("bar")


def test_scrub_redacts_session_uuid_top_level():
    out = before_send_scrub({"session_uuid": "abc"}, {})
    assert out["session_uuid"] == REDACTED


def test_scrub_redacts_gps_lat_nested_in_extra():
    out = before_send_scrub({"extra": {"gps_lat": 34.1}}, {})
    assert out["extra"]["gps_lat"] == REDACTED


def test_scrub_redacts_gps_lng_nested():
    out = before_send_scrub({"request": {"data": {"gps_lng": -118.1}}}, {})
    assert out["request"]["data"]["gps_lng"] == REDACTED


def test_scrub_redacts_blob_url_in_breadcrumbs():
    event = {"breadcrumbs": [{"data": {"blob_url": "https://blob/x"}}]}
    out = before_send_scrub(event, {})
    assert out["breadcrumbs"][0]["data"]["blob_url"] == REDACTED


def test_scrub_passes_through_safe_fields():
    event = {"event_id": "abc", "level": "error", "message": "oops"}
    out = before_send_scrub(event, {})
    assert out == event


def test_scrub_handles_none_values():
    out = before_send_scrub({"extra": None, "session_uuid": None}, {})
    assert out["session_uuid"] == REDACTED
    assert out["extra"] is None


def test_scrub_no_mutation_during_iteration():
    # Pitfall 8 regression. All four redact keys at top level.
    event = {"session_uuid": "a", "gps_lat": 1.0, "gps_lng": 2.0, "blob_url": "x"}
    out = before_send_scrub(event, {})
    assert out is not event   # new object, not in-place mutation
    for k in ("session_uuid", "gps_lat", "gps_lng", "blob_url"):
        assert out[k] == REDACTED


def test_scrub_idempotent():
    event = {"session_uuid": "a", "extra": {"gps_lat": 34.1}}
    once = before_send_scrub(event, {})
    twice = before_send_scrub(once, {})
    assert once == twice

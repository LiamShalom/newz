"""D-12, D-13, D-18 verification + signature parity guard."""
import importlib
import inspect

import pytest


def _reload_storage(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)
    return backend.storage


def test_dispatcher_local_default(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    storage = _reload_storage(monkeypatch, OFFLINE_DEMO="false")
    assert storage.save_clip_bytes.__module__ == "backend.storage.local"


def test_dispatcher_blob_when_set(monkeypatch):
    storage = _reload_storage(
        monkeypatch,
        STORAGE_BACKEND="blob",
        OFFLINE_DEMO="false",
        BLOB_READ_WRITE_TOKEN="vercel_blob_rw_TESTSTORE_xxxxx",
    )
    assert storage.save_clip_bytes.__module__ == "backend.storage.blob"


def test_dispatcher_offline_demo_overrides(monkeypatch):
    storage = _reload_storage(
        monkeypatch,
        STORAGE_BACKEND="blob",
        OFFLINE_DEMO="true",
        BLOB_READ_WRITE_TOKEN="",
    )
    assert storage.save_clip_bytes.__module__ == "backend.storage.local"


def test_local_blob_signature_parity():
    from backend.storage import blob, local
    assert set(blob.__all__) == set(local.__all__)
    for name in blob.__all__:
        l_obj = getattr(local, name)
        b_obj = getattr(blob, name)
        assert inspect.iscoroutinefunction(l_obj) == inspect.iscoroutinefunction(b_obj), (
            f"{name}: async/sync mismatch"
        )
        l_sig = inspect.signature(l_obj)
        b_sig = inspect.signature(b_obj)
        assert len(l_sig.parameters) == len(b_sig.parameters), (
            f"{name}: param count mismatch local={l_sig} blob={b_sig}"
        )

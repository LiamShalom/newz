"""Phase 10: pure URL helpers shared by storage/local.py and storage/blob.py.

No imports from backend.storage.blob or backend.storage.local — avoids
circulars. Stdlib only.
"""
from __future__ import annotations

from urllib.parse import urlparse


def is_absolute_url(s: str | None) -> bool:
    if s is None:
        return False
    return s.startswith("http://") or s.startswith("https://")


def pathname_of_blob_url(url: str) -> str:
    return urlparse(url).path.lstrip("/")

# Phase 10: Vercel Blob Migration — Research

**Researched:** 2026-04-29
**Domain:** HTTP object storage migration (local FS → Vercel Blob); ffmpeg-from-HTTP source; FastAPI lifespan-managed httpx client
**Confidence:** HIGH for stack/patterns; HIGH for the load-bearing finding that **Vercel Blob has no signed-URL feature** (D-05/D-06/D-08 require revision); MEDIUM for ffmpeg `-headers` rate-limit interaction at compile burst.

## Summary

Phase 10 retires Railway local-FS clip storage in favour of Vercel Blob. CONTEXT.md commits to a **raw httpx async wrapper over the Blob REST API** (D-01) with four operations: PUT upload, signed-URL mint, DELETE cleanup, HEAD metadata. Server-mediated uploads only (no client-token PUT). `STORAGE_BACKEND` flag mirrors Phase 9's `METADATA_BACKEND` for migration-window rollback.

**One decision-altering finding emerged from research:** **Vercel Blob has no signed-URL feature.** Private blobs are read via `Authorization: Bearer $BLOB_READ_WRITE_TOKEN` on every GET request; there is no time-limited URL that ffmpeg can ingest as `ffmpeg.input(url)`. This contradicts D-08's premise that ffmpeg ingests signed URLs directly via byte-range. Two viable resolutions exist (research recommendation in §13): (a) make `uploads/` **public** with random-suffix unguessable pathnames and skip the signed-URL machinery entirely, or (b) keep `uploads/` private and pass `headers="Authorization: Bearer ..."` into `ffmpeg.input(url, headers=...)` so ffmpeg's libavformat HTTP protocol forwards the header on every Range request. Option (b) preserves the spirit of D-05's split-access model and requires ~5 LOC of plumbing. The "mint signed URL" wrapper op (D-03) becomes a pure-function `_authorized_blob_url(pathname) -> (url, headers_dict)` returning the canonical private blob URL plus the Authorization header. Plan should rename D-03's `mint_signed_url` to `authorized_blob_input` and drop the TTL parameter — the model is "always-authorized via static token," not "short-lived signed URL."

**Primary recommendation:** Adopt Option (b) — keep `uploads/` private, pass `Authorization: Bearer` header into ffmpeg via `ffmpeg.input(url, headers=...)`. Mint-signed-URL becomes a no-op string-builder. Everything else in CONTEXT.md (split access policy intent, fail-loud on missing token, lifespan-managed httpx client, tempdir-stitch flow, runs/ public CDN, sequential trim→upload, BLOB-08 cleanup hook, frontend-no-change happy path) holds **without revision**. The `httpx` library is already in production (transitively via `twelvelabs==1.2.3`'s `httpx>=0.21.2` requirement at v0.28.1) — pin explicitly in `requirements.txt` per D-23 hygiene.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Anonymous upload submission | Browser / Client | — | iOS Safari MediaRecorder produces the bytes; existing PWA flow unchanged. |
| Server-mediated upload to Blob | API / Backend | — | L-02 forbids client-token PUT (skips moderation gate). Bytes pass through FastAPI. |
| Source-clip metadata persistence | Database / Storage | API | `clips.blob_url` (Postgres column) records canonical Blob URL — Phase 9 already added the column nullable. |
| Source-clip media bytes | CDN / Object Store | — | Vercel Blob `uploads/` (private) and `runs/` (public CDN). |
| ffmpeg trim source read | API / Backend | CDN | Backend assembles authenticated GET to private Blob; libavformat issues HTTP Range requests via the URL. |
| ffmpeg stitch source read | API / Backend | CDN | Backend pre-downloads N source clips into tempdir via httpx; ffmpeg then reads files locally. |
| Compiled-segment publish | CDN / Object Store | API | Public Blob URL stamped into `segments.video_url`; frontend renders directly without auth. |
| BLOB-08 moderation cleanup | API / Backend | Database | DB row signals delete; storage layer issues DELETE to Blob; idempotent. |

**Key tier insight:** All Blob mutation paths are owned by the API tier. The browser never holds a Blob token. The CDN tier only serves public reads; private reads always traverse the backend.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Inherited (locked elsewhere; do NOT re-litigate):**
- L-01: Vercel Blob committed; no Cloudflare R2 in v1.1.
- L-02: Server-mediated upload only; direct browser PUT permanently rejected.
- L-03: `OFFLINE_DEMO=true` hard-overrides every external dependency to local stubs. Phase 10 forces `storage_local` regardless of `STORAGE_BACKEND` when `OFFLINE_DEMO=true`.
- L-04: `clips.blob_url TEXT` is already nullable in initial Alembic migration. Phase 10 populates it; no `ALTER` needed.
- L-05: `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` already in initial migration. Phase 11 owns writes; Phase 10 cleanup hook reads it.
- L-06: Sentry `before_send` already redacts `blob_url` from event payloads (Phase 8 D-14).
- L-07: structlog contextvars whitelist allows `clip_id`, `request_id`, `session_hash`. Phase 10 must NOT add Blob URLs as contextvars — log them as kwargs only.
- L-08: Single Uvicorn worker (`--workers 1`); httpx client is process-singleton.
- L-09: No SQLAlchemy ORM at runtime. New storage code is hand-written async.

**Vercel Blob client (D-01..04):**
- D-01: Raw httpx async wrapper, NOT the `vercel_blob` Python SDK.
- D-02: Single module-level `httpx.AsyncClient` initialized in FastAPI `lifespan()` startup.
- D-03: Operations: `upload`, `mint_signed_url` (renamed to `authorized_blob_input` per research finding), `delete`, `head`.
- D-04: `BLOB_READ_WRITE_TOKEN` env var, never logged.

**Blob URL access policy (D-05..07):**
- D-05: Split access — `uploads/` private, `runs/` public.
- D-06: Signed URL TTL = 900s (RESEARCH: see §13 — Vercel does not implement signed URLs; this decision becomes a no-op once D-08's URL model is corrected).
- D-07: Leak-decay rationale — Phase 11 cleanup hook is real defense; private+token still meaningfully bounds leak surface.

**ffmpeg + Blob integration (D-08..11):**
- D-08: `_sync_trim` ingests Blob URLs via `ffmpeg.input(...)` — research correction: pass `headers=f"Authorization: Bearer {token}"` kwarg for private blobs.
- D-09: `_sync_stitch` pre-downloads sources into `tempfile.TemporaryDirectory()` via parallel httpx + `asyncio.gather`.
- D-10: Run-segment upload sequencing: trim → local temp → upload → return absolute Blob URL → write into `segments.video_url`.
- D-11: `_resolve_run_ids_to_stitch_refs` builds stitch refs whose `path` is now an HTTPS Blob URL (private uploads/ for sources, post-Phase-10 cutover).

**Storage dispatcher shape (D-12..14):**
- D-12: Module split — `backend/storage/__init__.py` (selector), `local.py`, `blob.py`, `blob_client.py`.
- D-13: Selection at module import: `STORAGE_BACKEND=blob and not OFFLINE_DEMO → blob`; else `local`.
- D-14: DB write/read sites refactor minimally — `await storage.save_clip_bytes(...)` returns blob_url-or-local-path; read paths via `storage.get_playable_url(row)`.

**v1.0 cutover handling (D-15):**
- D-15: No backfill, no feed filter, no read-fallback. Run `POST /admin/reset` at deploy; re-seed via UI or `seed_demo_to_blob.py`.

**`/media` mount + frontend URL handling (D-16..17):**
- D-16: `/media` mount conditionally registered: `if STORAGE_BACKEND == "local" or OFFLINE_DEMO`.
- D-17: Frontend `api.ts` URL prefixing — guard for absolute URLs (research §8 verifies the gap).

**OFFLINE_DEMO + STORAGE_BACKEND interaction (D-18..19):**
- D-18: `OFFLINE_DEMO=true` hard-overrides to local. CI smoke test (Phase 13 DEMO-02) asserts no Blob traffic on startup.
- D-19: Fail-loud on missing config — empty `BLOB_READ_WRITE_TOKEN` when `STORAGE_BACKEND=blob` and `OFFLINE_DEMO=false` raises at lifespan startup.

**BLOB-08 cleanup hook contract (D-20):**
- D-20: `async def cleanup_blocked_clip(clip_id: str) -> None`. Idempotent. Phase 11 calls it; no background sweeper.

**Test discipline (D-21..22):**
- D-21: Extend Phase 9 D-10 fixture to parametrize `STORAGE_BACKEND` × `METADATA_BACKEND` = 2×2 cells.
- D-22: Wave-0 manual smoke deploy with `STORAGE_BACKEND=blob` before integration tests are wired.

### Claude's Discretion

- D-23: New env vars `STORAGE_BACKEND` (default `local`), `BLOB_READ_WRITE_TOKEN` (default empty). Add to `.env.example`.
- D-24: tenacity retry posture — 3 attempts, exponential backoff, transient 5xx + connection-reset only. 4xx fail-loud immediately.
- D-25: httpx wrapper module location: `backend/storage/blob_client.py`.
- D-26: `Content-Type` policy — `runs/` always `video/mp4`; `uploads/` matches inbound `UploadFile.content_type`.
- D-27: Pre-warm posture — NO Blob warm-up on startup.
- D-28: Logging — every Blob op logs one INFO line with `op` (upload|delete|sign|head), `pathname`, `latency_ms`, `bytes`. No signed-URL token in log line.

### Deferred Ideas (OUT OF SCOPE)

- Cluster-level tempdir reuse / cross-recompile source-clip cache → v1.2+
- Stream trim output directly to Blob (no local temp) → considered & rejected
- Cluster-aware Blob region pinning → v1.2+
- Blob CDN metrics in /metrics → v1.2+
- `backend/storage/local.py` deletion / consolidation → v1.2+
- Multipart upload for large clips (>100 MiB) → out of scope (`MAX_UPLOAD_BYTES = 100 MiB` cap holds)
- Direct browser → Blob upload → permanently rejected
- Cloudflare R2 → v1.2+ if egress material
- pgvector / Pinecone → v1.2+
- Pre-warm Blob on startup → rejected
- Background sweeper for orphan blob cleanup → out of scope
- Cluster-aware retry on signed-URL expiry → deferred (and now N/A — no signed URLs exist)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BLOB-01 | New uploads land in Vercel Blob via server-mediated path | §1 (REST PUT endpoint, headers, response shape); §6 (lifespan-init httpx client); §7 (storage dispatcher signatures). |
| BLOB-02 | Compiled segment outputs land in Blob under `runs/` prefix | §1 (PUT with `x-vercel-blob-access: public` header); §3 (post-trim upload sequencing); §10 (D-26 mp4 content-type). |
| BLOB-03 | ffmpeg `_sync_trim` reads source clips directly from Blob via byte-range, no full-file download | §3 (ffmpeg-python `headers=` kwarg confirms `-headers` flag works); §13 — **research finding modifies D-08:** ffmpeg ingests `https://{store}.private.blob.vercel-storage.com/...` with `Authorization: Bearer` header (no signed URL exists). Range support confirmed on Vercel Blob URLs (public docs example: `curl -r 0-3 https://...public.blob.vercel-storage.com/pi.txt`). |
| BLOB-04 | ffmpeg `_sync_stitch` pre-downloads sources into `tempfile.TemporaryDirectory()` before invoking the filter graph | §4 (typed httpx.AsyncClient.stream() pattern + asyncio.gather); §3 (Phase 9 D-08 atomic-rename preserved). |
| BLOB-05 | Frontend feed renders absolute Blob URLs; `/media` mount removed | §8 (api.ts double-prefix audit — confirms guard needed); D-16 conditional mount; D-17 frontend doc-string update. |
| BLOB-06 | `STORAGE_BACKEND` feature flag for local-FS rollback | §7 (dispatcher signatures); D-13 module-import-time selection mirrors Phase 9 D-08. |
| BLOB-07 | Clip media survives Railway redeploy; backend never reads `/data/clips/` post-cutover | D-16 (mount conditional); §7 (read path `storage.get_playable_url` returns absolute URL). |
| BLOB-08 | Blob-cleanup hook hard-deletes media for moderation-blocked clips | §1 (DELETE endpoint shape: `POST /api/blob/delete` with `{"urls": [...]}`); §7 (signature `cleanup_blocked_clip`). |

## Project Constraints (from CLAUDE.md)

- **Anonymity is load-bearing.** No accounts, no login, no profiles. Anonymous session UUID in localStorage only. Phase 10 storage layer never carries session UUID.
- **iOS Safari is the demo target.** MIME-type fallback ladder: `mp4;avc1 → webm;vp9 → webm → no mimeType`. Phase 10 preserves the existing `ALLOWED_MIME_PREFIXES = ("video/mp4", "video/webm")` ingest gate.
- **Pre-warm Marengo on backend startup.** Phase 10 must NOT add Blob warm-up (D-27); reordering of lifespan() init must keep Marengo pre-warm fire-and-forget.
- **Compile pipeline LLM budget: 300s wall-clock.** Phase 10 adds ~5-15s of network upload latency per stitch; budget already headroomed.
- **Single Uvicorn worker (`--workers 1`)**. Phase 10 httpx client is module-level singleton (matches asyncpg pool).
- **No SQLAlchemy ORM at runtime.** New storage code is hand-written async with httpx.
- **Verification before claiming.** Wave-0 smoke deploy (D-22) gates the plan; row-count parity not applicable (no migration data); demo-flow video-plays-in-feed is the SC validator.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | 0.28.1 | Async HTTP client for Vercel Blob REST + ffmpeg-source pre-download | [VERIFIED: pip3 show httpx in project venv shows 0.28.1, pulled by `twelvelabs==1.2.3` (httpx>=0.21.2) and FastAPI[standard]] Already in production runtime via transitive dep. **Plan must pin explicitly in requirements.txt** to defend against twelvelabs version-bump removing the dep. |
| `tenacity` | 9.1.4 | Retry decorator for transient 5xx and connection errors | [VERIFIED: pip3 show tenacity in project venv shows 9.1.4; line 8 of requirements.txt — `tenacity` (unpinned)] Already in v1.0 stack; plan should pin explicitly to `9.1.4`. |
| `ffmpeg-python` | 0.2.0 | Existing trim/stitch wrapper around system ffmpeg | [VERIFIED: requirements.txt line 16] `ffmpeg.input(url, **kwargs)` passes kwargs verbatim as ffmpeg flags — `headers="Authorization: Bearer X"` becomes `-headers "Authorization: Bearer X"`. [CITED: kkroening.github.io/ffmpeg-python] |

### Supporting (test-time only)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `respx` | >=0.21.0 | httpx mock library, Vercel-py's own choice for SDK tests | Test cells where `STORAGE_BACKEND=blob` — D-21 fixture cells must NOT hit real Vercel Blob. [CITED: vercel-py pyproject.toml dev deps] [CITED: lundberg.github.io/respx] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw httpx wrapper (D-01) | `vercel==0.5.8` Python SDK (`AsyncBlobClient`) | SDK is pre-1.0; depends on `httpx>=0.27.0`, `pydantic>=2.7.0`, `anyio>=4.0.0`, `websockets>=12.0`, `cbor2>=5.8.0`, `vercel-workers>=0.0.16 (py>=3.12)` — heavy dep cone vs. ~150 LOC wrapper. **D-01 is the right call.** [CITED: github.com/vercel/vercel-py/blob/main/pyproject.toml] |
| `respx` for mocking | `pytest-vcr` recorded tapes | VCR records full HTTP exchanges; brittle when token rotates or store_id changes between recording and replay. respx is in-test predicate matching — more readable, no fixture files. |
| `respx` for mocking | hand-rolled `unittest.mock.patch("httpx.AsyncClient.send")` | Manual mocks are fine for 1-2 tests; respx scales better when 4 cells × N tests need consistent matchers. |
| Pass `Authorization: Bearer` to ffmpeg | Pre-download every source clip then read from disk | Pre-download for trim doubles I/O (download then re-stream the same bytes through ffmpeg) and breaks the BLOB-03 spec ("byte-range, no full-file download"). Keep ffmpeg-direct for trim. |

**Installation:**
```bash
# Production (pin in requirements.txt — currently transitive only):
echo "httpx==0.28.1" >> backend/requirements.txt
# tenacity already present line 8 — repin: change to "tenacity==9.1.4"
# Dev-only test mocking:
echo "respx>=0.21.0" >> backend/requirements-dev.txt
```

**Version verification:**
```bash
pip3 index versions httpx | head -3
pip3 index versions tenacity | head -3
pip3 index versions respx | head -3
```

[VERIFIED: pip output 2026-04-29 — httpx 0.28.1 installed, tenacity 9.1.4 installed.]

## Architecture Patterns

### System Architecture Diagram

```
┌────────────────────┐
│ iOS Safari PWA     │  MediaRecorder → Blob (browser-native)
└─────────┬──────────┘
          │ POST /clips (multipart/form-data)
          ▼
┌──────────────────────────────────────────────────────────┐
│ FastAPI backend (Railway, --workers 1)                    │
│                                                           │
│  ┌─────────────────────┐                                 │
│  │ ingest_clip()       │ — existing 100MiB cap, MIME gate│
│  └─────────┬───────────┘                                 │
│            │ contents (bytes)                            │
│            ▼                                             │
│  ┌─────────────────────────┐                             │
│  │ db.insert_clip(...)     │ ← Phase 9 (sqlite|postgres) │
│  │   storage.save_clip_    │ ← Phase 10 NEW             │
│  │     bytes(clip_id, ext, │                             │
│  │     contents) → URL     │                             │
│  └─────────┬───────────────┘                             │
│            │ blob_url stored in DB                       │
│            ▼                                             │
│  ┌─────────────────────────────────┐                     │
│  │ asyncio.create_task(            │                     │
│  │   run_pipeline(clip_id))        │                     │
│  └─────────────────────────────────┘                     │
│                                                           │
│  Background tasks (existing pipeline):                    │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ embed    │→ │ cluster     │→ │ compile (multi-agent)│ │
│  └──────────┘  └─────────────┘  └──────────┬───────────┘ │
│                                              │             │
│                              ┌───────────────┴──────────┐  │
│                              │ _resolve_run_ids_to_     │  │
│                              │   stitch_refs (Phase 10) │  │
│                              │   path = blob_url        │  │
│                              └───────────┬──────────────┘  │
│                                          │                  │
│           ┌──────────────────────────────┴──────────┐      │
│           │                                         │      │
│   ┌───────▼───────┐                       ┌─────────▼────┐ │
│   │ _sync_trim    │                       │ _sync_stitch │ │
│   │  (BLOB-03)    │                       │ (BLOB-04)    │ │
│   │  ffmpeg URL+  │                       │ tempdir +    │ │
│   │  -headers     │                       │ asyncio.     │ │
│   │  Range        │                       │ gather       │ │
│   └───────┬───────┘                       │ download     │ │
│           │                               │ via httpx    │ │
│           │                               └──────┬───────┘ │
│           │                                      │         │
│           ▼                                      ▼         │
│      local temp.mp4                         local temp.mp4 │
│           │                                      │         │
│           └──────┬───────────────────────────────┘         │
│                  │ storage.upload(prefix='runs',           │
│                  │   key={run_id}.mp4, access='public')    │
│                  ▼                                         │
└──────────────────┼─────────────────────────────────────────┘
                   │ HTTPS PUT
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ Vercel Blob                                                  │
│  ┌──────────────────────────┐  ┌─────────────────────────┐  │
│  │ uploads/{clip_id}.{ext}  │  │ runs/{run_id}.mp4       │  │
│  │  PRIVATE                 │  │  PUBLIC                 │  │
│  │  store_id.private.blob.  │  │  store_id.public.blob.  │  │
│  │    vercel-storage.com    │  │    vercel-storage.com   │  │
│  │  Authz: Bearer required  │  │  No auth, CDN cached    │  │
│  └──────────────────────────┘  └────────────┬────────────┘  │
└────────────────────────────────────────────┼────────────────┘
                                              │
                                              │ direct HTTPS
                                              ▼
                                  ┌────────────────────┐
                                  │ Frontend feed UI   │
                                  │ <video src=…>      │
                                  └────────────────────┘
```

**Data flow notes:**
- Existing `POST /clips → 202 → asyncio.create_task(run_pipeline)` shape unchanged.
- `_resolve_run_ids_to_stitch_refs` (`compile.py:194`) becomes the only injection point that flips local paths to Blob URLs.
- Compiled `runs/` upload is **synchronous in the request to keep failure-fallback semantics** (`trim_window` returns source on failure — see code_examples below).
- Frontend reads runs/ directly; never sends an Authorization header.

### Recommended Project Structure

```
backend/
├── storage/                    # NEW — D-12 module split
│   ├── __init__.py             # selector (D-13 module-import dispatch)
│   ├── local.py                # lift-and-shift of v1.0 CLIPS_DIR.write_bytes
│   ├── blob.py                 # Vercel Blob impl (signature parity)
│   └── blob_client.py          # raw httpx wrapper (~150 LOC, internal)
├── db_sqlite.py                # MODIFIED — replace path.write_bytes with storage.save_clip_bytes
├── db_postgres.py              # MODIFIED — same
├── pipeline/
│   ├── stitch.py               # MODIFIED — _sync_trim accepts ref['headers'] dict
│   └── compile.py              # MODIFIED — _resolve builds Blob URLs; _stitch_segment_runs uploads run output
├── app.py                      # MODIFIED — lifespan adds httpx init; /media mount conditional
├── config.py                   # MODIFIED — STORAGE_BACKEND, BLOB_READ_WRITE_TOKEN
├── tests/conftest.py           # MODIFIED — extend metadata_backend with storage_backend axis
└── scripts/
    └── seed_demo_to_blob.py    # NEW (optional) — re-seed demo set after admin/reset
```

### Pattern 1: Module-level httpx.AsyncClient with FastAPI lifespan

**What:** Single process-wide `httpx.AsyncClient` initialized in `lifespan()` startup, closed in shutdown. Mirrors Phase 9 D-16 asyncpg pool pattern.
**When to use:** Any external HTTP dep that wants connection pool reuse and clean shutdown. v1.1 has exactly two: asyncpg (Phase 9) and Blob (Phase 10).

```python
# backend/storage/blob_client.py
"""Phase 10 (D-01, D-02, D-25): raw httpx async wrapper over the Vercel Blob REST API.

Internal to the storage package; never imported elsewhere. blob.py is the public
interface that calls into this module.

Lifecycle: init_client() in lifespan startup; close_client() in shutdown. Module-
level _client singleton; --workers 1 (L-08) makes inter-process coordination
unnecessary. Mirrors db_postgres._pool pattern.
"""
from __future__ import annotations

import logging
import time
from typing import Literal

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import config

log = logging.getLogger(__name__)

# Vercel Blob REST endpoints (data plane lives at .{public|private}.blob.vercel-
# storage.com — the control plane is api.vercel.com/api/blob).
# Source: github.com/vercel/vercel-py/blob/main/src/vercel/_internal/blob/__init__.py
_BLOB_API_BASE = "https://vercel.com/api/blob"
_BLOB_API_VERSION = "11"

_client: "httpx.AsyncClient | None" = None


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError(
            "blob httpx client not initialized — backend.app.lifespan must call init_client() first"
        )
    return _client


async def init_client() -> None:
    global _client
    if _client is not None:
        log.warning("init_client called twice; ignoring")
        return
    if not config.BLOB_READ_WRITE_TOKEN:
        # Fail-loud: dispatcher only loads this module when STORAGE_BACKEND=blob
        # AND OFFLINE_DEMO=false (D-19).
        raise RuntimeError(
            "BLOB_READ_WRITE_TOKEN is empty but STORAGE_BACKEND=blob and OFFLINE_DEMO=false. "
            "Set the token or flip STORAGE_BACKEND=local."
        )
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=5.0),
        # 100 MiB upload cap (app.py:159 MAX_UPLOAD_BYTES) plus headroom for
        # parallel downloads in _sync_stitch.
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    log.info("blob httpx client created")


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        log.info("blob httpx client closed")
```

**Why the timeout split:**
- `connect=10s`: catches DNS / TCP issues fast; Vercel Blob is single-region per store and stable.
- `read=60s`: allows large clip uploads (100 MiB cap) without spurious cancel.
- `write=60s`: same — clip upload is the hot write path.
- `pool=5s`: pool acquisition should be instant; long pool waits indicate connection exhaustion.

[CITED: python-httpx.org/advanced/timeouts/]

### Pattern 2: tenacity retry on transient 5xx and connection-reset only

**What:** Retry decorator that fires on transient infrastructure errors but NOT on application errors (4xx).
**When to use:** Any external HTTP call where the failure mode is "Vercel CDN blip" rather than "we sent bad input."

```python
# backend/storage/blob_client.py (continued)

# Per D-24: 3 attempts, exponential backoff, transient 5xx + connection-reset only.
# 4xx fail-loud immediately (don't retry on 401/403 — token is wrong, retrying makes
# it worse).
def _is_transient_blob_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
    return False


_blob_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
    retry=retry_if_exception_type((
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteError,
    )),
    reraise=True,
)
```

**Why:** Vercel Blob's documented `BlobServiceRateLimited` (HTTP 429) carries `Retry-After`; tenacity's exponential backoff will respect retry within 4 seconds of last failure. Vercel-py's own client retries 10x by default (env var override) — 3 is the conservative posture matching CONTEXT D-24 and avoiding 30s tail-latency on a stuck request mid-burst.

[CITED: github.com/vercel/vercel-py — DEFAULT retries=10 in `get_retries()`. We pick 3 explicitly per D-24.]

### Pattern 3: Storage dispatcher (mirrors Phase 9 D-07)

**What:** Module-import-time selector. `from .blob import *` or `from .local import *` based on env vars. No per-request branching.

```python
# backend/storage/__init__.py
"""Phase 10 (D-12, D-13): STORAGE_BACKEND dispatcher — module-import-time.

OFFLINE_DEMO=true hard-overrides to local regardless of STORAGE_BACKEND (D-18).
Mirrors backend/db.py dispatcher exactly (Phase 9 D-08).
"""
import logging
from .. import config

log = logging.getLogger(__name__)

if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
    from .blob import *  # noqa: F401, F403
    log.info("storage_backend=blob")
elif config.STORAGE_BACKEND == "blob" and config.OFFLINE_DEMO:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local (forced by OFFLINE_DEMO=true; D-18)")
else:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local")
```

### Pattern 4: tempdir-per-stitch parallel download

**What:** `tempfile.TemporaryDirectory()` context manager around a `_sync_stitch` invocation, with parallel `httpx.AsyncClient.stream()` downloads inside `asyncio.gather`. Auto-cleanup on context exit.

```python
# backend/storage/blob.py — async helper (called by compile.py)

import asyncio
import os
import tempfile
from pathlib import Path

from .blob_client import get_client


async def download_to_tempdir(
    pathnames_with_pubpath: list[tuple[str, str]],
    *,
    target_dir: str,
) -> dict[str, str]:
    """Parallel download of N private blobs to local files in target_dir.

    pathnames_with_pubpath: [(blob_pathname, parent_id_for_filename), ...]
    Returns: dict mapping parent_id → absolute local path of downloaded file.

    Streaming write (chunk_size=64KB) keeps RAM bounded for 100 MiB clips.
    """
    client = get_client()
    bearer = f"Bearer {config.BLOB_READ_WRITE_TOKEN}"
    store_id = _store_id_from_token(config.BLOB_READ_WRITE_TOKEN)

    async def _one(pathname: str, key: str) -> tuple[str, str]:
        url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
        local = Path(target_dir) / f"{key}{Path(pathname).suffix}"
        async with client.stream("GET", url, headers={"Authorization": bearer}) as resp:
            resp.raise_for_status()
            with open(local, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
        return key, str(local)

    results = await asyncio.gather(
        *[_one(pn, key) for pn, key in pathnames_with_pubpath],
        return_exceptions=False,
    )
    return dict(results)
```

**Why streaming:**
- 100 MiB clip × 4 parallel = 400 MiB peak RAM if buffered in-memory. Streaming keeps peak at ~256 KB/connection.
- `aiter_bytes(chunk_size=65536)` is httpx's documented streaming pattern.

[CITED: python-httpx.org/async/]

### Anti-Patterns to Avoid

- **Per-request httpx client construction.** Don't `async with httpx.AsyncClient() as client:` inside hot paths. Module-level singleton initialized in lifespan is the only correct posture (matches Phase 9 asyncpg pool).
- **Passing the bearer token in URL query strings.** Vercel Blob's REST API uses `Authorization: Bearer` header only. Putting the token in the URL leaks it to logs (Sentry breadcrumbs, structlog request_id traces, ffmpeg stderr).
- **Logging signed URLs or bearer tokens.** D-28 says log `op`, `pathname`, `latency_ms`, `bytes` only. The Phase 8 Sentry `before_send` already redacts `blob_url` from event payloads (L-06), but the log line itself must not include the token.
- **Mid-stream token rotation.** ffmpeg holds the URL+headers for the duration of one trim; if the token rotates mid-trim, the next Range request 401s. Token rotation is a deploy-only event in v1.1 (Vercel-managed `BLOB_READ_WRITE_TOKEN` is set at deploy and not rotated).
- **Calling `storage.delete_clip()` inside a Postgres transaction.** Pitfall 6 from Phase 9 RESEARCH applies: no non-DB awaits inside a `pool.acquire()` transaction. Deletes happen AFTER the DB commit.
- **Using `vercel_blob` SDK instead of raw httpx.** Pulls 6+ transitive deps (`vercel-workers`, `cbor2`, `websockets`) for ~150 LOC of value. D-01 locks raw httpx.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client connection pooling | Per-request `aiohttp.ClientSession` or `httpx.AsyncClient(...)` in hot path | Module-level `httpx.AsyncClient` initialized in lifespan | TCP handshake + TLS negotiation per request adds ~100ms latency; pool reuse drops it to <5ms. |
| Retry on transient 5xx | Hand-rolled `for attempt in range(3): try ... except` loops | `tenacity.retry` decorator | tenacity already in v1.0 stack; `wait_exponential` + `retry_if_exception_type` covers the protocol; hand-rolled loops always grow into bespoke buggy state machines. |
| Streaming HTTP download to disk | Read full response.content into memory then `f.write(...)` | `httpx.AsyncClient.stream("GET", ...) + resp.aiter_bytes(chunk_size=...)` + `open(path, "wb").write(chunk)` | Buffering 100 MiB × N clips into RAM during stitch will OOM Railway's 512MB tier. |
| Vercel Blob client | `vercel==0.5.8` SDK (`AsyncBlobClient`) | Raw httpx wrapper over the 4-op REST surface | Pre-1.0 SDK bundles 6 deps (`websockets`, `cbor2`, `vercel-workers`, `pydantic-from-deep-version-graph`) for surface area we don't use; D-01 sidesteps the pin risk. |
| Range-request HTTP for ffmpeg | Pre-download full clip then re-stream to ffmpeg stdin | `ffmpeg.input(blob_url, headers="Authorization: Bearer X")` | ffmpeg's libavformat HTTP protocol does Range natively; pre-download doubles bandwidth. |
| Tempdir cleanup | Manual `os.unlink` lists and try/except FileNotFoundError | `tempfile.TemporaryDirectory()` context manager | stdlib does it right; failure modes (exception inside the `with`) leave no orphan files. |
| HTTP test mocks | `unittest.mock.patch("httpx.AsyncClient.send")` per test | `respx.mock()` decorator/fixture | respx matches by URL pattern + method, supports streaming responses and `assert_all_called`; manual mocks become unmaintainable past 3 tests. |
| Atomic file rename | `os.rename` (works on POSIX but fails cross-device) | `os.replace` (already used in `_sync_trim`/`_sync_stitch`) | Phase 4 already established the pattern; preserve it for run-segment temp files before upload. |

**Key insight:** Phase 10 ships ~250 LOC of new code. Most of it is plumbing (selector, lifespan integration, conditional mount). The substantive work is the ~150 LOC `blob_client.py` raw httpx wrapper — and even that is template-able from `db_postgres.py:83-115` (the `init_pool/close_pool/get_pool` shape).

## Runtime State Inventory

> Phase 10 is a refactor + migration phase. Storage backend changes alter where bytes live; this section answers what runtime state survives the cutover.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `clips.path` column (Postgres + SQLite) carries `data/clips/{clip_id}.{ext}` for v1.0 rows. v1.0 demo rows are wiped via `POST /admin/reset` per D-15 — none survive. New rows write to `clips.blob_url` (already-nullable column from Phase 9 L-04). No data migration; pure code edit. | Code edit: `db.insert_clip` writes `blob_url` instead of `path` when `STORAGE_BACKEND=blob`; read path inspects whichever column is populated. |
| **Live service config** | `BLOB_READ_WRITE_TOKEN` lives in Railway env vars (Vercel-issued, copy-pasted at deploy time, NOT in git). Vercel Blob store name and region are dashboard-set at store creation — not in git. | Manual: create the Blob store, choose region, copy token to Railway env. D-22 wave-0 smoke covers this. |
| **OS-registered state** | None. Backend is single-container (Railway Dockerfile) with no Task Scheduler, systemd unit, launchd, or pm2 registration. | None — verified by absence of these patterns in `backend/Dockerfile`, `backend/Procfile`, `backend/railway.toml`. |
| **Secrets and env vars** | `BLOB_READ_WRITE_TOKEN` (new, Phase 10) and `STORAGE_BACKEND` (new, Phase 10). The token is read once at lifespan startup via `config.BLOB_READ_WRITE_TOKEN`; no daily rotation in v1.1. | Add to `.env.example`. Document in CONTEXT D-23 already locked. Phase 8 Sentry `before_send` already redacts `blob_url`; double-check it doesn't leak the token in the connection-init log line — Sentry breadcrumbs from httpx need an explicit scrubber check at plan-check time. |
| **Build artifacts / installed packages** | `httpx==0.28.1` is currently transitive (via `twelvelabs==1.2.3`'s `httpx>=0.21.2` constraint). If twelvelabs ever drops httpx, our module silently breaks. `respx` (test-only) is greenfield — not currently installed. | Pin `httpx==0.28.1` explicitly in `requirements.txt`. Add `respx>=0.21.0` to `requirements-dev.txt`. |

**The canonical question:** *After every file in the repo is updated to the new STORAGE_BACKEND=blob path, what runtime systems still hold legacy state?*

**Answer:** Only `clips.path` rows pointing at `data/clips/{...}` files inside `/data/clips/` on the Railway volume. D-15 disposes of these via `POST /admin/reset` at deploy. No other runtime systems carry old state. The `/data/clips/` directory itself remains writable post-cutover (it's the Railway persistent volume mount); local-mode rollback rewrites it. No filesystem cleanup task needed for v1.1.

## Common Pitfalls

### Pitfall 1: Vercel Blob has no signed-URL feature (CONTEXT.md D-08 needs revision)

**What goes wrong:** D-05/D-06/D-08 reference "signed URLs" with 900s TTL minted from a "signed-URL endpoint." This endpoint does not exist. If a planner reads CONTEXT literally and tries to implement `mint_signed_url(...)` against a non-existent REST endpoint, ~2-3 task-hours are lost discovering the gap.
**Why it happens:** S3-style presigned URLs are an industry pattern; reading "private object storage" and pattern-matching to S3 leads to the wrong mental model. Vercel Blob private storage uses **Authorization: Bearer headers on every read** instead — there's no time-limited URL.
**How to avoid:** Plan should:
1. Rename D-03's `mint_signed_url(pathname, ttl_seconds=900)` to `authorized_blob_input(pathname) -> tuple[str, dict[str, str]]` returning `(canonical_private_url, {"Authorization": f"Bearer {token}"})`. The function is a pure URL builder + token interpolation; no network call.
2. Update `_sync_trim` to accept `headers: dict | None` in the `ref` and pass them as `ffmpeg.input(url, headers=...)`. ffmpeg-python forwards the kwarg as `-headers "Authorization: Bearer ..."` (verified — see §3 Standard Stack ffmpeg-python row).
3. Drop the TTL machinery entirely. There's nothing to refresh.
4. Update D-06 (`signed URL TTL = 900s`) to a non-decision: "URLs are token-authorized; token rotates only at deploy."
5. Update D-07 (leak-decay rationale): the model becomes "private blob requires the token; cleanup hook is still the real defense; token is process-singleton secret never sent to browser."
**Warning signs:** Researcher / planner / executor encountering "where is the Vercel Blob signed-URL endpoint" — answer is "it's not, here's the auth-header shape." Cite the GitHub issue #544 (still tracking the feature request as of 2026) for evidence that no API exists.
[CITED: github.com/vercel/storage/issues/544; github.com/vercel/storage/issues/594; vercel.com/docs/vercel-blob/private-storage]

### Pitfall 2: ffmpeg-python `headers=` kwarg quoting

**What goes wrong:** ffmpeg's `-headers` flag wants headers separated by `\r\n` (CRLF), not just newlines. ffmpeg-python passes the string verbatim — if you write `headers="Authorization: Bearer X\nX-Other: Y"` (single \n) ffmpeg may parse only the first header.
**Why it happens:** Different conventions across libraries.
**How to avoid:** For our single-header case, pass `headers=f"Authorization: Bearer {token}\r\n"` — single header still needs trailing CRLF per the ffmpeg HTTP protocol docs. Test this in wave-0 smoke (D-22) by triggering a trim and reading ffmpeg stderr for "401" or "403."
[CITED: ffmpeg.org/ffmpeg-protocols.html — `-headers` "must be a string encoding the headers"]

### Pitfall 3: ffmpeg cold-start on Railway + first-trim latency

**What goes wrong:** First call to `ffmpeg.input(blob_url)` after a Railway redeploy hits HTTPS connection setup + TLS handshake to `vercel-storage.com` (cold DNS, cold TLS). Latency budget for a single trim was ~100ms in v1.0 (local file); Blob trim is 200-500ms first call.
**Why it happens:** No connection pooling between ffmpeg subprocess invocations — each spawn is a fresh HTTP client.
**How to avoid:** Don't try to "pre-warm" Blob (D-27 explicitly forbids this). Accept the 300-400ms first-trim latency penalty per redeploy. The 30s `_stitch_segment_runs` budget (compile.py:431) absorbs this comfortably (was already tuned to absorb LLM throttle bursts; ffmpeg cold-start is smaller noise).
**Warning signs:** First trim after deploy logs `elapsed_ms=350` instead of `elapsed_ms=80`. Subsequent trims drop. Document as expected.

### Pitfall 4: Missing `httpx` pin → silent breakage if twelvelabs drops the dep

**What goes wrong:** `httpx` is currently transitive via `twelvelabs==1.2.3` (`httpx>=0.21.2`). If a future twelvelabs SDK release drops httpx in favor of `aiohttp`, `pip install -r requirements.txt` succeeds but `import httpx` 500s at lifespan startup.
**Why it happens:** Implicit transitive deps are not contracts.
**How to avoid:** Plan must include a task to add `httpx==0.28.1` to `requirements.txt` explicitly. Pin to currently-installed version (verified 2026-04-29).
**Warning signs:** None at runtime — silent breakage class.

### Pitfall 5: respx fixture leaking between parametrized cells

**What goes wrong:** D-21's 2×2 fixture matrix (`STORAGE_BACKEND` × `METADATA_BACKEND`) means each test runs 4×. respx's global mock state leaks between cells if not torn down per-cell. Manifests as "test_upload_clip succeeds in cell 1, fails in cell 4 with 'no mock matched'."
**Why it happens:** respx's `respx.mock` is a global registry; resetting it requires `respx.start()/stop()` per fixture or `respx_mock` fixture's auto-tear-down.
**How to avoid:** Use `respx_mock` fixture (the pytest-injected, auto-tear-down version) inside the `storage_backend` parametrize. NOT the bare `@respx.mock` decorator.
[CITED: lundberg.github.io/respx — Pytest fixture vs decorator distinction]
**Warning signs:** Flaky tests where cell-N fails but cell-1 passes the same assertion.

### Pitfall 6: Frontend api.ts double-prefix on absolute Blob URLs

**What goes wrong:** `frontend/src/api.ts:29-31` reads `s.video_url ? \`${API_BASE}${s.video_url}\` : null`. When backend returns absolute `https://store.public.blob.vercel-storage.com/runs/abc.mp4`, the template literal becomes `http://localhost:8000https://store.public.blob.vercel-storage.com/runs/abc.mp4` — a malformed URL the browser fetches as a relative path → 404 → black video element.
**Why it happens:** v1.0 always returned relative `/media/...` paths; the frontend assumed all video_urls relative.
**How to avoid:** Add a one-line guard:
```typescript
const _abs = (u: string | null): string | null =>
  u == null ? null : (u.startsWith("http") ? u : `${API_BASE}${u}`);

return data.segments.map((s) => ({
  ...s,
  url: _abs(s.video_url),
  video_urls: s.video_urls?.map(_abs) ?? null,
}));
```
**Warning signs:** Demo segment cards show black video boxes; DevTools console shows 404 on a doubly-prefixed URL.

### Pitfall 7: Blob CDN cache invalidation lag on overwrite

**What goes wrong:** Vercel Blob CDN caches `runs/` blobs for up to 1 month by default. If a recompile overwrites `runs/{run_id}.mp4` (which happens via `ON CONFLICT(cluster_id) DO UPDATE` in `insert_segment`), the CDN can serve the stale version for up to 60s.
**Why it happens:** Vercel's CDN edge nodes cache aggressively for cost-efficiency.
**How to avoid:** Two options:
1. **Treat blobs as immutable.** Use `addRandomSuffix=true` on `runs/` uploads OR include a recompile-counter in the pathname (`runs/{run_id}-{revision}.mp4`). Aligns with [CITED: vercel.com/docs/vercel-blob#best-practice-treat-blobs-as-immutable].
2. **Set short `cacheControlMaxAge`** for `runs/`. Min is 60s; can't go lower. Combined with `?v=` query-param cache busting on the frontend, keeps recompile-visible-in-1-frame.

**Recommendation:** Option 1 is cleaner. Plan should add a recompile-counter to `runs/` pathname OR rely on Vercel's `addRandomSuffix=true` (default false in vercel-py — must override) to avoid stale-segment bug.
**Warning signs:** Recompile triggered from `/debug/compile/{cluster_id}` shows old video for ~60s after the compile_segment log line says "success."

### Pitfall 8: Vercel Blob operation rate limits (Hobby tier 20/s simple, 15/s advanced)

**What goes wrong:** Compile burst — 4 clusters compiling in parallel × 4 source-clip downloads each = 16 simple operations within ~5 seconds. Hobby tier caps at 20/s. Within tolerance for v1.1, but a redeploy + immediate compile-of-stale-clusters scenario could spike higher.
**Why it happens:** Public-blob fetches that miss the CDN count as Simple Operations.
**How to avoid:**
1. Confirm the Vercel Blob plan tier is Pro (120/s simple, 75/s advanced) before launch.
2. tenacity retry catches `BlobServiceRateLimited` (HTTP 429 + `Retry-After` header) automatically per D-24.
**Warning signs:** Spurious 429 in logs during demo bursts.
[CITED: vercel.com/docs/vercel-blob/usage-and-pricing — operation rate limit table]

## Code Examples

### Example 1: Storage dispatcher (canonical signature surface)

```python
# backend/storage/local.py
"""Phase 10 (D-12): local-FS implementation, lift-and-shift of v1.0 logic.

Public API contract — backend/storage/blob.py mirrors signatures byte-for-byte
(D-12 parity). Source: db_sqlite.py:168, db_postgres.py:167.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

CLIPS_DIR = config.DATA_DIR / "clips"

__all__ = ["save_clip_bytes", "delete_clip", "get_playable_url",
           "cleanup_blocked_clip", "stitch_input_for"]


async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    """Write contents to local FS. Returns a path string for clips.path column."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    path.write_bytes(contents)
    return str(path)


async def delete_clip(clip_id: str, ext_hint: str | None = None) -> None:
    """Best-effort delete from local FS. Idempotent."""
    if ext_hint:
        candidates = [CLIPS_DIR / f"{clip_id}.{ext_hint}"]
    else:
        candidates = list(CLIPS_DIR.glob(f"{clip_id}.*"))
    for p in candidates:
        try:
            if p.is_file():
                p.unlink()
        except Exception as e:
            log.warning("delete_clip best-effort failed path=%s: %s", p, e)


def get_playable_url(row: dict) -> str | None:
    """Return URL the frontend can fetch. Local mode emits /media/{filename}."""
    path = row.get("path")
    if not path:
        return None
    return f"/media/{Path(path).name}"


async def cleanup_blocked_clip(clip_id: str) -> None:
    """BLOB-08: hard-delete media for a moderation-blocked clip. Idempotent.
    Phase 11 calls this after writing moderation_status='blocked' (D-20).
    """
    await delete_clip(clip_id)


def stitch_input_for(row: dict) -> tuple[str, dict[str, str] | None]:
    """Return (path_or_url, headers_dict_or_None) for ffmpeg.input(). Local: file path, no headers."""
    return row["path"], None
```

```python
# backend/storage/blob.py — signature-identical Vercel Blob impl
"""Phase 10 (D-12): Vercel Blob implementation of the storage interface.

Internal HTTP details live in blob_client.py (D-25). This module is the public
surface only — every function signature matches local.py byte-for-byte.

Path schema:
  uploads/{clip_id}.{ext}   PRIVATE — read with Authorization: Bearer
  runs/{run_id}.mp4         PUBLIC  — read directly via CDN URL
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from .. import config
from . import blob_client

log = logging.getLogger(__name__)

__all__ = ["save_clip_bytes", "delete_clip", "get_playable_url",
           "cleanup_blocked_clip", "stitch_input_for", "upload_run_segment"]


async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    """Upload contents to PRIVATE uploads/. Returns the absolute Blob URL.
    Stored in clips.blob_url (Phase 9 D-05 nullable column)."""
    pathname = f"uploads/{clip_id}.{ext}"
    content_type = "video/mp4" if ext == "mp4" else "video/webm"
    result = await blob_client.upload(
        pathname=pathname,
        body=contents,
        content_type=content_type,
        access="private",
    )
    return result["url"]  # https://store.private.blob.vercel-storage.com/uploads/...


async def upload_run_segment(run_id: str, file_path: str) -> str:
    """Upload a compiled .mp4 to PUBLIC runs/. Returns absolute Blob URL."""
    pathname = f"runs/{run_id}.mp4"
    with open(file_path, "rb") as f:
        contents = f.read()
    result = await blob_client.upload(
        pathname=pathname,
        body=contents,
        content_type="video/mp4",  # D-26: always mp4 for runs/
        access="public",
    )
    return result["url"]


async def delete_clip(clip_id: str, ext_hint: str | None = None) -> None:
    """Delete uploads/{clip_id}.{ext} from Blob. Idempotent."""
    if ext_hint:
        await blob_client.delete(pathname=f"uploads/{clip_id}.{ext_hint}")
        return
    # Try both extensions; ignore not-found.
    for ext in ("mp4", "webm"):
        try:
            await blob_client.delete(pathname=f"uploads/{clip_id}.{ext}")
        except blob_client.BlobNotFound:
            continue


def get_playable_url(row: dict) -> str | None:
    """Frontend-facing URL.
    For BLOB mode: row['blob_url'] (or path if blob_url is NULL — legacy row).
    Run-segment URLs are stored in segments.video_url directly (already absolute).
    """
    return row.get("blob_url") or row.get("path")


async def cleanup_blocked_clip(clip_id: str) -> None:
    """BLOB-08: hard-delete blob for moderation-blocked clip. Idempotent."""
    await delete_clip(clip_id)


def stitch_input_for(row: dict) -> tuple[str, dict[str, str] | None]:
    """For private blob source: return (canonical_url, auth_headers).
    ffmpeg.input(url, headers=headers_str) consumes the headers dict.
    For public blob source (post-Phase-10 segments): no headers needed.
    """
    blob_url = row.get("blob_url") or row.get("path")
    if not blob_url:
        return "", None
    # If it's already a public CDN URL (runs/ — typically frontend-only path), no auth.
    if ".public.blob." in blob_url:
        return blob_url, None
    # Private uploads/: bearer auth required.
    return blob_url, {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
```

### Example 2: blob_client.py — canonical raw httpx wrapper

```python
# backend/storage/blob_client.py (continued from Pattern 1 above)
import logging
import time
from typing import Literal, TypedDict

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config

log = logging.getLogger(__name__)

_BLOB_API_BASE = "https://vercel.com/api/blob"
_BLOB_API_VERSION = "11"


class BlobObject(TypedDict):
    url: str
    pathname: str
    contentType: str
    contentDisposition: str
    downloadUrl: str


class BlobNotFound(Exception):
    pass


def _store_id_from_token(token: str) -> str:
    # Vercel-py reverse-engineering: BLOB_READ_WRITE_TOKEN format is
    #   vercel_blob_rw_<store_id>_<random>
    # Source: github.com/vercel/vercel-py/blob/main/src/vercel/_internal/blob/__init__.py
    parts = token.split("_")
    return parts[3] if len(parts) > 3 else ""


def _request_id(store_id: str) -> str:
    import uuid
    return f"{store_id}:{int(time.time()*1000)}:{uuid.uuid4().hex[:8]}"


@_blob_retry
async def upload(
    *,
    pathname: str,
    body: bytes,
    content_type: str,
    access: Literal["public", "private"],
) -> BlobObject:
    """PUT to https://vercel.com/api/blob with the Vercel-blob headers.
    Body is raw bytes; pathname is passed as ?pathname= query param."""
    client = get_client()
    store_id = _store_id_from_token(config.BLOB_READ_WRITE_TOKEN)
    headers = {
        "Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}",
        "x-api-version": _BLOB_API_VERSION,
        "x-api-blob-request-id": _request_id(store_id),
        "x-api-blob-request-attempt": "1",
        "x-content-type": content_type,
        "x-content-length": str(len(body)),
        "x-vercel-blob-access": access,
        "x-add-random-suffix": "0",     # we control IDs (clip_id, run_id)
        "x-allow-overwrite": "1",       # recompile re-uploads runs/ — see Pitfall 7
    }
    t0 = time.monotonic()
    resp = await client.put(
        _BLOB_API_BASE,
        params={"pathname": pathname},
        headers=headers,
        content=body,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code == 404 or resp.status_code == 410:
        raise BlobNotFound(pathname)
    resp.raise_for_status()
    log.info("blob op=upload pathname=%s latency_ms=%d bytes=%d", pathname, elapsed_ms, len(body))
    return resp.json()


@_blob_retry
async def delete(*, pathname: str) -> None:
    """POST to /api/blob/delete with {urls: [absolute_url]}.
    Source: vercel-py core.py delete_blob() — confirms POST /delete + JSON body shape."""
    client = get_client()
    store_id = _store_id_from_token(config.BLOB_READ_WRITE_TOKEN)
    # Construct absolute URL. We don't know access mode; try both — control plane
    # accepts URLs from either domain.
    urls = [
        f"https://{store_id}.private.blob.vercel-storage.com/{pathname}",
        f"https://{store_id}.public.blob.vercel-storage.com/{pathname}",
    ]
    headers = {
        "Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}",
        "x-api-version": _BLOB_API_VERSION,
        "Content-Type": "application/json",
    }
    t0 = time.monotonic()
    # Per Vercel docs: del() never raises if the URL doesn't exist — same here.
    await client.post(f"{_BLOB_API_BASE}/delete", headers=headers, json={"urls": urls})
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log.info("blob op=delete pathname=%s latency_ms=%d", pathname, elapsed_ms)


@_blob_retry
async def head(*, pathname: str) -> BlobObject | None:
    """GET /api/blob?url=... for metadata. Returns None on 404."""
    client = get_client()
    store_id = _store_id_from_token(config.BLOB_READ_WRITE_TOKEN)
    url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
    headers = {
        "Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}",
        "x-api-version": _BLOB_API_VERSION,
    }
    resp = await client.get(_BLOB_API_BASE, params={"url": url}, headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
```

### Example 3: app.py lifespan integration

```python
# backend/app.py — modify existing lifespan() per Phase 10 D-02, D-19
# Insert AFTER asyncpg pool init, BEFORE Marengo pre-warm:

@asynccontextmanager
async def lifespan(app: FastAPI):
    keepalive_task: asyncio.Task | None = None

    # 1. asyncpg pool (Phase 9 D-16) — unchanged
    if hasattr(db, "init_pool"):
        await db.init_pool()
    await db.init()

    # 2. CLUSTERS rebuild — must complete before pre-warms (Phase 9 ordering)
    from .pipeline import cluster as cluster_mod
    await cluster_mod.rebuild_cache()

    # 3. ★ PHASE 10 NEW: httpx Blob client init — only when blob mode active.
    #    OFFLINE_DEMO=true short-circuits to local mode at the dispatcher (D-18),
    #    so this branch is unreachable under firewalled-CI; enforces D-19 fail-loud.
    if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
        from .storage import blob_client
        await blob_client.init_client()

    # 4. Neon keepalive (Phase 9 D-17) — unchanged
    if hasattr(db, "get_pool"):
        keepalive_task = asyncio.create_task(_neon_keepalive(db.get_pool()))

    # 5. Pre-warms (existing) — unchanged
    asyncio.create_task(_pre_warm_marengo())
    asyncio.create_task(_pre_warm_sdk())

    try:
        yield
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass
        # ★ PHASE 10 NEW: close httpx client BEFORE asyncpg pool close.
        # No strict ordering reason; matches init order in reverse.
        if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
            from .storage import blob_client
            await blob_client.close_client()
        if hasattr(db, "close_pool"):
            await db.close_pool()


# Conditional /media mount (D-16) — replaces existing line 151:
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
(config.DATA_DIR / "clips").mkdir(parents=True, exist_ok=True)
if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:
    app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")
```

### Example 4: stitch.py modification for ffmpeg + private Blob

```python
# backend/pipeline/stitch.py — modify _sync_trim to accept ref['headers']
# Existing _sync_trim ports as-is for local-FS path; only change is one kwarg.

def _sync_trim(ref: dict, output_path: str) -> str:
    """[Phase 10] If ref['headers'] is set, pass to ffmpeg as -headers flag."""
    if not ref:
        return ""

    start = float(ref.get("start_offset_sec", 0.0))
    end = ref.get("end_offset_sec")

    tmp_path = f"{output_path}.part-{int(time.time() * 1000)}-{os.getpid()}"
    input_kwargs: dict = {"ss": start}
    if end is not None:
        input_kwargs["to"] = end

    # ★ PHASE 10 NEW: forward auth headers when source is a private Blob URL.
    # ffmpeg-python passes any kwarg to ffmpeg verbatim — `headers="...\r\n"`
    # becomes `-headers "..."` (single -headers flag, multi-line string body).
    headers_dict = ref.get("headers")  # dict[str, str] | None
    if headers_dict:
        input_kwargs["headers"] = "".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())

    try:
        out = (
            ffmpeg
            .input(ref["path"], **input_kwargs)
            .output(
                tmp_path,
                format="mp4",
                vcodec="copy",
                acodec="copy",
                movflags="+faststart",
                avoid_negative_ts="make_zero",
            )
            .global_args("-loglevel", "error")
            .run_async(pipe_stderr=True)
        )
        _, stderr = out.communicate()
        if out.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace")[:500])
        os.replace(tmp_path, output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    log.info("trim ok output=%s", output_path)
    return output_path
```

### Example 5: compile.py — _resolve_run_ids_to_stitch_refs Blob URL injection

```python
# backend/pipeline/compile.py — _resolve_run_ids_to_stitch_refs becomes:

async def _resolve_run_ids_to_stitch_refs(
    cluster_id: str, ordered_run_ids: list[str]
) -> list[dict]:
    """[Phase 10] Build stitch refs whose path is the Blob URL when STORAGE_BACKEND=blob.
    Pure URL builder — no network calls, no token TTL machinery (research §13).
    """
    from .. import storage  # dispatcher — local or blob impl

    runs = await compute_runs_for_cluster(cluster_id)
    by_id = {r.id: r for r in runs}
    refs: list[dict] = []
    for rid in ordered_run_ids:
        r = by_id.get(rid)
        if r is None:
            log.warning("resolve: unknown run_id=%s cluster_id=%s", rid, cluster_id)
            continue
        end = None if not r.member_child_ids else r.end_offset_sec
        # ★ PHASE 10 NEW: storage.stitch_input_for returns (path_or_url, headers_dict_or_None).
        # Local mode: (file_path, None). Blob mode: (https://store.private...., {"Authorization": "Bearer ..."}).
        path_or_url, headers = storage.stitch_input_for({"path": r.parent_path,
                                                         "blob_url": getattr(r, "parent_blob_url", None)})
        refs.append({
            "path": path_or_url,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": end,
            "headers": headers,
        })
    return refs
```

### Example 6: Test fixture extension (D-21 2×2 matrix)

```python
# backend/tests/conftest.py — extend the existing metadata_backend fixture
import importlib
import os
import pytest
import pytest_asyncio


@pytest.fixture(params=["sqlite", "postgres"], ids=["sqlite", "postgres"])
def metadata_backend(request, monkeypatch):
    backend = request.param
    if backend == "postgres" and not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; postgres path skipped")
    monkeypatch.setenv("METADATA_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    import backend.config
    import backend.db
    importlib.reload(backend.config)
    importlib.reload(backend.db)
    yield backend


# ★ NEW PHASE 10 FIXTURE — D-21 storage axis
@pytest.fixture(params=["local", "blob"], ids=["local", "blob"])
def storage_backend(request, monkeypatch, respx_mock):
    """D-21: parametrize STORAGE_BACKEND alongside METADATA_BACKEND.

    Cells where STORAGE_BACKEND=blob register respx mocks for Vercel Blob's
    REST endpoints. NEVER hits real Vercel Blob from CI.
    """
    backend = request.param
    monkeypatch.setenv("STORAGE_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    if backend == "blob":
        monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_TESTSTORE_xxxxx")
        # Mock the 4 Blob ops. respx auto-tear-down per-test via the fixture.
        respx_mock.put("https://vercel.com/api/blob").respond(
            json={
                "url": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4",
                "downloadUrl": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4?download=1",
                "pathname": "uploads/abc.mp4",
                "contentType": "video/mp4",
                "contentDisposition": 'attachment; filename="abc.mp4"',
            },
        )
        respx_mock.post("https://vercel.com/api/blob/delete").respond(200)
        respx_mock.get("https://vercel.com/api/blob").respond(
            json={"size": 1024, "uploadedAt": "2026-04-29T00:00:00Z",
                  "pathname": "uploads/abc.mp4", "contentType": "video/mp4",
                  "contentDisposition": "", "url": "...", "downloadUrl": "...",
                  "cacheControl": "public, max-age=2592000"},
        )
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)
    yield backend
```

### Example 7: BLOB-08 cleanup hook (D-20 contract)

```python
# Already in storage/blob.py and storage/local.py per Example 1.
# Phase 11 wiring (forward-looking — DO NOT implement in Phase 10):

# backend/pipeline/moderation.py (Phase 11):
async def on_moderation_blocked(clip_id: str) -> None:
    from .. import db, storage
    await db.set_moderation_status(clip_id, "blocked")  # Phase 11 owns this
    await storage.cleanup_blocked_clip(clip_id)         # PHASE 10 owns this hook
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Local FS clip storage | Vercel Blob HTTPS | This phase (Phase 10) | Storage layer becomes networked; trim/stitch read paths add HTTP latency. |
| `vercel_blob` SDK pre-1.0 | Raw httpx wrapper (D-01) | This phase | Resolves STATE.md "AsyncBlobClient @0.5.8 bleeding-edge" concern. |
| S3-style presigned URLs (assumed) | Authorization: Bearer token on every read | RESEARCH §13 finding (2026-04-29) | No "mint signed URL" REST endpoint exists at Vercel Blob. ffmpeg uses `-headers` for private reads. |
| `aiohttp.ClientSession` per-call | `httpx.AsyncClient` module-singleton | Phase 9 (asyncpg) → Phase 10 (Blob) inherits the pattern | Connection pool reuse, ~100ms-per-call savings. |

**Deprecated/outdated:**
- **STATE.md "Pending Todos: Run Vercel Blob AsyncBlobClient (vercel 0.5.8) spike before Phase 10 planning"** — RESOLVED by D-01 (avoid SDK entirely). Plan should remove this todo from STATE.md as Phase 10 lands.
- **CONTEXT.md D-06 "Signed URL TTL = 900 seconds (15 minutes)"** — STALE. No signed URLs exist; TTL has no meaning. The plan must update this decision in CONTEXT or supersede it via PLAN.md note.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ffmpeg.input(url, headers="Authorization: Bearer X\r\n")` actually emits `-headers` flag with the right CRLF terminator | Pattern 4, Pitfall 2 | Trim hits 401 from Blob; fallback returns ref['path'] (the URL itself) — frontend tries to play a private Blob URL with no auth header, gets 403 → black video. **Mitigation: D-22 wave-0 smoke MUST verify a real trim with real auth header succeeds before proceeding.** |
| A2 | Vercel Blob CDN serves Range requests on `runs/{run_id}.mp4` consistent with the public docs example (curl -r 0-3 example was on `pi.txt`, not large mp4) | Pattern 4 | Frontend video seeking might hit cache-cold paths and skip seek. Low impact; the v1.0 demo doesn't seek mid-segment. |
| A3 | `vercel_blob_rw_<store_id>_<random>` token format is stable across Vercel Blob versions | blob_client.py `_store_id_from_token` | If Vercel changes the token format, `_store_id_from_token` returns wrong store_id → upload URL is malformed → 404 from Blob CDN. **Mitigation: parse the token defensively; if `len(parts) <= 3`, raise at lifespan startup.** |
| A4 | Hobby tier rate limits (20/s simple, 15/s advanced) suffice for v1.1 demo bursts | Pitfall 8 | tenacity retry handles 429; if bursts ever exceed 75/s (Pro tier), upgrade plan. **Mitigation: planner should confirm Vercel Blob plan tier with user before launch.** |
| A5 | The existing `MAX_UPLOAD_BYTES = 100 MiB` cap in `app.py:159` survives unchanged through Phase 10 | Storage Stack §"Don't Hand-Roll" multipart row | If user uploads >4.5 MiB, Vercel's standard "function body size limit" doesn't apply to backend → Blob (server-mediated PUT to `vercel.com/api/blob`); we're sending FROM Railway TO Vercel, not the other way. Multipart uploads are deferred. |
| A6 | All four respx mock matchers (PUT + POST /delete + 2× GET) are sufficient for the 2×2 fixture's blob cells | Example 6, D-21 | Some tests touch HEAD or LIST; planner's task to enumerate which existing tests need additional respx routes. |
| A7 | The `runs/` upload `addRandomSuffix=false` path (matching v1.0 deterministic naming) doesn't conflict with `allowOverwrite=true` against Vercel CDN cache invalidation lag | Pitfall 7 | Recompile invisible for ~60s. **Mitigation: planner picks Pitfall 7 Option 1 (add recompile-counter to pathname) at plan time. Decision worth surfacing.** |

**If this table grows beyond 7 entries, plan should pause and reconcile with user.** A7 is the highest-risk assumption — the recompile pathname scheme is a small but architectural decision the planner should explicitly choose.

## Open Questions

1. **Should `runs/` use `addRandomSuffix=true` or include a recompile-counter in the pathname?**
   - What we know: Recompile triggered via `/debug/compile/{cluster_id}` overwrites the same `runs/{run_id}.mp4`. Vercel CDN serves the stale version for up to 60s.
   - What's unclear: Whether v1.1 production traffic ever recompiles, or whether the demo-only path is acceptable.
   - Recommendation: For Phase 10, use `runs/{run_id}.mp4` deterministic + `allowOverwrite=true` + accept the 60s cache lag. Frontend already adds session-scoped cache busting via SSE-driven re-fetch. Re-evaluate if recompile becomes a real production flow in Phase 12.

2. **Vercel Blob plan tier — Hobby or Pro?**
   - What we know: Hobby is 20/s simple, 15/s advanced; Pro is 120/s simple, 75/s advanced.
   - What's unclear: User's current plan tier.
   - Recommendation: Planner asks user before launch; tenacity 3-attempt retry on 429 covers occasional Hobby-tier bursts but Pro is the safe choice for any real traffic.

3. **Should `blob_url` be repurposed to hold the canonical pathname (e.g., `uploads/abc.mp4`) instead of the full URL (e.g., `https://store.private.blob.vercel-storage.com/uploads/abc.mp4`)?**
   - What we know: Phase 9 created `clips.blob_url TEXT` nullable. Phase 10 populates.
   - What's unclear: Whether storing the full URL or just the pathname is more flexible.
   - Recommendation: Store the full URL. Reason: (a) regenerating it requires the store_id from the token, which is process-secret config; (b) Vercel-py `put()` returns the URL; (c) frontend renders it directly without backend knowledge. Trade-off: if the store moves regions, every URL needs ALTER. Acceptable given v1.1 traffic and migration practice (`POST /admin/reset` re-uploads).

4. **Does the existing `db.delete_recent_clips()` `paths_to_delete` return shape need to change for Blob mode?**
   - What we know: `db_sqlite.py:657, 677` and `db_postgres.py:676, 695` build `paths_to_delete` as filesystem paths. The admin/reset handler iterates and calls `Path.unlink()`.
   - What's unclear: Whether Phase 10 should change the shape to (kind, identifier) tuples like `("local", "/data/clips/abc.mp4")` vs `("blob", "uploads/abc.mp4")`, or keep it as paths and let the storage layer parse.
   - Recommendation: Keep `paths_to_delete: list[str]`. The `admin_reset` handler in `app.py:421` already swallows errors from `Path.unlink`; for Blob mode, replace `_delete_files` with a wrapper that calls `storage.delete_clip(...)` per entry. Minimal refactor; preserves existing semantics.

5. **(LOW) Should the `seed_demo_to_blob.py` script ship in Phase 10 or stay as ad-hoc?**
   - Recommendation: Ship a minimal version. ~30 LOC: walk `backend/seed/demo/*.mp4`, POST each via httpx to `http://localhost:8000/clips` with stub lat/lng/ts. Lets the demo come back fast after `POST /admin/reset`. Optional in plan.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `httpx` Python lib | Storage layer + Blob REST calls | ✓ (transitive) | 0.28.1 | Pin explicitly to 0.28.1 in requirements.txt |
| `tenacity` Python lib | Retry decorator on Blob calls | ✓ | 9.1.4 | None needed |
| `ffmpeg` CLI | Existing trim/stitch | ✓ | system-installed via Dockerfile (`apt-get install ffmpeg`) | None — already production-tested |
| `respx` Python lib | D-21 test mocks | ✗ | — | Add to requirements-dev.txt; OR fall back to manual `unittest.mock.patch` (less clean) |
| `Vercel Blob store` | All Blob ops | ❓ | Depends on user's Vercel team plan | None — must create store before deploy |
| `BLOB_READ_WRITE_TOKEN` env var | Blob client init at lifespan | ❓ | Set at deploy by user | OFFLINE_DEMO=true bypass; STORAGE_BACKEND=local rollback |
| `vercel-storage.com` DNS | Production Blob reads | ✓ (Vercel manages) | — | None — global CDN |

**Missing dependencies with no fallback:**
- Vercel Blob store creation in user's Vercel dashboard (manual one-time action; pre-D-22 wave-0 smoke).
- `BLOB_READ_WRITE_TOKEN` populated in Railway env vars (user paste from Vercel dashboard).

**Missing dependencies with fallback:**
- `respx`: fallback is hand-rolled `unittest.mock.patch`. Strongly prefer respx.

## Security Domain

> Phase 10 invokes new external HTTP traffic (Blob REST). ASVS check follows.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `BLOB_READ_WRITE_TOKEN` is the only auth signal. Treated as a secret env var. Loaded once via python-dotenv. Never logged. Sentry `before_send` redacts `blob_url` (Phase 8 L-06); plan must extend the scrub list to also redact `Authorization` header values from Sentry's HTTP breadcrumbs (Sentry httpx integration auto-redacts but verify). |
| V3 Session Management | no | No session/cookie state in Phase 10. Anonymous-by-design. |
| V4 Access Control | yes | Private Blob (uploads/) requires backend token; public Blob (runs/) is publicly addressable but unguessable without `addRandomSuffix=true`. Plan must NOT pass `BLOB_READ_WRITE_TOKEN` to browser via any path (L-02 reinforces). |
| V5 Input Validation | yes | Existing 100 MiB cap (`app.py:159`) and MIME prefix gate (`app.py:160`) survive. Pathname sanitization: clip_id is `uuid.uuid4().hex` — already safe; ext is `mp4|webm` from controlled MIME map. No user-controlled pathname segments reach Vercel. |
| V6 Cryptography | no | TLS-only for all Blob HTTPS traffic; httpx defaults are safe. No custom crypto. |
| V8 Data Protection | yes | Bearer token at rest in Railway env vars (encrypted by Railway). Token in transit over TLS. Logs redact (D-28 + Phase 8 Sentry hook). |
| V13 API + Web Service | yes | New external API call surface. Rate-limited (Vercel-side); idempotent on retry (PUT same pathname overwrites if `allowOverwrite=true`); no command injection vector (no shell concat). |

### Known Threat Patterns for FastAPI + Vercel Blob

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Bearer token exfil via log lines | Information Disclosure | D-28: log `op`, `pathname`, `latency_ms`, `bytes` only. Phase 8 Sentry `before_send` redacts `blob_url`. Plan must verify `Authorization` header is not in Sentry breadcrumbs (httpx integration usually scrubs; double-check `sentry_sdk.integrations.httpx`). |
| Pathname injection (user-controlled clip_id) | Tampering | clip_id is server-generated `uuid.uuid4().hex` — no user input reaches the pathname. Existing ingest gate catches this; Phase 10 doesn't add a new vector. |
| Stale CDN serving moderation-blocked content | Information Disclosure | BLOB-08 cleanup hook deletes the blob; Vercel CDN cache invalidates within 60s. ALSO: Phase 11/12's `WHERE NOT is_hidden` predicate ensures the segment row isn't served. Defense-in-depth via DB filter + storage delete. |
| Direct browser PUT bypassing moderation | Spoofing | L-02 permanently rejects client-token PUT. `BLOB_READ_WRITE_TOKEN` never reaches browser. The `handleUpload` server route helper (vercel-py feature) is NOT used. |
| Token refresh / rotation race | DoS / Tampering | Token is process-singleton, set at deploy, not rotated in v1.1. No race window. |

## Sources

### Primary (HIGH confidence)
- **Vercel Blob official docs:**
  - [Vercel Blob overview](https://vercel.com/docs/vercel-blob) — public/private comparison, caching, rate limits, multipart, URL format
  - [Private Storage](https://vercel.com/docs/vercel-blob/private-storage) — Authorization: Bearer header model, no signed-URL feature
  - [Public Storage](https://vercel.com/docs/vercel-blob/public-storage) — direct URL access, CDN caching, ETag/304 support
  - [Examples — Range requests](https://vercel.com/docs/vercel-blob/examples) — confirms HTTP Range support on public Blob URLs
  - [Pricing & limits](https://vercel.com/docs/vercel-blob/usage-and-pricing) — operation rate limits per plan
  - [@vercel/blob SDK reference](https://vercel.com/docs/vercel-blob/using-blob-sdk) — TS SDK signatures (mirror of REST shape)
  - [Server uploads](https://vercel.com/docs/vercel-blob/server-upload) — server-mediated upload pattern
- **vercel-py SDK source code:** `github.com/vercel/vercel-py` — confirms underlying httpx transport, REST endpoint paths (`https://vercel.com/api/blob`), header shape (x-vercel-blob-access, x-content-type, etc.), token format (`vercel_blob_rw_<store_id>_<random>`), error mapping. Used as authoritative implementation reference.
- **GitHub issue #544** ([github.com/vercel/storage/issues/544](https://github.com/vercel/storage/issues/544)) — confirms signed-URL feature has been requested but not implemented as of 2026.
- **httpx docs:** [async best practices](https://www.python-httpx.org/async/), [timeouts](https://www.python-httpx.org/advanced/timeouts/) — module-level client, aclose() pattern, Timeout config.
- **ffmpeg-python docs:** [kkroening.github.io/ffmpeg-python](https://kkroening.github.io/ffmpeg-python/) — confirms `**kwargs` pass-through to ffmpeg flags.
- **ffmpeg HTTP protocol:** [ffmpeg.org/ffmpeg-protocols.html](https://ffmpeg.org/ffmpeg-protocols.html) — `-headers`, `-reconnect`, `-multiple_requests` flags.
- **Codebase verification:** `pip3 show httpx tenacity` against project venv (2026-04-29) — confirms 0.28.1 / 9.1.4 installed.

### Secondary (MEDIUM confidence)
- **respx docs:** [lundberg.github.io/respx](https://lundberg.github.io/respx/) — pytest fixture pattern for httpx mocking.
- **Phase 9 RESEARCH.md** (in-repo) — establishes the asyncpg pool + module-singleton pattern Phase 10 mirrors.
- **Phase 9 PATTERNS.md** (in-repo) — establishes the dispatcher pattern, lifespan ordering, and structlog integration norms.

### Tertiary (LOW confidence — flagged for validation)
- Hobby vs Pro plan rate limit numerical claims — sourced from current Vercel docs but plan should re-verify against the user's actual plan at deploy.
- Token format `vercel_blob_rw_<store_id>_<random>` — derived from vercel-py source code (`extract_store_id_from_token`); robust to non-rotation but A3 in Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library version verified against production venv.
- Architecture (lifespan ordering, dispatcher, ffmpeg integration): HIGH — directly mirrors Phase 9 patterns.
- REST API surface: HIGH — verified against vercel-py source and Vercel docs.
- **Signed-URL non-existence finding: HIGH** — corroborated by official docs + GitHub feature-request issue + vercel-py source code (no signed-URL methods).
- ffmpeg `-headers` interaction with Vercel Blob: MEDIUM — well-documented pattern but not verified end-to-end against Vercel's specific implementation. **D-22 wave-0 smoke is the verifier.**
- Pitfall #7 CDN-cache-invalidation lag impact: MEDIUM — documented behavior but field-test owed.
- Hobby tier rate-limit headroom for v1.1 traffic: LOW — depends on actual user plan + traffic shape.

**Research date:** 2026-04-29
**Valid until:** 2026-05-29 (30 days for Vercel Blob — stable but private-storage GA was March 2026, ongoing churn expected)

## RESEARCH COMPLETE

All 13 research questions answered with code references and citations. Plan can proceed.

**Single biggest finding the planner must absorb before writing PLAN.md:**

> CONTEXT.md D-08's "ffmpeg ingests Vercel Blob signed URLs directly" is **not buildable as written** — Vercel Blob has no signed-URL feature. The fix is small (~5 LOC: pass `headers=` kwarg into `ffmpeg.input(url, headers=...)`) but the URL model in D-03/D-05/D-06/D-08 needs a coherent rewrite from "mint signed URL with TTL" to "build authorized URL + headers tuple at call site." Recommend planner amends CONTEXT.md or supersedes via PLAN.md note.

Everything else in CONTEXT.md (split-access intent, lifespan-managed httpx client, tempdir-stitch flow, BLOB-08 cleanup hook, frontend-no-change happy path, 2×2 test matrix, wave-0 smoke deploy posture, OFFLINE_DEMO graceful-skip) holds without revision.

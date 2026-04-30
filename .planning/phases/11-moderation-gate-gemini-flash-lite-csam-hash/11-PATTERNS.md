# Phase 11: Moderation Gate (Gemini Flash-Lite + classifier-only CSAM) - Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 12 (4 new + 8 modified, post-reconciliation file set)
**Analogs found:** 12 / 12

> Reconciliation note: per `11-CONTEXT.md` reconciliation header (2026-04-29), Phase 11 ships
> classifier-only CSAM detection. This map omits `csam_client.py`, `CSAM_PROVIDER` env vars,
> Cloudflare client lifecycle, and `MODERATION_PROVIDER` parametrize fixtures. Decisions D-02,
> D-10, D-13, D-16..D-18, D-20..D-25, D-27..D-29 are superseded; this map encodes only the
> reconciled file set.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/pipeline/moderate.py` | service (pipeline stage) | request-response (Gemini SDK upload-poll-generate) + parallel cancel | `backend/pipeline/caption_pipeline.py:424-506` | exact (same SDK, same upload-poll-generate, same response_schema; parallel-cancel mirrors RESEARCH Pattern 2) |
| `backend/migrations/versions/20260430_0004_moderation_columns.py` | migration (DDL) | batch ALTER | `backend/migrations/versions/20260428_0002_relax_clips_path_not_null.py` | exact (ALTER + descends from existing head; same downgrade=raise pattern) |
| `backend/migrations/versions/20260430_0005_segments_soft_flag.py` | migration (DDL) | batch ALTER | `backend/migrations/versions/20260428_0002_relax_clips_path_not_null.py` | exact (additive ALTER ADD COLUMN with default) |
| `backend/tests/pipeline/test_moderate.py` | test (unit + behavioral) | request-response w/ respx mock | `backend/tests/test_blob_client.py` | exact (respx_mock fixture + module-reload pattern; conftest.py:69-103 supplies the storage_backend respx setup template) |
| `backend/pipeline/run.py` (modify ~L79) | controller (pipeline orchestrator) | request-response | self (existing `STAGE_DURATION` wrap pattern at L78,90) | exact (extends in-file pattern) |
| `backend/db_postgres.py` (modify) | service (data layer, asyncpg) | CRUD | `backend/db_postgres.py:484-514` (insert_comment / list_comments / count_comments_since) | exact (Phase 01 comment writes are the most recent insert + read pair; UNIQUE constraint precedent at insert_segment L334-349) |
| `backend/db_sqlite.py` (modify) | service (data layer, aiosqlite) | CRUD | `backend/db_sqlite.py:509-544` (insert_comment / list_comments / count_comments_since) | exact (parity contract — same module, same pair as the postgres analog) |
| `backend/config.py` (modify) | config | static load | `backend/config.py:46-67` (Phase 9 + Phase 10 env-var blocks) | exact (extends in-file pattern) |
| `backend/.env.example` (modify) | config | docs | self (Phase 9/10 entries) | exact (cannot be read in this env — see "No Analog Found / Caveat" below) |
| `backend/observability/__init__.py` (modify — extend scrubber via `anonymity.REDACT_KEYS`) | utility (PII scrub) | transform | `backend/observability/anonymity.py:18-25` | exact (one-liner addition to `REDACT_KEYS` frozenset) |
| `backend/tests/conftest.py` (modify) | test fixture | mock setup | `backend/tests/conftest.py:69-109` (storage_backend with respx_mock) | exact (in-file precedent for respx-based parametrize fixture) |
| `backend/pipeline/compile.py` (modify) | service (pipeline stage) | batch read + write | `backend/pipeline/compile.py:537-634` (compile_segment Phase 1.5 parent-diversity guard) | role-match (defensive cluster-member iteration + row patch — mirrors `_enforce_parent_diversity` shape) |
| `backend/app.py` (lifespan one-line WARN) | config (startup guard) | event-driven (lifespan) | `backend/app.py:51-67` (_pre_warm_sdk gracefully-degrades + WARN log) | exact (same `log.warning(...)` posture, same conditional guard) |
| `frontend/src/types.ts` (modify) | model (TS interface) | static type | `frontend/src/types.ts:52-84` (Segment interface fields) | exact (additive optional/boolean field — extends in-file pattern) |

---

## Pattern Assignments

### `backend/pipeline/moderate.py` (new — service, request-response + parallel cancel)

**Analog:** `backend/pipeline/caption_pipeline.py:424-506` (Gemini SDK call) + `backend/pipeline/run.py:55-111` (structlog/STAGE_DURATION boundary) + RESEARCH.md Pattern 2 (asyncio.wait FIRST_COMPLETED).

**Module docstring + imports pattern** (mirror `caption_pipeline.py:1-20` + `embed.py:1-30`):
```python
"""backend/pipeline/moderate.py — Gemini 2.5 Flash-Lite moderation classifier.

Public API:
    moderate_clip(clip_id) -> ModerationResult
        Async entry point. Called from run_pipeline() at run.py:79.
        Runs Gemini classifier in parallel with embed_worker via
        asyncio.wait FIRST_COMPLETED (cancel-when-embed-finishes, D-03).

Constants:
    SYSTEM_PROMPT       — locked classifier prompt (D-12; see RESEARCH §Recommended SYSTEM_PROMPT).
    PROMPT_VERSION      — semver string persisted on every moderation_decisions row.
    RESPONSE_SCHEMA     — Gemini response_schema mirroring caption_pipeline.py:474-476.
"""
import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass

from .. import config, db
from ..observability.metrics import STAGE_DURATION
from .embed import embed_worker

log = logging.getLogger(__name__)
```

**Gemini SDK call pattern** — copy verbatim from `caption_pipeline.py:424-479`, swap `config.GEMINI_MODEL` → `config.GEMINI_MODERATION_MODEL`, swap `SYSTEM_PROMPT` text + `RESPONSE_SCHEMA`, drop the file-upload step (classifier takes raw bytes via `client.files.upload` like caption does, since Flash-Lite supports the same Files API):
```python
# Verbatim from caption_pipeline.py:424-479 — only the schema/prompt/model differ.
try:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=120_000),  # ms
    )

    # 1. Upload (sync SDK call wrapped in executor)
    loop = asyncio.get_running_loop()
    uploaded = await asyncio.wait_for(
        loop.run_in_executor(None, lambda: client.files.upload(file=clip_local_path)),
        timeout=30.0,
    )

    # 2. Poll until ACTIVE
    for _ in range(30):  # ~30s ceiling
        if uploaded.state.name == "ACTIVE":
            break
        await asyncio.sleep(1)
        uploaded = await loop.run_in_executor(
            None, lambda: client.files.get(name=uploaded.name)
        )
    if uploaded.state.name != "ACTIVE":
        log.warning(
            "moderate: file did not reach ACTIVE state clip_id=%s state=%s",
            clip_id, uploaded.state.name,
        )
        return None

    # 3. Generate content with structured JSON schema
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=config.GEMINI_MODERATION_MODEL,           # NEW config var (D-24 retained)
                contents=[uploaded, "Classify this clip per the locked taxonomy."],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,           # Phase 11 prompt
                    temperature=0.0,                            # deterministic — moderation, not creative
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,            # locked taxonomy (D-11)
                ),
            ),
        ),
        timeout=125.0,                                          # belt-and-suspenders alongside outer wait
    )

    parsed = json.loads(response.text)
    # ... verdict aggregation ...
finally:
    try:
        await loop.run_in_executor(None, lambda: client.files.delete(name=uploaded.name))
    except Exception as e:
        log.warning("moderate: file cleanup failed: %s", e)
```

**SYSTEM_PROMPT + PROMPT_VERSION constants pattern** (mirror `caption_pipeline.py:36` and `caption_pipeline.py:145`):
```python
# caption_pipeline.py:36 establishes the convention — module-level constant, triple-quoted, with a docstring above.
SYSTEM_PROMPT = """You are an AP-wire breaking-news writer for a hyperlocal news app.
..."""

RESPONSE_SCHEMA = {
    # caption_pipeline.py:145+ shape — Gemini structured-output schema dict
    ...
}
```
For Phase 11: `PROMPT_VERSION = "1.0.0"` lives next to `SYSTEM_PROMPT`. Both are persisted on every `moderation_decisions` row via the new `prompt_version` column (D-12).

**Cancel-when-embed-finishes pattern** — copy from RESEARCH.md Pattern 2 (lines 269-310 in 11-RESEARCH.md). The pattern is already adapted to this codebase (uses `embed_worker(clip_id)`, `_gemini_classify(clip_id)`, `config.MODERATION_MAX_BUDGET_S`).

**SHA-256 hash compute pattern** for `reported_csam` preservation (replaces D-17's perceptual-hash research):
```python
# Standard library — used inline at the csam-block branch only. Mirror anonymity.session_hash style.
def _content_hash(clip_bytes: bytes) -> str:
    return hashlib.sha256(clip_bytes).hexdigest()
```
Loose mirror of `backend/observability/anonymity.py:28-32` (`session_hash` — same one-liner sha256-hex shape).

**Structlog boundary log lines** — mirror `run.py:80-95`:
```python
# run.py:80-83 establishes the structured kwargs style for stage boundaries.
log.info("moderate gate decision=%s provider=%s reason=%s latency_ms=%d",
         decision, provider, reason, latency_ms)
```
Per L-10 / D-26: kwargs only, NO raw_response or prompt_version in log lines (those go in JSONB column).

**Error handling tier classification** — copy verbatim from CONTEXT.md D-05 block (typed-exception catch chain). No analog in codebase yet (this is the first pipeline stage with tier-classified failure routing).

**STAGE_DURATION wrap is in `run.py`, not here.** moderate.py exposes `moderate_clip(clip_id)`; the wrap lives at the call site (D-01).

---

### `backend/migrations/versions/20260430_0004_moderation_columns.py` (new — migration)

**Analog:** `backend/migrations/versions/20260428_0002_relax_clips_path_not_null.py` (most recent ALTER-style migration, same shape).

**File header pattern** (verbatim shape from `0002_relax_clips_path_not_null.py:1-23`):
```python
"""ALTER moderation_decisions + reported_csam — Phase 11 owns the column shape.

Revision ID: 0004_moderation_columns
Revises: 0003_merge_comments_blob
Create Date: 2026-04-30

Phase 9 (D-04) shipped the moderation_decisions table with id+clip_id+created_at only.
Phase 11 (D-13, post-reconciliation) lands decision/reason/provider/raw_response/
latency_ms/prompt_version + UNIQUE INDEX(clip_id, provider). Phase 11 also adds
reported_csam.ncmec_report_id BIGINT NULL for the manual-NCMEC-receipt audit trail
(reconciled D-20 — additive now, cheaper than ALTER later).

Descends from 20260429_0003_merge_comments_blob, the current head after the
Phase 01-comments + Phase 10-blob branch merge.

Downgrade (D-15): hackathon-grade, no rollback. Mirrors 0001's posture.
"""
from alembic import op


revision = "0004_moderation_columns"
down_revision = "0003_merge_comments_blob"
branch_labels = None
depends_on = None
```

**ALTER body pattern** (verbatim shape from `0001_initial_v1_1_schema.py:34-114` + Phase 9 column-shape source-of-truth from `0001_initial_v1_1_schema.py:103-141`):

The Phase 9 baseline created these tables (lines 103-141):
```sql
-- moderation_decisions (Phase 9 baseline — Phase 11 ALTERs):
CREATE TABLE moderation_decisions (
  id TEXT PRIMARY KEY,
  clip_id TEXT NOT NULL REFERENCES clips(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_moderation_decisions_clip_id ON moderation_decisions(clip_id);

-- reported_csam (Phase 9 baseline — Phase 11 ALTERs):
CREATE TABLE reported_csam (
  id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  content_preserved_until TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_reported_csam_content_hash ON reported_csam(content_hash);
```

Phase 11 upgrade body (mirror `0002_relax_clips_path_not_null.py:26-31` `op.execute(...)` style):
```python
def upgrade() -> None:
    # moderation_decisions (Phase 11 column shape per CONTEXT D-13)
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN decision TEXT NOT NULL DEFAULT 'unknown'")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN reason TEXT")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN provider TEXT NOT NULL DEFAULT 'gemini_flash_lite'")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN raw_response JSONB")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN latency_ms INTEGER")
    op.execute("ALTER TABLE moderation_decisions ADD COLUMN prompt_version TEXT")
    op.execute(
        "CREATE UNIQUE INDEX idx_moderation_decisions_clip_provider "
        "ON moderation_decisions(clip_id, provider)"
    )
    # reported_csam (post-reconciliation D-20: keep ncmec_report_id BIGINT NULL for manual-receipt audit)
    op.execute("ALTER TABLE reported_csam ADD COLUMN ncmec_report_id BIGINT")


def downgrade() -> None:
    # Mirror 0001's posture (line 144-149).
    raise NotImplementedError(
        "Phase 11 moderation columns ALTER is one-way; rollback unsupported (D-15)"
    )
```
Note: NOT NULL DEFAULTs are required because the Phase 9 table is non-empty in production — without defaults the ALTER fails.

---

### `backend/migrations/versions/20260430_0005_segments_soft_flag.py` (new — migration)

**Analog:** Same as 0004 — `0002_relax_clips_path_not_null.py`.

**Pattern:** Identical header shape. `down_revision = "0004_moderation_columns"`. Body:
```python
def upgrade() -> None:
    op.execute(
        "ALTER TABLE segments ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 11 segments.soft_flag ALTER is one-way; rollback unsupported (D-15)"
    )
```
Default-false satisfies the "non-empty table" gotcha (existing segments rows get `soft_flag=FALSE`).

---

### `backend/tests/pipeline/test_moderate.py` (new — test, respx-based)

**Analog:** `backend/tests/test_blob_client.py:1-90` (respx_mock fixture + module-reload pattern) + `backend/tests/conftest.py:69-109` (storage_backend respx fixture as the parametrize template).

**Imports + reload-fixture pattern** (verbatim shape from `test_blob_client.py:7-30`):
```python
"""moderate.py unit tests using respx_mock.

Covers:
  - Happy path: classifier returns pass verdict → write moderation_decisions row, no clip hide.
  - Hard-block: classifier returns csam → write reported_csam + moderation_decisions, call cleanup_blocked_clip.
  - Soft-flag: classifier returns hate/violence flag → pass through, segments.soft_flag set at compile time.
  - Cancel-when-embed-finishes: embed completes first → gemini_task cancelled → asyncio.TimeoutError → blocked.
  - 5xx outage: Gemini 503 → decision='unknown', clip hidden, clustering paused.
  - OFFLINE_DEMO=true: passthrough decision, no httpx call attempted.
"""
import importlib
import logging

import httpx
import pytest


@pytest.fixture
def reload_moderate(monkeypatch):
    """Reload backend.config + backend.pipeline.moderate with desired env."""

    def _do(**env):
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        import backend.config
        import backend.pipeline.moderate as m
        importlib.reload(backend.config)
        importlib.reload(m)
        return m

    return _do
```

**Test body pattern** (verbatim shape from `test_blob_client.py:33-70`):
```python
@pytest.mark.asyncio
async def test_moderate_pass_happy_path(reload_moderate, respx_mock, fresh_db):
    m = reload_moderate(GEMINI_API_KEY="test-key", OFFLINE_DEMO="false")
    # Mock Gemini Files API + generate_content endpoints (mirror conftest:82-103 storage_backend setup)
    respx_mock.post("https://generativelanguage.googleapis.com/upload/v1beta/files").respond(
        json={"file": {"name": "files/abc", "state": "ACTIVE"}},
    )
    respx_mock.get("https://generativelanguage.googleapis.com/v1beta/files/abc").respond(
        json={"name": "files/abc", "state": "ACTIVE"},
    )
    respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(
        json={"candidates": [{"content": {"parts": [{"text": '{"csam": {"verdict": "pass", "score": 0.0, "rationale": ""}, ...}'}]}}]},
    )
    # ... call moderate_clip and assert moderation_decisions row written ...
```

**Cancel-when-embed-finishes behavioral test** — separate test, no respx required because the trick is `asyncio.sleep` ordering:
```python
@pytest.mark.asyncio
async def test_moderate_cancels_gemini_when_embed_finishes_first(reload_moderate, fresh_db, monkeypatch):
    """Embed finishes first → gemini_task cancelled → TimeoutError → decision='blocked'."""
    m = reload_moderate(GEMINI_API_KEY="test-key", MODERATION_MAX_BUDGET_S="20")

    async def _fast_embed(_clip_id):
        await asyncio.sleep(0.01)  # very fast
        return ("clip_abc", np.zeros(512, dtype=np.float32))
    async def _slow_gemini(_clip_id):
        await asyncio.sleep(5)     # very slow — must be cancelled before completion
        raise AssertionError("gemini should have been cancelled")

    monkeypatch.setattr(m, "embed_worker", _fast_embed)
    monkeypatch.setattr(m, "_gemini_classify", _slow_gemini)
    result = await m.moderate_clip("clip_abc")
    assert result.decision == "blocked"
    assert result.reason == "classifier_timeout"
```
Mirror of RESEARCH.md §"Pattern 2" cancel-handling — the test asserts the cancel branch is hit.

**Conftest fixture extension pattern** — see "`backend/tests/conftest.py`" entry below.

---

### `backend/pipeline/run.py` (modify — controller, request-response)

**Analog:** Self — extend the existing `STAGE_DURATION.labels(stage=...).time()` pattern at `run.py:78,90` (existing `embed` and `cluster` wraps).

**Existing pattern at L78** (verbatim — extend it, do not replace):
```python
with STAGE_DURATION.labels(stage="embed").time():
    parent_clip_id, parent_vec = await embed_worker(clip_id)
```

**Phase 11 transformation (per reconciled D-01 + D-02 4-step sequence):**
```python
# REPLACE the bare embed call (L78-79) with the gate. Keep the structlog kwargs +
# events.broadcast call shape that L80-88 already establishes.
from .moderate import moderate_clip  # NEW import at top

with STAGE_DURATION.labels(stage="moderate").time():
    mod_result = await moderate_clip(clip_id)  # internally: SHA-256 + parallel embed/gemini + asyncio.wait FIRST_COMPLETED

if mod_result.decision == "blocked":
    log.info("pipeline blocked clip_id=%s reason=%s", clip_id, mod_result.reason)
    return  # short-circuit — cleanup_blocked_clip already called inside moderate_clip
if mod_result.decision == "unknown":
    log.info("pipeline unknown clip_id=%s reason=%s — clip hidden, queued for admin", clip_id, mod_result.reason)
    return  # clustering paused; admin /resume re-enters via _resume_pipeline

# Decision == "passed" — embed task already completed inside moderate_clip; pull its result.
parent_clip_id, parent_vec = mod_result.embed_result
# ... continues with existing cluster_worker call at L91 unchanged ...
```

**`_resume_pipeline(clip_id)` pattern** — new public function in this same file, mirrors the existing `run_pipeline(clip_id)` shape. Phase 12 imports it. Sketch (mirror `run.py:55-111` structure but skip the gate — by definition a resume means decision was cleared by admin):
```python
async def _resume_pipeline(clip_id: str) -> None:
    """Phase 12 admin endpoint entry — re-enter pipeline after admin clears unknown clip.
    Skips the gate (decision was admin-cleared); jumps straight to cluster_worker.
    Parent embedding is already on the row from the prior gate run (D-06)."""
    bind_contextvars(clip_id=clip_id)
    try:
        parent_vec = await db.get_embedding(clip_id)
        if parent_vec is None:
            raise RuntimeError(f"_resume_pipeline: no embedding for clip {clip_id!r}")
        # ... continues from cluster_worker through compile, mirror L90-105 ...
    finally:
        unbind_contextvars("clip_id")
```

**Error scrub pattern** — `_scrub` at L16-38 already exists; no changes needed. Gate exceptions flow through the existing `except Exception` at L107-109.

---

### `backend/db_postgres.py` + `backend/db_sqlite.py` (modify — service, CRUD)

**Analog (postgres):** `backend/db_postgres.py:484-514` (insert_comment / list_comments / count_comments_since — Phase 01's most recent insert+read pair). Plus `db_postgres.py:321-350` (insert_segment with `ON CONFLICT(cluster_id) DO UPDATE` for the UNIQUE-constraint upsert pattern).

**Analog (sqlite):** `backend/db_sqlite.py:509-544` — same three functions, parity-required per the dispatcher contract documented at `db_sqlite.py:1-9` + `db_postgres.py:1-13`.

**Postgres `write_moderation_decision` pattern** — copy `insert_segment`'s ON CONFLICT shape from `db_postgres.py:333-349` (verbatim shape; only the table name + column list differ):
```python
# db_postgres.py:333-349 establishes the upsert shape (UNIQUE constraint on cluster_id).
# Phase 11 mirrors with UNIQUE INDEX on (clip_id, provider) per D-13.
async def write_moderation_decision(
    clip_id: str,
    provider: str,
    decision: str,
    reason: str | None,
    raw_response: dict | None,
    latency_ms: int | None,
    prompt_version: str | None,
) -> str:
    """Idempotent: UNIQUE(clip_id, provider) — retries produce one row per provider per clip."""
    dec_id = uuid.uuid4().hex
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO moderation_decisions
             (id, clip_id, provider, decision, reason, raw_response, latency_ms, prompt_version)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           ON CONFLICT(clip_id, provider) DO UPDATE SET
             decision       = EXCLUDED.decision,
             reason         = EXCLUDED.reason,
             raw_response   = EXCLUDED.raw_response,
             latency_ms     = EXCLUDED.latency_ms,
             prompt_version = EXCLUDED.prompt_version
           RETURNING id""",
        dec_id, clip_id, provider, decision, reason,
        json.dumps(raw_response) if raw_response else None,
        latency_ms, prompt_version,
    )
    return row["id"]
```

**Postgres `write_reported_csam` pattern** — copy `insert_comment` shape from `db_postgres.py:484-493`:
```python
async def write_reported_csam(content_hash: str, preserved_until: float) -> str:
    """1-year retention per 2024 REPORT Act (D-19). UNIQUE INDEX on content_hash → ON CONFLICT DO NOTHING.
    Caller passes preserved_until=NOW()+INTERVAL '1 year' as a Unix timestamp (or use SQL NOW() inline)."""
    rep_id = uuid.uuid4().hex
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO reported_csam (id, content_hash, content_preserved_until)
           VALUES ($1, $2, to_timestamp($3))
           ON CONFLICT(content_hash) DO NOTHING
           RETURNING id""",
        rep_id, content_hash, preserved_until,
    )
    return row["id"] if row else rep_id  # ON CONFLICT NOTHING returns no row — return the dedup hit's id is fine for callers.
```

**Postgres `set_clip_hidden` pattern** — copy `assign_clip_to_cluster` shape from `db_postgres.py:309-319` (single UPDATE):
```python
async def set_clip_hidden(clip_id: str, hidden: bool) -> None:
    pool = get_pool()
    await pool.execute("UPDATE clips SET is_hidden = $1 WHERE id = $2", hidden, clip_id)
```

**Postgres `get_moderation_decisions` pattern** — copy `list_comments` shape from `db_postgres.py:496-504`:
```python
async def get_moderation_decisions(clip_id: str) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT provider, decision, reason, raw_response, latency_ms, prompt_version, created_at
           FROM moderation_decisions WHERE clip_id = $1 ORDER BY created_at DESC""",
        clip_id,
    )
    return [dict(r) for r in rows]
```

**Postgres `aggregate_verdict` pattern** — pure-Python aggregator over `get_moderation_decisions` rows. No SQL analog needed (one row in post-reconciliation, but D-10 still requires the function for forward-compat with future per-provider rows). Implementation: any `decision='blocked'` wins, else any `decision='unknown'` wins, else `'passed'`.

**SQLite parity** — for each function above, write the aiosqlite mirror inside `db_sqlite.py`. Use `?`-style placeholders, `aiosqlite.connect(DB_PATH)` context manager, `await conn.commit()`. Direct mirror of how `insert_comment` (sqlite L509-520) parallels `insert_comment` (postgres L484-493).

**`__all__` extension** — both files: append `"write_moderation_decision", "write_reported_csam", "set_clip_hidden", "get_moderation_decisions", "aggregate_verdict"` to `__all__`. (See `db_postgres.py:30-59` for the existing list; `db_sqlite.py:27-54` parity.)

---

### `backend/config.py` (modify — config)

**Analog:** Self — extend the Phase 9/10 env-var blocks at `config.py:42-67`.

**Pattern** (verbatim shape from L46-49 + L62-67 — comment-block + `os.environ.get(...).strip()`):
```python
# Phase 11: Moderation gate (post-reconciliation D-24)
# GEMINI_MODERATION_MODEL: separate from GEMINI_MODEL (L18) so the moderation
#   classifier model can iterate independently of the caption pipeline model.
GEMINI_MODERATION_MODEL: str = os.environ.get("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
# MODERATION_MAX_BUDGET_S: absolute upper-bound on the gate (D-03). Default 20s.
#   Cancel-when-embed-finishes is the typical primitive; this is the safety floor.
MODERATION_MAX_BUDGET_S: float = float(os.environ.get("MODERATION_MAX_BUDGET_S", "20.0"))
```
DO NOT add `CSAM_PROVIDER` or `CLOUDFLARE_CSAM_API_KEY` (reconciled D-24 — superseded).

---

### `backend/.env.example` (modify — config docs)

**Analog (cannot be read in this environment — directory permission denied):** Phase 9/10 add their own commented blocks; Phase 11 mirrors the in-file convention. Planner pattern: add a block right after the Phase 10 block:
```
# Phase 11: Moderation gate (Gemini Flash-Lite classifier)
# GEMINI_MODERATION_MODEL=gemini-2.5-flash-lite
# MODERATION_MAX_BUDGET_S=20.0
```

---

### `backend/observability/__init__.py` + `backend/observability/anonymity.py` (modify — utility, transform)

**Analog:** `backend/observability/anonymity.py:18-25` (the `REDACT_KEYS` frozenset).

**Existing pattern** (verbatim):
```python
# anonymity.py:18-25
REDACT_KEYS: frozenset[str] = frozenset({
    "session_uuid",
    "gps_lat",
    "gps_lng",
    "blob_url",
})
```

**Phase 11 modification** (per reconciled D-27 — drop `csam_hash` since classifier-only mode has no separate hash field):
```python
REDACT_KEYS: frozenset[str] = frozenset({
    "session_uuid",
    "gps_lat",
    "gps_lng",
    "blob_url",
    # Phase 11 (D-27 reconciled): classifier raw response + prompt version may surface
    # in error contexts (Gemini 4xx/5xx with reflected payload). Redact at the Sentry
    # boundary; primary sink is the moderation_decisions.raw_response JSONB column.
    "raw_response",
    "prompt_version",
})
```
The `_scrub` recursion at L35-52 walks any nested dict — no other code change needed. `before_send_scrub` at L55-61 already calls `_scrub`. Phase 11 = one-liner extension to the frozenset; `observability/__init__.py` itself does NOT change (the scrubber list lives in `anonymity.py`).

---

### `backend/observability/metrics.py` (no change required)

**Analog:** `backend/observability/metrics.py:43-48` — `STAGE_DURATION` already declares `labelnames=("stage",)` with the comment `# ingest|embed|cluster|compile|stitch`. The label is bounded-enum; adding `"moderate"` as a value at the call site (in `run.py`) does NOT require a metric definition change. Per L-11.

The comment on L46 should be updated when planner edits run.py to add the `moderate` stage:
```python
# OLD: labelnames=("stage",),         # ingest|embed|cluster|compile|stitch
# NEW: labelnames=("stage",),         # ingest|moderate|embed|cluster|compile|stitch
```
This is a docstring tweak, not a metric registration change.

---

### `backend/tests/conftest.py` (modify — test fixture)

**Analog:** Self — `backend/tests/conftest.py:69-109` (storage_backend respx fixture).

**Existing fixture shape** (verbatim, from L69-103):
```python
@pytest.fixture(params=["local", "blob"], ids=["local", "blob"])
def storage_backend(request, monkeypatch, respx_mock):
    backend = request.param
    monkeypatch.setenv("STORAGE_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    if backend == "blob":
        monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_TESTSTORE_xxxxx")
        respx_mock.put("https://vercel.com/api/blob").respond(json={...})
        respx_mock.post("https://vercel.com/api/blob/delete").respond(200)
        respx_mock.get("https://vercel.com/api/blob").respond(json={...})
    import importlib
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)
    yield backend
```

**Phase 11 modification — single Gemini-mock fixture (NO MODERATION_PROVIDER parametrize per reconciled D-25):**
```python
@pytest.fixture
def gemini_moderation_mock(respx_mock, monkeypatch):
    """Phase 11: Gemini Flash-Lite classifier mock. Single fixture, no parametrize.
    Caller overrides .respond(...) to vary verdicts per test."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
    # Default: pass-verdict response. Tests override by re-registering the same route.
    respx_mock.post(
        "https://generativelanguage.googleapis.com/upload/v1beta/files"
    ).respond(json={"file": {"name": "files/test", "state": "ACTIVE"}})
    respx_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/files/test"
    ).respond(json={"name": "files/test", "state": "ACTIVE"})
    respx_mock.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    ).respond(json={"candidates": [{"content": {"parts": [{"text": _all_pass_response()}]}}]})
    yield respx_mock
```
DO NOT add `MODERATION_PROVIDER` parametrize.

---

### `backend/pipeline/compile.py` (modify — service, batch read+write)

**Analog:** `backend/pipeline/compile.py:537-634` (compile_segment) — specifically the Phase 1.5 parent-diversity guard at L592-596 (`_enforce_parent_diversity`) which has the same shape as what Phase 11 needs: iterate cluster members, read a per-member signal, conditionally update the segment row.

**Existing pattern** (`compile.py:592-596`, verbatim):
```python
if not isinstance(a_result, Exception):
    try:
        await _enforce_parent_diversity(cluster_id, min_parents=2)
    except Exception as exc:
        log.warning("parent diversity guard failed cluster_id=%s: %s", cluster_id, exc)
```

**Phase 11 transformation** (D-14 — read decisions per member, write segments.soft_flag at insert_segment time at L626-634):
```python
# At compile_segment, after Phase 1.5 parent-diversity guard, before Phase 2 stitch:
soft_flag = False
try:
    members = await db.fetch_cluster_clips(cluster_id)
    for member in members:
        decisions = await db.get_moderation_decisions(member["id"])
        for d in decisions:
            raw = d.get("raw_response") or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            for cat in ("hate", "violence"):
                cat_signal = raw.get(cat, {})
                if cat_signal.get("verdict") in ("flag", "block"):
                    soft_flag = True
                    break
            if soft_flag:
                break
        if soft_flag:
            break
except Exception as exc:
    log.warning("soft_flag derivation failed cluster_id=%s: %s — defaulting false", cluster_id, exc)

# Then at insert_segment (L626-634), pass soft_flag=soft_flag as a new kwarg.
# insert_segment signature gains a soft_flag: bool = False kwarg.
```

**`fetch_cluster_clips` is already in the dispatcher** (`db_postgres.py:567-575`, `db_sqlite.py:593-603`) — Phase 11 reuses it.

**`insert_segment` signature extension** — both backends add `soft_flag: bool = False` kwarg, write through to the new column. Mirror the existing `video_url`/`title` kwarg pattern at `db_postgres.py:321-329`.

---

### `backend/app.py` lifespan (modify — config, startup guard)

**Analog:** `backend/app.py:51-67` (`_pre_warm_sdk` graceful-degrade with WARN log).

**Existing pattern** (verbatim, L51-67):
```python
async def _pre_warm_sdk() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning(
            "ANTHROPIC_API_KEY not set — compile pipeline will be unavailable. "
            "Set the key to enable."
        )
        return
    # ... otherwise pre-warm ...
```

**Phase 11 modification** (per reconciled D-18 — non-blocking WARN, NOT a startup-refusal):
```python
# Inside lifespan(), after step 5 pre-warm tasks (right before `try: yield`):
if not config.OFFLINE_DEMO and config.SENTRY_ENVIRONMENT == "production":
    log.warning(
        "Phase 11 ships classifier-only CSAM detection. "
        "Real hash vendor + NCMEC reporting deferred post-pilot."
    )
```
Single line of code, mirrors the `_pre_warm_sdk` WARN style. NO Cloudflare client init; NO startup-refusal.

---

### `frontend/src/types.ts` (modify — model)

**Analog:** `frontend/src/types.ts:52-84` — the existing `Segment` interface fields.

**Existing pattern** (verbatim, L52-84): nested fields with JSDoc above each. Follow the convention.

**Phase 11 addition** (after L83, before the closing `}`):
```typescript
  /**
   * Phase 11 (D-15): true when any cluster member's Gemini classifier flagged
   * hate/violence. Frontend wraps autoplay in a tap-to-reveal interstitial.
   * Backend handoff only — UI implementation lives in feature-track #6 (Roan).
   */
  soft_flag: boolean;
```

---

## Shared Patterns

### Module-level dispatcher (RETAINED — D-22 simplified, no provider split)

**Source:** `backend/db.py:1-24` and `backend/storage/__init__.py:1-23` (both verbatim 3-arm shape).

Phase 11 does NOT need a dispatcher in `moderate.py` because the reconciliation collapses to a single Gemini provider. The OFFLINE_DEMO short-circuit lives inside `moderate_clip` itself as an early-return:
```python
async def moderate_clip(clip_id: str) -> ModerationResult:
    if config.OFFLINE_DEMO:
        # Mirror db.py L19-21 + storage/__init__.py L18-20 OFFLINE_DEMO short-circuit
        return ModerationResult(decision="passed", provider="stub", reason="offline_demo", ...)
    ...
```

### structlog kwargs at stage boundaries

**Source:** `backend/pipeline/run.py:80-95` + `backend/pipeline/embed.py:100-104`.
**Apply to:** `moderate.py` log lines.

```python
# run.py:80-95 establishes the convention. clip_id is auto-bound at line 76 — never re-pass it.
log.info("moderate gate decision=%s provider=%s reason=%s latency_ms=%d",
         decision, provider, reason, latency_ms)
```
Per L-10: NO `raw_response`, NO `prompt_version` in log lines — they go in the JSONB column.

### tenacity retry with typed-exception filter

**Source:** `backend/pipeline/embed.py:33-38` + `backend/storage/blob_client.py:36-41`.
**Apply to:** Internal Gemini classifier helper (transient 5xx retry — but NOT for the cancel-when-embed-finishes outer wait).

```python
# embed.py:33-38 — verbatim
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
```
Phase 11: narrower `retry_if_exception_type` — only `httpx.TransportError` + 5xx-wrapped exceptions. 4xx fails fast (per D-05 typed-exception classification).

### OFFLINE_DEMO graceful-degrade

**Source:** `backend/storage/__init__.py:14-23` (storage dispatcher) + `backend/db.py:16-24` (db dispatcher) + `backend/observability/sentry.py:25-27` (sentry init).
**Apply to:** `moderate.py` early-return; `app.py` lifespan WARN.

The pattern is consistent across all three: empty/false signal → log one INFO/WARN line → skip external init.

### Module-level singleton lifecycle (NOT NEEDED for Phase 11)

The pattern at `backend/storage/blob_client.py:67-127` (`_client` singleton, `init_client`/`close_client`/`get_client`) and `backend/db_postgres.py:67-127` (`_pool` singleton with same triplet) is the precedent the original CONTEXT D-23 wanted Phase 11 to mirror for a Cloudflare httpx client. **Per reconciliation, Phase 11 does NOT add a new singleton.** Gemini SDK creates its `Client` per-call inside `caption_pipeline.py:433-436`; Phase 11 mirrors verbatim (no singleton). This decision is the load-bearing simplification.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | All 12 files have an in-codebase analog. |

**Caveat — `backend/.env.example`:** This file is in a directory denied by tool permissions in this environment, so its contents could not be read directly. The pattern (commented `KEY=value` block per phase) is inferable from `backend/config.py:42-67` and the Phase 9/10 conventions documented inline there. Planner should mirror the in-file shape when adding the two new vars (`GEMINI_MODERATION_MODEL`, `MODERATION_MAX_BUDGET_S`).

---

## Metadata

**Analog search scope:**
- `backend/pipeline/` (caption_pipeline.py, run.py, embed.py, compile.py)
- `backend/migrations/versions/` (0001, 0002 variants, 0003 merge)
- `backend/db_postgres.py`, `backend/db_sqlite.py`, `backend/db.py`
- `backend/observability/` (anonymity.py, metrics.py, sentry.py, __init__.py)
- `backend/storage/` (blob_client.py, __init__.py)
- `backend/tests/` (conftest.py, test_blob_client.py)
- `backend/app.py` (lifespan + middleware setup)
- `backend/config.py`
- `frontend/src/types.ts`

**Files scanned:** ~20

**Pattern extraction date:** 2026-04-29

**Reconciliation alignment:** All pattern assignments above respect the 2026-04-29 reconciliation header in `11-CONTEXT.md`. Superseded D-NN entries (D-02, D-10, D-13 naming, D-16..D-18, D-20..D-25, D-27..D-29) are not referenced as load-bearing in any pattern assignment.

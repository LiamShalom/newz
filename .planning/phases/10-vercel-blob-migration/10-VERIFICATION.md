---
phase: 10-vercel-blob-migration
verified: 2026-04-29T05:23:33Z
status: human_needed
score: 14/14 must-haves verified in code; 7 must-haves deferred to merge-time HUMAN-UAT
overrides_applied: 0
re_verification:
  previous_status: null
  previous_score: null
  gaps_closed: []
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Task 5.5 — cleanup_blocked_clip end-to-end smoke against live Vercel Blob"
    expected: "POST /clips with STORAGE_BACKEND=blob; confirm uploads/{clip_id}.mp4 in Blob console; cleanup_blocked_clip() removes the object; idempotent re-call succeeds"
    why_human: "Requires live BLOB_READ_WRITE_TOKEN + Vercel Blob console — captured in 10-HUMAN-UAT.md test 1"
  - test: "SC-1 — Backend redeploy + Blob URLs render in feed"
    expected: "Railway redeploy with STORAGE_BACKEND=blob; /health 200; feed renders absolute Blob URLs; /media returns 404"
    why_human: "Requires Railway deploy + browser inspection — captured in 10-HUMAN-UAT.md test 2"
  - test: "SC-2 — New clip POST lands in Blob uploads/"
    expected: "iOS Safari PWA records clip; POST /clips returns 202; Vercel Blob console shows uploads/{clip_id}.{ext}; clips.blob_url populated"
    why_human: "Requires iOS PWA + live Blob — captured in 10-HUMAN-UAT.md test 3"
  - test: "SC-3 — Compiled run-segments land in Blob runs/"
    expected: "After clustering triggers compile, run-segment uploads to runs/{run_id}.mp4 (public); frontend renders absolute Blob URL with no auth header"
    why_human: "Requires live cluster trigger + Blob console — captured in 10-HUMAN-UAT.md test 4"
  - test: "SC-4 — Direct browser PUT to Vercel Blob is rejected"
    expected: "Browser-console fetch PUT to https://*.blob.vercel-storage.com returns 401/403"
    why_human: "Requires browser DevTools against live Vercel Blob — captured in 10-HUMAN-UAT.md test 5"
  - test: "SC-5 — Cleanup hook hard-deletes blocked clips within window"
    expected: "Manually flip clip's moderation_status to blocked; cleanup_blocked_clip(clip_id) removes Blob object verifiable in console"
    why_human: "Requires DB write + live Blob console (same as Task 5.5) — captured in 10-HUMAN-UAT.md test 6"
  - test: "SC-6 — STORAGE_BACKEND=local rolls back without code changes"
    expected: "Set STORAGE_BACKEND=local on Railway, redeploy; /media mount registered; new uploads to /data/clips/; existing Blob rows still serve via stored URL"
    why_human: "Requires Railway env var flip + redeploy + smoke — captured in 10-HUMAN-UAT.md test 7"
---

# Phase 10: Vercel Blob Migration — Verification Report

**Phase Goal:** Retire Railway `/data/clips/` for clip media; uploads land in Vercel Blob via server-mediated path; ffmpeg reads from Blob with two strategies (signed-URL byte-range trim, tempdir-download stitch); compiled segments served from Blob CDN.
**Verified:** 2026-04-29T05:23:33Z
**Branch:** liam/phase-10-blob-migration
**Re-verification:** No — initial verification

---

## VERDICT: PASS WITH DEFERRED HUMAN-UAT

All 14 in-scope code-verifiable must-haves pass: 6 ROADMAP success criteria covered by code paths, 8 BLOB-XX requirements implemented and unit-tested, all 8 decision amendments honored, all 14 anti-patterns avoided, all 5 cross-phase inheritance items respected. The 7 live-Blob smoke checks (Task 5.5 + SC-1..6) require a live `BLOB_READ_WRITE_TOKEN` and Railway redeploy; intentionally deferred to merge-time HUMAN-UAT per `10-HUMAN-UAT.md`.

Phase 10 unit tests: **13/13 passed** (storage dispatcher, blob client, OFFLINE_DEMO firewall).
Frontend Phase 10 tests: **9/9 passed** (api `_abs` guard + SegmentCard absolute-URL fixture).
Full backend suite: **124 passed, 5 skipped (postgres without DATABASE_URL), 3 failed (pre-existing fixture leak — confirmed against pre-Phase-10 tree)**.

---

## 1. ROADMAP Success Criteria — Coverage

| SC | Description | Status | Evidence |
|---|---|---|---|
| 1 | Backend redeploys; clip media plays from feed (Blob URLs absolute; `/media` mount removed) | covered (code) + awaiting-human-UAT (live) | `backend/app.py:163` conditional mount; `frontend/src/api.ts:12-13` `_abs` guard |
| 2 | New clip POST lands at `uploads/{clip_id}.{ext}` | covered (code) + awaiting-human-UAT (live) | `backend/storage/blob.py:31-39` `save_clip_bytes` → `pathname=f"uploads/{clip_id}.{ext}"`, `access="private"` |
| 3 | Compiled segments at `runs/{run_id}.mp4` (public) | covered (code) + awaiting-human-UAT (live) | `backend/pipeline/stitch.py:122-127` (stitch path), `:218-223` (trim path) — both upload `pathname=f"runs/{run_id}.mp4"`, `access="public"` |
| 4 | Direct browser PUT to Vercel Blob is rejected | covered (code) + awaiting-human-UAT (live) | No `mint_client_upload_token` in repo (grep clean); `BLOB_READ_WRITE_TOKEN` server-only in `config.py:67`; wrapper exposes only `upload`/`delete`/`head` |
| 5 | Moderation-block → Blob hard-delete (BLOB-08) | covered (code) + awaiting-human-UAT (live) | `backend/storage/blob.py:68-76` `cleanup_blocked_clip` (idempotent); `backend/storage/local.py:68-77` parity; `test_blob_client.test_delete_idempotent_on_404` |
| 6 | `STORAGE_BACKEND=local` rolls back without code changes | covered (code) + awaiting-human-UAT (live) | `backend/storage/__init__.py:15-23` 3-arm dispatcher; `local.py` self-contained (no httpx import); `app.py:163` conditional `/media` mount |

Score: **6/6 SCs covered by code; 6/6 awaiting live HUMAN-UAT** (`10-HUMAN-UAT.md`).

---

## 2. BLOB-01..08 Requirements — Coverage

| Req | Description | Status | Evidence |
|---|---|---|---|
| BLOB-01 | Server-mediated upload to `uploads/{clip_id}.{ext}` (private) | covered | `storage/blob.py:31-39` (`access="private"`); `db_sqlite.py:172-192` + `db_postgres.py:165-182` insert_clip routes through dispatcher |
| BLOB-02 | Compiled segments to `runs/{run_id}.mp4` (public) | covered | `pipeline/stitch.py:118-129` (`stitch_clips`), `:212-225` (`trim_window`); both `access="public"` |
| BLOB-03 | ffmpeg `_sync_trim` reads from Blob via byte-range, no full download | covered | `pipeline/stitch.py:159-163` builds `headers=` kwarg with `\r\n` CRLF; `vcodec="copy"` preserved; ffmpeg-python passes through to libavformat HTTP Range |
| BLOB-04 | ffmpeg `_sync_stitch` pre-downloads to `tempfile.TemporaryDirectory()` | covered | `pipeline/compile.py:79` `with tempfile.TemporaryDirectory() as tmpdir:` in `stitch_multi_source`; `_download_refs_to_tempdir` uses `httpx.stream` + `aiter_bytes` parallel via `asyncio.gather` |
| BLOB-05 | Frontend renders absolute Blob URLs; `/media` mount removed | covered | `app.py:163` conditional mount; `api.ts:12-13` `_abs` guard preserves absolute URLs (also `:36` for `video_urls`) |
| BLOB-06 | `STORAGE_BACKEND` flag for rollback | covered | `config.py:62`; `storage/__init__.py:15-23` 3-arm dispatcher; `test_storage_dispatcher.py` 4 tests pass |
| BLOB-07 | Clip media survives Railway redeploy; backend never reads `/data/clips/` post-cutover | covered | `db_sqlite.py:181/186` insert routes blob_url to row when result is HTTP URL; `_stitch_segment_runs` (`compile.py:415-419`) writes to `tempfile.NamedTemporaryFile` in blob mode; no `/data/clips/` reads in blob path |
| BLOB-08 | Cleanup hook for moderation-blocked clips | covered | `storage/blob.py:68-76` `cleanup_blocked_clip` looks up row, calls `delete_clip` (idempotent); `local.py:68-77` parity; `test_blob_client.test_delete_idempotent_on_404` passes |

Score: **8/8 requirements satisfied**. All have code paths plus unit-test coverage.

---

## 3. Decision Amendments Compliance (D-03/D-05/D-06/D-08 supersedes)

| # | Amendment | Status | Evidence |
|---|---|---|---|
| 1 | No `mint_signed_url` op; `authorized_blob_input` is pure | satisfied | `grep -rn mint_signed_url backend/` returns only doc-comments saying "superseded"; `storage/blob.py:89-95` `authorized_blob_input` is pure (token interpolation only, no `await`) |
| 2 | Split-access intent; `Authorization: Bearer` for private reads | satisfied | `storage/blob.py:85` builds `Bearer` headers for private reads; `runs/` access="public" at `:127` of stitch.py |
| 3 | No 900s TTL; `(url, headers)` tuple per call site | satisfied | `storage/blob.py:79-86` `stitch_input_for` returns `(url, headers)` tuple; no `ttl_seconds` parameter on storage functions (`grep -rn "ttl_seconds" backend/storage/` empty) |
| 4 | ffmpeg `headers=` kwarg with CRLF terminator | satisfied | `pipeline/stitch.py:163` `"".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())` — verified literal `\r\n` |
| 5 | Recompile CDN cache lag accepted; `x-allow-overwrite: 1` | satisfied | `storage/blob_client.py:168` `"x-allow-overwrite": "1"`; `:166` `"x-add-random-suffix": "0"`; `test_upload_includes_required_headers` asserts both |
| 6 | Hobby tier; tenacity retry on 429 + 5xx | satisfied | `blob_client.py:140-145` `_blob_retry` uses `_RetryableHTTPError` for 429 + 5xx; `:133-134` classifier wraps both; `test_5xx_retries_three_times` and `test_429_retries` pass |
| 7 | Ship `seed_demo_to_blob.py` in this phase | satisfied | `backend/scripts/seed_demo_to_blob.py` present (65 lines); reads `ADMIN_TOKEN` from env not argparse |
| 8 | Pin `httpx==0.28.1` and `tenacity==9.1.4` | satisfied | `requirements.txt:8-9` pins exact versions; `requirements-dev.txt:11` pins `respx>=0.21` |

Score: **8/8 amendments honored**.

---

## 4. Anti-Pattern Audit (PATTERNS.md)

| # | Anti-pattern | Status | Evidence |
|---|---|---|---|
| 1 | Per-request `STORAGE_BACKEND` branching | clean | Dispatcher in `storage/__init__.py:15-23` is module-import-time only |
| 2 | `import httpx` in `storage/blob.py` or `storage/__init__.py` | clean | `grep -rn "import httpx" backend/storage/` shows only `blob_client.py:35` |
| 3 | Logging signed URLs / bearer tokens verbatim | clean | `blob_client.py` logs only `op`, `pathname`, `latency_ms`, `bytes`; init failure sanitized to `type(exc).__name__`; `test_no_token_in_logs` passes |
| 4 | Adding `blob_url`/`pathname` as structlog contextvar | clean | `grep -rn "bind_contextvars" backend/storage/` empty |
| 5 | Pre-warm Blob on startup | clean | `grep -n "warm-up\|prewarm\|pre_warm" backend/storage/` empty; `app.py` lifespan adds Blob client init only |
| 6 | In-process URL caching | clean | `grep -rn "_cache\|cache\[" backend/storage/` empty; `authorized_blob_input` mints per-call |
| 7 | Direct browser PUT (Vercel client-upload tokens) | clean | No `mint_client_upload_token` op; `BLOB_READ_WRITE_TOKEN` server-only in `config.py:67`; not exposed via any endpoint |
| 8 | Streaming trim through pipe to Blob | clean | `pipeline/stitch.py:135-191` preserves `_sync_trim` atomic-rename pattern; upload happens in async wrapper `:212-225` after `os.replace` |
| 9 | Cluster-level tempdir reuse / cross-recompile cache | clean | `compile.py:79` `tempfile.TemporaryDirectory()` is per-`stitch_multi_source` call; `_stitch_segment_runs:415-419` per-trim NamedTemporaryFile |
| 10 | Adding downgrade body to Alembic migration to drop `blob_url` | clean | `ls backend/migrations/versions/` shows only `20260428_0001_initial_v1_1_schema.py`; no new revisions |
| 11 | Heredoc/CLI-arg secrets in seed script | clean | `seed_demo_to_blob.py:28` `ADMIN_TOKEN = os.environ.get(...)` — env only |
| 12 | Re-mounting `/media` unconditionally | clean | `app.py:163` `if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:` gating |
| 13 | High-cardinality Prometheus labels (e.g., `pathname`) | clean | `grep -rn "labels.*pathname\|pathname.*labels" backend/observability/` empty; `blob_client.py` adds no metrics |
| 14 | Reading `clips.path` as Path in blob mode | clean | `db_sqlite.py:217` and `db_postgres.py:203` route through `storage.get_playable_url(row)` |

Score: **14/14 anti-patterns avoided**.

---

## 5. Cross-Phase Inheritance

| Item | Status | Evidence |
|---|---|---|
| Phase 8 PRIV-02 — Blob URLs/tokens are kwargs only, never contextvars | satisfied | `grep -rn bind_contextvars backend/storage/` empty; logs use `op`/`pathname`/`latency_ms` kwargs |
| Phase 8 D-14 — Sentry `before_send` already scrubs `blob_url`; no new scrub-list tasks | satisfied | `backend/observability/anonymity.py:23` lists `"blob_url"` in scrub keys (pre-existing); no Phase 10 modifications to anonymity.py |
| Phase 9 D-08 — module-import-time dispatcher pattern mirrored | satisfied | `storage/__init__.py:15-23` mirrors `db.py` 3-arm shape with logging |
| Phase 9 D-11 — `OFFLINE_DEMO=true` hard-overrides `STORAGE_BACKEND` to local | satisfied | `storage/__init__.py:18-20` "(forced by OFFLINE_DEMO=true; D-18)"; `test_dispatcher_offline_demo_overrides` passes; `test_offline_demo_firewall_no_blob_calls` proves zero HTTP calls |
| Phase 9 D-16 — module-level singleton with lifespan-managed init/close | satisfied | `blob_client.py:67-115` mirrors asyncpg pool pattern; `app.py:110-112, 133-135` lifespan init/close gated on `STORAGE_BACKEND=blob and not OFFLINE_DEMO` |

Score: **5/5 cross-phase invariants preserved**.

---

## 6. Test Results

### Phase 10 unit tests (focused run)

```
$ backend/.venv/bin/python -m pytest backend/tests/test_storage_dispatcher.py \
    backend/tests/test_offline_demo_firewall.py backend/tests/test_blob_client.py -v
============================== 13 passed in 5.01s ==============================

backend/tests/test_storage_dispatcher.py::test_dispatcher_local_default PASSED
backend/tests/test_storage_dispatcher.py::test_dispatcher_blob_when_set PASSED
backend/tests/test_storage_dispatcher.py::test_dispatcher_offline_demo_overrides PASSED
backend/tests/test_storage_dispatcher.py::test_local_blob_signature_parity PASSED
backend/tests/test_offline_demo_firewall.py::test_offline_demo_firewall_no_blob_calls PASSED
backend/tests/test_blob_client.py::test_init_fails_loud_on_empty_token PASSED
backend/tests/test_blob_client.py::test_init_fails_on_malformed_token PASSED
backend/tests/test_blob_client.py::test_upload_happy_path PASSED
backend/tests/test_blob_client.py::test_upload_includes_required_headers PASSED
backend/tests/test_blob_client.py::test_delete_idempotent_on_404 PASSED
backend/tests/test_blob_client.py::test_5xx_retries_three_times PASSED
backend/tests/test_blob_client.py::test_429_retries PASSED
backend/tests/test_blob_client.py::test_no_token_in_logs PASSED
```

### Frontend Phase 10 tests

```
$ cd frontend && ./node_modules/.bin/vitest run src/api.test.ts src/components/SegmentCard.test.tsx
 Test Files  2 passed (2)
      Tests  9 passed (9)

 ✓ src/api.test.ts (4 tests) 1ms        — _abs guard prefix/passthrough/null/undefined
 ✓ src/components/SegmentCard.test.tsx (5 tests) 32ms — render+absolute Blob URL no-double-prefix
```

### Full backend suite (excluding `test_db_clusters.py` and `test_segments_db.py` per `deferred-items.md`)

```
$ backend/.venv/bin/python -m pytest backend/tests/ \
    --ignore=backend/tests/test_db_clusters.py \
    --ignore=backend/tests/test_segments_db.py
================== 3 failed, 124 passed, 5 skipped in 17.90s ===================

FAILED backend/tests/test_debug_clusters.py::test_debug_clusters_empty_returns_envelope
FAILED backend/tests/test_pipeline_integration.py::test_lifespan_rebuilds_cache_from_sqlite
FAILED backend/tests/test_pipeline_integration.py::test_solo_parent_cluster_does_not_trigger_compile
```

The 3 failures are all the **same pre-existing fixture-leak class** as the documented `test_db_clusters.py` / `test_segments_db.py` issues: their `tmp_db` fixture monkey-patches `db.DB_PATH` (the dispatcher re-export) but the actual queries resolve `db_sqlite.DB_PATH` directly, so writes go to `/Users/liamshalom/Hacktech/data/newz.db` (production) and reads from a tmp path return `no such table: clips`. Confirmed by checking out the pre-Phase-10 versions of these test files (`git checkout 530597d -- ...`) and re-running — same root cause, in fact 5 failures pre-Phase-10 (Phase 10 incidentally fixed 2 of them via the storage refactor reads).

5 skips are postgres-parametrized tests skipped because `DATABASE_URL` is not set in this dev environment (expected per Phase 9 D-10 fixture).

Phase 10 introduced **zero new test failures**.

---

## 7. Schema Discipline

```
$ ls backend/migrations/versions/
__init__.py
20260428_0001_initial_v1_1_schema.py
__pycache__/
```

- Only the original Phase 9 Alembic revision exists.
- `clips.blob_url TEXT` confirmed in `20260428_0001_initial_v1_1_schema.py:52`.
- `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` confirmed at `:53`.
- SQLite branch carries a defensive `ALTER TABLE clips ADD COLUMN blob_url TEXT` (PRAGMA-guarded, idempotent) at `db_sqlite.py:103-104` — that's a runtime no-op for the v1.0-leftover SQLite DBs only; not a new Alembic revision.

---

## 8. Spot-check Behaviors

| Behavior | Command | Result | Status |
|---|---|---|---|
| Dispatcher selects local by default | `pytest test_storage_dispatcher.py::test_dispatcher_local_default` | PASSED | ✓ PASS |
| Dispatcher selects blob when env set | `pytest test_storage_dispatcher.py::test_dispatcher_blob_when_set` | PASSED | ✓ PASS |
| OFFLINE_DEMO overrides STORAGE_BACKEND | `pytest test_dispatcher_offline_demo_overrides` | PASSED | ✓ PASS |
| local/blob signature parity (D-12) | `pytest test_local_blob_signature_parity` | PASSED | ✓ PASS |
| OFFLINE_DEMO=true → zero Blob HTTP calls | `pytest test_offline_demo_firewall_no_blob_calls` | PASSED | ✓ PASS |
| init_client fails loud on empty token | `pytest test_init_fails_loud_on_empty_token` | PASSED | ✓ PASS |
| init_client fails loud on malformed token | `pytest test_init_fails_on_malformed_token` | PASSED | ✓ PASS |
| Tenacity retries 5xx 3 times then raises | `pytest test_5xx_retries_three_times` | PASSED | ✓ PASS |
| Tenacity retries 429 | `pytest test_429_retries` | PASSED | ✓ PASS |
| Bearer token never appears in logs | `pytest test_no_token_in_logs` | PASSED | ✓ PASS |
| Frontend `_abs` no-ops on absolute URLs | `vitest src/api.test.ts` | PASSED (4/4) | ✓ PASS |
| SegmentCard renders absolute Blob URL without double-prefix | `vitest SegmentCard.test.tsx` | PASSED (5/5) | ✓ PASS |

12/12 automated spot-checks pass.

---

## 9. Deferrals — Live HUMAN-UAT (`10-HUMAN-UAT.md`)

These are the only checks NOT verified programmatically; all require a live `BLOB_READ_WRITE_TOKEN` and Railway redeploy. Captured in `.planning/phases/10-vercel-blob-migration/10-HUMAN-UAT.md` (status: `pending`).

| # | Test | Maps to | Coverage |
|---|---|---|---|
| 1 | Task 5.5 — `cleanup_blocked_clip` end-to-end smoke against live Vercel Blob | BLOB-08, SC-5 | Code path verified; live Blob console check pending |
| 2 | SC-1 — Backend redeploy + Blob URLs render in feed | SC-1, BLOB-05, BLOB-07 | Code path verified; Railway redeploy + DevTools check pending |
| 3 | SC-2 — New clip POST lands in Blob `uploads/` | SC-2, BLOB-01 | Code path verified; iOS PWA + Blob console check pending |
| 4 | SC-3 — Compiled run-segments land in Blob `runs/` | SC-3, BLOB-02 | Code path verified; live cluster trigger + Blob console check pending |
| 5 | SC-4 — Direct browser PUT to Vercel Blob is rejected | SC-4 | Code path verified (no client-token op); browser-console fetch check pending |
| 6 | SC-5 — Cleanup hook hard-deletes blocked clips within window | SC-5, BLOB-08 | Same as #1 |
| 7 | SC-6 — `STORAGE_BACKEND=local` rolls back without code changes | SC-6, BLOB-06 | Code path verified; Railway env-var flip + smoke pending |

The deferral is documented with a clear resolution clause in `10-HUMAN-UAT.md`: when all 7 tests pass, update frontmatter to `status: resolved`.

---

## 10. Pre-Existing Issues Noted (out of scope for Phase 10)

Per `.planning/phases/10-vercel-blob-migration/deferred-items.md`:

- **`backend/tests/test_db_clusters.py`** — `tmp_db` fixture monkey-patches `db.DB_PATH` but `db_sqlite.upsert_cluster` resolves `db_sqlite.DB_PATH`, so writes leak to `data/newz.db`. NOT introduced by Phase 10. Confirmed by stashed-state re-run.
- **`backend/tests/test_segments_db.py`** — same fixture-leak class, same root cause. NOT introduced by Phase 10.
- **Additional test files affected by the same fixture-leak class** (discovered during this verification run, not in original deferred-items.md): `test_debug_clusters.py::test_debug_clusters_empty_returns_envelope`, `test_pipeline_integration.py::test_lifespan_rebuilds_cache_from_sqlite`, `test_pipeline_integration.py::test_solo_parent_cluster_does_not_trigger_compile`. All confirmed PRE-EXISTING by checking out `git show 530597d -- <test files>` (Phase 10's merge-base with main) and re-running — same failures, same root cause. Phase 10 incidentally fixed 2 of them by routing reads through the new `storage.get_playable_url` indirection.

These are not Phase 10 deliverables. Recommend: in a follow-up phase, rewrite `tmp_db` to monkey-patch `db_sqlite.DB_PATH` directly (or migrate to Phase 9's `fresh_db` pattern). Not blocking.

---

## 11. Gaps Requiring Fix-Up

**None.** All 14 code-verifiable must-haves pass. The 7 live-Blob smoke checks are intentionally deferred to merge-time HUMAN-UAT and tracked in `10-HUMAN-UAT.md`.

---

_Verified: 2026-04-29T05:23:33Z_
_Verifier: Claude (gsd-verifier, opus-4-7[1m])_
_Tests run: 13 Phase-10 unit + 9 Phase-10 frontend + 124 backend (3 pre-existing failures) + 5 skipped (postgres unset) = total 151_

# Phase 10: Vercel Blob Migration — Plan Check Verdict

**Checked:** 2026-04-29
**Plan under review:** `.planning/phases/10-vercel-blob-migration/10-01-PLAN.md` (1588 lines, 1 plan covering all 8 BLOB-XX requirements)
**Reviewer:** gsd-plan-checker (goal-backward methodology)

---

## Goal Coverage Table

### ROADMAP Success Criteria (1–6)

| SC | Description | Plan Verification Section | Tasks Cited | Status |
|---|---|---|---|---|
| 1 | Backend redeploys; clip media plays from feed (Blob URLs absolute; `/media` mount removed) | SC-1 (manual: Railway redeploy + DevTools network; automated: `test_offline_demo_firewall.py`) | 2.3 (conditional `/media` mount), 5.1 (`_abs` guard) | covered |
| 2 | New clip lands at `uploads/{clip_id}.{ext}` | SC-2 (manual: iOS PWA → Blob console; automated: `test_insert_clip and blob`) | 1.7 (blob.save_clip_bytes), 2.1/2.2 (DB callsite refactor) | covered |
| 3 | Compiled segments at `runs/{run_id}.mp4`; frontend renders absolute URLs | SC-3 (manual: `/debug/compile/{cluster_id}` + Blob console; automated: `test_stitch_runs and blob`) | 3.2 (trim_window/stitch_clips upload), 3.3 (compile.py tempdir + tempfile output), 5.1 (`_abs` guard) | covered |
| 4 | Direct browser PUT to Blob is rejected | SC-4 (manual DevTools fetch; automated: `test_init_fails_loud_on_empty_token`) | 1.4 (token never to browser), threat T-10-02 | covered |
| 5 | Moderation-block → Blob hard-delete (BLOB-08) | SC-5 (manual Wave 5.5 smoke; automated: `test_delete_idempotent_on_404`) | 1.6/1.7 (`cleanup_blocked_clip`), 5.5 (manual smoke) | covered |
| 6 | `STORAGE_BACKEND=local` rolls back without code changes | SC-6 (manual local uvicorn + curl; automated: dispatcher unit tests) | 1.6 (local.py lift-and-shift), 1.8 (dispatcher), 2.3 (conditional mount), 4.3 (parity tests) | covered |

### BLOB-01..08 Requirements

| Req ID | Requirement | Plan Tasks | Status |
|---|---|---|---|
| BLOB-01 | Server-mediated upload to `uploads/{clip_id}.{ext}` | 1.4 (httpx wrapper), 1.7 (blob.save_clip_bytes), 2.1, 2.2 (DB callsite refactor) | covered |
| BLOB-02 | Compiled segments to `runs/{run_id}.mp4` | 3.2 (`access="public"` upload), 3.3 (compile.py output via tempfile + upload) | covered |
| BLOB-03 | ffmpeg `_sync_trim` reads from Blob via byte-range, no full download | 3.1 (CRLF `headers=` kwarg into `ffmpeg.input`), `_sync_trim` retains `vcodec="copy"` | covered |
| BLOB-04 | ffmpeg `_sync_stitch` pre-downloads to `tempfile.TemporaryDirectory()` | 3.3 Edit B (tempdir + `asyncio.gather`-parallel httpx stream download) | covered |
| BLOB-05 | Frontend renders absolute Blob URLs; `/media` mount removed | 2.3 Edit 2 (conditional mount), 5.1 (`_abs` guard), 5.2 (types.ts), 5.3/5.4 (frontend tests) | covered |
| BLOB-06 | `STORAGE_BACKEND` flag for rollback | 1.1 (config.py), 1.2 (.env.example), 1.8 (dispatcher), 4.3 (dispatcher tests) | covered |
| BLOB-07 | Clip media survives Railway redeploy; backend never reads `/data/clips/` post-cutover | 2.1/2.2 (`blob_url` populated; absolute URL returned by storage), 2.3 (no unconditional `/media` mount), 3.3 (run output via tempfile) | covered |
| BLOB-08 | Cleanup hook for moderation-blocked clips | 1.6 (`local.cleanup_blocked_clip`), 1.7 (`blob.cleanup_blocked_clip`), 5.5 (manual smoke), 4.4 case 5 (idempotent on 404) | covered |

### Decision Amendments (D-03/D-05/D-06/D-08 supersede)

| Amendment | Status |
|---|---|
| 1 — Drop `mint_signed_url`; introduce `authorized_blob_input` | captured at top of PLAN.md (lines 111-116); `<interfaces>` block reflects it (lines 211-218); `blob_client.py` task explicitly drops it (Task 1.4) |
| 2 — Split-access intent stands; `Authorization: Bearer` for private reads | captured (lines 118); enforced in `stitch_input_for` (Task 1.7) and `_sync_trim` (Task 3.1) |
| 3 — No 900s TTL; `(url, headers)` tuple per call site | captured (line 120); pure function `stitch_input_for` is no-network |
| 4 — ffmpeg `headers=` kwarg, CRLF terminator | captured (line 122); Task 3.1 explicitly assembles `"".join(f"{k}: {v}\r\n" ...)`; verify command checks for CR+LF |
| 5 — Recompile CDN cache lag accepted; `x-allow-overwrite: 1` | captured (line 124); Task 1.4 includes `x-allow-overwrite: 1` header |
| 6 — Hobby tier; tenacity retry on 429 + 5xx | captured (line 126); Task 1.4 includes retry posture |
| 7 — Ship `seed_demo_to_blob.py` in this phase | captured (line 128); Task 6.1 |
| 8 — Pin `httpx==0.28.1` and `tenacity==9.1.4` | captured (line 130); Task 1.3 |

All 8 amendments traced to implementing tasks.

---

## Anti-pattern Audit (per PATTERNS.md)

| # | Anti-pattern | Plan Status |
|---|---|---|
| 1 | Per-request branching on `STORAGE_BACKEND` | NOT introduced — Task 1.8 implements module-import-time three-arm dispatcher (mirrors `db.py:16-24`) |
| 2 | `import httpx` inside `backend/storage/blob.py` | NOT introduced — Task 1.7 explicitly imports only `blob_client, _url, config`; doc-string forbids httpx |
| 3 | Logging signed URLs / bearer tokens verbatim | NOT introduced — Task 1.4 logs `op`/`pathname`/`latency_ms`/`bytes` only; sanitizes init-failure to `type(exc).__name__`; Task 4.4 case 8 is an explicit token-leak test |
| 4 | Adding `blob_url`/`pathname` as structlog contextvar | NOT introduced — kwargs-only logging stated; phase_history_digest line 240 reaffirms PRIV-02 whitelist |
| 5 | Pre-warm Blob on startup | NOT introduced — D-27 honored; lifespan ordering (Task 2.3) does NOT add a Marengo-style warm-up call |
| 6 | In-process signed-URL caching | NOT introduced (and N/A — amendment 3 eliminates signed-URL machinery entirely) |
| 7 | Direct browser PUT (Vercel client-upload tokens) | NOT introduced — wrapper exposes only upload/delete/head; threat T-10-02 mitigation explicit |
| 8 | Streaming trim output through pipe to Blob | NOT introduced — Task 3.2 follows D-10 sequential trim → local temp → upload (atomic-rename preserved) |
| 9 | Cluster-level tempdir reuse / cross-recompile cache | NOT introduced — Task 3.3 wraps each `_stitch_segment_runs` invocation in its own `tempfile.TemporaryDirectory()` |
| 10 | Adding downgrade body to Alembic migration to drop `blob_url` | NOT introduced — `must_haves.artifacts` lists migration as READ-ONLY confirmation; checklist item 18 satisfied |
| 11 | Heredoc/CLI-arg secrets in seed script | NOT introduced — Task 6.1 reads `ADMIN_TOKEN` from env, not argparse |
| 12 | Re-mounting `/media` unconditionally | NOT introduced — Task 2.3 Edit 2 wraps mount in `if STORAGE_BACKEND == "local" or OFFLINE_DEMO:` |
| 13 | High-cardinality Prometheus labels | NOT introduced — plan adds no metrics; logging spec uses `op` only |
| 14 | Reading `clips.path` as Path in blob mode | NOT introduced — `get_playable_url(row)` is the indirection; Task 2.1/2.2 route reads through it |
| EXTRA | Dropping `try/except` failure-fallback in trim_window | NOT introduced — Task 3.2 preserves `fallback_path = ref["path"]` and returns local_out on upload failure |

All 14 documented anti-patterns avoided.

---

## Threat Model Audit

The PLAN.md includes a `<threat_model>` block (lines 251-273) that satisfies the mandatory step 5.55 requirement.

| Threat | Severity | Mitigation Mapped to Task | Status |
|---|---|---|---|
| T-10-01 Information Disclosure (token leak in logs) | high | Task 1.4 redacted log lines + Task 4.4 case 8 (`test_no_token_in_logs`) | mitigated + tested |
| T-10-02 Spoofing (browser PUT bypass) | high | Wrapper exposes no `mint_client_upload_token`; SC-4 manual + Task 4.4 case 1 | mitigated + tested |
| T-10-03 Information Disclosure (leaked private URL replay) | medium | BLOB-08 cleanup hook (Tasks 1.6/1.7) + amendment 3 token-only model | mitigated (medium per plan disposition) |
| T-10-04 DoS / fail-open on missing token | high | Task 1.4 fail-loud RuntimeError; Task 4.4 case 1 + case 2 | mitigated + tested |
| T-10-05 Tampering (OFFLINE_DEMO firewall bypass) | high | Task 1.8 dispatcher hard-override; Task 4.2 explicit firewall test | mitigated + tested |

`Block-on: all severity=high rows` clause is present (line 272). All 5 high-severity rows have implementing-task references AND test references.

**No additional threats noticed beyond T-10-01..05.** The catalog covers the obvious surface (token at-rest in env, token in flight, log breadcrumbs, browser-side bypass, OFFLINE_DEMO firewall, leaked-URL replay).

---

## Locked-Decision Conformance

### CONTEXT.md L-01..L-09 (inherited locks)
- L-01 (Vercel Blob): plan implements; no R2 mention.
- L-02 (server-mediated only): T-10-02 mitigation + wrapper surface in `<interfaces>` excludes client-token op.
- L-03 (OFFLINE_DEMO hard-override): Task 1.8 + Task 4.2.
- L-04 (`clips.blob_url` already nullable): `must_haves.artifacts` lists migration as READ-ONLY; PLAN.md does NOT add an alembic migration. (Task 2.1's defensive `ALTER TABLE` is sqlite-only and gated on PRAGMA — does NOT touch the Postgres branch. Compliant with the L-04 intent.)
- L-05 (`is_hidden` already exists): plan does not write it (correct — Phase 11 owns).
- L-06 (Sentry `before_send` already redacts `blob_url`): plan does NOT add scrub-list tasks (correct — checklist item 12 honored).
- L-07 (structlog contextvars whitelist): explicitly noted in `phase_history_digest` line 240; Task 1.4 / 1.7 log via kwargs not contextvars.
- L-08 (single Uvicorn worker; httpx singleton): Task 1.4 module-level `_client`; init/close in lifespan (Task 2.3).
- L-09 (no SQLAlchemy ORM): plan adds no SQLAlchemy. Verified by SC-cross-cutting "no SQLAlchemy imports added."

### CONTEXT.md non-superseded decisions (D-01, D-02, D-04, D-07, D-09..D-28)
Spot-checked: D-01 (raw httpx, not SDK) — Task 1.4. D-02 (lifespan-managed singleton) — Task 2.3. D-04 (token never logged) — Task 1.4 + 4.4. D-09 (`_sync_stitch` tempdir) — Task 3.3 Edit B. D-13 (module-import dispatcher) — Task 1.8. D-19 (fail-loud on missing token) — Task 1.4 + 4.4 case 1. D-20 (sync hook contract) — Task 1.6/1.7. D-21 (2x2 fixture) — Task 4.1. D-22 (wave-0 smoke) — Wave 0. D-23 (env vars) — Task 1.1. D-25 (blob_client.py location) — Task 1.4. D-27 (no pre-warm) — confirmed absent from Task 2.3 lifespan ordering. All checked decisions honored.

### Project-level constraints (anonymity, iOS Safari, single worker)
- Anonymity: plan adds no auth, no profiles. Storage layer never sees session_uuid.
- iOS Safari MIME ladder: `ALLOWED_MIME_PREFIXES = ("video/mp4", "video/webm")` at `app.py:160` is preserved (Task 2.3 Edit 1/2 do not touch lines 132-147 / 160).
- Single Uvicorn worker: Task 1.4 module-level singleton, no inter-process coordination.

---

## Code-Reference Validity

Spot-checked every line-number claim against actual source:

| Plan Reference | Actual | Match |
|---|---|---|
| `backend/app.py:151` `/media` mount | confirmed at line 151 | yes |
| `backend/app.py:159-160` MAX_UPLOAD + MIME gate | confirmed | yes |
| `backend/app.py:420-430` `_delete_files` | function at line 420 | yes |
| `backend/app.py:472, 483` `_delete_files` callers | confirmed at 472 + 483 | yes |
| `backend/db_sqlite.py:168` `path.write_bytes` | confirmed at line 169 (off-by-one, harmless) | yes |
| `backend/db_postgres.py:167` `path.write_bytes` | confirmed at line 169 (off-by-one, harmless) | yes |
| `backend/db_sqlite.py:202-205` `f"/media/{filename}"` | confirmed at line 199 | yes |
| `backend/pipeline/stitch.py:30` `_sync_stitch` | confirmed at line 30 | yes |
| `backend/pipeline/stitch.py:112` `_sync_trim` | confirmed at line 112 | yes |
| `backend/pipeline/compile.py:194-217` `_resolve_run_ids_to_stitch_refs` | confirmed at line 194 | yes |
| `backend/pipeline/compile.py:312-359` `_stitch_segment_runs` | confirmed at line 312 | yes |
| `backend/pipeline/compile.py:343` output_path | confirmed at line 345 (off-by-two, harmless) | yes |
| `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py` `blob_url` + `is_hidden` | confirmed at lines 52-53 | yes |
| `frontend/src/api.ts:29-31` template-literal prefix | confirmed at lines 29-31 | yes |
| `backend/observability/anonymity.py` scrubs `blob_url` | confirmed at line 23 | yes |

All cross-references are accurate (within ±2 lines — code drifts as expected).

---

## Execution Mechanics

| Check | Status |
|---|---|
| Tasks atomic (files + action + verify + done) | yes — every `<task type="auto">` has all four; `checkpoint:human-action`/`-verify` tasks have what-built/how-to-verify/resume-signal |
| `[BLOCKING]` prefix on gating tasks | uses `gate="blocking"` attribute on Wave 0 / Wave 5.5 checkpoints (template style); env-var setup is autonomous: false at the plan level |
| Wave order (storage → DB callsite → pipeline → tests → frontend) | yes — Wave 0 (smoke) → Wave 1 (storage package) → Wave 2 (DB + lifespan) → Wave 3 (pipeline) → Wave 4 (tests) → Wave 5 (frontend) → Wave 6 (seed script). Each wave's `Wave dependencies:` line is sane. |
| Acceptance check on every task | yes — every `<task type="auto">` has a `<verify><automated>...</automated></verify>` shell command; checkpoints have explicit verify steps |
| Dependency on Phase 9 cited | yes — `depends_on: [9]` in frontmatter; CONTEXT.md inheritance summarized in `phase_history_digest` |
| No assumption of Phase 11/12 code | yes — `cleanup_blocked_clip` is shipped but never called by Phase 10's own code (only by SC-5 manual smoke and Task 4.4 unit test); BLOB-08 explicitly says Phase 11 is the caller |
| Wave 0 env-var gate is autonomous: false with explicit instructions | yes — Task 0.1 lists exact dashboard paths and env var names; Task 0.2 ships a scratch `python -` REPL one-liner |

---

## Specific Gaps & Required Fixes

The plan is unusually thorough. Three small items rise to ATTENTION (not blocking) — none rise to MUST-FIX:

1. **(LOW) Task 2.1's defensive `ALTER TABLE clips ADD COLUMN blob_url TEXT` for sqlite is a one-time migration in the hot path of `init()`.**
   The plan specifies it correctly (PRAGMA-guarded, idempotent), but the executor should be aware that this runs on every backend startup and adds a tiny SQLite metadata read. Not a fix — just a note.

2. **(LOW) Task 3.3 Edit A patches `compute_runs_for_cluster` to surface `parent_blob_url` on the `Run` dataclass, but the plan only describes this in prose ("read the file to confirm, then add via `compute_runs_for_cluster` join").**
   `runs.py:17` `@dataclass class Run` does NOT currently have a `parent_blob_url` field, so Task 3.3 must in fact mutate `runs.py` even though `runs.py` is not in `files_modified` at the top of PLAN.md.
   **Recommendation (non-blocking):** add `backend/pipeline/runs.py` to `files_modified` for transparency. The plan can still pass without this addition; the executor will discover the need from the prose.

3. **(LOW) Task 3.2 modifies `stitch_clips` to take a `run_id` kwarg and upload, but the existing `stitch_clips` async wrapper at `stitch.py:90-109` is invoked only from a single fallback path (a multi-source concat).**
   Phase 10's hot path is `trim_window` (per-run trim — see `compile.py:_trim_one`); `stitch_clips` is rarely exercised. The plan correctly applies the same upload tail to both, but the verify command (line 1033) only greps for `runs/` and `access="public"` in both — fine. Just be aware that real-world coverage of the `stitch_clips` upload path will only land if a multi-source concat happens during the wave-5.5 manual smoke.

None of these are blockers. The plan can proceed.

---

## Notes for the Executor

1. **Order-of-operations in `lifespan()`:** Task 2.3 inserts the `init_client()` call AFTER `cluster_mod.rebuild_cache()` but BEFORE the `keepalive_task` creation. This is correct for two reasons: (a) `cluster_mod.rebuild_cache()` must finish before any storage I/O happens (no dependency, but logically clean); (b) keepalive should start AFTER all bound clients are up so its first PING doesn't race the asyncpg-pool acquisition. Stick to the order.

2. **Amendment 4's CRLF terminator** is the highest-risk implementation detail (Pitfall 2). The verify command at Task 3.1 line 977 explicitly checks for `chr(13)+chr(10)` in the source — runs as `\r\n`. Do not accept just `\n`. If the wave-0 trim smoke shows 401 from Vercel Blob, the headers string is the place to look first.

3. **Amendment 3 means there is NO mint_signed_url.** Even though CONTEXT.md D-03 still mentions it, PLAN.md's `<interfaces>` block is the source of truth for the executor — `blob_client.py` exposes `upload`, `delete`, `head` only. If the executor finds itself implementing a TTL machine, stop and re-read amendment 3.

4. **The `cleanup_blocked_clip` `from .. import db` lazy import** in Task 1.6 / 1.7 is intentional (avoids circular: `storage` ← `db` ← `storage` for `db.get_clip`). Do not refactor to a top-level import.

5. **Wave 5.5 manual smoke depends on the user having a Blob store + STORAGE_BACKEND=blob locally.** This is the only Phase 10 manual gate that exercises the full BLOB-08 hook end-to-end. If the user can't run it locally, the hook ships with only the unit-test mock as proof; the real validation moves to Phase 11 integration. Document this in 10-01-SUMMARY.md.

6. **`paths_to_delete` in admin/reset is now mixed local-paths + Blob URLs** post-Task 2.4. Task 2.4 routes them through `storage.delete_clip` correctly. The existing `mode=all` path scans the local clips dir physically (no DB lookup) — Task 2.4 leaves it untouched, with a 2-line WHY comment justifying that orphan blobs are acceptable for v1.1 demo. Phase 11 cleanup hook is the production-grade defense.

7. **`runs.py:Run` dataclass needs a `parent_blob_url: str | None = None` field** (gap #2 above). This is Task 3.3 Edit A's prose. Add the field; populate it in `compute_runs_for_cluster` from the same row that yields `parent_path`. (`fetch_cluster_clips_with_children` already returns `blob_url` if `db_sqlite.py:467` / `db_postgres.py:474` join it through.)

---

## VERDICT: PASS

The plan is comprehensive, faithful to CONTEXT.md (including the supersede amendments for D-03/D-05/D-06/D-08), and has no missing requirements, no broken dependencies, no anti-pattern intrusions, and no threat-model gaps.

Coverage summary: 6/6 ROADMAP success criteria, 8/8 BLOB-XX requirements, 8/8 decision amendments, 5/5 STRIDE threats, 14/14 anti-patterns avoided, all L-01..L-09 honored.

Three LOW-severity observations (sqlite ALTER side-effect, `runs.py` not in `files_modified`, `stitch_clips` real-world coverage) do not block execution. Note them in the Wave 0 / Wave 1 prep so the executor isn't surprised.

The executor can proceed to `/gsd-execute-phase 10`.

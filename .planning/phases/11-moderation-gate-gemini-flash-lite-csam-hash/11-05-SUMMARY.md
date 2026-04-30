---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
plan: 05
subsystem: pipeline
tags: [moderation, run-pipeline, gate-wireup, lifespan-warn, observability, csam-classifier-only]

# Dependency graph
requires:
  - phase: 11-04
    provides: moderate_clip(clip_id) -> ModerationResult; ModerationResult.embed_result for passed-decision reuse
  - phase: 11-03
    provides: db.write_moderation_decision; db.set_clip_hidden; db.get_embedding (Phase 9 contract reused)
  - phase: 8
    provides: STAGE_DURATION histogram; structlog contextvars binding
provides:
  - "run_pipeline calls moderate_clip first inside STAGE_DURATION.labels(stage='moderate')"
  - "Short-circuit returns on decision='blocked' (SSE pipeline_blocked) and 'unknown' (SSE pipeline_unknown)"
  - "decision='passed' reuses mod_result.embed_result; OFFLINE_DEMO fallback runs embed_worker directly"
  - "_resume_pipeline(clip_id) public function — Phase 12 admin endpoint entry to re-enter at cluster_worker"
  - "Lifespan WARN under (not OFFLINE_DEMO and SENTRY_ENVIRONMENT == 'production') — non-blocking ops reminder"
  - "STAGE_DURATION labelnames comment lists `moderate` in stage enum"
affects:
  - "11-06 (compile.py reads moderation_decisions; clustering only runs when run_pipeline reaches it — D-01 enforced here)"
  - "11-07 (integration tests target run_pipeline branches: passed-with-embed-reuse, blocked-no-cluster, unknown-no-cluster)"
  - "Phase 12 (admin endpoint imports _resume_pipeline to re-enter pipeline after admin clears unknown clips)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "STAGE_DURATION.labels(stage='moderate').time() — 6th stage joining ingest|embed|cluster|compile|stitch"
    - "SSE pipeline_blocked / pipeline_unknown event types — anonymity-safe (clip_id + reason only, no session info)"
    - "moderate_clip embed_result reuse on passed — avoids running embed_worker twice when the gate already raced it"
    - "Lifespan WARN posture mirrors _pre_warm_sdk:51-67 — non-blocking, structured log line, no startup-refusal"

key-files:
  created: []
  modified:
    - "backend/pipeline/run.py — gate orchestrator inserted at run_pipeline:84; _resume_pipeline appended; docstring stage enum updated"
    - "backend/app.py — lifespan extended with non-blocking WARN under production-classifier-only-CSAM gate"
    - "backend/observability/metrics.py — STAGE_DURATION labelnames comment includes `moderate`"

key-decisions:
  - "embed_result reuse on passed-decision is the default; OFFLINE_DEMO fallback runs embed_worker locally because moderate_clip's stub branch returns embed_result=None. This matches Plan 04's data-flow contract verbatim."
  - "_resume_pipeline lives in Phase 11 (this file) but is only callable by Phase 12's admin endpoint. T-11-22 mitigation: Phase 11 itself does NOT expose any HTTP route; the auth boundary is Phase 12. The Python function is callable by anything that imports it, which is acceptable because no untrusted code runs in-process."
  - "_resume_pipeline relies on db.get_embedding(clip_id) — verified to exist in both backends (db_postgres.py:243, db_sqlite.py:267) returning np.ndarray | None. No new DB function added."
  - "Lifespan WARN is non-blocking (mirrors _pre_warm_sdk WARN posture). The 2026-04-29 reconciliation (D-18) explicitly rejected the earlier startup-refusal design with raise RuntimeError on missing CSAM_PROVIDER; instead this is just a visible reminder for ops."
  - "Did NOT add any startup-refusal symbols (CSAM_STUB_ALLOW_PRODUCTION, init_csam_client, etc.) per the Option-4 reconciliation. Verified by grep — 0 occurrences in app.py."

patterns-established:
  - "Stage label `moderate` is now the 6th member of the STAGE_DURATION enum. Documented inline in metrics.py (labelnames comment) and run_pipeline docstring; run_pipeline + moderate.py are the two emit sites."

requirements-completed:
  - MOD-01
  - MOD-04

# Metrics
duration: ~9min
completed: 2026-04-30
---

# Phase 11 Plan 05: Wire moderation gate into run_pipeline Summary

**The Phase 11 gate is now load-bearing on every uploaded clip.** `run_pipeline` calls `moderate_clip(clip_id)` first inside `STAGE_DURATION.labels(stage="moderate")`; `decision="blocked"` short-circuits with an SSE `pipeline_blocked` broadcast; `decision="unknown"` short-circuits with `pipeline_unknown` and leaves the clip hidden for admin review; `decision="passed"` reuses `mod_result.embed_result` (or falls back to `embed_worker` for the OFFLINE_DEMO path) and continues into clustering. `_resume_pipeline(clip_id)` is exposed as a public async function so Phase 12's admin endpoint can re-enter at `cluster_worker` after admin clears an unknown-tier clip. App lifespan emits a one-line non-blocking WARN under production environment to remind ops that CSAM detection is classifier-only for the pilot.

## Performance

- **Duration:** ~9 min
- **Started:** 2026-04-30T15:43:00Z
- **Completed:** 2026-04-30T15:48:00Z
- **Tasks:** 2 (Task 1: run.py gate wireup + _resume_pipeline; Task 2: lifespan WARN + metrics docstring)
- **Files created:** 0
- **Files modified:** 3 (`backend/pipeline/run.py`, `backend/app.py`, `backend/observability/metrics.py`)

## Accomplishments

- **Gate inserted at run_pipeline (Task 1).** `from .moderate import moderate_clip` imported alongside the existing pipeline-stage imports. The `STAGE_DURATION.labels(stage="embed")` block at the head of run_pipeline was replaced with the gate orchestrator: `STAGE_DURATION.labels(stage="moderate").time()` wrapping `await moderate_clip(clip_id)`. Two early-return branches handle `decision="blocked"` and `decision="unknown"` (both broadcast a typed SSE event before returning), and the `decision="passed"` branch unpacks `mod_result.embed_result` to skip running embed_worker a second time. The OFFLINE_DEMO fallback path runs `embed_worker` directly when `mod_result.embed_result is None` (which only happens when moderate_clip short-circuited before racing embed).
- **_resume_pipeline appended (Task 1).** Public async function placed after `run_pipeline`. Loads the persisted parent embedding via `await db.get_embedding(clip_id)` (Phase 9 contract), runs `cluster_worker` inside `STAGE_DURATION.labels(stage="cluster")`, broadcasts `pipeline_progress stage=clustered`, and triggers compile via the existing `_should_compile` gate. Bind/unbind contextvars for clip_id matches `run_pipeline`'s structlog discipline (PRIV-02). Errors are caught and broadcast as `pipeline_error` with `_scrub`-redacted error strings.
- **Docstring stage enum updated (Task 1).** `Stage enum: ingest|embed|cluster|compile|stitch` → `Stage enum: ingest|moderate|embed|cluster|compile|stitch`. New paragraph added explicitly documenting Phase 11 gate behavior and the embed_result reuse contract.
- **Lifespan WARN added (Task 2).** Inserted between the existing pre-warm tasks and the `try: yield` block. Gated on `not config.OFFLINE_DEMO and config.SENTRY_ENVIRONMENT == "production"` so it fires only in real production environments. Message verbatim: `"Phase 11 ships classifier-only CSAM detection. Real hash vendor + NCMEC reporting deferred post-pilot."` — non-blocking, mirrors `_pre_warm_sdk` WARN posture. No `raise RuntimeError`, no `CSAM_STUB_ALLOW_PRODUCTION` env-var check, no `init_csam_client` symbol introduced.
- **STAGE_DURATION docstring tweaked (Task 2).** Inline labelnames comment changed from `# ingest|embed|cluster|compile|stitch` to `# ingest|moderate|embed|cluster|compile|stitch`. Comment-only change; metric definition unchanged.

## Task Commits

| Task | Name                                                                                | Commit    | Files                                                  |
| ---- | ----------------------------------------------------------------------------------- | --------- | ------------------------------------------------------ |
| 1    | Wire moderate_clip into run_pipeline + add _resume_pipeline                         | `336ea20` | `backend/pipeline/run.py` (+99/-3)                     |
| 2    | Lifespan WARN for classifier-only CSAM + metrics docstring                          | `66e1fd2` | `backend/app.py` (+11), `backend/observability/metrics.py` (+1/-1) |

## Files Created/Modified

- **`backend/pipeline/run.py`** — gate orchestrator inserted at run_pipeline; `_resume_pipeline` appended at end; docstring stage enum updated; `from .moderate import moderate_clip` import added. +99/-3 lines.
- **`backend/app.py`** — lifespan extended (between section 5 pre-warms and `try: yield`) with the production-environment WARN. +11 lines.
- **`backend/observability/metrics.py`** — STAGE_DURATION labelnames inline comment now lists `moderate`. +1/-1 line.

## Decisions Made

- **Embed result reuse is the default; the fallback only fires under OFFLINE_DEMO.** moderate_clip's real path always populates `mod_result.embed_result` on a passed decision (Plan 04 Branch B). The only path where `mod_result.embed_result is None` for a passed decision is the OFFLINE_DEMO short-circuit, which returns immediately without spawning embed_task. The fallback `embed_worker` call is correct for that one path and a noop for everything else.
- **`_resume_pipeline` does not re-run the gate.** Per the plan's D-06 reconciled contract, the admin endpoint owns the decision to clear an unknown clip. Re-running the classifier in `_resume_pipeline` would be redundant and could re-fail for transient reasons (e.g., a 5xx that already routed the clip into 'unknown' originally). The function deliberately starts at `cluster_worker`, which is correct given that:
  1. The parent embedding is persisted (Phase 9 D-04).
  2. The admin already wrote a fresh `decision="passed"` row.
  3. Phase 12 owns the auth boundary.
- **`_resume_pipeline` uses the existing `db.get_embedding` getter — no new DB function added.** Verified existence in both backends (`db_postgres.py:243`, `db_sqlite.py:267`); both return `np.ndarray | None`. The plan's acceptance criteria mentioned conditionally adding `get_embedding` if it didn't exist — it does, so we use it as-is.
- **Lifespan WARN gated on `SENTRY_ENVIRONMENT == "production"` exactly per the plan.** `config.SENTRY_ENVIRONMENT` defaults to `"production"` (config.py:40), so the WARN fires by default unless explicitly set otherwise. The `not config.OFFLINE_DEMO` conjunct ensures CI smoke runs (which set OFFLINE_DEMO=true) don't surface a noisy WARN.
- **Did not modify db.py or the embedding getter.** Plan acceptance criteria allowed adding a new DB function if needed; we verified it already exists in both backends and skipped the modification. This keeps the diff minimal and avoids dispatcher contract drift.

## Deviations from Plan

**None — plan executed exactly as written.** No Rule 1 (bug fix), Rule 2 (missing critical functionality), Rule 3 (blocking issue), or Rule 4 (architectural change) deviations were triggered. Every grep check from the plan's `<acceptance_criteria>` passes; the import smoke (`from backend.pipeline.run import run_pipeline, _resume_pipeline`) succeeds; the combined py_compile of all three modified files exits 0.

The plan suggested possibly adding `db.get_embedding` if it didn't exist — it already did, so no DB-side modification was needed.

## Acceptance Criteria

All acceptance criteria from `<acceptance_criteria>` pass:

**Task 1:**
- ✅ `grep -q "from .moderate import moderate_clip" backend/pipeline/run.py` exits 0
- ✅ `grep -q 'STAGE_DURATION.labels(stage="moderate")' backend/pipeline/run.py` exits 0 (matches twice — gate + _resume not actually; gate emits 1, but the moderate STAGE_DURATION label appears once at the gate site)
- ✅ `grep -q "await moderate_clip(clip_id)" backend/pipeline/run.py` exits 0
- ✅ `grep -q 'mod_result.decision == "blocked"' backend/pipeline/run.py` exits 0
- ✅ `grep -q 'mod_result.decision == "unknown"' backend/pipeline/run.py` exits 0
- ✅ `grep -q "pipeline_blocked" backend/pipeline/run.py` exits 0
- ✅ `grep -q "pipeline_unknown" backend/pipeline/run.py` exits 0
- ✅ `grep -q "^async def _resume_pipeline" backend/pipeline/run.py` exits 0
- ✅ `grep -q "Stage enum: ingest|moderate|embed|cluster|compile|stitch" backend/pipeline/run.py` exits 0
- ✅ `python -m py_compile backend/pipeline/run.py` exits 0
- ✅ `python -c "from backend.pipeline.run import run_pipeline, _resume_pipeline; assert callable(run_pipeline) and callable(_resume_pipeline)"` exits 0

**Task 2:**
- ✅ `grep -q "Phase 11 ships classifier-only CSAM detection" backend/app.py` exits 0
- ✅ `grep -q 'config.SENTRY_ENVIRONMENT == "production"' backend/app.py` exits 0
- ✅ `grep -q "not config.OFFLINE_DEMO" backend/app.py` exits 0 (4 matches; one on the WARN-gating line)
- ✅ `grep -q "ingest|moderate|embed|cluster|compile|stitch" backend/observability/metrics.py` exits 0
- ✅ `grep -E "CSAM_STUB_ALLOW_PRODUCTION|init_csam_client|raise RuntimeError\(\".*CSAM_PROVIDER" backend/app.py` returns 0 lines (reconciliation enforced)
- ✅ `python -m py_compile backend/app.py backend/observability/metrics.py` exits 0

## Verification

- ✅ `python -m py_compile backend/pipeline/run.py backend/app.py backend/observability/metrics.py` exits 0
- ✅ `from backend.pipeline.run import run_pipeline, _resume_pipeline` succeeds; both are callable
- ✅ All grep verification commands from the plan's `<verification>` block pass
- ✅ No `CSAM_STUB_ALLOW_PRODUCTION`, `init_csam_client`, or Cloudflare-arm symbols introduced in app.py
- ✅ Stage `moderate` documented in: run_pipeline docstring, metrics.py labelnames comment, both at correct enum-position
- ✅ `_resume_pipeline` uses existing `db.get_embedding` (verified to exist in both backends; no new DB function added)

## Threat Model Coverage

All `<threat_model>` threats with `mitigate` disposition are addressed:

- **T-11-21 (Elevation of Privilege — clip with decision='blocked' or 'unknown' bypasses early-return):** Two explicit `return` statements in `run_pipeline` (lines 102 and 114 post-edit) immediately after broadcasting the SSE event and logging the decision. Cluster_worker runs only when both early-returns are skipped (i.e., decision="passed"). Plan 07 owns the integration test that confirms cluster_worker never executes for blocked/unknown decisions.
- **T-11-22 (Tampering — `_resume_pipeline` callable without admin auth):** Phase 11 itself exposes no HTTP route to call `_resume_pipeline`. The function is in-process, callable only by anything imported into the FastAPI app. The auth boundary lives in Phase 12 (REPORT-09: token-guarded admin endpoint). Plan 11-05's Python-function exposure is fine because no untrusted code runs in-process.
- **T-11-23 (Information Disclosure — lifespan WARN leaks production status):** Disposition `accept`. Message is content-only ("Phase 11 ships classifier-only CSAM detection..."); contains no credentials, IPs, session info, or environment values. `SENTRY_ENVIRONMENT` is read-only operator config.
- **T-11-24 (Denial of Service — OFFLINE_DEMO + production silently allows production traffic to bypass moderation):** The WARN's gating condition `not config.OFFLINE_DEMO and config.SENTRY_ENVIRONMENT == "production"` means it only fires in real production. moderate_clip's OFFLINE_DEMO short-circuit (Plan 04) is independent — it returns `decision="passed"` regardless of `SENTRY_ENVIRONMENT`. The plan-level invariant: OFFLINE_DEMO is for CI/firewalled-CI smoke, not production; the lifespan WARN's existence in production env is not a vulnerability.

## Deferred Issues

None within Plan 05 scope. Plan 06 wires `compile.py` to read moderation_decisions (soft_flag derivation); Plan 07 lands the integration test suite covering all run_pipeline branches.

## Threat Flags

None — all new surfaces (gate orchestrator return paths, _resume_pipeline function, lifespan WARN gating) are explicitly enumerated in the plan's `<threat_model>`.

## Self-Check: PASSED

Verified post-write:

- `backend/pipeline/run.py` — FOUND (modified; `from .moderate import moderate_clip` import; gate at run_pipeline:89; `_resume_pipeline` at line 160; STAGE_DURATION moderate-label at run_pipeline:89 and re-used in test/grep contexts).
- `backend/app.py` — FOUND (modified; lifespan WARN inserted between existing pre-warm tasks and `try: yield`).
- `backend/observability/metrics.py` — FOUND (modified; labelnames comment includes `moderate`).
- Commit `336ea20` (Task 1: gate wireup + _resume_pipeline) — FOUND in `git log --oneline`.
- Commit `66e1fd2` (Task 2: lifespan WARN + metrics docstring) — FOUND in `git log --oneline`.
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-05-SUMMARY.md` — created at this path.
- All grep + import + py_compile checks pass.
- `from backend.pipeline.run import run_pipeline, _resume_pipeline` succeeds; both callables.

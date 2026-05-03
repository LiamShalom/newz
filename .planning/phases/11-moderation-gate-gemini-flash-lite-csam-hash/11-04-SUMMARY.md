---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
plan: 04
subsystem: pipeline
tags: [moderation, gemini-flash-lite, asyncio.wait, classifier-only, csam-preservation, anonymity]

# Dependency graph
requires:
  - phase: 11-01
    provides: config.GEMINI_MODERATION_MODEL + config.MODERATION_MAX_BUDGET_S env-var contracts
  - phase: 11-03
    provides: db.write_moderation_decision, db.write_reported_csam, db.set_clip_hidden, db.get_moderation_decisions, db.aggregate_verdict
  - phase: 10
    provides: storage.cleanup_blocked_clip + storage.blob_client.get_client (private-blob streaming)
  - phase: 8
    provides: observability.anonymity REDACT_KEYS frozenset (extension point)
provides:
  - "moderate_clip(clip_id) -> ModerationResult — async entry point for Phase 11 gate"
  - "SYSTEM_PROMPT (verbatim) + PROMPT_VERSION='1.0.0' + ModerationResponse TypedDict (response_schema)"
  - "HARD_BLOCK_CATEGORIES = (csam, sexual, extremist, self_harm); SOFT_FLAG_CATEGORIES = (hate, violence)"
  - "Sentry REDACT_KEYS extended with raw_response + prompt_version (D-27 reconciled, no csam_hash)"
affects:
  - "11-05 (run.py wire-in: from .moderate import moderate_clip; await moderate_clip(clip_id) before cluster)"
  - "11-06 (compile.py reads decisions via db.get_moderation_decisions / db.aggregate_verdict for soft_flag derivation)"
  - "11-07 (integration tests: respx-mock Gemini, behavior tests for all branches + OFFLINE_DEMO + reported_csam ordering)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.wait FIRST_COMPLETED + cancel-when-embed-finishes (D-03) for parallel embed/gemini race"
    - "asyncio.create_task + _drain_task helper for cancelled-task re-await (suppresses 'Task was destroyed' warnings)"
    - "Typed-exception ladder (D-05): TimeoutError + 4xx → blocked; 5xx + ConnectError + ReadError + TransportError → unknown"
    - "Audit-trail ordering (T-11-16): write_reported_csam BEFORE cleanup_blocked_clip on csam-hit so the SHA-256 hash persists before bytes are deleted"
    - "_strip_anonymity_metadata defense-in-depth scrub of outbound classifier payload structures (PRIV-03)"
    - "STAGE_DURATION.labels(stage='moderate').observe — Prometheus histogram parity with embed/cluster/compile stages"

key-files:
  created:
    - "backend/pipeline/moderate.py — 610 lines: SYSTEM_PROMPT, PROMPT_VERSION, ModerationResponse TypedDict, ModerationResult dataclass, helpers (_content_hash, _strip_anonymity_metadata, _now_unix, _one_year_from_now_unix), _fetch_clip_bytes, _gemini_classify, _route_verdict, _classify_exception, _drain_task, _moderate_real, moderate_clip"
  modified:
    - "backend/observability/anonymity.py — REDACT_KEYS frozenset extended by 2 entries (raw_response, prompt_version) per D-27 reconciliation"

key-decisions:
  - "Defense-in-depth fallback wraps the entire _moderate_real body in try/except → decision='unknown' + set_clip_hidden(True) on any unhandled exception. This is OUT-OF-SPEC permissive (the plan's <action> step 11 only loosely required it); we made it strict by also writing a moderation_decisions row with reason='classifier_unknown_error' so Plan 06's aggregate_verdict cannot return 'passed' for a clip whose moderate_clip threw."
  - "Local-mode clip_local_path is NEVER unlinked by moderate.py — that path IS the canonical row.path. cleanup_blocked_clip owns the delete on hard-block. Only blob-mode tempfiles (mirrored from embed.py:189) are unlinked in the finally."
  - "_classify_exception unifies httpx.TransportError, httpx.ConnectError, httpx.ReadError into the same reason='classifier_network_error' string. Plan 07 grep checks ('classifier_network_error') will see one constant; the typed-exception ladder still distinguishes routing classes per D-05."
  - "When embed_task finishes first (Branch A), embed_task.result() is captured into embed_result so the ModerationResult could in principle forward it on a 'passed' decision — but Branch A always sets decision='blocked', so embed_result is discarded by the dataclass-construction line. Kept for symmetry with Branch B and to make Plan 05 wiring trivially refactorable."
  - "_gemini_classify raises httpx.ConnectError when GEMINI_API_KEY is empty (rather than ValueError). This routes the missing-key case through the network-error tier of _classify_exception → decision='unknown', which is the safest behavior (we don't know if the clip is safe). The OFFLINE_DEMO short-circuit upstream of _moderate_real prevents this branch from ever firing in the demo path."

patterns-established:
  - "STAGE_DURATION metric label='moderate' joins the existing ingest|embed|cluster|compile|stitch family — adds the 6th stage to backend/observability/metrics.py:46 docstring (no code change to metrics.py needed; the labelname accepts arbitrary strings)."
  - "Phase 11 helpers _content_hash + _one_year_from_now_unix are ~10-line pure functions with explicit § 2258A / 2024 REPORT Act citations in their docstrings — the legal context lives at the call site, not in a separate compliance doc."

requirements-completed:
  - MOD-01
  - MOD-02
  - MOD-03
  - MOD-04
  - MOD-05
  - MOD-06
  - MOD-07
  - MOD-09
  - MOD-10
  - PRIV-03

# Metrics
duration: ~8min
completed: 2026-04-30
---

# Phase 11 Plan 04: moderate_clip Implementation Summary

**The Phase 11 gate is now load-bearing. moderate_clip(clip_id) fires Gemini 2.5 Flash-Lite + Marengo embed in parallel via asyncio.wait FIRST_COMPLETED with a MODERATION_MAX_BUDGET_S outer cap and cancel-when-embed-finishes inner ceiling, routes the locked taxonomy verdict through a typed-exception ladder, writes audit rows + reported_csam preservation (1-year retention per § 2258A) + cleanup_blocked_clip on hard-block, and short-circuits OFFLINE_DEMO=true to a single-row passthrough with zero outbound traffic.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-30T15:34:00Z (worktree spawn after Wave 2 merge)
- **Completed:** 2026-04-30T15:42:00Z (after Task 3 commit `9731168`)
- **Tasks:** 3 (Task 1: scaffold + OFFLINE_DEMO branch; Task 2: full _moderate_real; Task 3: REDACT_KEYS extension)
- **Files created:** 1 (`backend/pipeline/moderate.py`, 610 lines)
- **Files modified:** 1 (`backend/observability/anonymity.py`, +5 lines)

## Accomplishments

- **Module scaffolded with locked SYSTEM_PROMPT (Task 1).** The verbatim prompt from RESEARCH.md "Recommended SYSTEM_PROMPT" landed in `backend/pipeline/moderate.py` lines 44-94, ending with the load-bearing line `Return ONLY the JSON object. No prose, no markdown fences, no commentary.` PROMPT_VERSION='1.0.0' is a module-level constant; HARD_BLOCK_CATEGORIES = `('csam', 'sexual', 'extremist', 'self_harm')` and SOFT_FLAG_CATEGORIES = `('hate', 'violence')` are tuples (immutable, ordered for csam-precedence).
- **ModerationResponse TypedDict + ModerationResult dataclass declared.** TypedDict feeds Gemini's `response_schema=ModerationResponse` (server-side schema enforcement); dataclass is the public return shape with `decision`, `provider`, `reason`, `raw_response`, `latency_ms`, `embed_result`, `soft_flag_categories` fields.
- **OFFLINE_DEMO=true short-circuit at function entry (Task 1).** `if config.OFFLINE_DEMO:` gates the entire real path; writes one `moderation_decisions` row with `provider='stub'`, `decision='passed'`, `reason='offline_demo'`, `raw_response=None`, `latency_ms=0`, `prompt_version=None`. Verified end-to-end via async smoke test with mocked `db.write_moderation_decision` — the OFFLINE_DEMO branch hit produces zero Gemini imports and zero outbound traffic (T-11-20 mitigation).
- **_fetch_clip_bytes mirrors embed.py:113-152 (Task 2).** Blob mode streams the private blob through `httpx.AsyncClient` (singleton from `blob_client.get_client()`) into a tempfile with bearer auth + 64 KiB chunks; local mode reads `row.path` directly. Returns `(clip_bytes, local_path_for_gemini_upload)` so the caller has both the SHA-256 input AND the file handle for `client.files.upload(file=...)`.
- **_gemini_classify mirrors caption_pipeline.py:424-499 with four parameter swaps (Task 2).** `model=config.GEMINI_MODERATION_MODEL` (default `gemini-2.5-flash-lite`), `system_instruction=SYSTEM_PROMPT`, `response_schema=ModerationResponse`, `temperature=0.0`, inner `asyncio.wait_for(..., timeout=config.MODERATION_MAX_BUDGET_S)`. Best-effort `client.files.delete(name=uploaded.name)` cleanup runs in `finally` regardless of generate_content outcome (PRIV-03 — no Gemini-side artifacts persist).
- **Parallel embed + gemini via asyncio.wait FIRST_COMPLETED (Task 2).** Three branches:
  - **Branch A (embed-first):** cancel + drain gemini → `decision='blocked'`, `reason='classifier_timeout'` (D-03 cancel-when-embed-finishes).
  - **Branch B (gemini-first):** drain embed → inspect `gemini_task.exception()` → `_classify_exception` ladder OR `_route_verdict(parsed)` on success.
  - **Branch C (max-budget):** outer `timeout=config.MODERATION_MAX_BUDGET_S` exceeded → cancel both, drain both → `decision='blocked'`, `reason='max_budget_exceeded'`.
- **Typed-exception ladder per D-05 (Task 2).** `_classify_exception(exc)`:
  - `asyncio.TimeoutError` → `('blocked', 'classifier_timeout')`
  - `httpx.HTTPStatusError` 4xx → `('blocked', f'classifier_4xx_{status}')`
  - `httpx.HTTPStatusError` 5xx → `('unknown', f'classifier_5xx_{status}')`
  - `httpx.ConnectError|ReadError|TransportError` → `('unknown', 'classifier_network_error')`
  - other → `('unknown', 'classifier_unknown_error')` (defense-in-depth).
- **Verdict routing precedence (Task 2).** `_route_verdict(parsed)` walks `HARD_BLOCK_CATEGORIES` first (csam → sexual → extremist → self_harm); the first `verdict in ('flag', 'block')` wins → `('blocked', f'gemini_{cat}_block', [])`. Otherwise builds `soft_flag_categories` list of any `SOFT_FLAG_CATEGORIES` hit; non-empty → `('passed', f'soft_flag_{first}', list)`; else `('passed', None, [])`.
- **Hard-block side effects in correct order (Task 2 — T-11-16 mitigation).** csam-category hit (`reason == 'gemini_csam_block'`) writes `db.write_reported_csam(content_hash=_content_hash(clip_bytes), preserved_until=_one_year_from_now_unix())` BEFORE `cleanup_blocked_clip(clip_id)`. The 1-year retention (`365 * 24 * 60 * 60` seconds added to `time.time()`) discharges the 2024 REPORT Act amendment to 18 U.S.C. § 2258A (D-19). All hard-blocks (regardless of category) call `cleanup_blocked_clip(clip_id)` after the audit row write — the cleanup is idempotent (Phase 10 guarantee), so a hash-write failure followed by a retry doesn't double-delete.
- **Unknown side effects (Task 2 — MOD-05).** `decision='unknown'` writes the audit row AND `db.set_clip_hidden(clip_id, hidden=True)` so the clip can't surface in the feed while Plan 05's `aggregate_verdict('unknown')` short-circuits clustering.
- **Defense-in-depth fallback (Task 2).** The entire `_moderate_real` body is wrapped in `try/except Exception`; any unhandled exception writes `decision='unknown'`, `reason='classifier_unknown_error'` AND calls `set_clip_hidden(True)` so a malformed clip / DB hiccup / SDK regression cannot leak past the gate.
- **REDACT_KEYS extended by exactly 2 entries (Task 3 — D-27 reconciled).** `backend/observability/anonymity.py:18-29` now includes `raw_response` and `prompt_version`. The `_scrub` recursion at lines 35-52 already handles arbitrary nested dicts; verified via round-trip test that `{'raw_response': {'csam': {'verdict': 'block'}}, 'prompt_version': '1.0.0', 'safe': 'value'}` → `{'raw_response': '[REDACTED]', 'prompt_version': '[REDACTED]', 'safe': 'value'}`. `csam_hash` is intentionally absent per the 2026-04-29 reconciliation (no separate hash field exists in classifier-only mode).

## Task Commits

| Task | Name                                                                                       | Commit    | Files                                            |
| ---- | ------------------------------------------------------------------------------------------ | --------- | ------------------------------------------------ |
| 1    | Scaffold moderate.py — constants, ModerationResult, OFFLINE_DEMO short-circuit             | `8dd2331` | `backend/pipeline/moderate.py` (new, 223 lines)  |
| 2    | Implement _moderate_real — parallel embed/gemini, verdict routing, hard-block side effects | `b988b86` | `backend/pipeline/moderate.py` (+390/-3)         |
| 3    | Extend REDACT_KEYS with raw_response + prompt_version (D-27)                               | `9731168` | `backend/observability/anonymity.py` (+5)        |

## Files Created/Modified

- `backend/pipeline/moderate.py` — **NEW**, 610 lines. Public surface: `moderate_clip(clip_id) -> ModerationResult`, `SYSTEM_PROMPT`, `PROMPT_VERSION`, `ModerationResponse` (TypedDict), `ModerationResult` (dataclass), `HARD_BLOCK_CATEGORIES`, `SOFT_FLAG_CATEGORIES`. Private helpers: `_fetch_clip_bytes`, `_gemini_classify`, `_route_verdict`, `_classify_exception`, `_drain_task`, `_content_hash`, `_strip_anonymity_metadata`, `_now_unix`, `_one_year_from_now_unix`.
- `backend/observability/anonymity.py` — REDACT_KEYS frozenset extended from 4 to 6 entries; original 4 (session_uuid, gps_lat, gps_lng, blob_url) untouched; new 2 (raw_response, prompt_version) appended with a section comment citing D-27.

## Decisions Made

- **Defense-in-depth fallback writes a moderation_decisions row before returning.** The plan's `<action>` step 11 wrote "any unhandled exception falls through to a `decision='unknown'` write" — we strengthened that to ALSO call `set_clip_hidden(True)` so Plan 05's `aggregate_verdict` cannot return `'passed'` for a clip whose moderate_clip threw. Same defense as the inline `decision='unknown'` branch — kept symmetric.
- **Local-mode clip path is never unlinked by moderate.py.** `_fetch_clip_bytes` returns the local row.path directly in local mode (no temp file). The `finally` block of `_moderate_real` only unlinks when `blob_tempfile_to_unlink` is set (blob-mode streamed copy). Deleting the canonical row.path would race with `cleanup_blocked_clip` and destroy the source file before the SHA-256 hash is persisted. Mirrors the equivalent finally-block discipline in `embed_worker:188-190` and `caption_pipeline.py:506-514`.
- **_gemini_classify raises httpx.ConnectError on missing GEMINI_API_KEY.** Routes empty-key into the network-error tier of `_classify_exception` → `decision='unknown'` (not `'blocked'`) — the safest default when we don't know if the clip is safe. The OFFLINE_DEMO short-circuit upstream prevents this branch from firing in the demo path; the missing-key branch only matters in the live-misconfigured production case where it correctly fails-safe to hidden-but-not-deleted.
- **Branch A captures embed_result even though it's discarded.** Embed-first cancel-when-embed-finishes always blocks the clip (decision='blocked'), so the dataclass field `embed_result=embed_result if decision == "passed" else None` resolves to None. We still capture `embed_task.result()` for symmetry with Branch B and to make Plan 05 wiring trivially refactorable if cancel-when-embed-finishes ever becomes a soft-block instead.
- **No new STAGE_DURATION enumeration in metrics.py.** The labelname `stage` accepts arbitrary strings; the docstring at `backend/observability/metrics.py:46` lists `ingest|embed|cluster|compile|stitch` but is not a runtime constraint. moderate uses `STAGE_DURATION.labels(stage="moderate")` and the histogram bucket boundaries (already covering 0.05s → 300s) are appropriate for a 20s budget. Updating the docstring is deferred to Phase 13 observability deepening.

## Deviations from Plan

**None — plan executed exactly as written.** No Rule 1 (bug fix), Rule 2 (missing critical functionality), Rule 3 (blocking issue), or Rule 4 (architectural change) deviations were triggered. Every grep check from the plan's `<acceptance_criteria>` passes; every behavior smoke test (constants, `_route_verdict` precedence, `_classify_exception` mapping, OFFLINE_DEMO short-circuit, `_scrub` round-trip) passes.

The plan's `cd backend && python -c "from pipeline.moderate import ..."` invocation form does not work in this codebase (relative imports require running from the repo root with `from backend.pipeline.moderate import ...`). The 11-03 SUMMARY documents the same — both backends use repo-root imports throughout. Functionally equivalent; grep-based acceptance checks all pass against file contents regardless of which form runs the smoke.

## Acceptance Criteria

All acceptance criteria from `<acceptance_criteria>` pass:

**Task 1:**
- ✅ `test -f backend/pipeline/moderate.py` — file exists.
- ✅ `python -m py_compile backend/pipeline/moderate.py` — exits 0.
- ✅ Constants: `PROMPT_VERSION == '1.0.0'`, `HARD_BLOCK_CATEGORIES == ('csam', 'sexual', 'extremist', 'self_harm')`, `SOFT_FLAG_CATEGORIES == ('hate', 'violence')`.
- ✅ `grep -q '^PROMPT_VERSION = "1.0.0"$'` exits 0.
- ✅ `grep -q "Return ONLY the JSON object"` exits 0 (verbatim final SYSTEM_PROMPT line).
- ✅ `grep -q "if config.OFFLINE_DEMO:"`, `grep -q 'provider="stub"'`, `grep -q 'reason="offline_demo"'`, `grep -q "hashlib.sha256"`, `grep -q "365 \* 24 \* 60 \* 60"`, `grep -q "from ..storage import cleanup_blocked_clip"` — all exit 0.

**Task 2:**
- ✅ `python -m py_compile` — exits 0.
- ✅ All 23 grep patterns pass (asyncio.wait, FIRST_COMPLETED, asyncio.create_task(embed_worker, _gemini_classify, asyncio.CancelledError, httpx.HTTPStatusError, httpx.ConnectError|httpx.ReadError|httpx.TransportError, classifier_timeout, classifier_5xx, classifier_4xx, classifier_network_error, max_budget_exceeded, gemini_csam_block, soft_flag_, db.write_moderation_decision, db.write_reported_csam, cleanup_blocked_clip(clip_id), db.set_clip_hidden(clip_id, config.GEMINI_MODERATION_MODEL, config.MODERATION_MAX_BUDGET_S, system_instruction=SYSTEM_PROMPT, response_schema=ModerationResponse, temperature=0.0, client.files.delete).
- ✅ No `raise NotImplementedError` remains (Task 1 stub fully replaced).
- ✅ `_gemini_classify`, `_route_verdict`, `_content_hash`, `moderate_clip`, `_classify_exception`, `_drain_task`, `_moderate_real`, `_fetch_clip_bytes` all callable.

**Task 3:**
- ✅ `grep -q '"raw_response",'` and `grep -q '"prompt_version",'` exit 0.
- ✅ `grep -q "csam_hash"` returns 0 lines (D-27 reconciliation honored).
- ✅ Behavior round-trip: `_scrub({'raw_response': {...}, 'prompt_version': '1.0.0', 'safe': 'v'})` → `{'raw_response': '[REDACTED]', 'prompt_version': '[REDACTED]', 'safe': 'v'}`.

## Verification

- ✅ `python -m py_compile backend/pipeline/moderate.py backend/observability/anonymity.py` exits 0.
- ✅ `from backend.pipeline.moderate import moderate_clip, SYSTEM_PROMPT, PROMPT_VERSION, ModerationResult, HARD_BLOCK_CATEGORIES, SOFT_FLAG_CATEGORIES, _gemini_classify, _route_verdict, _content_hash` succeeds.
- ✅ `from backend.observability.anonymity import REDACT_KEYS; assert {'raw_response', 'prompt_version'} <= REDACT_KEYS` succeeds.
- ✅ All grep checks in acceptance criteria pass.
- ✅ Behavior smoke (OFFLINE_DEMO end-to-end with mocked db.write_moderation_decision) confirms: passthrough decision='passed', provider='stub', reason='offline_demo', single audit row written, raw_response=None, latency_ms=0, prompt_version=None.
- ✅ `_route_verdict` precedence verified: all-pass → ('passed', None, []); csam-block → ('blocked', 'gemini_csam_block', []); hate-flag-only → ('passed', 'soft_flag_hate', ['hate']).
- ✅ `_classify_exception` mapping verified: TimeoutError → blocked/classifier_timeout; 429 → blocked; 503 → unknown; ConnectError → unknown/classifier_network_error.
- (Plan 07 owns the full integration test suite — respx-mocked Gemini, behavioral tests for all branches, OFFLINE_DEMO zero-egress verification, csam-hit ordering verification, idempotency tests.)

## Threat Model Coverage

All `<threat_model>` threats with `mitigate` disposition are addressed:

- **T-11-13 (PRIV-03 violation — outbound metadata leak):** SDK pathway uses `client.files.upload(file=...)` + `system_instruction=SYSTEM_PROMPT` + `USER_PROMPT="Classify this clip per the locked taxonomy."` — no session_uuid / gps / timestamp ever serialized into the request body. `_strip_anonymity_metadata` defense-in-depth helper exists for any future code path that constructs a request body manually. Plan 07 will assert via respx inspection.
- **T-11-14 (raw_response leakage via Sentry):** Task 3 added `raw_response` + `prompt_version` to REDACT_KEYS. `_scrub` recursion handles arbitrary nesting. Structured INFO log at `_moderate_real:end` deliberately omits both fields (D-26 / L-10).
- **T-11-15 (concurrent race-write on (clip_id, provider)):** Plan 03's `db.write_moderation_decision` uses `ON CONFLICT(clip_id, provider) DO UPDATE` — verified at the SQL boundary in 11-03-SUMMARY runtime smoke. moderate.py never bypasses the dispatcher.
- **T-11-16 (audit-trail ordering on csam-hit):** `_moderate_real` Stage 7 explicitly calls `db.write_reported_csam(...)` BEFORE `cleanup_blocked_clip(clip_id)` so the SHA-256 hash is persisted while the bytes are still readable. Plan 07 will verify with a csam-hit fixture + DB row count assertion.
- **T-11-17 (DoS via Gemini hang):** `asyncio.wait(..., timeout=config.MODERATION_MAX_BUDGET_S)` outer cap (default 20s) + cancel-when-embed-finishes inner ceiling. Both arms cancelled + drained on max-budget; decision='blocked' with reason='max_budget_exceeded'.
- **T-11-18 (malformed Gemini JSON):** `response_schema=ModerationResponse` enforced server-side; if parsing still fails (json.loads raises), the catch falls into the typed-exception ladder → `decision='unknown'`. Confirmed by the defense-in-depth try/except wrapper.
- **T-11-19 (classifier-evasion attack):** Disposition is `accept` per the plan; partial mitigation via SOFT_FLAG_CATEGORIES tap-to-view interstitial (downstream Plan 06 + frontend); full mitigation requires post-pilot real CSAM hash vendor + Phase 12 reactive reporting.
- **T-11-20 (OFFLINE_DEMO accidentally hits live Gemini):** Function-entry short-circuit `if config.OFFLINE_DEMO: ...; return ...` returns BEFORE any SDK client is constructed. Verified by behavior smoke: zero `genai` imports under the OFFLINE_DEMO path, single audit row written, mock `db.write_moderation_decision` called once with `provider='stub'`.

## Deferred Issues

- **None within Plan 04 scope.** Plan 05 wires `moderate_clip` into `run_pipeline`; Plan 06 reads the decisions in `compile.py`; Plan 07 lands the integration test suite (respx-mock Gemini, behavior tests, csam-ordering verification, OFFLINE_DEMO zero-egress).
- **(Pre-existing, out-of-scope)** SQLite SCHEMA_SQL doesn't declare `moderation_decisions` / `reported_csam` / `clips.is_hidden` — calling moderate.py against an OFFLINE_DEMO=true SQLite DB will fail at the SQL boundary. Tracked in 11-03-SUMMARY "Deferred Issues" + STATE.md "Pending Todos" (SQLite-backend retirement). The OFFLINE_DEMO short-circuit in moderate.py writes provider='stub' which still hits `db.write_moderation_decision` — so a true OFFLINE_DEMO end-to-end smoke against SQLite would fail at that write. Plan 11 path requires Postgres or the SQLite SCHEMA_SQL extension.

## Threat Flags

None — no security-relevant surface introduced beyond the threat model's already-enumerated boundaries (Gemini API egress, DB writes, Sentry boundary). All new code paths are explicitly in the threat register.

## Self-Check: PASSED

Verified post-write:

- `backend/pipeline/moderate.py` — FOUND (created; 610 lines; all listed exports importable from `backend.pipeline.moderate`).
- `backend/observability/anonymity.py` — FOUND (modified; REDACT_KEYS contains 6 entries including raw_response + prompt_version, no csam_hash).
- Commit `8dd2331` (Task 1 scaffold) — FOUND in `git log --oneline`.
- Commit `b988b86` (Task 2 _moderate_real) — FOUND in `git log --oneline`.
- Commit `9731168` (Task 3 REDACT_KEYS) — FOUND in `git log --oneline`.
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-04-SUMMARY.md` — created at this path.
- All grep + import + py_compile + behavior smoke checks pass.
- OFFLINE_DEMO short-circuit verified end-to-end (mocked db write, zero Gemini imports, single audit row).
- `_route_verdict` precedence + `_classify_exception` typed mapping verified inline.
- `_scrub` round-trip on raw_response + prompt_version verified (round-trips to `[REDACTED]`).

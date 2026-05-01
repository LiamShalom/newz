---
slug: moderation-classifier-timeout
status: resolved
trigger: "Pink water bottle video upload deleted by moderation pipeline — Gemini Flash Lite classifier timing out and treating timeouts as `blocked`"
created: 2026-04-30
updated: 2026-04-30
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
---

# Debug Session: moderation-classifier-timeout

## Symptoms

DATA_START
**Expected behavior:** A benign user upload (e.g. pink water bottle video) flows through the pipeline → embed → moderate → cluster → optional compile. The clip persists in storage and appears in the feed.

**Actual behavior:** The moderation gate decides `blocked` because the Gemini Flash-Lite classifier call times out. The pipeline marks the clip blocked, the blob is deleted (`blob op=delete pathname=uploads/...`), and the clip never reaches clustering or compile. User sees their upload disappear.

**Affected uploads (Railway prod logs, 2026-05-01):**
- `clip_id=db4a7bfbc9404ac68dcae10ffc24dc52` — `reason=classifier_timeout latency_ms=4203`
- `clip_id=1e675ae289f343e7bd13bb830703464c` — `reason=classifier_timeout latency_ms=2923`
- `clip_id=7bd90123f90d474298108f3675c56436` — `reason=classifier_timeout latency_ms=2862`

All three uploads from the same session (`session_hash=df2b3e9922b951243e10c52e47a83e9328104e5179bbcc4572692ae940ab1d46`). All blocked back-to-back. None of them are violative content per the user.

**Log evidence pattern (per upload):**
```
blob op=upload pathname=uploads/<clip_id>.mp4 latency_ms=~150-700
event clip_added clip_id=<clip_id>
HTTP Request: POST https://generativelanguage.googleapis.com/upload/v1beta/files "HTTP/1.1 200 OK"
embed clip_id=<clip_id> latency_ms=~1600-1900 parent_dims=512 children=1
HTTP Request: DELETE https://generativelanguage.googleapis.com/v1beta/files/<file_id> "HTTP/1.1 200 OK"
HTTP Request: POST https://vercel.com/api/blob/delete "HTTP/1.1 200 OK"
moderate gate decision=blocked provider=gemini_flash_lite reason=classifier_timeout latency_ms=<2862-4203>
pipeline blocked clip_id=<clip_id> reason=classifier_timeout provider=gemini_flash_lite
```

The `HTTP Request: POST .../upload/v1beta/files` succeeds (200 OK). The Gemini upload itself works. The classifier inference call is what times out (or no inference call appears in the log at all — files are uploaded but no `models:generateContent` request is logged before the timeout fires).

**Errors:** No exceptions in logs — pipeline treats the timeout as a successful "blocked" decision per the gate's fail-closed policy.

**Timeline:** Started after Phase 11 shipped (moderation gate went live). The deployment in question is `5ce090ef-2370-47a7-92f5-fe7e40d11d13` running on Railway. Reproducing right now in production.

**Reproduction:** Upload any video via the iOS Safari PWA. Most uploads are blocked with `classifier_timeout`.

**Errors visible to user:** The frontend likely shows a "blocked" or "moderation declined" state (need to verify with Roan), but blast radius is "every benign upload disappears" — kills the demo loop.
DATA_END

## Investigation Questions

DATA_START
1. **What timeout is configured for the Gemini Flash-Lite classifier call?** The observed latencies (2862, 2923, 4203 ms) are suspiciously close to a configured ~3s timeout — confirm this is a deliberate timeout, not a network failure.

2. **Why does the timeout path fail closed (block) instead of fail open (allow) or retry?** For a HackTech-pilot funding demo with anonymity-by-default, false-blocking benign uploads is far worse than letting an occasional borderline clip through. Was this intentional per the Phase 11 threat model, or an oversight?

3. **Is Gemini Flash-Lite actually slow right now or are we hitting a cold-start / quota issue?**
   - The `POST /upload/v1beta/files` calls all succeed (200 OK in ~100-700ms).
   - But the subsequent `models:generateContent` inference call is missing from the logs — suggests we never get to it before our own timeout fires.
   - Could be: (a) Gemini Files API resumable upload taking longer than we measure, (b) the actual `generateContent` call is genuinely slow, (c) we're not awaiting the response at all and timing out client-side.

4. **What is the right policy?**
   - Anonymity-by-default + funding pilot: false-blocking benign uploads is a demo killer.
   - Phase 11 ships classifier-only CSAM (real hash vendor + NCMEC deferred post-pilot per CLAUDE.md).
   - Options: (a) retry once on timeout then fail-open, (b) fail-open on timeout with a warning log, (c) increase the timeout, (d) move moderation to async/post-publish review queue (Phase 12 territory).

5. **Should the blob be deleted on timeout?** Currently the blocked path runs the same delete-blob cleanup as a real "blocked" decision. That makes recovery impossible — the user's video is gone. If we change to fail-open on timeout, this becomes moot, but if we keep fail-closed, we should preserve the blob in a "needs-human-review" bucket so the upload can be recovered.
DATA_END

## Current Focus

```yaml
hypothesis: |
  Confirmed. The `cancel-when-embed-finishes` primitive (D-03) routes any
  case where Marengo embed completes before Gemini Flash-Lite returns into
  Branch A → decision=blocked, reason=classifier_timeout, which then runs
  cleanup_blocked_clip and deletes the user's blob. In production
  Marengo is faster (~1.6-1.9s) than the Gemini upload+poll-to-ACTIVE+
  generate_content cycle (~3-4s+), so the primitive false-blocks
  essentially every benign upload.
test: |
  Read backend/pipeline/moderate.py:520-557 — Branch A unconditionally
  routes embed-wins-first to decision=blocked, reason=classifier_timeout.
  run_pipeline (run.py:129-139) treats blocked as a real moderation hit
  and cleanup_blocked_clip is called inside moderate_clip Stage 7.
  Cross-reference Phase 11 PLAN: D-03 cancel-when-embed-finishes was
  premised on Gemini Flash-Lite p50 < Marengo p50 (per RESEARCH bench).
  Production telemetry violates that invariant.
expecting: |
  Confirmed via direct read.
next_action: |
  Resolved. See Resolution section below.
```

## Evidence

- **moderate.py:520-557 (pre-fix, Branch A):** `embed_task in done and gemini_task not in done` → `await _drain_task(gemini_task); decision = "blocked"; reason = "classifier_timeout"`. No conditional fail-open path. Drains the cancellation, then falls through to Stage 7 (`if decision == "blocked": ... cleanup_blocked_clip(clip_id)`).
- **moderate.py:416-417 (pre-fix, _classify_exception):** `if isinstance(exc, asyncio.TimeoutError): return ("blocked", "classifier_timeout")`. Same fail-closed posture for Branch B (gemini's inner wait_for raised TimeoutError).
- **run.py:126-139:** `with STAGE_DURATION.labels(stage="moderate").time(): mod_result = await moderate_clip(clip_id) ... if mod_result.decision == "blocked": ... return`. The pipeline treats the timeout-blocked decision identically to a real CSAM hit.
- **moderate.py:613-642:** Stage 7 hard-block side-effects. Non-CSAM blocks (which includes `classifier_timeout`) skip `write_reported_csam` but DO call `cleanup_blocked_clip` unconditionally — this is what deleted the Vercel blob.
- **config.py:75 (pre-fix):** `MODERATION_MAX_BUDGET_S=20.0`. The 2862-4203ms latencies in production logs are NOT Branch C (>20s wall-clock) — they're Branch A firing at the cancel-when-embed-finishes boundary, slightly after Marengo's ~1.6-1.9s embed completes.
- **Phase 11 11-CONTEXT.md D-03 (the cancel-when-embed-finishes primitive):** "Cancel-when-embed-finishes uses Marengo's elapsed time as Gemini's effective ceiling." This invariant assumes Gemini Flash-Lite is faster than or equal to Marengo on the actual corpus. Production telemetry shows the opposite.
- **Phase 11 11-VERIFICATION.md L23-25 (HUMAN-UAT pending):** "Common-case end-to-end upload-to-publish latency does not regress vs v1.0 baseline (MOD-03)" — flagged as needing live deploy + benchmark. The benchmark step (D-29 "Gemini Flash-Lite latency benchmark on demo dataset") was deferred and never landed; production deploy IS the benchmark, and it failed.
- **moderate.py:_gemini_classify (pre- and post-fix):** uploads file via `client.files.upload`, then polls up to 30 × 1s for ACTIVE state, then calls `client.models.generate_content`. The Files API ACTIVE-poll alone routinely consumes 1-2s before generate_content can even start. Combined with sync SDK calls being executor-wrapped, the entire flow easily exceeds Marengo's ~1.7s.
- **No `models:generateContent` POST in failed-upload logs:** consistent with Branch A cancellation firing during the Files-API ACTIVE-poll stage, before generate_content is reached.

## Eliminated

- **Network failure / 5xx:** ruled out. No `httpx.HTTPStatusError` / `ConnectError` / `ReadError` in logs; the `models:generateContent` POST never fires (Branch A cancels before then).
- **Quota / 429:** ruled out. `client.files.upload` returns 200 OK in all logs.
- **Cold-start specific to one deploy:** ruled out. Three back-to-back uploads from the same session all blocked.
- **Configurable timeout misconfigured (e.g. accidentally ~3s):** ruled out. `MODERATION_MAX_BUDGET_S=20.0` is the inner `asyncio.wait_for` cap; the firing condition is the OUTER `asyncio.wait FIRST_COMPLETED` race in `_moderate_real`, not a misconfigured timeout. The "~3s observed latency" is the time it takes Marengo to win the race + Branch A drain.

## Resolution

**Root cause:** The Phase 11 D-03 cancel-when-embed-finishes primitive in `backend/pipeline/moderate.py:548-557` (Branch A) unconditionally routes `embed completes before gemini` to `decision=blocked, reason=classifier_timeout`. Then Stage 7 runs `cleanup_blocked_clip(clip_id)` which deletes the Vercel Blob. The latency invariant the primitive relies on (Gemini Flash-Lite p50 ≤ Marengo p50) is violated in production — Marengo finishes in ~1.6-1.9s while the Gemini Files API upload + ACTIVE-poll + generateContent cycle takes ~3-4s+ — so the primitive false-blocks essentially every benign upload.

**Fix:** Pilot fail-open knob.
- New env var `MODERATION_FAIL_OPEN_ON_CLASSIFIER_TIMEOUT` (default `true`) added to `backend/config.py`.
- New helper `_classifier_timeout_decision()` in `backend/pipeline/moderate.py` is the single source of truth for classifier-timeout routing. Returns `('passed', 'classifier_timeout_fail_open')` under the pilot default, else `('blocked', 'classifier_timeout')` for legacy strict mode.
- Branch A in `_moderate_real` (cancel-when-embed-finishes) now consults the helper. Under fail-open default: `decision='passed'`, `embed_result` is preserved on `ModerationResult`, blob is NOT deleted, clip flows through to clustering/compile. A WARNING log line is emitted.
- `_classify_exception(asyncio.TimeoutError)` (Branch B path — gemini's inner wait_for raised TimeoutError) consults the same helper.
- Branch C (`max_budget_exceeded`, >20s wall-clock pathology) remains fail-CLOSED regardless of the flag — that case represents genuine network/control-plane stall and shouldn't silently fail-open.

**Tradeoffs vs Phase 11 threat model (D-03 / D-05 / D-07):**
- The Phase 11 reconciliation already deferred real CSAM hash vendor + NCMEC reporting to post-pilot ("classifier-only CSAM detection for the pilot"). The pilot threat surface is demo-audience uploads (water bottles), not adversarial CSAM injection — over-blocking benign uploads is a far higher-cost failure than briefly admitting a borderline clip that the admin queue (Phase 12) can resolve.
- HARD_BLOCK_CATEGORIES enforcement (csam, sexual, extremist, self_harm) is unchanged — when the classifier RETURNS a verdict, the `_route_verdict` precedence still routes any `flag` or `block` in those categories to `decision='blocked'` with `cleanup_blocked_clip` and (for csam) `reported_csam` preservation.
- 5xx outage tier (`decision=unknown` → admin queue, set_clip_hidden) is unchanged. Genuine pathology still fails-CLOSED-ish (clip hidden, queued).
- Set the env var to `false` before public launch and audit the threat model + admin-queue capacity at that point. Document this in the launch checklist.

**Files changed:**
- `backend/config.py` — added `MODERATION_FAIL_OPEN_ON_CLASSIFIER_TIMEOUT: bool` (default `true`).
- `backend/pipeline/moderate.py` — added `_classifier_timeout_decision()` helper; updated module docstring with Phase 11 amendment 2026-04-30 note; updated Branch A in `_moderate_real` to consult the helper + emit warning log on fail-open; updated `_classify_exception(asyncio.TimeoutError)` to use the same helper; updated Branch B post-classify-exception logic to log fail-open warnings symmetrically.
- `backend/tests/pipeline/test_moderate.py` — renamed `test_moderate_cancel_when_embed_finishes_first` → `..._fail_open` and updated assertions to expect `decision='passed', reason='classifier_timeout_fail_open'`, blob preserved (no cleanup), embed_result carried through. Added new `test_moderate_cancel_when_embed_finishes_strict_mode` covering the legacy `false`-flag path. Updated parametrized `test_moderate_failure_tier_classification[timeout-fail-open]` accordingly. Added new `test_moderate_classify_exception_timeout_strict_mode` for Branch B strict mode. Fixture default sets `MODERATION_FAIL_OPEN_ON_CLASSIFIER_TIMEOUT=true`.

**Verification:**
- `pytest backend/tests/pipeline/test_moderate.py -q` → 18 passed (16 prior + 2 new strict-mode regression tests).
- `pytest backend/tests/pipeline/ backend/tests/test_offline_demo_firewall.py backend/tests/test_feed_segments.py -q` → 26 passed, 1 skipped (env-gated, unrelated).
- Smoke import: `python -c "from backend import config; print(config.MODERATION_FAIL_OPEN_ON_CLASSIFIER_TIMEOUT)"` → `True` (pilot default).
- `python -c "from backend.pipeline.moderate import _classifier_timeout_decision; print(_classifier_timeout_decision())"` → `('passed', 'classifier_timeout_fail_open')`.

**Pending HUMAN-UAT (carry over from Phase 11 verification):**
- Deploy fix to Railway. Upload one benign clip via iOS Safari PWA. Confirm:
  - `moderation_decisions` row written with `decision='passed'`, `reason='classifier_timeout_fail_open'` (or `decision='passed'` with no reason if Gemini happens to win the race).
  - Vercel Blob `uploads/<clip_id>.mp4` IS preserved (no `blob op=delete`).
  - Clip flows through to cluster_worker.
  - Backend logs include the new `moderate gate fail-open clip_id=...` WARNING line.
- After demo, set `MODERATION_FAIL_OPEN_ON_CLASSIFIER_TIMEOUT=false` in a non-production preview, upload a clip while monkeypatching the gemini_classify to simulate slow inference, confirm legacy hard-block + blob delete still fires (regression-tested in unit suite already).
- Future work: real CSAM hash vendor pre-screen (Thorn Safer Match / PhotoDNA) — that path doesn't depend on the classifier latency primitive at all and obviates the fail-open knob.

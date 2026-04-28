---
phase: 04-multi-agent-compile-real-time-feed
plan: 03
subsystem: pipeline
tags: [bugfix, performance, ffmpeg, h264, caption, gap-closure]

requires:
  - phase: 04-multi-agent-compile-real-time-feed
    provides: "compile_segment parallel-tracks shape (Track A agents + Track B stitch + Track C caption); spike 002 bench harness"
provides:
  - "stitch_clips H.264 ultrafast normalize-and-concat (~0.5-0.8s for 3 clips, vs 66.5s pre-fix)"
  - "Caption-grounding contract: Track C fallback returns None; compile.py only overwrites Track A's vision caption when source=='vision'"
  - "Place+date fallback caption template across compile.py _save_fallback_segment and seed/demo_segment.py (no more 'Multi-angle event captured')"
  - "Stitch perf smoke gate (test_stitch_clips_under_10s) + caption-grounding contract tests in test_compile.py"
  - "Spike 002 README post-fix run table documenting the speedup"
affects: ["05-demo-hardening"]

tech-stack:
  added: []
  patterns:
    - "Encoder-pinning at the call site (vcodec='libx264' + container .mp4) — not relying on container/extension to pick codec"
    - "filter_complex normalize-and-concat (scale->pad->setsar->fps per input, then concat n=N v=1 a=0) for mismatched-spec source clips"
    - "Source discriminator on multi-source results (caption_result.source=='vision') so call sites can decide whether to overwrite an upstream value"

key-files:
  created:
    - "backend/tests/test_stitch_perf.py"
  modified:
    - "backend/pipeline/stitch.py"
    - "backend/pipeline/compile.py"
    - "backend/pipeline/caption_pipeline.py"
    - "backend/seed/demo_segment.py"
    - "backend/tests/test_compile.py"
    - ".planning/spikes/002-compile-baseline/bench.py"
    - ".planning/spikes/002-compile-baseline/README.md"
    - ".planning/phases/04-multi-agent-compile-real-time-feed/04-VERIFICATION.md"

key-decisions:
  - "Encoder swap is libx264 ultrafast (not VP8/VP9 hardware) — H.264 baseline is the iOS Safari demo target's safest path; VP9 took 66s, libx264 ultrafast takes <1s"
  - "_fallback_caption returns None (not a place-only string) — minimum-viable surface change; the call site already handled None correctly via the seg.get('caption', '') fallback path"
  - "Source discriminator gate uses caption_result.get('source') == 'vision' — defends the contract even if a future _fallback_caption forgets and returns a dict"
  - "Pre-existing test_compile.py failures (3 tests broken by the Phase 4.5 reshape) auto-fixed under Rule 1 — verification step requires the suite to be green"

patterns-established:
  - "Per-input ffmpeg normalize chain: scale(W,H,force_original_aspect_ratio=decrease) -> pad -> setsar=1 -> fps(N) before concat — handles mismatched source specs without stream-copy hazards"
  - "Track-result source discriminator pattern: when multiple parallel tracks compete for the same field, tag each result with a source string and gate the final write on a known-good source"

requirements-completed:
  - CMP-06
  - CMP-08

duration: 35min
completed: 2026-04-25
---

# Phase 4 Plan 03: Runtime Gap Closure (Caption Grounding + Stitch Bottleneck) Summary

**Stitch encoder swapped from libvpx-vp9 (66.5s p50) to libx264 ultrafast normalize-and-concat (~0.8s p50, ~84x faster); Track C caption-overwrite gated on source=='vision' so Track A's vision caption survives Track C fallback; demo seed and fallback paths now emit place+date captions only.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-26T01:00 (worktree branch base, commit `e8d0cf1`)
- **Completed:** 2026-04-26T01:35Z
- **Tasks:** 9 (Tasks 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2)
- **Files modified:** 7 (1 new test file, 6 modified)

## Accomplishments

- **Stitch p50 dropped from 66512ms to 794ms** (~84× on the bench, ~127× on the direct ffmpeg call documented in `.planning/debug/stitch-clips-bottleneck.md`). 0/3 prod-cap timeouts (was 3/3).
- **Track A's vision-grounded caption now survives Track C fallback.** Track C returns `None` on Anthropic-unavailable / errors; compile.py gates the overwrite on `caption_result.get('source') == 'vision'`; the `seg.get('caption', '')` preservation path was already correct.
- **'Multi-angle event captured by …' template removed from all three sources** (`compile.py:_save_fallback_segment`, `caption_pipeline.py:_fallback_caption`, `seed/demo_segment.py`). `grep -ri 'multi-angle event captured' backend/` exits 1.
- **Output container switched .webm → .mp4** at the compile call site; downstream `video_url = /media/{name}` picks up the new extension automatically. iOS Safari demo target (CLAUDE.md hard constraint) gets H.264 mp4 + faststart.
- **6/6 tests pass** in `test_compile.py` + `test_stitch_perf.py` (3 new + 3 pre-existing repaired).
- **Spike 002 README** has a "Post-fix Run (2026-04-25)" section with the new numbers and the speedup factor.

## Task Commits

Each task was committed atomically with `--no-verify` (parallel-executor convention):

1. **Task 1.1: Rewrite `_sync_stitch` with H.264 ultrafast normalize-and-concat** — `7feeb55` (perf)
2. **Task 1.2: Switch output extension `.webm` → `.mp4`** — `fe7458f` (fix)
3. **Task 1.3: Add stitch perf smoke test** — `f119b8b` (test)
4. **Task 2.1: `_fallback_caption` returns `None`; success-path adds `source: 'vision'`** — `ffdf513` (fix)
5. **Task 2.2: Gate Track C overwrite on `source=='vision'`; rewrite `_save_fallback_segment` template** — `75d796e` (fix)
6. **Task 2.3: Replace seeded demo caption with concrete place-grounded sentence** — `2563396` (fix)
7. **Task 2.4: Caption-grounding contract tests + repair pre-existing mocks** — `c63a757` (test)
8. **Task 3.1: Re-run spike 002 bench post-fix; bench.py uses `.mp4`; README updated** — `7619a58` (perf)
9. **Task 3.2: Mark RUNTIME-CAP-01 and RUNTIME-CMP-02 closed in 04-VERIFICATION.md** — `47f012b` (docs)

Plus a follow-up commit to satisfy the `grep -ri 'multi-angle event captured' backend/` success criterion (test docstring contained the literal forbidden phrase):

- **Docstring fix** — `06644fd` (test)

## Files Created/Modified

- `backend/pipeline/stitch.py` — `_sync_stitch` rewritten as a normalize-and-concat filter graph; encoder = libx264 ultrafast; concat-demuxer + tempfile dropped; output `.mp4` (H.264 yuv420p faststart). Async wrapper signature unchanged.
- `backend/pipeline/compile.py` — output_path uses `.mp4`; `caption_result` extraction now requires `source=='vision'`; `_save_fallback_segment` caption template swapped from forbidden multi-angle phrasing to `{when} — {location}. Submitted footage from N contributor(s).`
- `backend/pipeline/caption_pipeline.py` — `_fallback_caption` returns `None`; `generate_caption` success-path returns `{caption, location, source: 'vision'}`; module + function docstrings updated to document the contract.
- `backend/seed/demo_segment.py` — caption replaced with `"Pedestrians crossing in front of Caltech campus at midday — Pasadena, CA."`. Removed `"Compiled from 3 angles"` (badge text lives in the FeedTile overlay).
- `backend/tests/test_stitch_perf.py` (NEW) — `test_stitch_clips_under_10s` smoke gate. Skips when fewer than 3 sample mp4 clips are findable.
- `backend/tests/test_compile.py` — added `test_track_c_fallback_does_not_overwrite_track_a_caption` and `test_no_multi_angle_template_in_fallback_paths`; repaired the 3 pre-existing tests that broke when `compile_segment` was reshaped into parallel tracks (mocks for `stitch_clips`, `generate_caption`, `_get_children_with_vecs`; `_save_fallback_segment` 2-arg signature).
- `.planning/spikes/002-compile-baseline/bench.py` — output_path uses `.mp4` (without this, the bench's stitch invocation silently falls back to the first clip's path because the H.264 stream cannot be muxed into a .webm container).
- `.planning/spikes/002-compile-baseline/README.md` — "Post-fix Run (2026-04-25)" section with the new numbers and speedup factor.
- `.planning/phases/04-multi-agent-compile-real-time-feed/04-VERIFICATION.md` — `closed: 2026-04-25` and `closed_in: 04-03` on both gap entries; one-line post-execution status note in the body.

## Decisions Made

- **libx264 ultrafast over VP9/VP8/HW encoders.** H.264 baseline + yuv420p + faststart is the iOS-safe demo path (CLAUDE.md hard constraint). HW encoders (videotoolbox) would need fallback paths on Linux deployment hosts; ultrafast software encode is already <1s per stitch and portable.
- **`_fallback_caption` returns `None`** (Option B from `.planning/debug/captions-multi-angle-template.md`) instead of a place-only string. Smaller surface change; call site at `compile.py:416-417` already preserved `seg.get('caption', '')` which is Track A's vision caption when `caption_result is None`.
- **Source discriminator gate** at the compile.py call site even though `_fallback_caption` returns `None` today. The `source=='vision'` check defends the contract against a future regression where `_fallback_caption` is changed back to returning a dict.
- **Pre-existing test failures auto-fixed under Rule 1.** The plan's verification step requires `pytest backend/tests/test_compile.py backend/tests/test_stitch_perf.py -v exits 0`. Three pre-existing tests were broken by commit `fd14662` (Phase 4.5 reshape) — they didn't mock the new `stitch_clips`, `generate_caption`, `_get_children_with_vecs` symbols, and one asserted the old `_save_fallback_segment(cluster_id)` 1-arg signature. Fixing them in the same commit as the new tests keeps the diff cohesive.
- **bench.py output_path .webm → .mp4** (Rule 1). Without this fix, the bench's stitch invocation silently fell back (H.264 cannot be muxed into a WebM container), producing a misleading ~120ms wall-clock that was actually the fallback-path latency rather than the encode time. The honest measurement is 794ms p50.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing test failures in `test_compile.py`**
- **Found during:** Task 2.4 (when running the new tests, the existing 3 also ran and failed)
- **Issue:** Phase 4.5 commit `fd14662` reshaped `compile_segment` into parallel tracks (added `stitch_clips`, `generate_caption`, `_get_children_with_vecs` calls) but didn't update `test_compile.py`. The 3 existing tests had `MagicMock can't be used in 'await' expression` errors and one asserted the wrong `_save_fallback_segment` signature.
- **Fix:** Added `patch("backend.pipeline.compile.stitch_clips", ...)`, `patch("...generate_caption", ...)`, and `patch("..._get_children_with_vecs", ...)` to all 3 tests. Updated the no-keyframes test's assertion to accept the 2-arg `_save_fallback_segment(cluster_id, video_url)` signature.
- **Files modified:** `backend/tests/test_compile.py`
- **Verification:** `python -m pytest backend/tests/test_compile.py backend/tests/test_stitch_perf.py -v` → 6 passed
- **Committed in:** `c63a757` (Task 2.4 commit)

**2. [Rule 1 - Bug] Spike 002 bench was silently using stitch fallback**
- **Found during:** Task 3.1 (re-running the bench)
- **Issue:** `bench.py:177` used `f"{cluster_id}_compiled.webm"` for `output_path`. After Task 1.1's H.264 swap, ffmpeg cannot mux H.264 into a WebM container, so every bench run hit the `stitch FAILED — falling back to first clip path` branch. The reported "stitch_clips" timing was the fallback-path latency (~120ms), not real encode time.
- **Fix:** Changed `bench.py:177` to use `.mp4` extension, matching the new contract from Task 1.2.
- **Files modified:** `.planning/spikes/002-compile-baseline/bench.py`
- **Verification:** Re-ran the bench: 0 stitch failures in logs; track_b p50 = 794ms (real encode time, no fallback).
- **Committed in:** `7619a58` (Task 3.1 commit)

**3. [Rule 3 - Blocking] `data/realworld-*.mp4` glob in Task 1.3 was wrong path**
- **Found during:** Task 1.3 (smoke test)
- **Issue:** Plan said to use `glob.glob('data/realworld-*.mp4')[:3]` as the sample-clip locator, but those files live at `backend/seed/demo/realworld-*.mp4`, not `data/`. A literal transcription would skip every test.
- **Fix:** Test searches multiple candidate globs (data/, backend/seed/demo/) and falls back to `pytest.skip()` if none yield 3 clips. CI safety preserved.
- **Files modified:** `backend/tests/test_stitch_perf.py`
- **Verification:** Test runs and passes locally (0.25s).
- **Committed in:** `f119b8b` (Task 1.3 commit)

**4. [Rule 1 - Bug] Forbidden phrase appeared in test docstring after Task 2.4**
- **Found during:** Final success_criteria check
- **Issue:** Test 2.4 added a docstring containing the literal `"Multi-angle event captured"` phrase to describe what the test forbids. The plan's success_criteria says `grep -ri 'multi-angle event captured' backend/` must exit 1 (zero matches). This is a borderline case — the phrase is documentation, not the template — but the success_criteria gate is explicit.
- **Fix:** Rephrased the docstring to "must NOT emit the forbidden cluster-framing template (substring check below catches it)". Functional behavior unchanged; the substring assertion below still catches regressions.
- **Files modified:** `backend/tests/test_compile.py`
- **Verification:** `grep -ri 'multi-angle event captured' backend/` exits 1.
- **Committed in:** `06644fd` (post-Task-3.2 docstring fix)

---

**Total deviations:** 4 auto-fixed (3× Rule 1 - bug, 1× Rule 3 - blocking)
**Impact on plan:** All deviations were either pre-existing bugs surfaced by the verification step (1, 2) or transcription gaps in the plan that would have caused tests to silently skip / produce misleading numbers (3). Plan substance unchanged; deviations are guard-rail fixes.

## Issues Encountered

- **Worktree branch base mismatch on startup.** ACTUAL_BASE was `1004d691...` (older main HEAD) instead of the expected `e8d0cf1...` (plan-creation HEAD). Reset hard per the worktree_branch_check protocol; verified correct after reset. Resolved by the `git reset --hard e8d0cf1...` in the first action.
- **STATE.md was modified on git stash pop.** A git stash pop after a transient debug step restored an unrelated STATE.md change (auto-edited by some other tool). Reverted via `git checkout -- .planning/STATE.md` to honor the parallel-executor rule (orchestrator owns STATE.md).
- **`ANTHROPIC_API_KEY` not set in bench env.** Track A errors fast with `caption-writer query error errors=None`; this does not affect Track B's measurement. Pre-existing condition noted in `.planning/debug/stitch-clips-bottleneck.md` — not addressed in this plan, deferred to follow-up.

## User Setup Required

None — no external service configuration required.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes introduced. Encoder swap is internal to the compile pipeline; output_path semantics (`.mp4` instead of `.webm`) flow through unchanged.

## Next Phase Readiness

- **Track B is no longer the dominant cost.** Track A (`_run_agents` orchestrator chain) is now the lever for hitting the CLAUDE.md 30s hard cap. With a real `ANTHROPIC_API_KEY`, Track A historically takes 110-120s. Phase 5 (or a follow-up plan) should consider: parallelizing sub-agents inside the orchestrator, dropping the editor stage, or replacing the SDK chain with a hand-orchestrated `query`. See spike 002 README "Pivot signals" for the full list.
- **`compile.py:391` still uses `timeout=60.0`, not 30.0.** CLAUDE.md hard cap is 30s; the headroom now exists post-stitch-fix. Consider tightening to 30s in a follow-up. Out of scope for this gap-closure plan.
- **Track A `caption-writer query error errors=None`** logged on every bench run. Separate, silent failure mode — not addressed here. Track in a follow-up debug session.
- **Reverse-geocode for `_save_fallback_segment` location.** Currently hardcoded `"Pasadena, CA"`. Defer to Phase 5 if needed.
- **Demo segment video file.** `seed/demo_segment.py` references `demo-clip-1`/`-2`/`-3`; no real `.mp4` files exist at those URLs. VERIFICATION.md notes this as a Phase 5 concern. Caption + badge render correctly without the video.

## Self-Check: PASSED

Verification of claimed artifacts:

- `backend/pipeline/stitch.py` — FOUND (modified)
- `backend/pipeline/compile.py` — FOUND (modified)
- `backend/pipeline/caption_pipeline.py` — FOUND (modified)
- `backend/seed/demo_segment.py` — FOUND (modified)
- `backend/tests/test_stitch_perf.py` — FOUND (created)
- `backend/tests/test_compile.py` — FOUND (modified)
- `.planning/spikes/002-compile-baseline/bench.py` — FOUND (modified)
- `.planning/spikes/002-compile-baseline/README.md` — FOUND (modified)
- `.planning/phases/04-multi-agent-compile-real-time-feed/04-VERIFICATION.md` — FOUND (modified)

Verification of claimed commits:

- `7feeb55` — FOUND (Task 1.1)
- `fe7458f` — FOUND (Task 1.2)
- `f119b8b` — FOUND (Task 1.3)
- `ffdf513` — FOUND (Task 2.1)
- `75d796e` — FOUND (Task 2.2)
- `2563396` — FOUND (Task 2.3)
- `c63a757` — FOUND (Task 2.4)
- `7619a58` — FOUND (Task 3.1)
- `47f012b` — FOUND (Task 3.2)
- `06644fd` — FOUND (post-3.2 docstring fix)

Verification of all success_criteria:

- `grep -ri 'multi-angle event captured' backend/` → exits 1 (no matches) — PASS
- `grep -n 'libvpx-vp9' backend/pipeline/stitch.py` → exits 1 (no matches) — PASS
- `grep -n 'libx264' backend/pipeline/stitch.py` → 2 matches — PASS
- `python -m pytest backend/tests/test_compile.py backend/tests/test_stitch_perf.py -v` → 6 passed — PASS
- Spike 002 bench `track_b (stitch_clips)` p50 = 794ms < 5000ms — PASS

---
*Phase: 04-multi-agent-compile-real-time-feed*
*Completed: 2026-04-25*

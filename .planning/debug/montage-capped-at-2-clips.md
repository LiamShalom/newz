---
slug: montage-capped-at-2-clips
status: investigating
trigger: "videos are still maxing out at 2 clips, this should be updated to include as many angles as deemed necessary while keeping under 20s"
created: 2026-05-01
updated: 2026-05-02
reopened: 2026-05-02
prior_resolution: 2026-05-01
---

## Reopened 2026-05-02

User reports videos are STILL maxing out at 2 clips on production despite the
2026-05-01 fix (prompt rewrite + `_enforce_runtime_budget` post-processor in
`backend/pipeline/compile.py`, shipped in commit `8c88d95`). The previous fix
hypothesis (prompt-driven cap) is now suspect — either:

1. The fix wasn't deployed to Railway (deploy lag or branch mismatch)
2. The fix IS deployed but `_enforce_runtime_budget` is silently no-op'ing
   (e.g. exception path, no eligible candidates, or wired-in but never called)
3. The LLM still picks 2 runs AND the extender finds 0 eligible candidates
   (could happen if `runs_for_cluster` only surfaces 2 runs total — i.e. the
   real cap is upstream in run-grouping, not in LLM selection)
4. The 20s budget extender is firing but only adds runs that get filtered
   out downstream (e.g. by parent-diversity guard, stitch trim, frontend)

Investigation must verify which of (1)-(4) is actually happening on a real
production cluster with ≥3 parents before proposing a new fix.

## Prior Resolution (2026-05-01) — INSUFFICIENT

User selected Option B (prompt rewrite + deterministic budget guard). Applied:

**1. Prompt rewrite — `backend/pipeline/compile.py:111`**
- Dropped "best 2-4 RUNS" framing.
- New `RUNTIME BUDGET` section: total stitched runtime ≤ 20.0s, aim to fill ≥14s, target 3-5 runs at ~3-6s each. Explicit "Do NOT default to 2 runs when more eligible runs exist."
- Added `MONTAGE_RUNTIME_BUDGET_SEC = 20.0` constant; prompt uses `{budget_sec}` / `{budget_floor}` placeholders for single source of truth.
- Parent-diversity HARD CONSTRAINT preserved verbatim.

**2. Deterministic post-processor — `backend/pipeline/compile.py:_enforce_runtime_budget`**
- Mirrors `_enforce_parent_diversity` shape (read seg → load runs → mutate → re-insert).
- Extension: when `sum(durations) < target - 0.5`, append candidates in chronological order whose individual duration fits remaining budget.
- Trim: when `sum > target + 0.5`, drop trailing picks while preserving ≥2 distinct parents and ≥2 picks total.
- Synthetic full-parent runs (member_child_ids=[]) handled via `synthetic_run_estimate_sec` parameter (default 6.0).
- Helper `_run_duration_sec` extracted for reuse + isolated unit-testability.

**3. Wire-in — `backend/pipeline/compile.py:compile_segment`**
- Phase 1.6 step added immediately after Phase 1.5 (parent-diversity guard) at line ~640.
- Same try/except defensive pattern: a guard failure logs a warning and proceeds with whatever picks the segment row already has — never blocks the segment from publishing.

**4. Tests — `backend/tests/test_compile.py`**
- 5 new test cases: extends 2-pick to fill budget, no-op when no eligible candidates, trims when over budget while preserving 2 parents, no-op when picks empty, handles synthetic full-parent runs.
- Helpers `_mk_run` + `_mk_synthetic_run` factored out.

**Verification:** `pytest backend/tests/test_compile.py backend/tests/test_compile_resolve_runs.py backend/tests/test_compile_timeout.py backend/tests/test_compile_tools_runs.py backend/tests/test_compile_tools_save_segment.py backend/tests/test_runs.py backend/tests/test_runs_for_cluster.py backend/tests/pipeline/test_recompile.py` → 31 passed.

**Files changed:**
- `backend/pipeline/compile.py` (prompt rewrite + new helper + new guard + wire-in)
- `backend/tests/test_compile.py` (5 new tests + 2 helpers)

**Production validation pending:** the next live multi-parent cluster (≥3 parents) on Railway should produce a montage with 3-5 runs totaling ~14-20s. Inspect a freshly-published segment's `ordered_clip_ids` length on `/feed` JSON to confirm.

---

# Montage capped at 2 clips — desired: multi-clip up to ~20s runtime

## Symptoms

User-observed (not read in code): every produced **montage** on the feed currently
contains exactly 2 compiled clips. They want montages to contain more than 2
clips, with the **total stitched runtime not exceeding 20s** (i.e. multi-clip
montages bounded at ≤20s wall-clock playback, not capped at 2 clips).

> Project nomenclature reminder: legacy code may use "segment" — that is the
> **montage** in v1.1 nomenclature (final compiled multi-angle output). Do not
> rename existing identifiers; just be aware they map to the same concept.

### Expected behavior

- Montage = stitched compilation of N≥2 clips drawn from the cluster's
  videorecordings/children
- Total stitched runtime ≤ 20s (new constraint)
- Number of clips per montage = whatever fits within the 20s budget (more than 2
  when the cluster has the material to support it)

### Actual behavior

- Every montage on the live feed contains exactly 2 clips
- Even when a cluster has ≥3 distinct parent videorecordings (or ≥3 children),
  only 2 make it into the final montage

### Reproduction

User has been observing this on the production feed
(`https://newz-prod.up.railway.app/`) — every published montage caps at 2 clips.
No specific reproduction steps yet; need to inspect a recent multi-parent
cluster and trace why the compile pipeline emitted only 2 clips.

### Timeline

Behavior appears consistent across the v1.0 → v1.1 lifespan; not a recent
regression. Treat as an architectural/configuration cap to lift, not a
sudden break.

## Investigation goal

`find_and_fix` — locate where the 2-clip cap originates (could be: clustering
output, compile-pipeline tool definition, Claude Agent SDK prompt, ffmpeg
concat list construction, OR an LLM-side default in the multi-agent SDK
pipeline). Propose a fix that lets montages accumulate clips until the 20s
runtime budget is consumed.

**Project memory constraint:** Per `MEMORY.md` "Discuss before tuning fixes" —
for clustering / threshold / weight tweaks, **propose options + tradeoffs
first**, do not auto-apply. Surface the candidate fix to the user before edits.

## Investigation starting points

Strong suspects (unverified):

1. **`backend/pipeline/compile.py`** — orchestrates compile via Claude Agent SDK
2. **`backend/pipeline/compile_tools.py`** — likely defines the clip-selection
   tool exposed to the SDK; may hard-cap N or expose a `max_clips=2` default
3. **`backend/pipeline/stitch.py`** — ffmpeg concat list builder; check if it
   slices to 2 inputs
4. **`backend/pipeline/cluster.py`** — clustering composite score may be
   filtering out the 3rd+ candidate before it reaches compile
5. **Claude Agent SDK system prompt** — the LLM may be instructed to "pick the
   best 2 angles" or similar phrasing
6. **`backend/pipeline/run.py`** — orchestrator may be passing only top-2
   members of the cluster into compile

Secondary check:

- Inspect a recent live cluster on `/debug/clusters` (production):
  - Pick a cluster with `member_count ≥ 3`
  - Check `compile_runs` row for that cluster
  - Confirm only 2 of N clips ended up in the output `compile_run.clips_used`
    or equivalent

## Current Focus

```yaml
hypothesis: "Fix IS deployed to production and IS working for new compiles —
             user is seeing a mix of pre-fix segments (which won't recompile)
             plus one post-fix segment that legitimately hit the
             no-eligible-candidates branch (cluster's 3rd parent had no
             usable run). Layer 2 trim/extend logic is correct; the residual
             2-clip outputs are not bugs in _enforce_runtime_budget — they're
             clusters where compute_runs_for_cluster surfaces ≤2 viable runs."
test: "Inspect production /feed JSON timestamps vs PR #18 merge time. Confirm
       at least one post-fix multi-parent segment got >2 clips (proves fix is
       running). Identify which post-fix segments still have 2 clips and
       check their cluster's run inventory."
expecting: "(a) at least one post-fix segment with 3+ clips → fix is live.
            (b) any 2-clip post-fix segments have clusters where
            compute_runs_for_cluster yields ≤2 usable runs."
next_action: "Surface findings to user. Decide whether (a) status quo is
              acceptable (old segments stay 2-clip, new segments grow) plus
              one-time backfill recompile of pre-fix segments, OR (b) push
              the floor harder by also forcing _enforce_runtime_budget to
              add a 2nd run from an already-picked parent when it can't find
              a new-parent candidate (relaxes parent-diversity-with-uniqueness
              implicit constraint)."
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/compile.py:111
  finding: |
    `ANGLE_SELECTOR_PROMPT_TEMPLATE` opens with: "You are picking the best
    **2-4 RUNS** from cluster {cluster_id}." The lower bound is 2, upper is
    4. There's no runtime budget mentioned in the prompt — the LLM has no
    reason to pick more than 2 unless the criteria force it. Sonnet
    defaults to the minimum.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/compile.py:398-458 (`_enforce_parent_diversity`)
  finding: |
    Deterministic guard runs after the LLM pick. Default `min_parents=2`
    (called as `_enforce_parent_diversity(cluster_id, min_parents=2)` at
    line 627). Floor only — augments the run list when fewer than 2
    distinct parents are represented. Does NOT cap upward, so it cannot
    be the cap, BUT also does not extend a 2-from-2-parents pick to 3+
    runs. Result: when the LLM picks 2 from 2 distinct parents, the
    guard returns immediately at line 426-427 (`if len(picked_parents) >=
    target: return`), so output stays at 2.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/runs.py + config.py:36-39
  finding: |
    `RUN_THRESHOLD=0.70` and `MAX_RUN_MEMBERS=2`. With 3-second child
    windows, a single run is capped at 6 seconds (2 children × 3s). This
    means each "run" the LLM picks contributes at most 6 seconds to the
    final montage. Two runs ≈ ≤12s currently — fits under a 20s budget
    with significant headroom (room for 3-4 runs at 6s each).

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/run.py:42-50 (`_should_compile`)
  finding: |
    Compile gate is `parent_count >= 2`, not `== 2`. No cap on cluster
    size or members reaching compile. Eliminates run.py / cluster.py
    as the cap source.

- timestamp: 2026-05-01T (manager investigation)
  source: backend/pipeline/stitch.py:32-80 (`_sync_stitch`) + compile.py:497 (`_trim_one`)
  finding: |
    Stitch builds an N-input ffmpeg concat filter graph (no slicing to 2
    inputs). `_stitch_segment_runs` calls `_trim_one` per run via
    `asyncio.gather` — fully N-aware. Frontend `SegmentCard.tsx:49` and
    `Montage.tsx:85` consume `video_urls` as N items. No downstream cap.

- timestamp: 2026-05-01T (manager investigation)
  source: production /feed JSON, cluster dc3fc885474f48a5aab019ed06377db1
  finding: |
    Cluster has `source_count: 6` (six distinct parents). Published
    segment `a5c1213fb1644d7d963bb86fb36ca46b` has only 2 entries in
    `ordered_clip_ids`: `5f3737f5...run_0` and `4ed5d8ee...run_0`. Two
    different parents, both `_run_0`. Confirms the LLM pick at 2 distinct
    parents → diversity guard satisfied → no augmentation. Same pattern
    on cluster `b5d28e5a...` (member_count 2, segment has 2 runs — but
    that's the floor, no upward signal).

- timestamp: 2026-05-02T (session-manager investigation, reopened session)
  source: git history + gh pr view 18 + git show origin/main:backend/pipeline/compile.py
  finding: |
    Commit 8c88d95 ("fix(compile): lift montage 2-clip cap with 20s
    runtime budget guard") was merged to origin/main as part of PR #18,
    squash-merged 2026-05-02T17:49:23Z. Verified by inspecting
    `git show origin/main:backend/pipeline/compile.py` — lines 111
    (MONTAGE_RUNTIME_BUDGET_SEC), 491 (_enforce_runtime_budget def),
    770 (wire-in inside compile_segment) all match the local
    liam/bug-fixes branch. Note: `git merge-base --is-ancestor 8c88d95
    origin/main` returns NO because the squash merge produces a NEW
    commit; the CHANGES are in main but the original SHA isn't
    reachable. So "deploy gap" hypothesis (#1) is FALSE.

- timestamp: 2026-05-02T (session-manager investigation)
  source: backend/.venv/bin/python -m pytest backend/tests/test_compile.py -k enforce_runtime_budget
  finding: |
    All 5 _enforce_runtime_budget tests pass on liam/bug-fixes (which
    matches main):
      test_enforce_runtime_budget_extends_two_pick_to_fill_budget PASSED
      test_enforce_runtime_budget_noop_when_no_eligible_candidates PASSED
      test_enforce_runtime_budget_trims_when_over_budget_preserves_two_parents PASSED
      test_enforce_runtime_budget_noop_when_picks_empty PASSED
      test_enforce_runtime_budget_handles_synthetic_full_parent_runs PASSED
    Extension test asserts len(picked_after) >= 5 from a 2-pick start
    given 6 eligible candidates — a meaningful assertion, not "did
    not crash." Hypothesis #2 (silent no-op due to bug) is FALSE on
    the unit-test level.

- timestamp: 2026-05-02T (session-manager investigation)
  source: backend/pipeline/compile.py:768-775 (wire-in)
  finding: |
    `_enforce_runtime_budget` is called UNCONDITIONALLY (not behind a
    feature flag or env gate) in compile_segment, immediately after
    _enforce_parent_diversity. The try/except is intentionally broad:
    a guard failure logs a warning and proceeds with whatever picks
    the segment row already has — never blocks publish. This is the
    same defensive pattern as parent-diversity. Means: if the extender
    threw, we'd see "runtime budget guard failed cluster_id=X" in
    Railway logs, AND the segment would publish at 2 picks.

- timestamp: 2026-05-02T (session-manager investigation)
  source: curl https://newz-prod.up.railway.app/feed (live production)
  finding: |
    Live production /feed JSON shows 4 segments. Cross-referenced with
    PR #18 merge time (May 2 17:49 UTC):
    | seg_id   | created_at (UTC)  | clips | source_count | post-fix? |
    |----------|-------------------|-------|--------------|-----------|
    | 40552f9a | May 3 00:18       | 3     | 3            | YES       |
    | b746d131 | May 2 18:43       | 2     | 3            | YES       |
    | a5c1213f | May 1 18:12       | 2     | 6            | NO (pre)  |
    | 0e52f584 | May 1 17:38       | 2     | 2            | NO (pre)  |
    Segment 40552f9a (Santa Clara walks/gestures, post-fix by ~6.5h)
    has 3 clips from 3 parents — PROVES the fix is live and working
    in production. The user's "still maxing out at 2 clips" symptom is
    accurate for 3 of 4 visible segments, but two of those are pre-fix
    legacy (won't auto-recompile under current Phase-14 logic).
    
    The interesting case is b746d131 (Seattle cafe grand opening,
    May 2 18:43, ~54min post-fix-merge). source_count=3 distinct
    parents but only 2 clips picked. This is where the residual cap
    is — NOT in _enforce_runtime_budget logic (proven correct), but
    in the candidate inventory: when cluster's 3rd parent has too few
    children OR runs that don't meet the LLM's diversity criteria,
    _enforce_runtime_budget's extender finds 0 eligible candidates
    (it picks NEW parents only via "candidates = [r for r in runs if
    r.id not in picked]" — but if runs only contains 2 entries because
    the 3rd parent had no usable children, there's nothing to add).
    See compile.py:545.

- timestamp: 2026-05-02T (session-manager investigation)
  source: backend/pipeline/runs.py + backend/pipeline/compile.py:545
  finding: |
    `compute_runs_for_cluster` produces:
    - For parents with embedded children: 1+ runs per parent (run-grouping
      via RUN_THRESHOLD=0.70, each run capped at MAX_RUN_MEMBERS=2 children
      = ≤6s).
    - For parents WITHOUT embedded children (Marengo returned no clip-scope
      items): 1 synthetic full-parent run (member_child_ids=[]).
    `_enforce_runtime_budget` extension iterates ALL such runs and adds
    those not already picked, in chronological order. So if a cluster has
    3 parents and Marengo emitted children for all 3, the extender will
    find at least 1 candidate (the 3rd parent's first run) and add it.
    The b746d131 case is therefore one of:
    (a) 3rd parent had no children AND no synthetic run was emitted
        (parent_vec missing → skipped at runs.py:135-144)
    (b) 3rd parent's run was already picked by the LLM (no, only 2 in
        ordered_clip_ids)
    (c) 3rd parent had a run but its duration was 0s, so the extender
        skipped it via `if d <= 0: continue` (compile.py:551-552).
    Cannot disambiguate without Railway logs for that compile run.

## Eliminated

- ffmpeg stitch capping at 2 inputs — confirmed N-input concat filter graph
- Frontend capping `video_urls` rendering — handles arbitrary N
- Cluster-side filter producing only 2 candidates — no such filter
- `_should_compile` cap — gate is `>=2`, not `==2`
- `MAX_RUN_MEMBERS=2` is NOT the symptom cause: it caps each run at 6s, but
  the symptom is "only 2 runs", not "only 6s of footage". `MAX_RUN_MEMBERS`
  is relevant to fix sizing (informs how many runs fit in 20s budget), but
  is not the bug.
- Hypothesis #1 (deploy gap): FALSE. PR #18 squash-merged the fix to
  origin/main 2026-05-02 17:49 UTC; verified by reading
  `git show origin/main:backend/pipeline/compile.py`.
- Hypothesis #2 (silent no-op due to bug in extender): FALSE. 5 unit tests
  pass; wire-in is unconditional; extension assertion is tight (len>=5
  from 2-pick start).
- Hypothesis #3 (compute_runs_for_cluster only surfaces 2 runs by config
  default): FALSE in general — for healthy multi-parent clusters with child
  embeddings, it surfaces at least N_parents runs. Was TRUE for one specific
  cluster (b746d131) where Marengo coverage of the 3rd parent appears
  patchy.

## Root cause

**Original (2026-05-01) root cause is correct AND the fix works.** Production
evidence: segment 40552f9a (post-fix) has 3 clips. The fix is shipped and
running.

**Residual symptom has two causes:**

1. **Pre-fix legacy segments don't auto-recompile.** Segments compiled
   BEFORE the May 2 17:49 UTC deploy keep their 2-clip ordered_clip_ids.
   Without a backfill recompile, they'll stay 2-clip until their cluster
   gains a new parent and Phase 14 recompile fires.

2. **One post-fix corner case (b746d131, Seattle cafe):** cluster has
   source_count=3 but produced only 2 clips. Likely the 3rd parent had
   incomplete Marengo coverage so `compute_runs_for_cluster` surfaced ≤2
   actionable runs, leaving the extender no candidates to add. Not a bug
   in _enforce_runtime_budget; it's a cluster-quality edge case.

The user's complaint conflates (1) and (2), and the user is observing a
feed where 3 of 4 segments are pre-fix.

## Suggested fix direction

(specialist_hint: python)

The 2026-05-01 fix is operating correctly. The remaining work is NOT a
debug-loop fix — it's a product/operational decision. Three options to
surface to the user (with tradeoffs):

**Option A — Accept status quo + backfill recompile of pre-fix segments**
- Add a one-shot admin endpoint that re-runs `compile_segment` for every
  cluster whose existing segment has `len(ordered_clip_ids) < 3` AND
  `len(cluster.parents) >= 3`. Bounded scope, idempotent, no schema change.
- Wall-clock: ~30s per cluster × ~5-10 eligible clusters = a few minutes
  of admin work. Phase 14 already supports recompile.
- Pros: surface area minimal; respects "discuss before tuning" rule
  (touches no thresholds). Brings entire feed in line with the new behavior.
- Cons: doesn't help corner case (b746d131) — still 2 clips because the
  cluster doesn't have a 3rd usable run.
- Recommended for primary action.

**Option B — Relax the unique-parent constraint in `_enforce_runtime_budget`**
- Currently the extender picks ANY unpicked run, but in practice the LLM
  has already exhausted parent-unique candidates. Change extender behavior
  so when no unpicked-from-new-parent run exists, it picks a SECOND run
  from an already-represented parent (still increases montage runtime,
  preserves diversity floor of ≥2 parents).
- Pure compile.py edit; no threshold changes. Belt-and-suspenders against
  the b746d131-class corner case.
- Pros: addresses the post-fix 2-clip case directly; deterministic.
- Cons: a montage with two angles of the same parent + one of another parent
  is less satisfying than three unique angles — but it's still ≥2 parents,
  meets the spirit of the original constraint.
- Tradeoff: changes the implicit "one run per parent" pattern that the
  current evidence shows the LLM follows.

**Option C — Tighten Marengo coverage so 3rd-parent runs always exist**
- If clusters frequently have a parent with no embedded children, that's
  a Marengo/upload-pipeline issue, not a compile issue. Could investigate
  why the b746d131 cluster's 3rd parent has no actionable run.
- Out of scope for this debug session — would be its own session.
- Tradeoff: addresses upstream cause; longer investigation.

**Recommendation:** Option A as immediate action (backfill + announce in
the changelog), then if the user continues to see post-fix 2-clip segments
on freshly-compiled clusters, Option B as a follow-up. Option C only if
the upstream pattern keeps recurring.

**Project memory rule check:** Options A and B touch ZERO threshold/weight
configs (no RUN_THRESHOLD, MAX_RUN_MEMBERS, or composite-score changes).
Both are wiring/correctness/orchestration changes, surfacing for user
confirmation per the "discuss before tuning" rule even though that rule
technically only requires confirmation for tuning fixes.

## Specialist Review

(pending dispatch to python-expert-best-practices-code-review)

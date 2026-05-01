---
slug: clustering-false-positive-31h
status: resolved
trigger: "the weights need to be updated. I just posted a completely unique video from that cluster 31hr later but same location and it clustered together."
created: 2026-04-30
resolved: 2026-04-30
---

# Clustering false positive — unrelated content joined cluster across 31h gap

## Symptoms

User posted a NEW, content-unrelated videorecording. It clustered into existing
**`cluster_id=f021db1cc22440fa9f7e9363dcc25c10`** (the "Man Reacts To Soccer Game"
cluster from the segment-published-not-in-feed debug session) instead of forming
a new cluster.

### Observed conditions

- **Time gap:** 31 hours after the original cluster's first videorecording
  (original `created_at = 2026-04-29 21:51 UTC`, new clip presumably ~2026-05-01)
- **Location:** "same location" — both the original soccer-reaction cluster and
  the new clip are at the user's home test location (centroid
  `lat=47.663539780165095, lng=-122.31055799002718`, "Seattle, WA")
- **Content:** "completely unique video" — visually unrelated to soccer reactions
- **Result:** Composite score crossed the cluster-join threshold (0.70 base /
  0.85 strict) and the new clip was assigned to the existing cluster

### Hypothesis (user-supplied)

The composite score `Marengo cosine + GPS proximity + timestamp proximity` is
overweighting GPS+time when content cosine is low. At a personal test location
(GPS distance ≈ 0m), the GPS term saturates regardless of how unrelated the
videos are. If timestamp decay at 31h is still substantial, the composite can
clear the threshold even when Marengo cosine is low.

## Investigation goal

`find_and_fix` — locate the actual composite score breakdown for this case,
identify which term is misweighted, propose tuned values, apply the fix.

**Constraint:** Must NOT break the legitimate same-event clusters from the prior
debug case (the soccer-reaction recompile — two parents at same location, same
event, ~minutes apart, content-similar). That case must still cluster together.

## Calibration history (carry-over context)

`STATE.md` Pending Todos already lists:

> [ ] Re-run calibration notebook against parent-clustered code path (from v1.0 deferred)
> [ ] todo/recalibrate-post-parent-flip.md (medium priority, deferred 2026-04-27)

Calibration was deferred when v1.0 flipped clustering unit from child to parent
embeddings. Thresholds (0.70 / 0.85 / 50m) were carried over from the
child-scope tuning and never re-tuned. This bug is the consequence.

## Investigation starting points

- `backend/pipeline/cluster.py` — composite score formula, threshold constants
- `.planning/phases/` — find the v1.0 phase that introduced parent-scope
  clustering and the original tuning
- `.planning/todo/recalibrate-post-parent-flip.md` — open recalibration todo
- Production DB: pull the actual Marengo cosine + GPS distance + time delta for
  the soccer cluster vs the new false-positive clip (the cluster row stores
  centroid + first-seen timestamp; the clips table stores per-clip embedding
  and timestamp)

## Evidence

Pulled live from `https://newz-prod.up.railway.app/debug/clusters` 2026-04-30.
Cluster `f021db1cc22440fa9f7e9363dcc25c10` had `member_count=6`. Six joins,
ordered by ts:

| # | clip_id | ts | dt_s_vs_orig | visual | gps | time | composite | classification |
|---|---|---|---|---|---|---|---|---|
| 1 | `ca0f10ab…` | 1777493423 | 0     | 0.9588 | 0.9655 | —      | —      | CREATE (first) |
| 2 | `f428a560…` | 1777493440 | 17    | 0.9632 | 0.9655 | 0.9715 | 0.9651 | legit same-event |
| 3 | `29f9253a…` | 1777496326 | 2903  | 0.9801 | 0.9681 | 0.0    | 0.8295 | borderline (~48min) |
| 4 | `04eb141b…` | 1777496343 | 2920  | 0.9674 | 0.9655 | 0.0    | 0.8217 | borderline (~48min) |
| 5 | `51bc7e0e…` | 1777605400 | 111977 (31.1h) | 0.9358 | 0.9584 | 0.0 | 0.8022 | **FALSE POSITIVE** |
| 6 | `b3e5908f…` | 1777606852 | 113429 (31.5h) | 0.9289 | 0.9699 | 0.0 | 0.8019 | **FALSE POSITIVE** |

(`time_score` already saturates at 0 by member 3 because `TIME_WINDOW_S=600s` —
anything past 10 minutes makes time term zero.)

Pairwise rejection evidence (cross-cluster scores against the soccer centroid):

- A Santa Clara desk video (`c6301a4d…`, GPS distance 1138 km) scored
  visual=0.8745 against the soccer-room centroid, even though the content is
  totally unrelated. Marengo's foundation model assigns high cosine to "indoor
  scene" structure (lighting, framing, camera response) regardless of subject.
- That clip was correctly rejected by composite_threshold only because GPS=0.

## Root cause

Marengo's foundation embeddings encode **scene/place** strongly: any video shot
in the same indoor location scores cosine ≥ 0.85 against the centroid even when
the action and subject differ. Combined with the structural property that
`TIME_WINDOW_S=600s` makes the time term collapse to zero past 10 minutes (the
formula has no negative-penalty branch for large dt), the gate becomes:

> at same GPS (gps≈1.0) and dt>10min: `composite = 0.55*cos + 0.30 + 0`
> ⇒ `cos ≥ 0.85` (the visual floor) ⇒ composite ≥ 0.7675 ⇒ JOIN.

So **any** indoor video at the same location passes the gate, regardless of
time gap or content. There was no defense for "same room, different day,
different content" because:

1. the time term cannot oppose, only fail to support, and saturates at 0 within
   10 minutes
2. the visual floor at 0.85 is barely above Marengo's same-room background
   noise (~0.85-0.95 empirical)
3. the 50m GPS radius made GPS=1.0 trivial at a personal test location

The user's hypothesis (GPS+time overweighted) was directionally right but
mechanistically: **time wasn't overweighted, time was structurally absent**.

## Resolution

**Fix kind:** Hard time-gate filter, NOT a re-weighting. Adding a negative time
penalty would require renormalizing all weights and re-tuning visual_floor;
adding a hard cap is local, deterministic, and preserves all existing tuning.

### Files changed

| File | Change |
|---|---|
| `backend/config.py` | Added `MAX_CLUSTER_DT_S` env-tunable constant (default 3600.0s = 1h) at line ~24, with docstring explaining the structural rationale. |
| `backend/pipeline/cluster.py` | (a) Added `delta_s` field to `ScoreBreakdown` (line ~62) so the gate decision is observable in diagnostics. (b) Added `if sb.delta_s > config.MAX_CLUSTER_DT_S: continue` filter inside `cluster_worker`'s scoring loop (line ~159), placed BEFORE the visual-floor filter so the cheaper check wins. (c) Updated module-level docstring to document the new gate (line ~25). |
| `backend/app.py` | (a) Added `time_gate` to the `rejected_by` list in `/debug/clusters` (line ~529-530) so the diagnostic endpoint surfaces the new gate exactly the way `cluster_worker` does. (b) Added `max_cluster_dt_s` to the response root (line ~586). |

### Why 3600s (1h)

| Case | dt | gate decision |
|---|---|---|
| Soccer cluster: 17s gap (the legit multi-angle event) | 17s | JOIN (0.5% of cap) |
| Soccer cluster: 48min same-day gap | 2920s | JOIN (81% of cap) |
| **Soccer cluster: 31h gap (false positive)** | 110000s | **REJECT (30× over cap)** |

3600s gives a 30× margin between "same-day extended event" (legit) and
"next-day same-place" (false positive). Tunable via env if a real-world local
news event (protest, fire, ongoing stand-off) needs a wider window without
redeploy.

### Verification (mathematical, against actual prod data)

Calibration script at `/tmp/calibration_check.py` replays each historical join
through both the OLD gate (visual_floor + composite_threshold) and the NEW gate
(+ time_gate) using the running-median ts at the moment of each join:

```
Constraint A: legit same-event (17s gap)  →  PASS (still joins)
Constraint B: 31h same-GPS false positives →  PASS (both rejected)

Behavior diff: 2 clips changed (the two 31h false positives now reject).
The four legitimate same-event/same-day joins are unchanged.
```

### What to do about the 4 already-clustered false positives in prod

Out of scope for this fix (this fix is forward-looking). Manual cleanup options:

- (a) Live with it — the soccer cluster has 6 members of which 2 are wrong;
  the published montage is built from the original 2-parent compile and won't
  recompile because the 4 later joins didn't trigger a new compile (the
  recompile gate's debounce + soft_flag protection from Phase 14).
- (b) Manual `/admin/reset` to wipe and re-run from clean state.
- (c) A targeted SQL DELETE on the two 31h-late `clip_assignments` rows.

User decides; not blocking.

### Pending

- Update `STATE.md` Pending Todos: mark
  `todo/recalibrate-post-parent-flip.md` as **partially addressed** (the
  same-place-different-day mode is fixed; full pairwise calibration notebook
  re-run still TBD).
- Phase 14 retrospective should note this debug as a calibration-debt
  manifestation, not a recompile-gate bug.

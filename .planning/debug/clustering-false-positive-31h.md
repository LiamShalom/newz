---
slug: clustering-false-positive-31h
status: investigating
trigger: "the weights need to be updated. I just posted a completely unique video from that cluster 31hr later but same location and it clustered together."
created: 2026-04-30
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

## What "fix" looks like

Tuned constants in `cluster.py` (or wherever the composite weights live) such
that:

1. **At GPS≈0m, Marengo cosine ≥0.4 (or whatever empirical floor) is required**
   to cluster — pure GPS+time agreement isn't enough
2. **Timestamp decay at >24h reduces the time term to ≤0.1** so multi-day same-
   location uploads don't pile in
3. **Same-event same-time same-location** (the soccer case: 2 parents at
   centroid, both within minutes, content-similar) still clusters together

Pick values empirically from the production data (false-positive composite
breakdown + soccer cluster's two-parent breakdown) — not from gut feel.

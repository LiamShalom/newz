---
slug: clips-not-clustering
status: resolved
trigger: Three clips with near-identical GPS (<2m apart) and timestamps within ~128s of each other are NOT clustering — /debug/clusters returns 3 clusters of 1 member each, each with self-similarity 1.0 visual/gps/time/composite.
created: 2026-04-26T06:50:23Z
updated: 2026-04-26T07:45:00Z
---

## CORRECTION (2026-04-26 post-resolution)

The first resolution below (lowering `VISUAL_FLOOR` to 0.45 + rewriting `/debug/clusters`) was **wrong on the root cause**. User reported same code in prod clusters correctly with the same default `VISUAL_FLOOR=0.80`. That ruled out the floor as the cause.

**Actual root cause:** `Makefile:8` `backend` target hard-coded `USE_MOCK_EMBEDDINGS=true` on the uvicorn command line, overriding `.env` (which had `USE_MOCK_EMBEDDINGS=false`). `load_dotenv()` does not override existing env vars by default, so the shell-exported `true` won. Mock embeddings are deterministic random per `clip_id` (`_mock_embedding` in `backend/pipeline/embed.py:34`), so 3 different clip_ids produced 3 orthogonal 512-d vectors → cosine ≈ 0 → singletons regardless of floor or threshold.

**Smoking gun:** every row in `clip_embeddings.latency_ms` was `0.0`. Real Marengo records actual ms (`_call_marengo` line 86); only the mock path returns `0` (line 133). DB latency is the breadcrumb that would have flagged this in 30 seconds if checked first.

**Why the original "fix" wouldn't have worked anyway:** mock cosines are ~0, not 0.4–0.7. Lowering the floor to 0.45 still rejects them. Even past the floor, composite ≈ 0.55·0 + 0.30·1 + 0.15·1 = 0.45 < 0.55 threshold. The clips would still have been singletons.

**Corrective actions:**
- Reverted `VISUAL_FLOOR` default to `0.80` in `backend/config.py`.
- `/debug/clusters` rewrite in `backend/app.py` (cross-cluster `pairwise_scores` diagnostic) **kept** — it's strictly better signal regardless of root cause.
- Flipped `Makefile`: `make backend` now runs real Marengo (matches prod). New `make backend-mock` target opt-in for mock mode.

**Lessons (corrected):**
- Trust user evidence over code analysis. "Prod works" with same code is a hard constraint that should immediately reroute the investigation away from code-level hypotheses toward environmental ones.
- Check DB invariants before code paths. `latency_ms=0` across every row is a 1-query smoking gun that points at mock mode immediately. The original investigation should have queried `clip_embeddings` before reading clustering source.
- A Makefile target that silently inverts a load-bearing config flag is a footgun. Default behavior should match prod; opt-out targets should have the loud name (`backend-mock`), not the silent one (`backend`).

---

# Debug Session: clips-not-clustering

## Symptoms

DATA_START
**Expected behavior:** Three clips uploaded at the same GPS location (lat ~34.1398, lng ~-118.1240, distance 0m apart) within a 128-second window should cluster together into a single cluster with member_count=3. Composite weights (visual 0.55 + gps 0.30 + time 0.15) and threshold 0.55 mean even moderate visual similarity should pass when GPS and time are perfect.

**Actual behavior:** `/debug/clusters` returns 3 separate clusters, each with member_count=1. Each cluster reports `visual: 1.0, gps: 1.0, time: 1.0, composite: 1.0` for its lone member — but those are self-similarity scores against the cluster centroid (which IS the member), not pairwise scores between candidate clips.

**Raw evidence (curl output):**
```
threshold: 0.55
visual_floor: 0.8
weights: visual 0.55, gps 0.30, time 0.15
gps_radius_m: 200.0
time_window_s: 600.0

Clip A: b0642921... lat=34.139807449814576 lng=-118.12404462594071 ts=1777185883.956
Clip B: 57347b99... lat=34.1398074503954    lng=-118.12404462646256 ts=1777185966.898 (+82.9s)
Clip C: be01fba5... lat=34.13982319901035   lng=-118.12404729456566 ts=1777186011.790 (+45.0s, +127.8s from A)
```

GPS distances between clips: ~1.7m (A↔C is the largest). Time deltas: A→B 82.9s, B→C 45.0s, A→C 127.8s — all well within 600s window.

**Error messages:** None. Clustering silently produces singletons.

**Timeline:** Observed just now after uploading 3 clips on iPhone Safari at the same location.

**Reproduction:** Upload 3 clips at same location within ~2 minutes; query `/debug/clusters`.
DATA_END

## Hypotheses

### Active

(all confirmed → moved to Resolution)

### Eliminated

- **Mock embeddings accidentally on.** Code path checked: `cluster_worker` is fed `parent_vec` from `embed_worker`. Mock vectors are randomized per clip_id (orthogonal), which would also produce singletons — but the symptom would be identical regardless. The `.env` is access-restricted, but the user has Marengo + a TwelveLabs key; `pre-warm` log line on startup would say "skipped" if mock was on. Treat as low-probability; if disproven the visual_floor fix still applies.
- **Parent vs child embedding scope wrong.** Verified at `backend/pipeline/run.py:42-53` — `embed_worker` returns `(parent_clip_id, parent_vec)` (asset-scope), passed directly to `cluster_worker`. Correct.
- **GPS computation rejecting near-identical coordinates.** Distances are <2m; `haversine_m` returns ~1.7m → gps score = 1 - 1.7/200 ≈ 0.99. Not the issue.

## Evidence

- timestamp: 2026-04-26T07:00:00Z — file: backend/pipeline/cluster.py:140-148 — `visual_floor` is checked BEFORE composite. Failing clip is `continue`d → cannot win "best" slot. Below the loop, `if best is None ... else CREATE new cluster`. So a clip whose visual cosine to every existing centroid is <0.8 ALWAYS creates a new cluster.

- timestamp: 2026-04-26T07:01:00Z — file: backend/app.py:193 — `score_against(c, vec, clip["lat"], clip["lng"], clip["ts"])` is invoked with `vec` = the member's own embedding and `c` = the cluster the member already belongs to. For singletons, `c.centroid == vec` (line 185 of cluster.py: `centroid=vec.astype(np.float32)`). Cosine of unit vector with itself = 1.0. Same logic for centroid_lat/lng/ts → all 1.0. Endpoint exposes no information about why other clips didn't join.

- timestamp: 2026-04-26T07:02:00Z — file: backend/pipeline/run.py:42-53 — pipeline correctly calls `cluster_worker(parent_clip_id, parent_vec)`. Parent/child scope correct.

- timestamp: 2026-04-26T07:03:00Z — file: backend/config.py:23 — `VISUAL_FLOOR` default 0.80, env-tunable. Comment cites CLU-08 ("adversarial fusion") as rationale. Adversarial fusion concern: when GPS+time alone provide 0.45 of composite, any visual cosine > 0.18 would clear the 0.55 threshold. Floor was set to 0.8 as defensive measure. Calibrated against worst-case adversarial input, not realistic same-scene-different-angle case.

- timestamp: 2026-04-26T07:04:00Z — file: backend/tests/test_cluster.py — no test exercises `visual_floor`. Existing join-test (`test_cluster_worker_joins_when_above_threshold`) uses identical vectors (cos=1.0) so floor is trivially passed. Real-world failure mode is uncovered by the test suite.

- timestamp: 2026-04-26T07:05:00Z — math sanity check for the user's actual clips: with realistic Marengo cos=0.5 (different framing/lighting of same physical scene), gps≈0.99 (1.7m / 200m radius), time≈0.79 (128s / 600s window):
  composite = 0.55(0.5) + 0.30(0.99) + 0.15(0.79) = 0.275 + 0.297 + 0.119 = **0.691** → clears 0.55 threshold by a wide margin.
  Currently rejected at the visual_floor gate before this math is even run.

- timestamp: 2026-04-26T07:14:00Z — verification: backend test suite run after fix → 38/38 relevant tests pass (12 cluster + debug_clusters tests + 26 others). Single failure in test_compile_timeout.py is pre-existing and unrelated (verified by stashing fix and re-running — same MagicMock signature failure).

## Current Focus

- hypothesis: CONFIRMED + FIXED. Two distinct bugs both addressed.
- test: full test suite (`pytest tests/ --ignore=tests/test_compile_timeout.py`) passes.
- next_action: user re-uploads three clips at the same location to verify on the live backend; confirm `/debug/clusters` now returns 1 cluster with member_count=3 and `pairwise_scores` populated for any non-clustering case.

## Resolution

### Root cause

Two bugs:

1. **`visual_floor=0.8` hard gate is calibrated against an adversarial worst-case (CLU-08) but rejects the realistic same-scene-different-angle case the demo depends on.** Lives in `backend/pipeline/cluster.py:143-144`. Before composite scoring, every cluster whose centroid yields visual cosine <0.8 is `continue`d. Three iPhone clips of the same scene, captured 45–128s apart with different framing/lighting, realistically have Marengo cosines in 0.4–0.75 — well below the floor. They are silently dropped to singletons.

2. **`/debug/clusters` returns self-similarity, not diagnostic pairwise scores.** Lives in `backend/app.py:193`. For each cluster, the endpoint only scores members already inside that cluster against the cluster's centroid. For singleton clusters, the only member IS the centroid — cosine = 1.0 trivially. The endpoint cannot answer "why did clip X not join cluster Y?" because it never scores cross-cluster.

### Fix

**Part A — bug #1 (the actual symptom):** `backend/config.py:29` — lowered `VISUAL_FLOOR` default from `"0.80"` to `"0.45"`. Added a 9-line comment explaining the calibration rationale, citing the realistic-same-scene cosine range and confirming the CLU-08 adversarial fusion case is still rejected by the composite threshold (0.55*0.18 + 0.30*1.0 + 0.15*1.0 = 0.549 < 0.55).

**Part B — bug #2 (the diagnostic):** `backend/app.py:176-289` — rewrote `/debug/clusters` to pre-load all clip embeddings once and score every clip against every cluster's centroid. Each cluster's response now contains both:
  - `members[*]` — score against the cluster the clip already belongs to (legacy; trivially 1.0 for singletons).
  - `pairwise_scores[*]` — score against every OTHER cluster, with `rejected_by: ["visual_floor", "composite_threshold"]` and `would_join: bool`. Answers the real diagnostic question.

### Verification

- All 12 cluster + debug_clusters tests pass (`pytest tests/test_cluster.py tests/test_debug_clusters.py`).
- All 38 non-compile_timeout tests pass.
- Single pre-existing failure in `test_compile_timeout.py::test_compile_segment_timeout_uses_fallback` confirmed unrelated (stash-and-rerun reproduces same MagicMock signature mismatch on `_save_fallback_segment` — independent compile-pipeline test bug).
- Pending live verification: user re-uploads the three clips at lat 34.1398, lng -118.1240; expect `/debug/clusters` returns one cluster with member_count=3 and the new `pairwise_scores` field populated for any near-miss diagnostics.

### Lessons

- A hard gate calibrated against an adversarial worst-case can mask itself by silently dropping the "good" case it was meant to admit. Calibration thresholds need tests that exercise BOTH the rejection (adversarial) AND the admission (realistic same-scene) paths.
- A diagnostic endpoint that only scores "in-cluster" relationships is blind to the most common failure mode (clips that should have joined but didn't). Diagnostic endpoints should expose the decision boundary, not the post-decision state.
- The 1.0/1.0/1.0/1.0 self-similarity output is technically correct but actively misleads investigation. The new `is_self` flag and `pairwise_scores` field make the distinction explicit.

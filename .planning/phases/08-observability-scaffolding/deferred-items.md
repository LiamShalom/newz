# Phase 8 Deferred Items

Items discovered during Plan 08 execution that are out of scope for this phase.

## Pre-existing Test Failure (out of scope)

**File:** `backend/tests/test_debug_clusters.py::test_debug_clusters_empty_returns_envelope`

**Failure:** Asserts `body["threshold"] == 0.55` but `backend/config.py:21` defaults `CLUSTER_THRESHOLD` to `0.70`.

**Discovered during:** Plan 08-01, post-implementation full-suite verification (`pytest backend/tests/`).

**Out of scope reason:** Phase 8 does not modify `config.py:CLUSTER_THRESHOLD`, `backend/pipeline/cluster.py`, or `backend/app.py:/debug/clusters`. The test/config drift predates Phase 8 work — `git stash` confirms the failure exists on a clean checkout of the worktree base commit.

**Recommended fix (future phase):** Either update the test to read `config.CLUSTER_THRESHOLD` dynamically, or update the test's hardcoded `0.55` to `0.70` to match the live default. Likely related to the `recalibrate-post-parent-flip.md` deferred item from v1.0 close (STATE.md `Deferred Items`).

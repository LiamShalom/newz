---
title: Re-run calibration notebook against parent-clustered code path
date: 2026-04-25
priority: medium
blocks: Phase 5 demo hardening
unblocked_by: Phase 4.6 (cluster on parents)
---

# Re-run calibration notebook against parent-clustered code path

## What

After Phase 4.6 lands (cluster on parents + ≥2-parent publish gate),
re-execute `backend/notebooks/calibration.ipynb` end-to-end and confirm:

- [ ] CLU-07 PASS: 4 staged demo clips fuse into one cluster (≥3 members)
- [ ] CLU-08 PASS: adversarial pair stays in separate clusters
- [ ] Thresholds (`CLUSTER_THRESHOLD=0.55`, `VISUAL_FLOOR`) unchanged
- [ ] `member_count` semantics: each member is now a parent upload
      (not a child slice); update notebook assertion text if it implies
      child-level granularity

## Why

Calibration was originally tuned against parent embeddings (verified in
`.planning/notes/cluster-on-parents-decision.md`). The flip restores
the original tuning context, so this should pass cleanly — but verify
before the demo. A failing calibration notebook the night before HackTech
is a known-foreseeable disaster we can rule out for the cost of one cell run.

## How

```bash
make seed-demo                                     # ensure staged clips ready
jupyter nbconvert --execute --to notebook \
    backend/notebooks/calibration.ipynb            # CI-style execution
```

Or open in Jupyter and run all cells. Both CLU-07 and CLU-08 assertions
should print PASS without modification.

## If it fails

- CLU-07 fails: likely a publish-gate side effect — clusters might form
  but the gate suppresses what the notebook expected to see in `/debug/clusters`.
  Check whether notebook reads pre-gate cluster state or post-gate.
- CLU-08 fails: thresholds drifted somehow — first sanity check
  `config.CLUSTER_THRESHOLD` and `config.VISUAL_FLOOR` against `df465ac` values.

---
status: partial
phase: 03-clustering-debug-overlay
source: [03-VERIFICATION.md]
started: 2026-04-25T08:45:00Z
updated: 2026-04-25T08:45:00Z
---

## Current Test

[awaiting human testing — requires real MP4 clips + Marengo API key]

## Tests

### 1. CLU-07 Same-Event Fusion
expected: Film 3-4 clips of one event at the venue, replace zero-byte placeholders at backend/seed/demo/clip-{1..4}.mp4, run `python -m backend.seed.seed_demo --base-url http://localhost:8000`, then `jupyter nbconvert --to notebook --execute backend/notebooks/calibration.ipynb`. Largest cluster must have >= 3 members. Cell 5 assertion must pass.
result: [pending]

### 2. RTM-04 Live Debug Update
expected: Upload a clip via POST /clips while polling `curl http://localhost:8000/debug/clusters`. After pipeline completes (~5-30s), the cluster list must show the clip as a member with a score breakdown (visual, gps, time, composite, gps_distance_m, time_delta_s all populated).
result: [pending]

### 3. CLU-08 Adversarial Separation
expected: Record two visually unrelated clips (e.g., empty hallway + parking lot), save as backend/seed/demo/adversarial-1.mp4 and adversarial-2.mp4, rerun calibration notebook. Cell 7 assertion must pass: adversarial clips land in DIFFERENT clusters even when uploaded with same GPS + timestamp.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

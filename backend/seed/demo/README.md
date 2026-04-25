# Phase 3 Demo Clips

3-4 short MP4s of one event from different angles. Used by:

- `backend/seed/seed_demo.py` — uploads via POST /clips with Caltech-area GPS
- `backend/notebooks/calibration.ipynb` — proves CLU-07 (same-event fuse) and CLU-08 (adversarial separate)

## Naming Convention

- `clip-1.mp4` ... `clip-4.mp4` — same event, different angles (10-15s each)
- `adversarial-1.mp4`, `adversarial-2.mp4` (optional) — unrelated content for CLU-08

Files glob via `sorted(CLIP_DIR.glob("clip-*.mp4"))` — names must sort lexicographically.

## Recording Guidance

- 3-4 angles within ~30m of each other
- Captured within ~60 seconds (so timestamp proximity scores stay high)
- Vertical orientation (matches iOS Safari capture)
- Total directory size under 30MB (committed to git)

## Re-uploading

Backend running on http://localhost:8000:

```
python -m backend.seed.seed_demo --base-url http://localhost:8000
```

Then `curl http://localhost:8000/debug/clusters | jq` to inspect.

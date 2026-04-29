# Demo Clips

3-4 short MP4s of one event from different angles, kept around for ad-hoc testing of the embed → cluster → compile pipeline. Used by `backend/notebooks/calibration.ipynb` to prove CLU-07 (same-event fuse) and CLU-08 (adversarial separate).

## Naming Convention

- `clip-1.mp4` ... `clip-4.mp4` — same event, different angles (10-15s each)
- `adversarial-1.mp4`, `adversarial-2.mp4` (optional) — unrelated content for CLU-08

Files glob via `sorted(CLIP_DIR.glob("clip-*.mp4"))` — names must sort lexicographically.

## Recording Guidance

- 3-4 angles within ~30m of each other
- Captured within ~60 seconds (so timestamp proximity scores stay high)
- Vertical orientation (matches iOS Safari capture)
- Total directory size under 30MB (committed to git)

## Manual upload

Use the in-app recorder or `curl` directly. Backend running on `http://localhost:8000`:

```bash
curl -F "file=@clip-1.mp4" -F "lat=34.1377" -F "lng=-118.1253" -F "ts=$(date +%s)" \
  http://localhost:8000/clips
```

Then `curl http://localhost:8000/debug/clusters | jq` to inspect.

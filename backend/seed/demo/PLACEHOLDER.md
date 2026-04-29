# Demo Clip Placeholders

**Status: DEFERRED — placeholder files only**

The files `clip-1.mp4`, `clip-2.mp4`, and `clip-3.mp4` in this directory are **zero-byte
placeholders**. They were committed to establish the directory structure and file naming
convention before the actual demo footage is available.

## What This Means

- Manual upload (in-app recorder or `curl`) of these placeholders will fail at the embed
  step because the files have no video content (FastAPI accepts the upload, but Marengo
  embedding fails or produces a zero-vector).
- The calibration notebook **Cell 5 (CLU-07 assertion) will FAIL** until real clips replace
  these placeholders. The assertion requires the largest cluster to have >= 3 members, which
  requires Marengo to produce similar embeddings for same-event footage.

## How to Replace

1. Film 3–4 short MP4s (10–15s each) of one shared event from different angles within
   ~30m of each other, captured within ~60 seconds total. Vertical orientation preferred
   (matches iOS Safari capture).

2. Replace the placeholder files:
   ```
   backend/seed/demo/clip-1.mp4
   backend/seed/demo/clip-2.mp4
   backend/seed/demo/clip-3.mp4
   backend/seed/demo/clip-4.mp4  (optional — makes CLU-07 stronger)
   ```

3. (Optional but valuable for CLU-08 adversarial cell) Film 2 UNRELATED clips:
   ```
   backend/seed/demo/adversarial-1.mp4
   backend/seed/demo/adversarial-2.mp4
   ```
   If absent, the CLU-08 notebook cell prints "SKIPPED" instead of running.

4. Commit the real clips:
   ```bash
   git add backend/seed/demo/
   git commit -m "seed(demo): add real staged demo clips for CLU-07 calibration"
   ```

5. Re-run calibration:
   ```bash
   cd backend && uvicorn app:app --port 8000
   # In a new terminal:
   jupyter nbconvert --to notebook --execute notebooks/calibration.ipynb
   ```

## Recording Guidance (from 03-RESEARCH.md)

- 3–4 angles within ~30m of each other
- Captured within ~60 seconds (high timestamp proximity score)
- Vertical orientation (matches iOS Safari capture)
- Total directory size under 30MB (committed to git)
- Suggested events: group activity (people walking past a fountain, conversation around a
  table, foot traffic at a corner)

## File Naming Convention

Files glob via `sorted(CLIP_DIR.glob("clip-*.mp4"))` — names **must sort lexicographically**.
Use `clip-1`, `clip-2`, `clip-3`, `clip-4` (NOT `clip-10` ahead of `clip-2`).

---
*Deferred: Phase 3 Plan 02 execution — filming requires physical presence at Caltech venue.*
*Follow-up: Phase 5 Demo Hardening (DEM-07 `make demo`) will automate seeding from these files.*

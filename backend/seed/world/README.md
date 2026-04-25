# World FYP seed

Bulk-ingest a globally-distributed set of multi-angle "events" so the FYP feed isn't
just the FED-05 stub + the Caltech demo. Each event = one source video (yt-dlp top
search result) sliced into N short angle clips, uploaded with jittered GPS + staggered
timestamps so the live pipeline groups them into one cluster + one compiled segment.

## Why same-source angles

Every angle of an event comes from the **same** source video at different timestamps.
This guarantees high visual cosine between angles (well above the 0.80 visual floor in
`backend/pipeline/cluster.py`), so all 3 angles fuse into one cluster instead of
splitting into 3 single-clip clusters.

## Prerequisites

```sh
brew install yt-dlp ffmpeg
# Backend running with real APIs (not OFFLINE_DEMO / mock embeddings):
export TWELVELABS_API_KEY=...
export ANTHROPIC_API_KEY=...
make backend-real
```

## Run

```sh
# 1. Download + trim source videos into cache/<slug>/angle-N.mp4 (idempotent)
python -m backend.seed.world.download

# 2. Upload through the live pipeline. Waits up to 90s/event for compiled segment.
python -m backend.seed.world.seed_world

# Optional: full reset (deletes local DB + uploaded clips, then RESTART backend)
python -m backend.seed.world.seed_world --wipe
make backend-real        # restart
python -m backend.seed.world.seed_world
```

## Editing the manifest

`manifest.json` schema per event:

| field | meaning |
|---|---|
| `slug` | dir name under `cache/` |
| `name`, `location_label` | display strings (informational; not sent to backend) |
| `lat`, `lng` | base GPS; per-angle is jittered ±20m |
| `minutes_ago` | clip timestamps land at `now - minutes_ago` (per-angle staggered 5s) |
| `search_query` | yt-dlp pulls top match (`ytsearch1:`); used unless `source_url` is set |
| `source_url` | optional explicit YouTube URL (overrides `search_query`) |
| `angles[]` | list of `{start_sec, duration_sec}` slices from the source video |

To swap an event: edit slug + GPS + search_query + angle offsets, then
`python -m backend.seed.world.download --force` for that slug (or delete its
`cache/<slug>/` dir).

## Troubleshooting

- **yt-dlp returncode != 0** — YouTube changed an extractor. `pip install -U yt-dlp`.
- **All angles uploaded but no `segment_published`** — backend likely hit the 60s compile
  timeout. The fallback writer in `compile.py` still saves a chronological segment with a
  generic caption; rerun `GET /feed` after another ~30s to see it.
- **Angles split into multiple clusters** — visual cosine fell below `VISUAL_FLOOR=0.80`.
  Pick a more visually-stable source (a static-camera walking tour rather than a dynamic
  drone tour); reduce `start_sec` gaps so frames are closer in content.
- **`backend not reachable`** — start backend first (`make backend-real`), then re-run.
- **Cold-start latency on first clip** — Marengo pre-warm runs on backend lifespan; if
  you skipped pre-warm, the first event may take ~30s longer. Subsequent events are fast.

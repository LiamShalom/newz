---
slug: stitch-clips-bottleneck
status: investigating
trigger: |
  stitch_clips dominates compile pipeline wall-clock at ~66s p50, blowing the
  60s prod timeout in 3/3 parallel bench runs and the 30s CLAUDE.md hard cap by
  >2x. Parallelization saves only 3.7s because Track B dwarfs Tracks A + C.
created: 2026-04-25
updated: 2026-04-25
---

# Debug Session: stitch-clips-bottleneck

## Symptoms

- **Expected behavior:** `stitch_clips` (Track B of compile pipeline) completes well under 30s for 3 clips so the overall compile pipeline can land inside the 30s CLAUDE.md hard cap (and ideally <10s to leave headroom for Tracks A and C).
- **Actual behavior:** `stitch_clips` takes ~66.5s p50 (parallel) / ~66.8s p50 (serial) across N=3 runs of 3 clips each. 100% of parallel runs (3/3) exceed the 60s prod timeout.
- **Error messages:** No errors from stitch itself. (Separate concern: every run logs `track_a_err: caption-writer query error errors=None` — tracked separately.)
- **Timeline:** First-time measurement via `.planning/spikes/002-compile-baseline/bench.py` — finished 2026-04-25 17:57. No prior baseline.
- **Reproduction:** `python .planning/spikes/002-compile-baseline/bench.py` against `/Users/liamshalom/Hacktech/data` (local clips).

## Bench Evidence

```
PARALLEL (ms, N=3)
| stage                  |    min |    p50 |    max |
|------------------------|-------:|-------:|-------:|
| track_a (_run_agents)  |   3049 |   3150 |   4394 |
| track_b (stitch_clips) |  66421 |  66512 |  66832 |
| track_c (gen_caption)  |    341 |    393 |    737 |
| TOTAL (parallel)       |  66421 |  66512 |  66832 |

would TimeoutError in prod (cap=60s): 3/3

SERIAL (ms, N=3)
| stage                  |    min |    p50 |    max |
|------------------------|-------:|-------:|-------:|
| track_a (_run_agents)  |   2827 |   2894 |   4200 |
| track_b (stitch_clips) |  66746 |  66834 |  67038 |
| track_c (gen_caption)  |    306 |    316 |    356 |
| TOTAL (serial)         |  69968 |  70248 |  71302 |

Parallel vs serial (medians):
  saved   = 3736 ms (~3.7s)
  speedup = 1.06x
```

Implication: Track B dominates so completely that parallelization barely helps. The fix MUST be inside `stitch_clips`, not in the orchestration.

## Project Context

- **Active phase:** Phase 4 — Multi-Agent Compile + Real-Time Feed.
- **Hard cap:** 30s wall-clock on the entire compile pipeline (CLAUDE.md). Currently >2x over budget on stitch alone.
- **Stack:** FastAPI backend, Python 3.11, likely ffmpeg via subprocess for stitching.
- **Test corpus:** 3 clips/run, sourced from `/Users/liamshalom/Hacktech/data`.
- **Bench script:** `.planning/spikes/002-compile-baseline/bench.py`.

## Current Focus

```yaml
hypothesis: |
  stitch_clips is calling ffmpeg with re-encoding (libx264 / libx265 / similar)
  rather than stream-copy, OR is doing per-clip transcoding before concat. At
  ~22s per clip on three short clips, this is consistent with full-pipeline
  re-encoding instead of `-c copy` concat. Alternative hypotheses: (1) running
  ffmpeg in a thread that doesn't release the GIL despite being subprocess —
  unlikely since subprocess is fine; (2) downloading clips from disk via slow
  IO path; (3) demux+remux via concat protocol with audio re-sample.
test: |
  Read backend stitch_clips source. Look for the ffmpeg invocation: codec args,
  filter graph (-vf / -filter_complex), -c copy vs -c:v libx264, concat list
  vs concat filter, audio handling. Time individual sub-steps if possible.
expecting: |
  Likely (1) re-encode rather than stream-copy concat, or (2) using the concat
  filter (which forces re-encode) when source clips are already H.264-aligned
  and could use the concat demuxer with -c copy for sub-second stitching.
next_action: |
  Locate stitch_clips in backend/. Read the ffmpeg invocation. Identify whether
  it's re-encoding and whether stream-copy concat is feasible given the clip
  format coming off iPhone Safari MediaRecorder (likely mp4/h264 or webm/vp9).
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-25 17:57 — Bench results above. p50=66.5s parallel, p50=66.8s serial. 3/3 parallel runs exceed 60s prod cap.
- timestamp: 2026-04-25 — Spike 002 bench script `.planning/spikes/002-compile-baseline/bench.py` ran successfully against `/Users/liamshalom/Hacktech/data`.

## Eliminated

- Track A (_run_agents) is not the bottleneck (3.15s p50, fails fast with caption-writer error).
- Track C (generate_caption) is not the bottleneck (0.39s p50).
- Parallelization itself is fine; the issue is that Track B's wall-clock dwarfs the others.

## Resolution

(pending)

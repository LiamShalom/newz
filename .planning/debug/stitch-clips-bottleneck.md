---
slug: stitch-clips-bottleneck
status: root_cause_found
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
```

Implication: Track B dominates so completely that parallelization barely helps. The fix MUST be inside `stitch_clips`, not in the orchestration.

## Project Context

- **Active phase:** Phase 4 — Multi-Agent Compile + Real-Time Feed.
- **Hard cap:** 30s wall-clock on the entire compile pipeline (CLAUDE.md). Currently >2x over budget on stitch alone.
- **Stack:** FastAPI backend, Python 3.11, ffmpeg via `ffmpeg-python` subprocess.
- **Test corpus:** 3 clips/run, sourced from `/Users/liamshalom/Hacktech/data`.
- **Bench script:** `.planning/spikes/002-compile-baseline/bench.py`.

## Current Focus

```yaml
hypothesis: |
  CONFIRMED: stitch_clips uses the concat *demuxer* correctly (good!) but pairs
  it with vcodec="libvpx-vp9" + acodec="libopus", which forces a full software
  VP9 re-encode of the entire concatenated stream. libvpx-vp9 at default speed
  is ~CPU-bound at single-digit fps for 720p input — 45s of input → ~66s
  encode. The concat demuxer doesn't auto-stream-copy; the vcodec arg dictates.
test: |
  Read backend/pipeline/stitch.py — confirmed line 45:
    .output(output_path, vcodec="libvpx-vp9", acodec="libopus", **{"b:v": "1M"})
  Reproduced bottleneck via direct ffmpeg call: 66.10s wall-clock, 118s user CPU.
  Tested H.264 ultrafast normalize-and-concat: 0.52s wall-clock (~127x faster).
expecting: |
  Two issues compound:
    (a) libvpx-vp9 software encode is the slow path for any container.
    (b) Source clips have mismatched specs (720x1296@30, 476x848@24, 720x1280@25
        with B-frames), so naive -c copy stream-copy concat is NOT safe — the
        clips need normalization (resize/pad/fps) before concat or after.
  Fix: switch to libx264 with -preset ultrafast, normalize via concat filter
  (handles mismatched specs), output .mp4. Bonus: iOS Safari (the demo target,
  CLAUDE.md hard constraint) prefers MP4 over WebM natively.
next_action: |
  Apply fix: rewrite _sync_stitch to use H.264 ultrafast + concat filter,
  switch output extension to .mp4, update compile.py:381 accordingly.
  Verify with bench re-run after fix.
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-25 17:57 — Bench results above. p50=66.5s parallel, p50=66.8s serial. 3/3 parallel runs exceed 60s prod cap.
- timestamp: 2026-04-25 — Spike 002 bench script `.planning/spikes/002-compile-baseline/bench.py` ran successfully against `/Users/liamshalom/Hacktech/data`.
- timestamp: 2026-04-25 18:10 — Read `backend/pipeline/stitch.py:42-47`. Confirmed: `ffmpeg.input(list_path, format="concat", safe=0).output(output_path, vcodec="libvpx-vp9", acodec="libopus", **{"b:v": "1M"})`. The concat *demuxer* is used (good — no scale/fps filters), but the vcodec is libvpx-vp9 which forces full software re-encode. **This is the root cause.**
- timestamp: 2026-04-25 18:11 — Probed seed clips. All H.264 but mismatched: clip1=720x1296@30 Constrained Baseline, clip2=476x848@24 Constrained Baseline, clip3=720x1280@25 High (B-frames=2). **Stream-copy `-c copy` is NOT safe** here without normalization.
- timestamp: 2026-04-25 18:12 — Reproduced current behavior via direct ffmpeg: `f concat | -c:v libvpx-vp9 -b:v 1M -c:a libopus` = 66.10s wall-clock, 118.81s user CPU. Matches bench p50 exactly (~66.5s).
- timestamp: 2026-04-25 18:12 — Tested fix candidate: 3-input filter_complex with scale-pad-fps normalize then concat, encode with `-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -movflags +faststart`. Result: **0.52s wall-clock**, output 13MB, 720x1280@30 valid 45.5s mp4. Faster than current by ~127x.

## Eliminated

- Track A (_run_agents) is not the bottleneck (3.15s p50, fails fast with caption-writer error).
- Track C (generate_caption) is not the bottleneck (0.39s p50).
- Parallelization itself is fine; the issue is that Track B's wall-clock dwarfs the others.
- Slow IO is NOT the cause (ffmpeg user CPU = 118s, well above wall-clock — clearly compute-bound).
- Audio resample is NOT the dominant cost (libopus is fast vs libvpx).
- GIL / asyncio executor is NOT the cause (wall-clock matches direct ffmpeg call).

## Root Cause

`backend/pipeline/stitch.py:45` calls ffmpeg with `vcodec="libvpx-vp9"`, which forces full software VP9 re-encode of the concatenated 45s of 720p video. libvpx-vp9 at default speed runs at ~3-5 fps for 720p → ~66s. The concat *demuxer* (correct choice for this layout) honors whatever codec args you pass to `.output()`; it does not auto-select stream-copy.

Compounding issue: source clips have mismatched resolution / framerate / profile, so naive `-c copy` stream-copy is not safe — they need normalization first.

## Proposed Fix

Rewrite `_sync_stitch` to:
1. Use a 3-input `filter_complex` with `scale → pad → setsar=1 → fps=30` per input, then `concat=n=N:v=1:a=0`.
2. Encode with `-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -movflags +faststart`.
3. Drop audio (matches CLAUDE.md scope — no audio rendering called out).
4. Switch output extension from `.webm` to `.mp4`.

Bonus alignment with project constraints:
- iOS Safari (CLAUDE.md hard constraint demo target) plays H.264 MP4 natively without codec negotiation; it does support WebM/VP9 in iOS 14.5+ but H.264 is the safer demo path.
- New stitch budget: ~0.5-1s for 3 clips. Leaves ~29s of the 30s cap for Tracks A and C.

## Specialist Hint

`python` — engineering review of subprocess invocation, error handling, and file extension contract change at the call site (`compile.py:381`).

## Resolution

(pending user confirmation to apply)

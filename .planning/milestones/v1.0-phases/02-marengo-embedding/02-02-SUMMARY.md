---
phase: 02-marengo-embedding
plan: 02
status: complete
completed: 2026-04-24
commit: e4fa620
duration: ~10min
requirements_completed: [EMB-05]
---

# Phase 2, Plan 02: Pre-warm + Pipeline Wiring — Summary

**Marengo pre-warm fires on startup via asyncio.create_task (non-blocking); embed_worker wired into run_pipeline; mock mode skips pre-warm cleanly.**

## Files Modified

- `backend/config.py` — added `PRE_WARM_CLIP_PATH` (absolute path via `Path(__file__).parent / "seed" / "prewarm.mp4"`)
- `backend/app.py` — added `_pre_warm_marengo()`, wired `asyncio.create_task(_pre_warm_marengo())` into existing lifespan, replaced `run_pipeline` stub with live `embed_worker` call
- `backend/seed/prewarm.mp4` — minimal 32-byte ftyp+mdat stub (Python struct, no ffmpeg required)

## Lifespan Wiring

Phase 1 scaffold already had a lifespan context manager with `await db_module.init_db()` and `await db_module.close_db()`. Added `asyncio.create_task(_pre_warm_marengo())` between init_db and yield — server starts accepting requests immediately, pre-warm runs in background.

## run_pipeline Modification

Phase 1 stub had a `# Phase 2 adds: embedding = await embed_worker(clip_id, conn)` comment. Replaced the stub body with the live call: `embedding = await embed_worker(clip_id, conn)` + SSE broadcast of `stage: embedded`. Cluster and compile stages remain as Phase 3/4 TODOs.

## Pre-warm Clip

ffmpeg unavailable on build machine. Created a minimal valid MP4 (ftyp + mdat boxes, 32 bytes) via Python struct. This satisfies `Path(pre_warm_path).exists()` validation. **Note:** the stub MP4 will cause a real Marengo call to fail (not a valid video stream). When `TWELVELABS_API_KEY` is set and `USE_MOCK_EMBEDDINGS=false`, replace `seed/prewarm.mp4` with a real 5-30s clip before demo. Mock mode never reads the file.

## config.py Accessor Pattern

`USE_MOCK_EMBEDDINGS` is already a `bool` (set via `.lower() == "true"` in config.py). No string comparison needed in callers — confirmed consistent with embed.py's `if config.USE_MOCK_EMBEDDINGS:` guard.

## End-to-End Mock Test Result

```
end-to-end mock: OK  status=done  latency_ms=0  dims=512
```

Clip goes from `embedding_status=pending` → `embedding_status=done` with 512-d BLOB in `clip_embeddings`. Pre-warm logs `pre-warm skipped (USE_MOCK_EMBEDDINGS=true)` and returns cleanly.

## Action Required Before Demo

Replace `backend/seed/prewarm.mp4` with a real video clip once `TWELVELABS_API_KEY` is available. Any 5-30s MP4/WebM works. The pre-warm will then pay the Marengo cold-start cost before judges arrive.

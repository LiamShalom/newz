# Milestones

## v1.0 Hackathon MVP — Shipped 2026-04-26 · Won HackTech 2026

**Status:** ✅ Shipped & WON
**Event:** HackTech (Caltech), April 24-26 2026
**Closed:** 2026-04-28

**Stats:** 4 phases · 12 plans · 35 tasks · 177 commits · ~28K LOC (Python + TS) · ~38h elapsed build window

### Delivered

AI-native local news from anonymous crowdsourced footage. Browser-based capture (iOS Safari) → POST `/clips` (202 fire-and-forget) → Twelve Labs Marengo 3.0 embedding (parent + child clips) → composite-score clustering (Marengo cosine + GPS + timestamp) → Claude Agent SDK multi-subagent compile pipeline (Angle Selector + Caption Writer + Publisher running in parallel) → ffmpeg stitch into one compiled segment → SSE-driven live feed re-render. Anonymous-by-default end-to-end; no accounts, no auth.

### Key Accomplishments

- **Phase 1 — Foundation, Capture & Ingest:** FastAPI + Vite/React/TS/Tailwind 4 scaffold, POST /clips with 202 + asyncio.create_task fire-and-forget, SQLite WAL clips table, anonymous session UUID in localStorage, iOS Safari MediaRecorder MIME-type fallback ladder (mp4;avc1 → webm;vp9 → webm), GPS-blocking submit with 5s geolocation timeout, Vercel + Railway deploy with persistent volume.
- **Phase 2 — Marengo Embedding:** marengo3.0 (lowercase) 512-d multimodal embedding worker via `loop.run_in_executor` so sync SDK never blocks the event loop, tenacity retry, deterministic mock mode (PYTHONHASHSEED-stable), startup pre-warm via asyncio.create_task to kill cold-start latency.
- **Phase 3 — Clustering + Debug Overlay:** composite-score clustering (final tuned thresholds: 0.70 base / 0.85 strict / 50m GPS radius), `GET /debug/clusters` exposing per-member score breakdown, `seed_demo.py` CLI uploader, calibration notebook asserting CLU-07 (staged clips fuse) + CLU-08 (adversarial pair separates), in-memory `CLUSTERS` dict rebuilt from SQLite on startup.
- **Phase 4 — Multi-Agent Compile + Real-Time Feed:** Claude Agent SDK pipeline with parallel Angle Selector + Caption Writer subagents, ≥2-distinct-parent compile gate, run-granularity stitching via ffmpeg `-c copy` parallel `asyncio.gather`, libx264 ultrafast normalize-and-concat (~0.8s p50, 84× faster than initial libvpx-vp9 path), Gemini 2.5 Flash native video captions replacing frame-aggregation, SSE-driven feed auto-refresh, token-guarded `POST /admin/reset` for demo resets.
- **Architectural pivot mid-build:** clustering unit flipped from children → parents (children remain in DB only as compile-time slicing metadata); compile fires only when cluster has ≥2 distinct parent uploads. Restored Phase 3's tuned-threshold context.
- **Demo readiness:** OFFLINE_DEMO env flag for cached-response fallback, staged-clip dataset, place+date caption fallback when vision pipeline times out.

### Known Gaps / Deferred (acknowledged at close)

- Phase 03 + Phase 04 VERIFICATION.md marked `human_needed` — never finalized post-demo
- Phase 04 HUMAN-UAT.md has 3 pending scenarios
- 1 open debug session: `montage-not-updating` (investigating)
- 1 medium-priority todo: `recalibrate-post-parent-flip.md` (re-run calibration notebook against parent-clustered code path)
- 3 quick-task status files missing despite code shipped (260425-pw1, -pyj, -q06)
- Roadmap Phases 4.5, 4.6, 5 planned mid-build but never executed; superseded by what actually shipped (4.5/4.6 substance landed via the parent-clustering pivot in Phase 4 + quick tasks)

See `.planning/STATE.md` Deferred Items for full table.

### Outcome

🏆 **Won HackTech 2026.** Shipped a live, demoable multi-angle event clustering pipeline with grounded AP-wire captions in under the 48h hackathon window.

---

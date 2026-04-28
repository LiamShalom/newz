# Newz — Living Retrospective

A milestone-by-milestone record of what worked, what didn't, and what we learned.

## Milestone: v1.0 — Hackathon MVP

**Shipped:** 2026-04-26 · **Won HackTech 2026**
**Phases:** 4 | **Plans:** 12 | **Tasks:** 35 | **Commits:** 177 | **LOC:** ~28K

### What Was Built

End-to-end multi-angle event clustering pipeline: anonymous in-app camera (iOS Safari) → POST /clips fire-and-forget ingest → Marengo 3.0 parent + child embeddings → composite-score clustering (Marengo cosine + GPS + timestamp) → Claude Agent SDK multi-subagent compile pipeline (Angle Selector + Caption Writer + Publisher running in parallel) → Gemini 2.5 Flash native-video captions → ffmpeg run-granularity stitch → SSE-driven feed auto-refresh. Anonymous-by-default end-to-end. Won HackTech 2026.

### What Worked

- **Fire-and-forget pipeline shape from Phase 1.** POST /clips returned 202 in <100ms with `asyncio.create_task` kicking off embed → cluster → compile. UI never blocked. This shape carried unchanged from Phase 1 through Phase 4 — every later phase plugged into the same pattern.
- **Mock mode + offline-demo flag baked in early.** `USE_MOCK_EMBEDDINGS=true` and `OFFLINE_DEMO=true` were Phase 2 deliverables, not last-minute Phase 5 retrofits. Made every later phase debuggable without burning Twelve Labs credits.
- **Calibration notebook as a Phase 3 deliverable, not a Phase 5 polish.** Tuned thresholds (0.55 → 0.70 / 0.80 → 0.85, 200m → 50m) before they had to carry the demo. The pitch ("multi-angle clustering") was load-bearing on these numbers being right.
- **Phase 3 was demoable on its own.** "If we stop here, we still have something" was non-negotiable. When the compile pipeline was being rewritten on day 2, the debug overlay + clustering still proved the thesis solo.
- **Run-in-executor for the sync Twelve Labs SDK.** Kept FastAPI's event loop unblocked without rewriting around an async SDK that didn't exist.
- **Mid-build pivot to parent-scope clustering survived because of locked decisions.** Phase 3's calibrated thresholds were anchored to parent embeddings; when sub-clip clustering broke them in Phase 4.5, flipping back to parent unit (quick task `260425-pyj`) restored the calibration context cleanly.

### What Was Inefficient

- **Phase 4.5 → 4.6 detour.** Spent meaningful time on child-scope clustering before realizing Phase 3's threshold calibration was tied to parent-scope embeddings. The pivot back via quick task `260425-pyj` was correct but the detour cost ~hours that could have gone to demo hardening. Lesson: when you change clustering inputs, the calibration is no longer valid — flag it as a constraint, not an assumption.
- **Initial libvpx-vp9 stitch encoder was 84× too slow.** ~66.5s p50 stitch made the 30s compile budget impossible. Switched to libx264 ultrafast normalize-and-concat for ~0.8s p50. Should have measured stitch latency before committing to vp9.
- **Anthropic frame-aggregation captions were the wrong tool.** Frame-by-frame caption then aggregate produced unstable, hallucinated headlines. Switched to Gemini 2.5 Flash native video input late. Lesson: when a model has native video input, prefer it over frame extraction + aggregation.
- **Compile budget kept getting bumped.** 30s → 60s → 120s → 300s as throttle/retry behavior surfaced. The original 30s cap from CMP-06 turned out to be aspirational under real API conditions.
- **Three quick tasks landed without status files.** Code shipped, status markers got skipped under hackathon time pressure, audit flagged them at close.

### Patterns Established

- **Fire-and-forget + asyncio.create_task as the pipeline contract.** Never `await` long-running work in a request handler. Never use BackgroundTasks (they coupled to request lifecycle in surprising ways).
- **Mock-mode by env flag, deterministic vectors.** `int.from_bytes` seed for PYTHONHASHSEED-stable mocks. Cheap to develop against; safe in CI.
- **Threshold env vars over hardcoded constants.** `RUN_THRESHOLD`, cluster join threshold, GPS radius — all hot-swappable without redeploy.
- **Calibration notebooks as commit-time artifacts.** CLU-07 (positive case fuses) + CLU-08 (adversarial pair separates) live in repo. Future tuning has a regression baseline.
- **Per-run ffmpeg parallelism via `asyncio.gather` with `-c copy`.** Per-clip trim outside the LLM gather budget so orchestrator slowness can't cancel ffmpeg mid-stitch.
- **Token-guarded admin endpoints for demo resets.** `POST /admin/reset` was a 1-hour add that paid off every time we re-ran the demo flow.
- **Two-phase deploy (deploy → get URLs → set env → redeploy).** Pattern for Railway + Vercel cross-service env wiring.

### Key Lessons

1. **Calibration is anchored to specific inputs.** Changing the clustering unit (parent vs. child) invalidates threshold tuning. Don't assume otherwise.
2. **Measure latency on the actual encoder before committing.** vp9 vs x264 was 84×. We didn't catch it until late.
3. **Native model capabilities > clever workarounds.** Gemini native video > frame-aggregation. Use the right tool.
4. **Demoable-at-every-phase is a pitch insurance policy.** Phase 3 carried the demo when later phases were mid-rewrite.
5. **Anonymity-by-default forced architectural decisions early.** No auth meant no per-user state, which meant no Redis, which meant single-process asyncio worked. The constraint compounded into simpler infra.

### Cost Observations

- Hackathon delivered in ~38h elapsed, well under the 48h cap
- Twelve Labs API consumption stayed reasonable thanks to mock mode in dev/CI
- Late-stage LLM timeout bumps (300s) absorbed throttle without falling back; would not be tenable at production scale

### Outcome

🏆 **Won HackTech 2026.**

## Cross-Milestone Trends

(First milestone — trend section will populate after v1.1 ships.)

---
*Last updated: 2026-04-28 after v1.0 milestone close*

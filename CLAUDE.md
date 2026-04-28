# Newz — Claude Code Project Guide

AI-native local news from anonymous crowdsourced footage. v1.0 won HackTech 2026 (Caltech, April 24-26 2026). Co-founders: Liam, Roan, Claude.

**Current state:** Post-hackathon. v1.0 shipped and archived. No v1.1 scope locked yet.

## Authoritative Project Context

Always read `.planning/` before suggesting changes:

- `.planning/PROJECT.md` — vision, current state, validated requirements, out-of-scope reasoning, key decisions
- `.planning/ROADMAP.md` — milestone summary (v1.0 archived, next milestone TBD)
- `.planning/STATE.md` — last activity, deferred items, locked decisions
- `.planning/MILESTONES.md` — shipped milestones with stats and accomplishments
- `.planning/RETROSPECTIVE.md` — what worked, what didn't, lessons learned per milestone
- `.planning/milestones/v1.0-*` — archived v1.0 roadmap, requirements, and phase artifacts (PLAN.md / SUMMARY.md / RESEARCH.md / VERIFICATION.md)

PROJECT.md is the source of truth for what's in/out of scope. Defer to it.

## Stack (as shipped in v1.0)

- **Frontend:** React 18 + Vite + TypeScript + Tailwind 4 — deployed to Vercel
- **Backend:** FastAPI + Uvicorn (Python 3.11) — deployed to Railway with persistent volume at `/data`
- **Video embeddings:** Twelve Labs `marengo3.0` (lowercase) via `twelvelabs==1.2.3`, 512-d, parent + child clips
- **Multi-agent compile:** Anthropic `claude-agent-sdk==0.1.68` — bundles CLI binary, no Node.js required on backend
- **Vision captions:** Gemini 2.5 Flash native video input (replaced Anthropic frame-aggregation)
- **Storage:** SQLite (aiosqlite, WAL mode) + local FS for clips. **No** Postgres, Redis, Pinecone, or S3 at this scale.
- **Vector search:** NumPy in-memory cosine over normalized 512-d vectors. **No** vector DB.
- **Stitching:** ffmpeg with libx264 ultrafast normalize-and-concat, per-run parallel via `asyncio.gather` + `-c copy`

## Architecture

Single-process FastAPI monolith. Pipeline stages chain via `asyncio.create_task` — no Celery, no message broker. SSE for real-time feed updates.

Hot path: `Browser → POST /clips (202) → embed (Marengo, parent + children) → cluster (composite score, parent-scope) → maybe compile (Claude Agent SDK + Gemini) → ffmpeg stitch → SSE broadcast → feed re-renders.`

Clustering composite: `Marengo cosine + GPS proximity + timestamp proximity`, tuned thresholds (0.70 base / 0.85 strict / 50m GPS radius). **Clustering unit is the parent upload** — children remain in DB only as compile-time slicing metadata. Compile fires only when cluster has ≥2 distinct parent uploads.

Admin endpoint: token-guarded `POST /admin/reset` wipes clips between demo runs.

## Hard Constraints (still applicable)

- **Anonymity is load-bearing.** No accounts, no login, no profiles. Anonymous session UUID in localStorage only.
- **iOS Safari is the demo target.** Verified on real iPhone. MIME-type fallback ladder: `mp4;avc1 → webm;vp9 → webm → no mimeType`.
- **OFFLINE_DEMO=true** serves cached embeddings + cached compile output without any external API calls.
- **Pre-warm Marengo on backend startup** with throwaway call. Cold-start latency = dead live demo.
- **Compile pipeline LLM budget:** 300s wall-clock (raised from original 30s during v1.0 to absorb retries/throttle).

## Out of Scope (carried forward from v1.0)

Live streaming · user accounts/login · likes/comments · user-authored captions · content moderation pipeline · native iOS app · in-app editing · map view · national/regional feed · Pinecone/Qdrant · Redis/Celery · server-side transcoding · wow-factor snap animation · streaming caption tokens · multi-agent status banner.

These are deliberately deferred — revisit before v1.1 only if productizing. See `.planning/PROJECT.md` "Out of Scope" for full reasoning.

## GSD Workflow

This project uses GSD (`get-shit-done`) for phase-by-phase execution.

- `/gsd-progress` — current state + next action
- `/gsd-new-milestone` — start v1.1 (questioning → research → requirements → roadmap)
- `/gsd-add-phase` / `/gsd-plan-phase` / `/gsd-execute-phase` — for individual phases once a milestone is locked

Config: YOLO mode, coarse granularity, parallel execution, research+plan-check+verifier enabled, Quality model profile.

## Lessons Carried Forward (from v1.0 retrospective)

- **Calibration is anchored to specific inputs.** Changing the clustering unit invalidates threshold tuning.
- **Measure encoder latency before committing.** libvpx-vp9 was 84× slower than libx264 ultrafast; almost killed the demo.
- **Native model capabilities > clever workarounds.** Gemini native video > frame-aggregation for captions.
- **Demoable-at-every-phase is pitch insurance.** Phase 3 carried the demo when later phases were mid-rewrite.
- **Anonymity-by-default forced simpler infra.** No auth → no per-user state → no Redis → single-process asyncio worked.

Full retrospective: `.planning/RETROSPECTIVE.md`.

---
*Last updated: 2026-04-28 after v1.0 milestone close*

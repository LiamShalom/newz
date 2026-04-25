# Newz — Claude Code Project Guide

AI-native local news from anonymous crowdsourced footage. Hackathon MVP, HackTech (Caltech) April 24-26, 2026. Co-founders: Liam, Roan, Claude.

## Authoritative Project Context

Always read `.planning/` before suggesting changes:

- `.planning/PROJECT.md` — vision, requirements (Validated/Active/Out of Scope), key decisions
- `.planning/REQUIREMENTS.md` — 61 v1 requirements with REQ-IDs
- `.planning/ROADMAP.md` — 5 phases, requirement-to-phase traceability, success criteria
- `.planning/STATE.md` — current phase + next action
- `.planning/research/SUMMARY.md` — synthesized research (stack, architecture, pitfalls)
- `.planning/research/STACK.md` / `ARCHITECTURE.md` / `PITFALLS.md` / `FEATURES.md` — full research

PROJECT.md is the source of truth for what's in/out of scope. Defer to it.

## Stack

- **Frontend:** React 18 + Vite + TypeScript + Tailwind 4 — deployed to Vercel
- **Backend:** FastAPI + Uvicorn (Python 3.11) — deployed to Railway with persistent volume
- **Video AI:** Twelve Labs `marengo3.0` (lowercase, NOT 2.7 — sunset 2026-03-30) via `twelvelabs==1.2.3`. 512-d embeddings.
- **Multi-agent AI:** Anthropic `claude-agent-sdk==0.1.68` — bundles CLI binary, no Node.js required on backend.
- **Storage:** SQLite (aiosqlite, WAL mode) + local FS for clips. **No** Postgres, Redis, Pinecone, or S3 at hackathon scale.
- **Vector search:** NumPy in-memory cosine over normalized 512-d vectors. **No** vector DB.

## Architecture

Single-process FastAPI monolith. Pipeline stages chain via `asyncio.create_task` — no Celery, no message broker. SSE for real-time feed updates.

Hot path: `Browser → POST /clips (202) → embed (Marengo) → cluster (composite score) → maybe compile (Claude Agent SDK 4-subagent pipeline) → SSE broadcast → feed re-renders.`

Clustering composite: `0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity`, threshold `0.55` (calibrate empirically against staged demo dataset).

## Hard Constraints

- **Anonymity is load-bearing.** No accounts, no login, no profiles. Anonymous session UUID in localStorage only.
- **iOS Safari is the demo target.** Verify on real iPhone, not emulator. MIME-type fallback ladder required: `mp4;avc1 → webm;vp9 → webm → no mimeType`.
- **Live-first demo with staged-clip fallback.** `OFFLINE_DEMO=true` env flag must serve cached embeddings + cached compile output without any external API calls.
- **30-second hard cap on compile pipeline wall-clock.** Fallback to default ordering + generic caption on timeout.
- **Pre-warm Marengo on backend startup** with throwaway call. Cold-start latency = dead demo.

## Out of Scope (do not propose adding)

Live streaming · user accounts/login · likes/comments · user-authored captions · content moderation pipeline · native iOS app · in-app editing · map view · national/regional feed · Pinecone/Qdrant · Redis/Celery · server-side transcoding · wow-factor snap animation · streaming caption tokens · multi-agent status banner.

See `.planning/PROJECT.md` and `.planning/REQUIREMENTS.md` "Out of Scope" tables for full reasoning.

## GSD Workflow

This project uses GSD (`get-shit-done`) for phase-by-phase execution.

- `/gsd-progress` — current state + next action
- `/gsd-discuss-phase <N>` — gather context for a phase before planning
- `/gsd-plan-phase <N>` — create executable plan
- `/gsd-execute-phase <N>` — run the plan
- `/gsd-next` — auto-advance

Config: YOLO mode, coarse granularity, parallel execution, research+plan-check+verifier enabled, Quality model profile (Opus for research/roadmap).

## Phase Map

1. **Foundation, Capture & Ingest** (5-7hr) — iPhone Safari camera + clip upload + raw feed playback
2. **Marengo Embedding** (3-4hr) — 512-d vectors per clip, mock flag, pre-warm
3. **Clustering + Debug Overlay** (4-5hr) — composite-score clustering + calibration notebook + visible score breakdown — **THE PITCH**
4. **Multi-Agent Compile + Real-Time Feed** (5-7hr) — 4-subagent Claude Agent SDK pipeline + SSE-driven feed
5. **Demo Hardening** (remaining) — `OFFLINE_DEMO`, staged replay, screencast, single `make demo`

## Top Pitfalls (from research/PITFALLS.md)

All 6 WOULD-KILL-DEMO pitfalls have phase homes — do not paper over them:

1. Marengo embed latency (5-30s) → fire-and-forget, never block UI
2. Untuned clustering thresholds → calibration notebook is a Phase 3 deliverable
3. iOS Safari MediaRecorder silently fails → MIME ladder + real-iPhone gate before anything else
4. Indoor GPS unavailable at Caltech → GPS weight collapses to 0; `?demo_location=` override
5. Compile pipeline >30s → parallel sub-agents (Angle Selector ‖ Caption Writer); 30s hard cap
6. Hackathon WiFi dies → `OFFLINE_DEMO` mode + 90s screencast Tier-5 fallback

---
*Generated: 2026-04-24 during /gsd-new-project*

# Newz — Claude Code Project Guide

AI-native local news from anonymous crowdsourced footage. v1.0 won HackTech 2026 (Caltech, April 24-26 2026). Co-founders: Liam (backend), Roan (UI), Claude (in-loop).

**Current state:** v1.1 Pilot MVP for funding — in progress. Per-feature GSD workflow. Comments + shares are the active phase.

## Nomenclature (use these exact terms — do NOT substitute "segment", "post", "story", or "video")

- **videorecording** — raw video uploaded by a user (taken in-app on iOS Safari or uploaded). One file = one videorecording.
- **clip** — embedding-space slice produced by Twelve Labs Marengo's `clip` flag. One videorecording → one or more clips.
- **montage** — the final compiled multi-angle output produced by the Claude Agent SDK pipeline. What users see in the feed; what comments and shares attach to.

If existing code uses other names (legacy hackathon naming), match the existing names in that file unless asked to rename.

## Authoritative Project Context

Always read `.planning/` before suggesting changes:

- `.planning/PROJECT.md` — vision, current state, in/out scope, constraints, key decisions, open strategic questions
- `.planning/ROADMAP.md` — v1.1 feature backlog (mando + non-mando) and per-feature phase index
- `.planning/STATE.md` — runtime cursor (active phase, locked decisions, deferred items, next action)
- `.planning/MILESTONES.md` — shipped milestones with stats and accomplishments
- `.planning/RETROSPECTIVE.md` — lessons learned per milestone
- `.planning/phases/<NN>-<slug>/` — active phase work (CONTEXT, PLAN, SUMMARY, etc.)
- `.planning/milestones/v1.0-*` — archived v1.0 artifacts

PROJECT.md is the source of truth for what's in/out of scope. Defer to it.

## Workflow — per-feature GSD (v1.1)

**Each backlog item is its own phase.** No master sequenced roadmap. When a feature gets picked up:

1. Promote the backlog row in ROADMAP.md to a phase (`phases/<NN>-<slug>/`).
2. Write `<NN>-CONTEXT.md` (problem, decisions made, scope in/out, open questions).
3. Write `<NN>-PLAN.md` (task breakdown, owner per task).
4. Branch: `feature/<slug>` off `main`.
5. Build, commit atomically per task.
6. Write `<NN>-SUMMARY.md` when shipped.
7. Update ROADMAP.md status + STATE.md cursor.

GSD slash commands (`/gsd-progress`, `/gsd-add-phase`, `/gsd-plan-phase`, `/gsd-execute-phase`) are available but not required — hand-scaffolding is preferred for per-feature work since the slash commands assume a sequenced multi-phase plan that we no longer have.

## Stack (as shipped in v1.0; still current for v1.1)

- **Frontend:** React 18 + Vite + TypeScript + Tailwind 4 — Vercel
- **Backend:** FastAPI + Uvicorn (Python 3.11) — Railway, persistent volume at `/data`
- **Video embeddings:** Twelve Labs `marengo3.0` (lowercase) via `twelvelabs==1.2.3`, 512-d, parent + child clips
- **Multi-agent compile:** Anthropic `claude-agent-sdk==0.1.68` (bundles CLI binary, no Node.js on backend)
- **Vision captions:** Gemini 2.5 Flash native video input
- **Storage:** SQLite (aiosqlite, WAL) + local FS. **No** Postgres, Redis, Pinecone, or S3.
- **Vector search:** NumPy in-memory cosine over normalized 512-d vectors.
- **Stitching:** ffmpeg libx264 ultrafast normalize-and-concat, per-run parallel via `asyncio.gather` + `-c copy`

## Architecture

Single-process FastAPI monolith. Pipeline stages chain via `asyncio.create_task` — no Celery, no message broker. SSE for real-time feed updates.

Hot path: `Browser → POST /clips (202) → embed (Marengo, parent + children) → cluster (composite score, parent-scope) → maybe compile (Claude Agent SDK + Gemini) → ffmpeg stitch → SSE broadcast → feed re-renders.`

Clustering composite: `Marengo cosine + GPS proximity + timestamp proximity`, tuned thresholds (0.70 base / 0.85 strict / 50m GPS radius). **Clustering unit is the parent videorecording** — children are compile-time slicing metadata. Compile fires only when cluster has ≥2 distinct parent uploads.

Admin endpoint: token-guarded `POST /admin/reset` wipes clips between runs.

## Hard Constraints

- **Anonymity is load-bearing.** No accounts, no login, no profiles, **no display names anywhere — including comments**. Anonymous session UUID in localStorage may be used server-side for rate limiting only; never displayed.
- **iOS Safari is the primary surface.** Verify on real iPhone (not emulator) before declaring camera/permission/upload work done. MIME ladder: `mp4;avc1 → webm;vp9 → webm → no mimeType`.
- **Reliability over polish for the pilot.** Funding conversations turn on "does it work when I try it" — broken flows kill the pitch faster than missing features. Fix bugs before adding features when in doubt.
- **OFFLINE_DEMO=true** still serves cached responses (kept for fallback).
- **Pre-warm Marengo on backend startup** — cold-start latency = dead live demo.
- **Compile pipeline LLM budget:** 300s wall-clock.

## Out of Scope (do not propose adding)

Live streaming · user accounts/login/profiles/display names · in-app videorecording editing · user-authored captions · native iOS app · national/regional feed · conventional likes · map view · Pinecone/Qdrant · Redis/Celery · server-side transcoding.

See `.planning/PROJECT.md` "Out of Scope" for full reasoning.

## Team Split

- **Roan:** UI only (React/TS/Tailwind in `frontend/`).
- **Liam:** Backend (FastAPI/Python in `backend/`).
- Cross-domain features need explicit handoffs. If a UI feature needs a backend change, flag it; don't propose backend changes to Roan.

## Lessons Carried Forward (from v1.0 retrospective)

- **Calibration is anchored to specific inputs.** Changing the clustering unit invalidates threshold tuning.
- **Measure encoder latency before committing.** libvpx-vp9 was 84× slower than libx264 ultrafast.
- **Native model capabilities > clever workarounds.** Gemini native video > frame-aggregation.
- **Demoable-at-every-phase is pitch insurance.**
- **Anonymity-by-default forced simpler infra.** No auth → no per-user state → no Redis → single-process asyncio worked. Continues into v1.1.

Full retrospective: `.planning/RETROSPECTIVE.md`.

---
*Last updated: 2026-04-27 — opened v1.1 Pilot, switched to per-feature GSD*

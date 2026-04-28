# Newz

## What This Is

Newz is AI-native local news from anonymous crowdsourced footage. Users open the web app on a phone, record a short clip with GPS auto-attached, and a multi-agent AI pipeline (Claude Agent SDK + Twelve Labs Marengo 3.0 + Gemini 2.5 Flash for vision captions) clusters footage of the same event from multiple angles into a single compiled news segment, served back as a hyperlocal feed. Anonymous-by-default end-to-end. Every user is both journalist and audience — there is no creator/consumer split.

Won HackTech 2026 with the v1.0 demo.

## Current State

**Shipped:** v1.0 Hackathon MVP — won HackTech 2026 (Caltech, April 24-26 2026).

- Backend: FastAPI monolith on Railway with persistent volume; SQLite (WAL) + local FS for clips; NumPy in-memory cosine for vector search; Marengo 3.0 embeddings (parent + child clips); Claude Agent SDK pipeline with parallel Angle Selector + Caption Writer; Gemini 2.5 Flash for vision-grounded captions; ffmpeg run-granularity stitch via libx264 ultrafast.
- Frontend: React 18 + Vite + TypeScript + Tailwind 4 on Vercel; iOS Safari MediaRecorder with MIME-type fallback ladder; SSE-driven feed auto-refresh; Stories-style segment cards with autoplay-on-scroll.
- Codebase: ~28K LOC TS+Python, 177 commits, ~38h elapsed build window.

## Next Milestone Goals

TBD. Live status: post-hackathon, no committed v1.1 scope yet. Open candidates (not locked):

- Resolve open verification + UAT gaps (Phase 03/04) and the `montage-not-updating` debug session
- Re-run calibration notebook against the post-pivot parent-clustered code path
- Decide on productization vs. archiving — content moderation, accounts, and live streaming were all explicitly out-of-scope for the hackathon and would need re-evaluation

Run `/gsd-new-milestone` to define v1.1.

<details>
<summary>Pre-shipment context (preserved for history)</summary>

## Core Value

**Multi-angle event clustering must work.** Show the same event captured by different people, automatically grouped and compiled into one coherent segment. If clustering fails, the entire product premise fails. (Validated at HackTech demo — clustering carried the pitch.)

## Hackathon Context (v1.0)

**Event:** HackTech (Caltech), April 24-26 2026. Submitted to four tracks: Best Use of AI, Creativity, YC x HackTech, Sideshift x HackTech.

**Why this project, why now:** Crowd footage already exists (everyone records on their phone) but is scattered across Snapchat, TikTok, group chats, and camera rolls. Traditional news can't cover hyperlocal events economically; social media captures moments but doesn't organize them. The combination of (a) zero-friction anonymous capture, (b) Twelve Labs multimodal video embeddings making automated clustering finally viable, and (c) Claude Agent SDK enabling cheap multi-agent editorial compilation made this buildable in 2026 in a way it wasn't a year ago.

**The "Best Use of AI" narrative:** Marengo 3.0 produces multimodal video embeddings (visual, motion, audio, speech in one vector) that make event clustering work. A Claude Agent SDK pipeline of distinct agent roles turns a cluster into a finished segment. Two complementary AI systems doing different jobs, both load-bearing.

**Team:** Liam + Roan + Claude (co-founder).

</details>

## Requirements

### Validated (shipped v1.0)

- ✓ Anonymous in-app camera (no account, no caption authoring) — v1.0
- ✓ Auto-attach GPS coordinates and timestamp to every clip — v1.0
- ✓ Backend ingest endpoint: 202 fire-and-forget + asyncio.create_task pipeline kickoff — v1.0
- ✓ Twelve Labs Marengo 3.0 embeddings per clip (parent + child) — v1.0
- ✓ Composite-score event clustering (Marengo cosine + GPS + timestamp) with tuned thresholds — v1.0
- ✓ Multi-agent compile pipeline (Claude Agent SDK, parallel subagents, ≥2-parent gate) — v1.0
- ✓ Local feed UI (Stories-style autoplay, SSE-driven) — v1.0
- ✓ One-tap pivot from feed → camera — v1.0
- ✓ Visible debug overlay with score breakdown — v1.0
- ✓ Pre-recorded staged demo dataset — v1.0
- ✓ iOS Safari MediaRecorder MIME fallback ladder — v1.0
- ✓ Vision-grounded captions (Gemini 2.5 Flash native video) — v1.0

### Active

(None — post-hackathon, awaiting v1.1 scoping.)

### Out of Scope (carried forward from v1.0; revisit before v1.1)

- **Live streaming** — not built; revisit if productizing
- **User accounts / login / profiles** — anonymity-by-default was load-bearing for the demo; productization would force this conversation
- **Content moderation pipeline** — acknowledged need; deferred at hackathon; mandatory before any public launch
- **Native iOS app** — PWA was sufficient
- **Per-segment engagement** (likes, comments, prioritization) — anonymity friction
- **User-authored captions** — defeats anonymity + AI editorial moat
- **National/regional feed escalation** — hyperlocal IS the differentiator
- **Map view** — feed shows distance overlay; defer
- **Wow-factor snap animation** — deferred at v1.0; revisit if pursuing UX polish
- **Pinecone / Qdrant / vector DB** — NumPy in-memory cosine sufficient at <1000 vectors
- **Redis / Celery / message queue** — single-process asyncio sufficient at hackathon scale; will need re-evaluation if scaling

## Constraints

- **Anonymity is load-bearing.** No accounts, no login, no profiles. Anonymous session UUID in localStorage only.
- **iOS Safari is the demo target.** Verified on real iPhone. MIME-type fallback ladder required.
- **Hackathon-scale infra:** SQLite + local FS + in-memory cosine. Productization would need to revisit.
- **30-second hard cap on compile pipeline wall-clock** (pushed to 300s for retry absorption late in the build).
- **Pre-warm Marengo on backend startup** — cold-start latency = dead demo (still applies post-hackathon for live demos).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React + FastAPI split | Python backend gets first-class Twelve Labs + Anthropic SDKs; React fastest path to credible web UI | ✓ Good |
| Claude Agent SDK for compile pipeline | Strongest "Best Use of AI" story; multi-agent narrative; on-brand co-founder framing | ✓ Good |
| Twelve Labs Marengo 3.0 for video embeddings | Multimodal embeddings are what made clustering work | ✓ Good |
| Web app, not native iOS | Hackathon demo only needed phone browser; native is multi-day overhead | ✓ Good |
| Anonymous by default (no accounts) | Removes biggest barrier to filming sensitive content; differentiator | ✓ Good (demo); ⚠️ Revisit for productization |
| Clustering = Marengo + GPS + timestamp weighted | Single-signal clustering breaks on adversarial cases; combination robust | ✓ Good (CLU-08 passed) |
| Pre-recorded staged demo dataset over live capture | Live demos fail; staged clips de-risk the pitch | ✓ Good |
| Local feed only (no national/regional) | Hyperlocal IS the differentiator | ✓ Good |
| No content moderation in v0 | Acknowledged risk; mention in pitch as Day 2 work | ⚠️ Revisit before any public launch |
| Parent-scope clustering (not child-scope) | Mid-build pivot (2026-04-26): children remain as compile-time slicing metadata only; cluster unit is parent upload; ≥2-distinct-parents required for compile | ✓ Good — restored Phase 3's tuned-threshold context |
| Drop Editor subagent (angle-selector → publisher direct) | Latency budget; Editor was redundant given Caption Writer + Publisher | ✓ Good |
| Gemini 2.5 Flash for vision captions (replaced Anthropic frame-aggregation) | Native video input + faster + grounded; produced cleaner AP-wire headlines | ✓ Good |
| libx264 ultrafast normalize-and-concat (replaced libvpx-vp9) | 84× faster (~0.8s vs 66.5s p50) | ✓ Good |
| Run-granularity stitching (per-run, not one fused montage) | Frontend can navigate angles instead of one blob | ✓ Good |
| Token-guarded POST /admin/reset | Demo-day need: wipe clips between runs without redeploy | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-28 after v1.0 milestone completion*

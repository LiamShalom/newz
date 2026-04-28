# Newz

## What This Is

Newz is AI-native local news from anonymous crowdsourced footage. Users open the web app on a phone, record a short videorecording with GPS auto-attached, and a multi-agent AI pipeline (Claude Agent SDK + Twelve Labs Marengo 3.0 + Gemini 2.5 Flash for vision captions) clusters footage of the same event from multiple angles into a single compiled montage, served back as a hyperlocal feed. Anonymous-by-default end-to-end. Every user is both journalist and audience — there is no creator/consumer split.

Won HackTech 2026 with the v1.0 demo. Now building toward a **pilot MVP for funding** as v1.1.

## Nomenclature (use these exact terms)

- **videorecording** — raw video uploaded by a user (taken in-app on iOS Safari or uploaded). One file = one videorecording.
- **clip** — embedding-space slice produced by Twelve Labs Marengo's `clip` flag. One videorecording → one or more clips.
- **montage** — the final compiled multi-angle output produced by the Claude Agent SDK pipeline. What users see in the feed; what comments/shares attach to.

Avoid "segment," "post," "story," "video" — they're ambiguous and create confusion in code and pitch.

## Current State

**Shipped — v1.0 Hackathon MVP** (won HackTech 2026, Caltech, April 24-26 2026):

- Backend: FastAPI monolith on Railway with persistent volume; SQLite (WAL) + local FS for clips; NumPy in-memory cosine for vector search; Marengo 3.0 embeddings (parent + child clips); Claude Agent SDK pipeline with parallel Angle Selector + Caption Writer; Gemini 2.5 Flash for vision-grounded captions; ffmpeg run-granularity stitch via libx264 ultrafast.
- Frontend: React 18 + Vite + TypeScript + Tailwind 4 on Vercel; iOS Safari MediaRecorder with MIME-type fallback ladder; SSE-driven feed auto-refresh; Stories-style montage cards with autoplay-on-scroll.
- Codebase: ~28K LOC TS+Python, 177 commits, ~38h elapsed build window.

**Active — v1.1 Pilot MVP for funding** (started 2026-04-27):

Goal: get in front of funders (TwelveLabs feature/credits, Buerk Center @ UW, CoMotion @ UW) with something that works for real users, not just a demo. Reliability + missing core features. Backlog in `ROADMAP.md`.

Workflow: per-feature GSD. Each backlog item that gets worked on becomes its own phase under `.planning/phases/<NN>-<slug>/`. **No master sequenced roadmap** — features are picked off opportunistically.

## Core Value

**Multi-angle event clustering must work.** Show the same event captured by different people, automatically grouped and compiled into one coherent montage. If clustering fails, the entire product premise fails. (Validated at HackTech demo.)

## Requirements

### Validated (shipped v1.0)

- ✓ Anonymous in-app camera (no account, no caption authoring) — v1.0
- ✓ Auto-attach GPS coordinates and timestamp to every videorecording — v1.0
- ✓ Backend ingest endpoint: 202 fire-and-forget + asyncio.create_task pipeline kickoff — v1.0
- ✓ Twelve Labs Marengo 3.0 embeddings per videorecording (parent + child clips) — v1.0
- ✓ Composite-score event clustering (Marengo cosine + GPS + timestamp) with tuned thresholds — v1.0
- ✓ Multi-agent compile pipeline (Claude Agent SDK, parallel subagents, ≥2-parent gate) — v1.0
- ✓ Local feed UI (Stories-style autoplay, SSE-driven) — v1.0
- ✓ One-tap pivot from feed → camera — v1.0
- ✓ Visible debug overlay with score breakdown — v1.0
- ✓ Pre-recorded staged demo dataset — v1.0
- ✓ iOS Safari MediaRecorder MIME fallback ladder — v1.0
- ✓ Vision-grounded captions (Gemini 2.5 Flash native video) — v1.0
- ✓ Upload timeout / reliability fix — v1.1 (Liam, PR #1)
- ✓ Location bug ("UW shows Pasadena") fix — v1.1 (Liam, PR #2)

### Active (v1.1 Pilot — see ROADMAP.md for full backlog)

**Mando for pilot** (must ship before showing funders):
- [ ] Anonymous comments on montages (no accounts, no display names, ever)
- [ ] Share montages (Web Share API)
- [ ] Clip selection logic fix (montages don't seem to actually pick clips)
- [ ] Safari location services bug — permissions gate decision
- [ ] Adding videorecordings to existing montages
- [ ] Video censoring
- [ ] Permissions gate (mic + cam + location flow)
- [ ] Real test suite

**Non-mando** (if time):
- [ ] Reduce Claude token usage
- [ ] Domain / new name
- [ ] Custom engagement signal (replace conventional likes)
- [ ] Audio embedding (verify Marengo doesn't already cover)
- [ ] Multiple feed tabs (Recent / Popular / Today)
- [ ] AI comment replies (depends on comments shipping first)

### Out of Scope (still — applies to v1.1 pilot)

- **Live streaming** — clip-based by design; live is a different product.
- **User accounts / login / profiles / display names** — anonymity is load-bearing for the pitch and the product. **Comments and shares MUST work without identity.**
- **Native iOS app** — web first; PWA + Add-to-Home-Screen hint is the surface.
- **Likes (conventional implementation)** — content isn't human-authored, so a human-style "like" carries low signal. Custom signal is non-mando.
- **National / regional feed escalation** — hyperlocal IS the differentiator.
- **In-app editing of videorecordings** — anonymity + zero friction.
- **User-authored captions / titles** — defeats anonymity + AI editorial moat.
- **Map view** — feed shows distance; defer.
- **Pinecone / Qdrant / vector DB** — NumPy in-memory cosine still sufficient at pilot scale.
- **Redis / Celery / message queue** — single-process asyncio still sufficient; revisit only if pilot scale outgrows it.

## Constraints

- **Anonymity is load-bearing.** No accounts, no login, no profiles, **no display names anywhere — including comments**. Anonymous session UUID in localStorage may be used server-side for rate limiting / abuse control, but is never displayed and never linked to identity.
- **iOS Safari is the primary surface.** Verify on real iPhone. MIME-type fallback ladder: `mp4;avc1 → webm;vp9 → webm → no mimeType`.
- **Reliability over polish for the pilot.** Funding conversations turn on "does it work when I try it." Broken flows kill the pitch faster than missing features.
- **Pre-warm Marengo on backend startup** — cold-start latency = dead live demo. Still applies.
- **OFFLINE_DEMO=true** — kept around for demo fallback even though pilot is live-first.
- **Compile pipeline LLM budget:** 300s wall-clock (carried over from v1.0 retry-absorption tuning).

## Open Strategic Questions (decide before locking each feature)

- **Censoring approach** — automated (face/license-plate detection) vs. human review vs. hybrid. Affects pipeline latency + infra.
- **Permissions gate flow** — require mic+cam+location before record, OR allow record-without-location with reduced clustering weight (PDF leans toward latter).
- **Custom engagement signal** — up/down votes vs. something novel. Decide before building.
- **Domain / new name** — "Newz" is placeholder.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React + FastAPI split | Python backend gets first-class Twelve Labs + Anthropic SDKs; React fastest path to credible web UI | ✓ Good |
| Claude Agent SDK for compile pipeline | Strongest "Best Use of AI" story; multi-agent narrative; on-brand co-founder framing | ✓ Good |
| Twelve Labs Marengo 3.0 for video embeddings | Multimodal embeddings are what made clustering work | ✓ Good |
| Web app, not native iOS | Phone browser is sufficient; PWA + A2HS hint is the install surface | ✓ Good (continues for v1.1) |
| Anonymous by default (no accounts, no display names) | Removes biggest barrier to filming sensitive content; differentiator. **Reaffirmed for v1.1: comments and shares are anonymous too.** | ✓ Good |
| Clustering = Marengo + GPS + timestamp weighted | Single-signal clustering breaks on adversarial cases; combination robust | ✓ Good (CLU-08 passed) |
| Pre-recorded staged dataset over live capture for demos | Live demos fail; staged clips de-risk the pitch | ✓ Good |
| Hyperlocal-only (no national/regional) | Hyperlocal IS the differentiator | ✓ Good |
| Parent-scope clustering (not child-scope) | Mid-build pivot 2026-04-26: children stay as compile-time slicing metadata only; cluster unit is parent upload; ≥2-distinct-parents required for compile | ✓ Good |
| Drop Editor subagent (angle-selector → publisher direct) | Latency budget; Editor was redundant given Caption Writer + Publisher | ✓ Good |
| Gemini 2.5 Flash for vision captions (replaced Anthropic frame-aggregation) | Native video input + faster + grounded; produced cleaner AP-wire headlines | ✓ Good |
| libx264 ultrafast normalize-and-concat (replaced libvpx-vp9) | 84× faster (~0.8s vs 66.5s p50) | ✓ Good |
| Run-granularity stitching (per-run, not one fused montage) | Frontend can navigate angles instead of one blob | ✓ Good |
| Token-guarded POST /admin/reset | Demo-day need: wipe clips between runs without redeploy | ✓ Good |
| **v1.1: per-feature GSD, no master roadmap** | Pilot scope is opportunistic feature-by-feature, not a sequenced waterfall. Each backlog item becomes its own phase when worked on. | ✓ Adopted 2026-04-27 |
| **v1.1: comments/shares fully anonymous (no display names)** | Anonymity is load-bearing for the pitch. Adding identity to engagement primitives would break the differentiator. | ✓ Adopted 2026-04-27 |
| **v1.1: Roan = UI, Liam = backend** | Continuing the v1.0 split. Cross-domain features need both; flag handoffs explicitly. | ✓ Continues |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Current State

---
*Last updated: 2026-04-27 — opened v1.1 Pilot MVP milestone, switched to per-feature GSD*

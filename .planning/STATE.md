---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Pilot MVP for funding (Public-Launch-Ready Backbone)
status: in_progress
last_updated: "2026-04-28T00:00:00.000Z"
last_activity: 2026-04-28 -- merged backbone + feature tracks
progress:
  total_phases: 8
  completed_phases: 4
  total_plans: 19
  completed_plans: 14
  percent: 50
---

# Project State: Newz

## Project Reference

**Core Value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent montage.

**Current Focus:** v1.1 Pilot MVP for funding — two parallel tracks:
- **Backbone (Liam):** Phase 9 (Postgres) just shipped; Phase 10 (Vercel Blob) up next.
- **Feature (Roan):** Phase `01-comments-and-sharing` planned, ready for execute.

## Current Position

| Field | Value |
|-------|-------|
| Active Milestone | v1.1 Pilot MVP for funding (Public-Launch-Ready Backbone) |
| Active Phases | Backbone: 10 next (planning) · Feature: `01-comments-and-sharing` (ready to execute) |
| Status | Backbone phases 8 + 9 shipped; feature track plan drafted |
| Workflow | Two tracks: backbone uses sequenced phases (8-13); feature track uses per-feature GSD |

```
[█████░░░░░░] ~50% — backbone 2/6 (8, 9 shipped); feature 0/N (01 ready)
```

## Accumulated Context

### Locked Decisions (carried forward from v1.0)

- React + Vite + TS + Tailwind 4 frontend; FastAPI + Uvicorn + Python 3.11 backend
- Twelve Labs Marengo 3.0 (`marengo3.0` lowercase) for video embeddings — non-negotiable
- Claude Agent SDK 0.1.68 for multi-agent compile (Sonnet for subagents, Haiku for Publisher)
- NumPy in-memory cosine; local FS for clip storage (Phase 10 will move clip media to Vercel Blob)
- Vercel for FE; Railway for BE
- Clustering unit = parent (asset-scope) Marengo embedding; children are compile-time slicing metadata
- compile_segment dispatches only when cluster has ≥2 distinct parent uploads
- ffmpeg libx264 ultrafast normalize-and-concat for stitching
- Gemini 2.5 Flash for vision-grounded captions

### Locked Decisions (new in v1.1)

- **Anonymous everywhere — including comments.** No accounts, no display names, ever. Anonymous session UUID may be used server-side for rate limiting only.
- **Two parallel tracks under one milestone.** Backbone (sequenced phases 8-13, Liam) + feature track (per-feature phases, Roan). Both share anonymity, OFFLINE_DEMO survivability, reliability bias.
- **Nomenclature:** videorecording (raw upload) / clip (Marengo embedding-space slice) / montage (final compiled output). Don't mix them up in code or docs.
- **Comments attach per-montage**, not per-clip or per-videorecording.
- **Roan = UI, Liam = backend.** Cross-domain features need explicit handoffs.

### Locked Decisions (backbone, Phase 9 + planning context)

- Neon Postgres over Supabase (avoid Supabase Auth pressure on anonymity-by-default)
- asyncpg + Alembic; **no SQLAlchemy ORM** during migration
- Vercel Blob for clip media; **no direct browser PUT** — server-mediated only
- Gemini 2.5 Flash-Lite for inline moderation classifier (same google-genai SDK already in stack)
- Cloudflare CSAM Scanning Tool for hash check (statutory 18 U.S.C. § 2258A)
- Logfire owns span tracing; Sentry `traces_sample_rate=0` to prevent double-instrumented spans
- Single Uvicorn worker locked (`--workers 1`); asyncpg pool max_size=10
- BYTEA for centroid storage (identical bytes round-trip as v1.0 BLOB) — **no pgvector** at v1.1
- `METADATA_BACKEND` and `STORAGE_BACKEND` feature flags for migration-window rollback
- `OFFLINE_DEMO=true` must work end-to-end across all v1.1 deps (firewalled CI smoke test gates)

### Pending Todos

**Feature track decisions:**
- [ ] Decision: censoring approach (automated / human / hybrid) — blocks feature-track censoring
- [ ] Decision: permissions gate flow (require all permissions vs. allow no-location with reduced clustering weight) — blocks location/permissions feature
- [ ] Decision: custom engagement signal design — blocks non-mando custom signal

**Backbone track pre-flight:**
- [ ] Run Vercel Blob AsyncBlobClient (vercel 0.5.8) spike before Phase 10 planning — bleeding-edge SDK
- [ ] Benchmark Gemini 2.5 Flash-Lite latency on actual v1.0 staged demo dataset before Phase 11 planning
- [ ] Start Cloudflare CSAM Scanning Tool / NCMEC approval application (unknown lead time) before Phase 11 scheduling

**Carry-overs:**
- [ ] Re-run calibration notebook against parent-clustered code path (from v1.0 deferred)
- [ ] Resolve `montage-not-updating` debug session (from v1.0 deferred)

### Blockers/Concerns

None blocking the active phase (`01-comments-and-sharing` ready to execute; Phase 10 backbone awaiting spike).

### Risks Being Tracked

- **Anonymous comments → spam/harassment with no identity lever.** Mitigation: rate limits via session UUID + content filter. Real risk; surface in pitch.
- **Web Share API support quirks on desktop.** May need fallback for non-supporting browsers (we picked Web Share only — re-evaluate if support gaps bite).
- **Phase numbering inconsistency.** Backbone uses 8-13; feature track restarted at 01. Reconcile during a planning cleanup pass.

## Deferred Items (from v1.0 — still open)

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| debug | montage-not-updating | investigating | 2026-04-27 |
| uat_gap | Phase 04 — 04-HUMAN-UAT.md | partial (3 pending scenarios) | 2026-04-27 |
| verification_gap | Phase 03 — 03-VERIFICATION.md | human_needed | 2026-04-27 |
| verification_gap | Phase 04 — 04-VERIFICATION.md | human_needed | 2026-04-27 |
| todo | recalibrate-post-parent-flip.md | medium priority | 2026-04-27 |

## Session Continuity

**Last session ended:** 2026-04-28 — pulled main, merged backbone (phases 8 + 9 shipped) into feature branch.

**Next action (feature track):** Execute `phases/01-comments-and-sharing/01-PLAN.md` — Wave 1 backend skeleton, then Wave 2 UI, then Wave 3 share + public route. Roan owns all waves.

**Next action (backbone track):** Liam to plan Phase 10 (Vercel Blob migration) once spike + dependency context cleared.

**Key files to load on resume:**

- `.planning/phases/01-comments-and-sharing/01-CONTEXT.md` — feature scope, decisions, open questions
- `.planning/phases/01-comments-and-sharing/01-PLAN.md` — task breakdown
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` — backbone Phase 9 context (just shipped)
- `.planning/PROJECT.md` — v1.1 active scope (both tracks), anonymity constraint, nomenclature
- `.planning/ROADMAP.md` — full v1.1 backlog

---
*Last updated: 2026-04-28 after merging main → feature/comments-and-sharing*

---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Public-Launch-Ready Backbone
status: planning
stopped_at: Phase 9 context gathered
last_updated: "2026-04-28T20:14:43.206Z"
last_activity: 2026-04-28
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 100
---

# Project State: Newz

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-04-27)

**Core value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent segment.
**Current focus:** Phase 08 — observability-scaffolding

## Current Position

Phase: 9
Plan: Not started
Status: Ready to plan
Last activity: 2026-04-28

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed (v1.1): 0
- Average duration: —
- Total execution time: 0h

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 8. Observability Scaffolding | 0/TBD | — | — |
| 9. Postgres Migration | 0/TBD | — | — |
| 10. Vercel Blob Migration | 0/TBD | — | — |
| 11. Moderation Gate | 0/TBD | — | — |
| 12. Reactive Reporting + Admin Queue | 0/TBD | — | — |
| 13. Observability Deepening + OFFLINE_DEMO Audit | 0/TBD | — | — |
| 08 | 3 | - | - |

*Updated after each plan completion.*

## Accumulated Context

### Locked Decisions (v1.1 — see PROJECT.md Key Decisions for full list)

- Neon Postgres over Supabase (avoid Supabase Auth pressure on anonymity-by-default)
- asyncpg + Alembic; **no SQLAlchemy ORM** during migration
- Vercel Blob (committed in PROJECT.md); **no direct browser PUT** — server-mediated only
- Gemini 2.5 Flash-Lite for inline moderation classifier (same google-genai SDK already in stack)
- Cloudflare CSAM Scanning Tool for hash check (statutory 18 U.S.C. § 2258A)
- Logfire owns span tracing; Sentry `traces_sample_rate=0` to prevent double-instrumented spans
- Single Uvicorn worker locked (`--workers 1`); asyncpg pool max_size=10
- BYTEA for centroid storage (identical bytes round-trip as v1.0 BLOB) — **no pgvector** at v1.1
- `METADATA_BACKEND` and `STORAGE_BACKEND` feature flags for migration-window rollback
- `OFFLINE_DEMO=true` must work end-to-end across all v1.1 deps (firewalled CI smoke test gates)

### Pending Todos

- [ ] Run Vercel Blob AsyncBlobClient (vercel 0.5.8) spike before Phase 10 planning — bleeding-edge SDK
- [ ] Benchmark Gemini 2.5 Flash-Lite latency on actual v1.0 staged demo dataset before Phase 11 planning
- [ ] Start Cloudflare CSAM Scanning Tool / NCMEC approval application (unknown lead time) before Phase 11 scheduling
- [ ] Confirm asyncpg + Neon TLS / sslmode=require interaction before Phase 9 cutover

### Blockers/Concerns

None.

### v1.0 Risks Resolved

(Hackathon shipped — v1.0 risks resolved or no longer load-bearing.)

## Deferred Items

Items acknowledged and carried forward from v1.0 milestone close on 2026-04-27:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| debug | montage-not-updating | investigating | 2026-04-27 |
| uat_gap | Phase 04 — 04-HUMAN-UAT.md | partial (3 pending scenarios) | 2026-04-27 |
| verification_gap | Phase 03 — 03-VERIFICATION.md | human_needed | 2026-04-27 |
| verification_gap | Phase 04 — 04-VERIFICATION.md | human_needed | 2026-04-27 |
| todo | recalibrate-post-parent-flip.md | medium priority | 2026-04-27 |

## Session Continuity

Last session: 2026-04-28T20:14:43.202Z
Stopped at: Phase 9 context gathered
Resume file: .planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md

---
*Last updated: 2026-04-28 — Phase 8 context gathered*

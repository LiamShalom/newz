---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Pilot MVP for funding (Public-Launch-Ready Backbone)
status: in_progress
last_updated: "2026-04-30T04:10:04.000Z"
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 20
  completed_plans: 13
  percent: 65
---

# Project State: Newz

## Project Reference

**Core Value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent montage.

**Current Focus:** Phase 11 — moderation-gate-gemini-flash-lite-csam-hash

- **Backbone (Liam):** Phase 9 (Postgres) shipped; Phase 10 (Vercel Blob) up next.
- **Feature (Roan):** Phase `01-comments-and-sharing` shipped 2026-04-28 (pending real-iPhone UAT — T4.1–T4.4).

## Current Position

Phase: 11 (moderation-gate-gemini-flash-lite-csam-hash) — EXECUTING
Plan: 1 of 7
| Field | Value |
|-------|-------|
| Active Milestone | v1.1 Pilot MVP for funding (Public-Launch-Ready Backbone) |
| Active Phases | Backbone: 11 next (Moderation Gate) · Feature: `01-comments-and-sharing` (shipped, pending iPhone UAT) |
| Status | Backbone phases 8 + 9 + 10 shipped; feature track Phase 01 shipped |
| Workflow | Two tracks: backbone uses sequenced phases (8-13); feature track uses per-feature GSD |

```
[███████░░░░] ~75% — backbone 3/6 (8, 9, 10 shipped); feature 0/N (01 ready)
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
- CSAM detection: classifier-only for pilot (Gemini `csam` category routes to hard-block + `reported_csam` preservation per § 2258A). Real hash vendor (Thorn / PhotoDNA / Hive) + automated NCMEC CyberTipline reporting deferred post-pilot. Cloudflare CSAM Scanning Tool DROPPED (CDN-cache-passive image-only feature, not a programmatic video API — Phase 11 research finding 2026-04-29).
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
- [ ] (POST-PILOT, before public launch) Pick CSAM hash vendor (Thorn Safer Match for video / PhotoDNA Cloud Service for images / Hive) and wire automated NCMEC CyberTipline reporting. Pilot ships classifier-only detection per Phase 11 reconciliation 2026-04-29.
- [ ] Retire SQLite (`db_sqlite.py`) once Neon cutover stabilizes. Mechanical: delete file, simplify `backend/db.py` to direct Postgres import, drop `aiosqlite` from requirements. Strategic: decide what `OFFLINE_DEMO=true` does without SQLite — in-memory stub vs. retire the flag entirely. Owner: Liam. Phase 01 (comments) added parallel SQLite + Postgres CRUD per current dispatcher contract; both go away together.

**Carry-overs:**

- [ ] Re-run calibration notebook against parent-clustered code path (from v1.0 deferred)
- [ ] Resolve `montage-not-updating` debug session (from v1.0 deferred)

### Blockers/Concerns

None blocking the active phase (`01-comments-and-sharing` ready to execute; Phase 10 backbone awaiting spike).

### Documented Overrides

- **2026-04-29 — Phase 11 plan-phase Decision Coverage Gate (step 13a) override.** Gate reported `0/29` D-NN IDs covered because the planner cited decisions inline (109 D-NN citations across 7 PLAN.md bodies) rather than in `must_haves` / `truths` YAML frontmatter. Plan-checker independently verified all 14 phase-specific checks pass, all 10 phase requirement IDs (MOD-01..08, MOD-10, PRIV-03) are covered, and the 2026-04-29 reconciliation header in CONTEXT.md explicitly supersedes 16 of the 29 decisions. Override rationale: tooling format mismatch, not a correctness gap. **verify-phase will re-surface this.** If verify-phase flags it as a real gap, batch-edit plan must_haves blocks to add D-NN citations OR tag superseded decisions as `[informational]` inline in CONTEXT.md.

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

**Last session ended:** 2026-04-29 — Phase 11 plan-phase researcher discovered Cloudflare CSAM Scanning Tool is a CDN-cache-passive image-only feature, not a programmatic video API. User confirmed Option 4 reconciliation: classifier-only CSAM detection for pilot (Gemini `csam` category in locked taxonomy → hard-block + `reported_csam` preservation per § 2258A). Real hash vendor + automated NCMEC reporting deferred post-pilot. CONTEXT.md L-02 / D-02 / D-16..18 / D-20 / D-22..28 reconciled to drop the CSAM-arm dispatcher; gate shape simplifies from CSAM-first-sequential-then-parallel to just parallel embed+gemini with cancel-when-embed-finishes. REQUIREMENTS.md MOD-04 amended (classifier-only acceptable for pilot), MOD-07 broadened (all hate + all violence soft-flag, no corroboration gating), MOD-09 corrected (1-year retention per 2024 REPORT Act, drop stale 90-day).

**Next action (backbone track):** Re-spawn `gsd-planner` for Phase 11 with reconciled CONTEXT.md (in-flight in current session).

**Next action (feature track):** Run Wave 4 verification (T4.1–T4.4) on a real iPhone + desktop browser for Phase 01 (comments + shares). See `phases/01-comments-and-sharing/01-SUMMARY.md`.

**Key files to load on resume:**

- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-CONTEXT.md` — Phase 11 locked decisions + canonical refs
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-DISCUSSION-LOG.md` — Phase 11 audit trail (alternatives considered)
- `.planning/phases/10-vercel-blob-migration/10-HUMAN-UAT.md` — Phase 10 UAT outcomes + spec amendments (private-store proxy)
- `.planning/phases/01-comments-and-sharing/01-SUMMARY.md` — feature track Phase 01 status
- `.planning/PROJECT.md` — v1.1 active scope (both tracks), anonymity constraint, nomenclature
- `.planning/ROADMAP.md` — full v1.1 backlog

---
*Last updated: 2026-04-29 — Phase 11 (Moderation Gate) context gathered, ready for /gsd-plan-phase*

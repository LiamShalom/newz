---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Pilot MVP for funding (Public-Launch-Ready Backbone)
status: ready_to_plan
last_updated: "2026-05-02T22:00:00.000Z"
last_activity: 2026-05-02 -- merged main into feature/feed-tabs-nearby-global; resolved conflicts in Feed.tsx, Masthead.tsx, STATE.md (Phase 03 + Phase 11 + Phase 14 + 6 quick tasks integrated). Phase 03 (Feed tabs Global/Nearby) shipped on branch; pending real-iPhone UAT before merge.
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 22
  completed_plans: 22
  percent: 100
---

# Project State: Newz

## Project Reference

**Core Value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent montage.

**Current Focus:** v1.1 Pilot MVP for funding — Phase 11 (Moderation gate) and Phase 14 (recompile-on-cluster-update) shipped on backbone; Phase 03 (Feed tabs Global/Nearby) shipped on feature track. Phase 12 (reactive reporting + admin queue) next on backbone.

- **Backbone (Liam):** Phase 8 (Observability) + Phase 9 (Postgres) + Phase 10 (Vercel Blob) + Phase 11 (Moderation gate) + Phase 14 (Recompile-on-cluster-update) shipped. Phase 12 next.
- **Feature (Roan):** Phase 01 (comments + shares) + Phase 02 (Safari permissions) + Phase 03 (Feed tabs Global/Nearby) shipped; SQLite retired in PR #11; UI polish landed. Next feature TBD.

## Current Position

Phase: 12
Plan: Not started
| Field | Value |
|-------|-------|
| Active Milestone | v1.1 Pilot MVP for funding (Public-Launch-Ready Backbone) |
| Active Phases | Backbone: 12 next (Reactive Reporting + Admin Queue) · Feature: 01 + 02 + 03 shipped, next TBD |
| Status | Backbone phases 8 + 9 + 10 + 11 + 14 shipped; feature track Phase 01 + Phase 02 + Phase 03 shipped; SQLite retired |
| Workflow | Two tracks: backbone uses sequenced phases (8-13); feature track uses per-feature GSD |

```
[█████████░] ~88% — backbone 5/6 (8, 9, 10, 11, 14 shipped); feature 3/N (01, 02, 03 shipped)
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
- [x] **Retire SQLite (`db_sqlite.py`)** — DONE 2026-04-29 (PR #11). Deleted db_sqlite.py + 6 SQLite-fixtured test files; collapsed `backend/db.py` to a single `from .db_postgres import *`; removed METADATA_BACKEND env var (no more dispatcher); rewrote `embed.py` and `keyframes.py` SQLite call sites to use the asyncpg pool; rewrote `/debug/dbstate` for postgres; dropped `aiosqlite` from requirements. OFFLINE_DEMO flag retained for Sentry/pre-warm/blob-client-skip; lifespan now skips pool init under OFFLINE_DEMO so the firewalled-CI smoke posture survives without a SQLite fallback. DB-touching routes 5xx under OFFLINE_DEMO — by design.

**Carry-overs:**

- [ ] Re-run calibration notebook against parent-clustered code path (from v1.0 deferred)
- [ ] Resolve `montage-not-updating` debug session (from v1.0 deferred)

### Blockers/Concerns

None blocking the active phase (`01-comments-and-sharing` ready to execute; Phase 10 backbone awaiting spike).

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260430-qya | SegmentCard eyebrow now shows `segment.location` instead of distance label | 2026-05-01 | 9b28e2b | [260430-qya-location-name-not-distance](./quick/260430-qya-location-name-not-distance/) |
| 260430-s4p | Masthead bumped to z-30 so SegmentCard h2 titles can't bleed under the NewZ logo | 2026-05-01 | 0d7be87 | [260430-s4p-fix-header-transparency](./quick/260430-s4p-fix-header-transparency/) |
| 260430-smd | Optimistic navigation on upload — feed shows immediately with top-of-feed UploadProgressBar instead of blocking on recording screen | 2026-05-01 | c2c70b3 | [260430-smd-when-a-user-clicks-button-to-upload-vide](./quick/260430-smd-when-a-user-clicks-button-to-upload-vide/) |
| 260501-bet | Caption pipeline split into per-parent structured-evidence Gemini extraction + cluster-level Claude intent synthesis (signs/audio/affiliations → topic/why-it-matters) | 2026-05-01 | 769acc9 | [260501-bet-structured-evidence-cluster-intent-synth](./quick/260501-bet-structured-evidence-cluster-intent-synth/) |
| 260502-c55 | SegmentCard caption clamped to 2 lines with inline Read more / Show less toggle (only renders when text overflows) | 2026-05-02 | 12b9ade | [260502-c55-the-story-under-each-segment-should-only](./quick/260502-c55-the-story-under-each-segment-should-only/) |
| 260502-c4t | BottomTabBar selected tab now reads as a filled `bg-surface-elevated` pill with `aria-current="page"` + bumped icon strokes — selected vs unselected legible at small viewports | 2026-05-02 | 0714c23 | [260502-c4t-make-selected-tab-clearer-in-cam-feed-sw](./quick/260502-c4t-make-selected-tab-clearer-in-cam-feed-sw/) |
| 260502-h26 | `_sync_trim` re-encodes through libx264+AAC when source is not H.264 — fixes black-video-no-sound on iPhone Safari for Chromebook/desktop Chrome WebM uploads (per-angle URLs) | 2026-05-02 | (pending PR) | [260502-h26-trim-ios-codec-compat](./quick/260502-h26-trim-ios-codec-compat/) |

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

**Last session ended:** 2026-05-02 — Phase 03 (Feed tabs Global/Nearby) shipped on `feature/feed-tabs-nearby-global` and merged with `origin/main` to pull in Phase 11 (Moderation Gate) + Phase 14 (Recompile-on-cluster-update) + 6 quick tasks (qya/s4p/smd/bet/c55/c4t). Conflict resolution: kept FeedTabs/banner/filter logic; layered in main's `checkPermission` permission soft-check + `<UploadProgressBar />`; dropped `viewerLat/viewerLng` props on FeedShell (main removed distance display via 260430-qya); Masthead taken from main wholesale (its z-30 + 16 px gradient fade subsumes our z-30 fix). Branch ahead of main; awaiting real-iPhone UAT before merge.

**Next action (backbone track):** Plan Phase 12 (Reactive Reporting + Admin Queue). Phase 11's `_resume_pipeline()` is the re-entry hook for cleared unknown-tier clips.

**Next action (feature track):** Real-iPhone UAT for Phase 03 (sticky tab strip on iOS rubber-band scroll, location-denied path, banner copy, no UploadProgressBar overlap regression). Then merge PR. Pending UAT for Phase 01 (comments + shares) still open from prior session.

**Key files to load on resume:**

- `.planning/phases/03-feed-tabs-nearby-global/03-SUMMARY.md` — Phase 03 status + UAT checklist
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-VERIFICATION.md` — Phase 11 verifier report (status: human_needed; 3 HUMAN-UAT items pending)
- `.planning/phases/11-moderation-gate-gemini-flash-lite-csam-hash/11-HUMAN-UAT.md` — Railway smoke + frontend interstitial + latency benchmark items
- `.planning/phases/10-vercel-blob-migration/10-HUMAN-UAT.md` — Phase 10 UAT outcomes + spec amendments (private-store proxy)
- `.planning/phases/01-comments-and-sharing/01-SUMMARY.md` — feature track Phase 01 status
- `.planning/PROJECT.md` — v1.1 active scope (both tracks), anonymity constraint, nomenclature
- `.planning/ROADMAP.md` — full v1.1 backlog

---
*Last updated: 2026-05-02 — Phase 03 (Feed tabs Global/Nearby) shipped on feature branch + main merged, pending real-iPhone UAT*

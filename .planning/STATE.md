---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Pilot MVP for funding
status: in_progress
last_updated: "2026-04-27T00:00:00.000Z"
last_activity: 2026-04-27
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 9
  completed_plans: 2
  percent: 22
---

# Project State: Newz

## Project Reference

**Core Value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent montage.

**Current Focus:** v1.1 Pilot MVP for funding — Phase 01: Anonymous comments + shares (planning)

## Current Position

| Field | Value |
|-------|-------|
| Active Milestone | v1.1 Pilot MVP for funding |
| Active Phase | Phase 01 — Anonymous comments + shares |
| Active Plan | 01-01 — drafted, awaiting execution |
| Status | Planning complete, ready for build (UI work; backend stubbed/mocked first) |
| Workflow | Per-feature GSD — each backlog item is its own phase, no master sequence |

```
[██░░░░░░░░] 22% — 2/9 mando shipped (timeout #1, location #3); 1 in planning (#5)
```

## Accumulated Context

### Locked Decisions (carried forward from v1.0)

- React + Vite + TS + Tailwind 4 frontend; FastAPI + Uvicorn + Python 3.11 backend
- Twelve Labs Marengo 3.0 (`marengo3.0` lowercase) for video embeddings — non-negotiable
- Claude Agent SDK 0.1.68 for multi-agent compile (Sonnet for subagents, Haiku for Publisher)
- NumPy in-memory cosine; SQLite metadata; local FS for clip storage
- Vercel for FE; Railway for BE with persistent volume at `/data`
- Clustering unit = parent (asset-scope) Marengo embedding; children are compile-time slicing metadata
- compile_segment dispatches only when cluster has ≥2 distinct parent uploads
- ffmpeg libx264 ultrafast normalize-and-concat for stitching
- Gemini 2.5 Flash for vision-grounded captions

### Locked Decisions (new in v1.1)

- **Anonymous everywhere — including comments.** No accounts, no display names, ever. Anonymous session UUID may be used server-side for rate limiting only.
- **Per-feature GSD.** Each backlog item gets its own phase. No master sequenced roadmap.
- **Nomenclature:** videorecording (raw upload) / clip (Marengo embedding-space slice) / montage (final compiled output). Don't mix them up in code or docs.
- **Comments attach per-montage**, not per-clip or per-videorecording.
- **Roan = UI, Liam = backend.** Cross-domain features need explicit handoffs.

### Open Todos

- [ ] Decision: censoring approach (automated / human / hybrid) — blocks Mando #6
- [ ] Decision: permissions gate flow (require all permissions vs. allow no-location with reduced clustering weight) — blocks Mando #4 + #7
- [ ] Decision: custom engagement signal design — blocks Non-mando #3
- [ ] Carry-over: re-run calibration notebook against parent-clustered code path (from v1.0 deferred)
- [ ] Carry-over: resolve `montage-not-updating` debug session (from v1.0 deferred)

### Active Blockers

None for Phase 01 (comments + shares). Phase 01 backend work depends on Liam having capacity once UI is mocked.

### Risks Being Tracked

- **Anonymous comments → spam/harassment with no identity lever.** Mitigation: rate limits via session UUID + content filter. Real risk; surface in pitch.
- **Web Share API support quirks on desktop.** May need fallback for non-supporting browsers (we picked Web Share only — re-evaluate if support gaps bite).

## Deferred Items (from v1.0 — still open)

| Category | Item | Status |
|----------|------|--------|
| debug | montage-not-updating | investigating |
| uat_gap | Phase 04 — 04-HUMAN-UAT.md | partial (3 pending scenarios) |
| verification_gap | Phase 03 — 03-VERIFICATION.md | human_needed |
| verification_gap | Phase 04 — 04-VERIFICATION.md | human_needed |
| todo | recalibrate-post-parent-flip.md | medium priority |

## Session Continuity

**Last session ended:** 2026-04-27 — opened v1.1 Pilot milestone, scaffolded comments-and-sharing phase.

**Next action:** Execute `phases/01-comments-and-sharing/01-PLAN.md` — UI build of comments bottom-sheet (mobile) / popup (desktop) + Web Share API integration. Backend endpoints stubbed/mocked until Liam picks them up.

**Key files to load on resume:**

- `.planning/phases/01-comments-and-sharing/01-CONTEXT.md` — feature scope, decisions, open questions
- `.planning/phases/01-comments-and-sharing/01-PLAN.md` — task breakdown
- `.planning/PROJECT.md` — v1.1 active scope, anonymity constraint, nomenclature
- `.planning/ROADMAP.md` — full v1.1 backlog

---
*Last updated: 2026-04-27 after opening v1.1 milestone*

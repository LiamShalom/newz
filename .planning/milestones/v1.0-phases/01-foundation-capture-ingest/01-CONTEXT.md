# Phase 1: Foundation, Capture & Ingest - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Skeleton (FastAPI + React) + iOS-Safari camera flow (priming → record → retake → submit) + ingest endpoint that returns 202 fast and kicks off the (yet-to-be-built) pipeline via `asyncio.create_task`. End state: a real iPhone records a clip and watches it play back from a raw feed. **No AI in this phase.**

21 requirements: FND-01..05, CAP-01..10, ING-01..06.

</domain>

<decisions>
## Implementation Decisions

### Camera Capture Flow

- **D-01 FAB:** Bottom-center, big circular red (TikTok/Instagram pattern). Risks conflict with iOS Safari bottom toolbar; accept and verify on real iPhone.
- **D-02 Priming modal:** Gating, once per session. Tapping FAB opens the modal first; user taps "Continue" to trigger native permission prompts. Skipped on subsequent FAB taps in the same browser session.
- **D-03 Recording UI:** Ring-fill only around the stop button. No numeric counter. 30s hard cap (CAP-05) is enforced silently — visual urgency only via ring progress (color shift acceptable but not required).
- **D-04 Capture defaults:** Audio ON (mic permission requested), rear camera default. Speech is a Marengo signal we keep.
- **D-05 Retake/submit screen:** Full-screen autoplay-looping playback. Top-left **X** dismisses back to the camera (counts as retake). Single bottom **Submit** button (filled red, primary). Two buttons total — fewer than CAP-06 implies but the X is the implicit retake.
- **D-06 Camera-flip toggle:** Rear default; flip-to-front icon in the top-right of the camera view. ~10 lines via `getUserMedia` constraint swap.
- **D-07 Permission denial — BLOCK on both camera AND GPS:** Camera denied = blocking error screen with "Open Settings" link. GPS denied OR `POSITION_UNAVAILABLE` OR timeout = block the record (no null-GPS clips accepted in Phase 1). **This conflicts with locked CAP-07** ("5s timeout, never blocks") — see Open Conflicts below. **Caltech indoor demo risk explicitly accepted by Liam.**

### Pre-AI Feed UX

- **D-08 Feed shell:** Throwaway scrollable list of `<video>` tiles, newest-first. Phase 4 (FED-02) rebuilds the feed for real (TikTok-style vertical full-screen + AI segments). Phase 1 spends ~30-60min on this, not ~2hr.

### Claude's Discretion (within Phase 1 throwaway-feed scope)

- Empty state: simple "Tap red button to record" text. No animated arrow, no pre-seeded staged clip in Phase 1 (FED-05 staged-clip-fallback lands with Phase 5 / DEM-01).
- Tile content: `<video>` + relative timestamp ("4 min ago"). No location, no source-count, no "mine" badge in Phase 1.
- Feed refresh: navigate-back-from-camera triggers a refetch + a manual pull-to-refresh. No background polling timer (and no SSE — that's Phase 4 RTM-01..03).
- Anonymous session UUID timing: generate on first feed-page load, persist to `localStorage.session_id`. Send as request header on POST `/clips`. Not exposed in UI in Phase 1.
- Failed upload retry: localStorage queue (CAP-09) with exponential backoff, retried on next feed visit. No persistent toast UI in Phase 1.

### Folded Todos

None — STATE.md open todos already align with phase scope (`/gsd-plan-phase 1` is this work; `pip show twelvelabs` is a Phase 2 day-1 check; Agent SDK parallel syntax verification is Phase 4 prep).

</decisions>

<open_conflicts>
## Open Conflicts vs. Locked Constraints

These need resolution by the planner or by amending REQUIREMENTS.md before execution.

1. **CAP-07 vs. D-07** — CAP-07 says "5s timeout, never blocks." D-07 says "block on GPS denied/unavailable/timeout." **Resolution required:** either rewrite CAP-07 to match D-07 ("blocks unless GPS lock acquired within 5s") or revisit D-07. Current state per Liam: CAP-07 is being overridden.
2. **Pitfall #4 (KILL-DEMO, indoor GPS)** — D-07 leaves Caltech indoor demo unmitigated in Phase 1. The pitfall's documented mitigations (`?demo_location=` override, GPS soft-fail) are both deferred or rejected. **Accepted risk per Liam.** Workaround paths: outdoor demo, or pull DEM-05 (`?demo_location` query param) into Phase 1 if the risk reverses later.
3. **CLU-06 ("GPS weight collapses to 0 when unavailable")** is structurally moot for Phase 1 because Phase 1 will not accept null-GPS clips. Phase 3 can keep the fallback for backfill scenarios; flag for re-evaluation when Phase 3 is planned.

</open_conflicts>

<canonical_refs>
## Canonical References

**Downstream agents (researcher, planner, executor) MUST read these before planning or implementing.**

### Project context (must read fully)
- `.planning/PROJECT.md` — vision, anonymity load-bearing, key decisions, out-of-scope list
- `.planning/REQUIREMENTS.md` — 21 Phase 1 reqs (FND-01..05, CAP-01..10, ING-01..06) with full text
- `.planning/ROADMAP.md` §"Phase 1: Foundation, Capture & Ingest" — goal, depends-on, requirements list, 5 success criteria, phase-to-pitfall mapping
- `.planning/STATE.md` — locked decisions, open todos, accumulated context
- `CLAUDE.md` — stack hard-constraints, anonymity, iOS Safari demo target, demo strategy

### Research (load-bearing)
- `.planning/research/SUMMARY.md` — TL;DR load-bearing decisions, stack table, build-order checkpoints (esp. Checkpoints 0+1)
- `.planning/research/STACK.md` — version pins (twelvelabs 1.2.3, claude-agent-sdk 0.1.68, FastAPI 0.115, Vite 5, Tailwind 4)
- `.planning/research/ARCHITECTURE.md` — system shape, project structure (`backend/`, `frontend/`), Pattern 1 (fire-and-forget asyncio), SQLite schema, MIME ladder, MediaRecorder integration
- `.planning/research/PITFALLS.md` — Pitfalls #3 (iOS Safari MediaRecorder), #4 (indoor GPS — RISK ACCEPTED here), #7 (Marengo file format), #8 (session continuity), #9 (embed queue), #13 (mic permission)
- `.planning/research/FEATURES.md` — table-stakes UX list, anti-features

### External docs (consult during planning)
- MDN MediaRecorder + WebKit blog on iOS Safari codec support — for D-03/D-04/D-05 implementation
- FastAPI BackgroundTasks vs `asyncio.create_task` distinction — for ING-05 implementation
- Railway FastAPI deploy guide (persistent volume) — for FND-04
- Vercel Vite deploy + HTTPS — for FND-05
- `aiosqlite` WAL-mode docs — for ING-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
None — repo has only `.planning/` and `CLAUDE.md`. Phase 1 is greenfield.

### Established Patterns
None in code. Patterns are documented in `.planning/research/ARCHITECTURE.md` and need to be instantiated by Phase 1:
- Project layout: `backend/` (FastAPI monolith) + `frontend/` (Vite SPA), per ARCHITECTURE §"Recommended Project Structure"
- Fire-and-forget pipeline pattern (Pattern 1)
- SQLite schema (`clips`, `clip_embeddings`, `clusters`, `segments`) — Phase 1 only needs `clips` populated
- Local-FS clip storage at `/data/clips/{clip_id}.{ext}` served via FastAPI `StaticFiles`

### Integration Points
- POST `/clips` is the upstream entry to the entire AI pipeline — Phase 1 must already call `asyncio.create_task(run_pipeline(clip_id))` even though `run_pipeline` is a stub in Phase 1 (real embed lands in Phase 2). Establish the fire-and-forget pattern from day 1, not retrofit it later.
- SSE event-bus stub (`events.broadcast(...)`) should exist in Phase 1 even though the only event fired is `clip_added`. Phase 4 wires up the real SSE endpoint.
- Anonymous session UUID is set in localStorage on first load and sent on POST; backend stores it on the clip row but never uses it for identity (ING-06 invariant).

</code_context>

<specifics>
## Specific Ideas

- Bottom-center red FAB is explicitly TikTok/Instagram-shaped — visual reference is the standard "big red record button," not a Material FAB.
- Ring-fill recording counter is Instagram-style (silent visual urgency, no numeric overlay). Color shift toward orange/red near the cap is acceptable but not required.
- Retake screen has only **X** (top-left) and **Submit** (bottom). No explicit "Retake" word — the X carries that load.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within Phase 1 scope.

### Reviewed Todos (not folded)

None — STATE.md open todos didn't surface as Phase 1 candidates beyond what's already covered.

</deferred>

---

*Phase: 01-foundation-capture-ingest*
*Context gathered: 2026-04-24*

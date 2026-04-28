# Phase 04: Multi-Agent Compile + Real-Time Feed — Planning Summary

**Planned:** 2026-04-25
**Phase:** 04-multi-agent-compile-real-time-feed
**Status:** Plans written, not yet executed

---

## Goal

When a cluster reaches size ≥ 2, a four-subagent Claude Agent SDK pipeline (Angle Selector, Caption Writer, Editor, Publisher) produces a published segment within a 30s wall-clock cap. The compiled feed re-renders live via SSE. Judges see an AP-wire caption, a source-count badge ("Compiled from N angles"), and a distance overlay — all driven by the live backend pipeline.

---

## Plans

| Plan | Wave | Scope | Requirements | Key Files |
|------|------|-------|--------------|-----------|
| 04-01 | 1 | Backend: compile pipeline, SSE bus, DB migration, run trigger, demo seed | CMP-01..09, FED-05, RTM-01..03 | compile.py, compile_tools.py, db.py, events.py, app.py, run.py, seed/demo_segment.py |
| 04-02 | 2 | Frontend: Segment types, EventSource hook, distance formatter, FeedTile/Feed upgrade | FED-01..05, RTM-01..03 | useEventSource.ts, distance.ts, types.ts, FeedTile.tsx, FeedShell.tsx, Feed.tsx, api.ts |

**Wave 2 depends on Wave 1** — the frontend consumes `GET /feed` (segments shape) and `GET /events` (SSE endpoint) that Plan 01 delivers.

---

## Architecture Summary

```
Browser                              FastAPI Monolith
──────                              ────────────────
Feed.tsx                            POST /clips (202)
 └─ useEventSource(GET /events) ◀── ├─ embed_worker
 └─ on "segment_published"          ├─ cluster_worker
     └─ fetchSegments(GET /feed)    └─ if _should_compile:
                                         asyncio.create_task(compile_segment)
FeedTile                                   ├─ asyncio.wait_for(_run_agents, 30.0)
 ├─ <video autoPlay muted>                 │   ├─ angle-selector (sonnet) ─┐
 ├─ caption                               │   ├─ caption-writer (sonnet) ──┤ parallel
 ├─ distance overlay                       │   ├─ editor (sonnet)          │
 └─ "Compiled from N angles"              │   └─ publisher (haiku) ◀──────┘
                                           └─ on timeout: _save_fallback_segment
                                       db.insert_segment (ON CONFLICT updates)
                                       events.broadcast({type: "segment_published"})
                                                │
                                       GET /events ── EventSourceResponse(ping=15)
                                         └─ per-client asyncio.Queue(maxsize=64)
```

---

## Key Decisions (from RESEARCH.md)

| Decision | Rationale |
|----------|-----------|
| `claude-agent-sdk==0.1.68` with `agents={}` dict | Locked by CLAUDE.md; bundles CLI binary — no Node.js on Railway; subagent narrative is the pitch hook |
| `asyncio.wait_for(..., 30.0)` hard cap | CMP-06 non-negotiable; fallback writes chronological + generic caption |
| `sse-starlette==3.3.4` `EventSourceResponse` | Handles framing, ping, disconnect detection; already transitive dep |
| Compile trigger in `run.py._should_compile` | Keeps cluster.py pure; trigger easy to mock in tests |
| `insert_segment` with `ON CONFLICT(cluster_id) DO UPDATE` | CMP-09 re-compile safety; one segment per cluster |
| `set_compile_in_flight` atomic CAS via `cursor.rowcount` | Prevents double-fire when two clips arrive within milliseconds |
| `asyncio.Lock` on `_subscribers` list | Subscribe/unsubscribe are rare but must not race with broadcast |
| Broadcast outside any cluster/compile lock | Prevents yield-induced deadlock (Phase 3 pattern preserved) |
| FED-05: seed segment at `db.init()` when table empty | Feed never blank on first open; references Phase 5 placeholder clips |
| Frontend: one `EventSource` per tab mounted in `Feed.tsx` | HTTP/1.1 6-connection-per-domain limit; documented in useEventSource.ts |

---

## New Files

### Backend (Plan 01)
- `backend/pipeline/compile.py` (~200 lines) — 4-subagent pipeline, `compile_segment`, `_save_fallback_segment`
- `backend/pipeline/compile_tools.py` (~80 lines) — MCP `@tool` definitions, `newz_tools_server`
- `backend/seed/demo_segment.py` (~40 lines) — FED-05 seeder
- `backend/tests/test_compile.py` — mocked `query()` happy path
- `backend/tests/test_compile_timeout.py` — `asyncio.TimeoutError` → fallback path
- `backend/tests/test_events_sse.py` — subscribe, broadcast, unsubscribe lifecycle
- `backend/tests/test_segments_db.py` — 5 DB helper tests (round-trip, conflict, CAS, TTL, ordering)
- `backend/tests/test_feed_segments.py` — `GET /feed` returns segments shape

### Frontend (Plan 02)
- `frontend/src/hooks/useEventSource.ts` — EventSource wrapper + `ServerEvent` union type
- `frontend/src/distance.ts` — haversine + `distanceLabel` formatter

### Modified Files

**Backend:**
- `backend/db.py` — schema migration (2 columns + 1 UNIQUE index) + 7 new helpers
- `backend/events.py` — `_LOCK`, `subscribe()`, `unsubscribe()`
- `backend/app.py` — `GET /events`, `GET /feed` → segments, `_pre_warm_sdk`, `seed_demo_segment` in lifespan
- `backend/pipeline/run.py` — `_should_compile` + `asyncio.create_task(compile_segment(...))`
- `backend/requirements.txt` — `claude-agent-sdk==0.1.68`, `sse-starlette==3.3.4`

**Frontend:**
- `frontend/src/types.ts` — `Segment`, `ServerEvent` added
- `frontend/src/components/FeedTile.tsx` — renders `Segment` (caption, distance, age, badge)
- `frontend/src/components/FeedShell.tsx` — accepts `Segment[]`
- `frontend/src/views/Feed.tsx` — `useEventSource`, `fetchSegments`, refetch on `segment_published`
- `frontend/src/api.ts` — `fetchSegments(lat?, lng?)` replaces `fetchFeed`

---

## Wave Structure

```
Wave 1: Plan 04-01 (backend — autonomous)
  Task 1: DB migration + 7 helpers + compile_tools.py + requirements.txt
  Task 2: compile.py + events.py + app.py + run.py + demo_segment.py + 4 test files

Wave 2: Plan 04-02 (frontend — autonomous, depends on 04-01)
  Task 1: useEventSource.ts + distance.ts + types.ts additions
  Task 2: FeedTile.tsx + FeedShell.tsx + Feed.tsx + api.ts upgrade
```

---

## Key Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Sonnet 4.5 latency makes 4-subagent pipeline exceed 30s | HIGH | Orchestrator prompt explicitly says "run angle-selector AND caption-writer in parallel"; hard cap + fallback ensures demo never hangs; Wave 0 benchmark in RESEARCH.md assumption A1 |
| Agent SDK cold start adds 5-10s to first compile | HIGH | `_pre_warm_sdk` fires at lifespan startup parallel with Marengo pre-warm; uses minimal one-token query |
| Caption hallucination embarrasses demo | MEDIUM | Caption Writer prompt restricts to metadata only; ≤200 char cap limits surface; no participant counts or speculative verbs |
| Double-compile race on simultaneous uploads | MEDIUM | Atomic CAS `UPDATE ... WHERE compile_in_flight=0`; `cursor.rowcount==1` confirms lock; UNIQUE index on `segments.cluster_id` as second defense |
| SSE connection limit (HTTP/1.1, 6 per domain) | LOW | HTTP/2 on Railway lifts limit; one EventSource per tab enforced by architecture; RESEARCH.md open question 2 (verify HTTP/2 with `curl -v --http2`) |
| `ordered_clip_ids[0]` not found on Railway (Phase 4 video URL) | LOW | Staged demo clips are placeholders until Phase 5; video shows black box; caption + badge render correctly |

---

## Success Criteria Checklist

- [ ] `POST /clips` → 202 in <100ms; compile fires as fire-and-forget (CMP-01)
- [ ] 4 subagents wired with correct model assignments: sonnet/sonnet/sonnet/haiku (CMP-02)
- [ ] Publisher has only `save_segment` in its tools list (CMP-03)
- [ ] Orchestrator prompt instructs parallel angle-selector + caption-writer (CMP-04)
- [ ] `segments` table gets a row with ordered_clip_ids, caption, location, source_count (CMP-05)
- [ ] `asyncio.wait_for(..., 30.0)` wraps `_run_agents`; fallback writes a row on timeout (CMP-06)
- [ ] `compile_started` and `segment_published` events emitted via SSE (CMP-07)
- [ ] Caption Writer prompt restricts to metadata-only; no hallucinated details (CMP-08)
- [ ] `set_compile_in_flight` CAS prevents double-compile; `ON CONFLICT DO UPDATE` handles re-compile (CMP-09)
- [ ] `GET /feed?lat&lng` returns segments sorted by proximity + recency (FED-01)
- [ ] FeedTile has `autoPlay loop` for TikTok-style autoplay (FED-02)
- [ ] FeedTile shows caption, distance label, age, source count badge (FED-03)
- [ ] RecordFAB visible on every feed view — no regression (FED-04)
- [ ] Pre-seeded demo segment visible on empty DB (FED-05)
- [ ] `GET /events` streams events via `EventSourceResponse(ping=15)` (RTM-01)
- [ ] `EventSource` browser auto-reconnects — no manual reconnect code (RTM-02)
- [ ] `segment_published` event triggers `refetchFeed()` in Feed.tsx (RTM-03)
- [ ] `npx tsc --noEmit` exits 0 (no TypeScript errors)
- [ ] All backend test files pass: `python -m pytest tests/ -x`

---

## Run Next

```
/gsd-execute-phase 04
```

Then `/clear` between plans for fresh context.

---
phase: 04-multi-agent-compile-real-time-feed
plan: 01
subsystem: backend
tags:
  - compile
  - sse
  - pipeline
  - sqlite
  - claude-agent-sdk
dependency_graph:
  requires:
    - 03-01 (cluster_worker, db.upsert_cluster, events.broadcast)
    - 03-02 (cluster.py composite score, CLUSTERS in-memory cache)
  provides:
    - compile_segment (4-subagent pipeline, 30s cap)
    - GET /events (SSE bus, EventSourceResponse)
    - GET /feed (segments with proximity sort)
    - db.insert_segment / fetch_recent_segments / get_segment_for_cluster
    - db.set_compile_in_flight / is_compile_in_flight (atomic CAS)
    - db.fetch_cluster_clips / get_cluster
    - seed_demo_segment (FED-05)
  affects:
    - 04-02 (frontend feed: now consumes GET /feed segments shape + GET /events)
tech_stack:
  added:
    - claude-agent-sdk==0.1.68 (4-subagent orchestration via single query() call)
    - sse-starlette==3.3.4 (EventSourceResponse with ping heartbeat)
  patterns:
    - asyncio.wait_for timeout wrapping async generator (30s hard cap)
    - asyncio.Lock on subscriber list (thread-safe SSE fan-out)
    - ON CONFLICT(cluster_id) DO UPDATE (idempotent segment upsert)
    - PRAGMA table_info check for SQLite ALTER TABLE idempotency
key_files:
  created:
    - backend/pipeline/compile.py
    - backend/pipeline/compile_tools.py
    - backend/seed/demo_segment.py
    - backend/tests/test_compile.py
    - backend/tests/test_compile_timeout.py
    - backend/tests/test_events_sse.py
    - backend/tests/test_feed_segments.py
    - backend/tests/test_segments_db.py
  modified:
    - backend/db.py
    - backend/events.py
    - backend/app.py
    - backend/pipeline/run.py
    - backend/requirements.txt
decisions:
  - "compile_segment is fire-and-forget via asyncio.create_task from run.py (not app.py HTTP handler) — keeps POST /clips at <100ms ING-02"
  - "Publisher subagent tools=['mcp__newz_tools__save_segment'] only — enforces CMP-03 write isolation"
  - "Fallback segment uses hardcoded 'Pasadena, CA' location — Caltech demo default; real reverse-geocode is out of scope"
  - "FED-05 demo seed uses zero-byte placeholder clips — Phase 5 filming task replaces bytes; FeedTile renders caption+source_count without real video"
  - "asyncio.Lock on _subscribers for subscribe/unsubscribe — broadcast() iterates outside lock to avoid deadlock with slow SSE consumers"
metrics:
  duration_minutes: 12
  completed_date: "2026-04-25"
  tasks_completed: 2
  files_changed: 13
---

# Phase 4 Plan 01: Compile Pipeline + SSE Bus + Segment Feed Summary

4-subagent Claude Agent SDK compile pipeline (angle-selector/caption-writer in parallel, editor, publisher) with 30s hard cap, idempotent SQLite segment upsert, asyncio.Queue SSE bus, and proximity-sorted segment feed replacing the raw-clips endpoint.

## What Was Built

### Task 1: DB Schema Migration + 7 Helpers + compile_tools.py + requirements.txt

**Schema migration (idempotent):**
- `PRAGMA table_info(clusters)` check before `ALTER TABLE clusters ADD COLUMN compile_in_flight INTEGER NOT NULL DEFAULT 0`
- `ALTER TABLE clusters ADD COLUMN last_compile_at REAL` (same idempotency check)
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_cluster_id ON segments(cluster_id)` — enforces one segment per cluster for ON CONFLICT upsert

**7 new db.py helpers:**

| Helper | SQL signature | Notes |
|--------|--------------|-------|
| `insert_segment(cluster_id, ordered_clip_ids, caption, location, source_count) -> str` | `INSERT ... ON CONFLICT(cluster_id) DO UPDATE ... RETURNING id` | Idempotent re-compile safe (CMP-09) |
| `fetch_recent_segments(limit=50) -> list[dict]` | `JOIN segments s JOIN clusters c ORDER BY s.created_at DESC` | Returns decoded `ordered_clip_ids` list (not JSON string) |
| `get_segment_for_cluster(cluster_id) -> dict | None` | `SELECT * FROM segments WHERE cluster_id=?` | Used by _run_agents to confirm Publisher wrote the row |
| `set_compile_in_flight(cluster_id, value, ttl_seconds=30.0) -> bool` | `UPDATE clusters SET compile_in_flight=1 WHERE ... AND (compile_in_flight=0 OR last_compile_at < now-ttl)` | Atomic CAS — rowcount==1 means lock acquired (T-04-01) |
| `is_compile_in_flight(cluster_id, ttl_seconds=30.0) -> bool` | `SELECT compile_in_flight, last_compile_at FROM clusters WHERE id=?` | Returns False when TTL expired even if flag=1 |
| `fetch_cluster_clips(cluster_id) -> list[dict]` | `SELECT id, path, lat, lng, ts FROM clips WHERE cluster_id=? ORDER BY ts ASC` | Used by angle-selector tool and fallback |
| `get_cluster(cluster_id) -> dict | None` | `SELECT * FROM clusters WHERE id=?` | Includes compile_in_flight, last_compile_at, member_count |

**compile_tools.py — 3 MCP @tool functions:**
- `get_cluster_clips(args)` — calls `db.fetch_cluster_clips`; available to angle-selector and caption-writer
- `get_clip_metadata(args)` — calls `db.get_clip`; available to angle-selector, caption-writer, editor
- `save_segment(args)` — calls `db.insert_segment`; available to publisher ONLY (CMP-03)
- `newz_tools_server = create_sdk_mcp_server(name="newz_tools", version="1.0.0", tools=[...])`

### Task 2: compile.py + events.py + app.py + run.py + demo_segment.py

**compile.py — 4-subagent pipeline:**

| Agent | Model | Tools | Role |
|-------|-------|-------|------|
| angle-selector | sonnet | get_cluster_clips, get_clip_metadata | Picks 2-4 best clips, orders establishing→action→reaction |
| caption-writer | sonnet | get_cluster_clips, get_clip_metadata | AP-wire caption ≤200 chars, grounded metadata only (CMP-08) |
| editor | sonnet | get_clip_metadata | Validates angle-selector ordering |
| publisher | haiku | save_segment ONLY | Calls save_segment exactly once (CMP-03) |

Orchestrator: `ClaudeAgentOptions(allowed_tools=["Agent", "mcp__newz_tools__*"], agents=AGENTS, max_turns=20, model="sonnet")`

Key invariants:
- `asyncio.wait_for(_run_agents(cluster_id), timeout=30.0)` — CMP-06 hard cap
- `_save_fallback_segment` checks `get_segment_for_cluster` first (idempotent even on partial timeout)
- `db.set_compile_in_flight(cluster_id, False)` in `finally` — always clears even on unhandled exception (T-04-08)
- `events.broadcast({"type": "segment_published", ...})` after finally — always fires

**events.py — SSE subscriber lifecycle:**
- `_LOCK = asyncio.Lock()` added at module level
- `subscribe()` acquires lock to append `Queue(maxsize=64)` to `_subscribers`
- `unsubscribe(q)` acquires lock to remove
- `broadcast()` shape unchanged — iterates `_subscribers` outside lock to avoid deadlock

**app.py changes:**
- `GET /events` — `EventSourceResponse(event_stream(), ping=15)`; generator checks `request.is_disconnected()` + `asyncio.wait_for(q.get(), 1.0)` in loop; `finally: await events.unsubscribe(q)` (RTM-01)
- `GET /feed` — replaced `{"clips": rows}` with `{"segments": rows}` from `db.fetch_recent_segments`; optional `?lat&lng` proximity sort via haversine (FED-01)
- `_pre_warm_sdk()` — `query(prompt="ok", options=ClaudeAgentOptions(model="sonnet"))` on startup; skipped when `OFFLINE_DEMO=true` or `ANTHROPIC_API_KEY` absent (logs warning, degrades gracefully)
- `lifespan` extended: `await seed_demo_segment()` + `asyncio.create_task(_pre_warm_sdk())`

**pipeline/run.py:**
- `_should_compile(cluster_id)`: checks `member_count >= 2` then calls `db.set_compile_in_flight(True)` (atomic CAS)
- `asyncio.create_task(compile_segment(cluster_id))` fires after cluster broadcast inside `run_pipeline` try block

**seed/demo_segment.py — FED-05:**
- Checks `SELECT COUNT(*) FROM segments`; no-op if any rows exist
- Inserts stub cluster (zero-vector centroid, centroid_lat=34.1377, centroid_lng=-118.1253)
- Calls `db.insert_segment(DEMO_CLUSTER_ID, DEMO_CLIP_IDS, caption, "Pasadena, CA", 3)`

## Test Coverage

| File | Tests | Coverage |
|------|-------|----------|
| test_segments_db.py | 5 | round-trip, conflict update, CAS atomicity, TTL expiry, ts ordering |
| test_compile.py | 1 | happy path: flag cleared in finally, segment_published broadcast |
| test_compile_timeout.py | 2 | timeout→fallback, exception→fallback; both clear flag + broadcast |
| test_events_sse.py | 3 | subscribe adds queue, broadcast delivers to all, unsubscribe removes |
| test_feed_segments.py | 2 | GET /feed returns "segments" key (not "clips"), with/without lat/lng |

Total new tests: 13. Full suite: 31 passed, 0 failed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] UploadFile.content_type property not settable in FastAPI 0.115**
- **Found during:** Task 1 test run (test_fetch_cluster_clips_ordered_by_ts)
- **Issue:** `upload.content_type = "video/mp4"` raises `AttributeError: property 'content_type' of 'UploadFile' object has no setter`
- **Fix:** Changed `_insert_test_clip` helper to pass `headers={"content-type": "video/mp4"}` to `UploadFile()` constructor (matching pattern already used in test_db_clusters.py)
- **Files modified:** backend/tests/test_segments_db.py
- **Commit:** 52b9220

**2. [Rule 1 - Bug] My edits initially landed in main repo /Users/roanhoward/Desktop/newz/backend/ instead of the worktree**
- **Found during:** Task 1 commit attempt — `git status` showed clean working tree
- **Fix:** Re-read all files from worktree path and wrote all changes to `/Users/roanhoward/Desktop/newz/.claude/worktrees/agent-a34b9a9813201a1d2/backend/` explicitly
- **Impact:** No lost work; all files correctly committed to worktree branch

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `stub_centroid = b"\x00" * (512 * 4)` | backend/seed/demo_segment.py | 36 | Zero-vector centroid for demo cluster FK stub; Phase 5 replaces with real clip embeddings |
| `DEMO_CLIP_IDS = ["demo-clip-1", "demo-clip-2", "demo-clip-3"]` | backend/seed/demo_segment.py | 12 | Placeholder clip IDs; real staged clips filmed at Caltech in Phase 5 |

These stubs are intentional (FED-05 design) and do not prevent the plan's goal: the feed returns a non-empty segment list on first boot. The caption, location, and source_count render correctly in FeedTile without real video.

## Open Questions for Wave 0 Benchmark (from RESEARCH.md)

1. **A1/A3 — Wall-clock latency:** Sonnet subagent latency 5-15s/agent is unverified. If `angle-selector + caption-writer` (parallel) + `editor` + `publisher` exceeds 30s, every compile will hit the fallback path. Wave 0 must measure `ResultMessage.duration_ms` with a real cluster before locking in the 4-agent design.

2. **CMP-04 parallel execution:** The orchestrator prompt says "Run angle-selector AND caption-writer IN PARALLEL" but whether Claude actually runs them concurrently depends on its planning. Wave 0 should log subagent invocation timestamps. If sequential, consider `asyncio.gather` with two separate `query()` calls (loses single-orchestrator narrative but guarantees parallelism).

3. **ANTHROPIC_API_KEY at Railway:** The key must be set as a Railway env var before demo. The `_pre_warm_sdk()` warning on startup will confirm if it's missing.

## Self-Check: PASSED

All 13 required files exist in the worktree. Both task commits (52b9220, e6cdfa3) exist in git log. 31 tests pass, 0 failures.

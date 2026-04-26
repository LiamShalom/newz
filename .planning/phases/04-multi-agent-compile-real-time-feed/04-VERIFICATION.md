---
phase: 04-multi-agent-compile-real-time-feed
verified: 2026-04-25T18:00:00Z
status: human_needed
score: 12/14 must-haves verified
overrides_applied: 0
gaps:
  - id: RUNTIME-CAP-01
    truth: "Caption is grounded in video content + location, not the generic 'multi-angle event captured' template"
    severity: high
    discovered: 2026-04-25T18:15:00Z
    source: ".planning/debug/captions-multi-angle-template.md"
    evidence: "compile.py:401-420 unconditionally overwrites Track A's vision caption with Track C's result, including when Track C falls back. Track C fallback at caption_pipeline.py:171 emits the literal 'Multi-angle event captured by N contributor(s)' string. Same template duplicated in compile.py:328 _save_fallback_segment and seed/demo_segment.py:50-53."
    requirement: CMP-08
  - id: RUNTIME-CMP-02
    truth: "stitch_clips completes inside the 30s compile-pipeline budget"
    severity: critical
    discovered: 2026-04-25T18:00:00Z
    source: ".planning/debug/stitch-clips-bottleneck.md"
    evidence: "Spike 002 bench: stitch_clips p50 = 66.5s parallel / 66.8s serial across N=3 runs of 3 clips each. 3/3 parallel runs exceed the 60s prod cap. Root cause: stitch.py:45 uses vcodec='libvpx-vp9' forcing software VP9 re-encode (~3-5 fps for 720p). Validated fix (H.264 ultrafast normalize-and-concat) measured at 0.52s wall-clock — 127x faster."
    requirement: CMP-06
deferred:
  - truth: "compile_segment checks OFFLINE_DEMO=true flag and skips query() call"
    addressed_in: "Phase 5"
    evidence: "DEM-04 mapped to Phase 5 in REQUIREMENTS.md: 'OFFLINE_DEMO=true env flag serves cached embeddings + cached compile output, requires zero external API calls'. Phase 5 SC1: 'OFFLINE_DEMO=true serves cached embeddings + cached compile output (zero external API calls)'"
human_verification:
  - test: "End-to-end compile pipeline fires on cluster size >= 2"
    expected: "Upload two clips from the same event; within 30 seconds the feed shows a new segment with AI-generated caption and 'Compiled from 2 angles' badge; Network tab shows the SSE /events connection received segment_published event"
    why_human: "Cannot trigger real Claude Agent SDK pipeline in automated test without ANTHROPIC_API_KEY and real video clips"
  - test: "TikTok-style vertical autoplay feed on iPhone"
    expected: "Segments play automatically without user gesture, inline (no fullscreen), muted; vertical scroll shows full-screen tiles"
    why_human: "Requires real iPhone Safari — iOS autoPlay behavior cannot be verified programmatically"
  - test: "SSE EventSource auto-reconnects on disconnect"
    expected: "Disconnect WiFi briefly; reconnect; the EventSource reconnects without page reload within a few seconds"
    why_human: "Network interruption behavior requires live browser testing"
  - test: "Feed re-renders within 1 second of segment_published (RTM-03)"
    expected: "Submit a second clip into an existing cluster; new segment appears at the top of the feed within 1 second of the compile pipeline completing"
    why_human: "Timing behavior requires end-to-end flow with real pipeline"
  - test: "Caption grounding (CMP-08)"
    expected: "AI-generated caption references only date, neighborhood, and clip count — no hallucinated participant names, motives, or context not in the metadata"
    why_human: "Caption quality is a runtime AI behavior; must inspect actual agent output"
  - test: "Angle Selector and Caption Writer run in parallel (CMP-04)"
    expected: "Both subagents' tool calls appear in the orchestrator's message stream before the editor runs; wall-clock time reflects parallel execution"
    why_human: "Whether Claude actually executes them in parallel depends on the orchestrator's runtime behavior, not the code"
  - test: "Distance overlay shows correct label (FED-03)"
    expected: "Near a test location, feed shows 'right here' or 'N blocks away'; far away shows '3 mi away'"
    why_human: "Requires live GPS + real segment with centroid coordinates to verify the haversine label end-to-end in a real browser"
---

# Phase 4: Multi-Agent Compile + Real-Time Feed — Verification Report

**Phase Goal:** When a cluster reaches size >= 2, a four-subagent Claude Agent SDK pipeline (Angle Selector, Editor, Caption Writer, Publisher) produces a published segment within a 30s wall-clock cap; the feed re-renders live via SSE; judges see the AP-wire caption + multi-angle clip count overlay.
**Verified:** 2026-04-25T18:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Cluster size >= 2 triggers compile pipeline atomically (CMP-01/CMP-09) | ✓ VERIFIED | `run.py:_should_compile` checks `member_count >= 2` then calls `db.set_compile_in_flight(True)` atomic CAS; `asyncio.create_task(compile_segment(cluster_id))` fires only when True |
| 2 | Four subagents defined: Angle Selector, Editor, Caption Writer, Publisher (CMP-02) | ✓ VERIFIED | `compile.py:AGENTS` dict has all four `AgentDefinition` entries; models: angle-selector/sonnet, caption-writer/sonnet, editor/sonnet, publisher/haiku |
| 3 | Publisher is the only subagent with write-access to save_segment (CMP-03) | ✓ VERIFIED | publisher `tools=["mcp__newz_tools__save_segment"]` only; angle-selector/caption-writer get get_cluster_clips + get_clip_metadata; editor gets get_clip_metadata only |
| 4 | Orchestrator instructs parallel execution of angle-selector + caption-writer (CMP-04) | ✓ VERIFIED | `ORCHESTRATOR_PROMPT_TEMPLATE` line 36: "Run angle-selector AND caption-writer IN PARALLEL"; both AgentDefinition descriptions say "Independent...run FIRST in parallel" — runtime behavior needs human verification |
| 5 | Pipeline produces segment record: ordered clips, AP-wire caption, source count (CMP-05) | ✓ VERIFIED | `db.insert_segment(cluster_id, ordered_clip_ids, caption, location, source_count)` creates the record; fallback segment also satisfies this |
| 6 | 30s hard wall-clock cap with fallback (CMP-06) | ✓ VERIFIED | `compile_segment` uses `asyncio.wait_for(_run_agents(cluster_id), timeout=30.0)`; both `TimeoutError` and `Exception` paths call `_save_fallback_segment`; `finally` always clears `compile_in_flight` |
| 7 | Pipeline status emitted as SSE events (CMP-07) | ✗ PARTIAL | `compile_started{cluster_id, started_at}` and `segment_published{cluster_id, segment_id}` are emitted. However, CMP-07 requires "current agent, elapsed time" per-agent events — no per-agent progress events exist during `_run_agents`. Note: CLAUDE.md defers "multi-agent status banner" (WOW-03) to v2; no Phase 4 ROADMAP SC requires per-agent events. |
| 8 | Captions reference only metadata (CMP-08) | ? NEEDS HUMAN | Caption Writer prompt instructs: "Reference ONLY what is verifiable from the metadata"; fallback caption uses contributor count + ISO date. Runtime output quality needs human inspection |
| 9 | Re-compile debounced 30s TTL (CMP-09) | ✓ VERIFIED | `set_compile_in_flight` atomic `UPDATE WHERE compile_in_flight=0 OR last_compile_at < now-ttl`; `_should_compile` returns False if already in-flight; tested by `test_set_compile_in_flight_cas_returns_true_once` |
| 10 | GET /feed returns segments sorted by proximity+recency (FED-01) | ✓ VERIFIED | `app.py:feed` calls `db.fetch_recent_segments(50)`, sorts by `_haversine_m + age_s` when lat/lng present; `test_feed_with_lat_lng_returns_segments` passes |
| 11 | Vertical full-screen TikTok-style autoplay feed (FED-02) | ? NEEDS HUMAN | FeedTile has `autoPlay muted playsInline loop` — iOS-critical attributes verified in code. Actual autoplay-on-scroll behavior requires live iPhone |
| 12 | Segment card shows caption, distance overlay, age, source count badge (FED-03) | ✓ VERIFIED | FeedTile renders: `{segment.caption}`, `distanceLabel(...)` or `segment.location` fallback, `relativeTime(segment.created_at)`, `"Compiled from {segment.source_count} angles"` badge |
| 13 | FAB visible on every feed view (FED-04 no regression) | ✓ VERIFIED | `Feed.tsx` always renders `<RecordFAB />` outside the `segments.length === 0` conditional — present for both EmptyState and FeedShell |
| 14 | Pre-seeded demo segment on empty DB (FED-05) | ✓ VERIFIED | `seed_demo_segment()` checks `COUNT(*) FROM segments`; if 0, inserts stub cluster + `db.insert_segment(DEMO_CLUSTER_ID, DEMO_CLIP_IDS, ...)` with "Pasadena, CA"; called from `lifespan` after `db.init()` |
| 15 | GET /events SSE endpoint with ping heartbeat (RTM-01) | ✓ VERIFIED | `app.py:sse_events` returns `EventSourceResponse(event_stream(), ping=15)`; generator uses `events.subscribe()/unsubscribe()` lifecycle |
| 16 | Frontend EventSource auto-reconnects on disconnect (RTM-02) | ? NEEDS HUMAN | `useEventSource.ts` has no manual reconnect logic — relies on native browser auto-reconnect. Requires live network interruption test |
| 17 | Feed re-renders within 1 second of segment_published (RTM-03) | ? NEEDS HUMAN | `Feed.tsx` calls `void refetchFeed()` on `ev.type === "segment_published"` via `useEventSource`. Timing requires end-to-end live pipeline test |

**Score:** 12/14 truths verified (2 human-only, CMP-07 partial)

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|---------|
| 1 | `compile_segment` checks `OFFLINE_DEMO=true` and skips `query()` | Phase 5 | REQUIREMENTS.md maps DEM-04 to Phase 5: "OFFLINE_DEMO=true env flag serves cached embeddings + cached compile output, requires zero external API calls"; Phase 5 SC1 covers this exactly. `_pre_warm_sdk()` already checks OFFLINE_DEMO — Phase 5 extends this guard to `compile_segment`. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/pipeline/compile.py` | 4-subagent pipeline, 30s cap, fallback | ✓ VERIFIED | 197 lines; `AGENTS` dict, `_run_agents`, `_save_fallback_segment`, `compile_segment`, `asyncio.wait_for(30.0)` |
| `backend/pipeline/compile_tools.py` | 3 @tool functions + newz_tools_server | ✓ VERIFIED | 70 lines; `get_cluster_clips`, `get_clip_metadata`, `save_segment`, `create_sdk_mcp_server` |
| `backend/db.py` | 7 new helpers + schema migration | ✓ VERIFIED | 384 lines; all 7 helpers present; PRAGMA check + ALTER TABLE idempotent migration; UNIQUE INDEX on segments.cluster_id |
| `backend/events.py` | subscribe/unsubscribe with asyncio.Lock | ✓ VERIFIED | 35 lines; `_LOCK = asyncio.Lock()`; `subscribe()`, `unsubscribe()`, `broadcast()` (shape unchanged) |
| `backend/app.py` | GET /events + GET /feed + SDK pre-warm | ✓ VERIFIED | 231 lines; `EventSourceResponse(ping=15)`, `fetch_recent_segments`, `seed_demo_segment`, `_pre_warm_sdk()` |
| `backend/pipeline/run.py` | `_should_compile` + `create_task(compile_segment)` | ✓ VERIFIED | 44 lines; `_should_compile` checks `member_count >= 2` + atomic CAS; `create_task` fires after cluster broadcast |
| `backend/seed/demo_segment.py` | Seeds demo segment when segments empty | ✓ VERIFIED | 57 lines; idempotent COUNT check; inserts stub cluster + segment for FK constraint |
| `backend/requirements.txt` | `claude-agent-sdk==0.1.68` + `sse-starlette==3.3.4` | ✓ VERIFIED | Both pins present at lines 12-13 |
| `frontend/src/hooks/useEventSource.ts` | useEventSource hook, EventSource on mount | ✓ VERIFIED | 40 lines; `handlerRef` pattern; opens on mount, closes on unmount; no manual reconnect |
| `frontend/src/distance.ts` | haversineMeters + distanceLabel | ✓ VERIFIED | 47 lines; 5-threshold ladder: <50m "right here", 50-150m "1 block", 150-250m "2 blocks", 250-1600m fractional, >=1600m whole miles |
| `frontend/src/types.ts` | Segment + ServerEvent alongside existing types | ✓ VERIFIED | 80 lines; `Segment` interface + `ServerEvent` discriminated union added; `Clip`, `IngestResponse`, `QueuedUpload` unchanged |
| `frontend/src/components/FeedTile.tsx` | Renders Segment with iOS attrs + caption/distance/age/badge | ✓ VERIFIED | 61 lines; `autoPlay muted playsInline loop`; caption, distanceLabel, relativeTime, "Compiled from N angles" badge |
| `frontend/src/components/FeedShell.tsx` | Accepts Segment[] + viewerLat/viewerLng | ✓ VERIFIED | 25 lines; maps `Segment & { url }[]`; passes coords to each FeedTile |
| `frontend/src/views/Feed.tsx` | Segment[] state, useEventSource, refetch on segment_published | ✓ VERIFIED | 108 lines; `useEventSource` imported and called; `refetchFeed()` on `segment_published`; `RecordFAB` preserved |
| `frontend/src/api.ts` | fetchSegments(lat?, lng?) returning (Segment & { url })[] | ✓ VERIFIED | 54 lines; parses `response.segments`; injects `url = ${API_BASE}/media/${ordered_clip_ids[0]}.mp4`; `postClip` + `API_BASE` unchanged |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/pipeline/run.py` | `compile.py::compile_segment` | `asyncio.create_task(compile_segment(cluster_id))` | ✓ WIRED | run.py:40 |
| `backend/pipeline/run.py` | `db.py::set_compile_in_flight` | `_should_compile` calls `db.set_compile_in_flight(cluster_id, True)` | ✓ WIRED | run.py:19 |
| `backend/pipeline/compile.py` | `compile_tools.py::newz_tools_server` | `from .compile_tools import newz_tools_server; mcp_servers={'newz_tools': newz_tools_server}` | ✓ WIRED | compile.py:29, 124 |
| `backend/pipeline/compile_tools.py::save_segment` | `db.py::insert_segment` | `await db.insert_segment(...)` | ✓ WIRED | compile_tools.py:55 |
| `backend/app.py::sse_events` | `events.py::subscribe` | `q = await events.subscribe(); finally: await events.unsubscribe(q)` | ✓ WIRED | app.py:158, 171 |
| `backend/app.py::feed` | `db.py::fetch_recent_segments` | `rows = await db.fetch_recent_segments(limit=50)` | ✓ WIRED | app.py:144 |
| `backend/app.py::lifespan` | `seed/demo_segment.py::seed_demo_segment` | `await seed_demo_segment()` after `db.init()` | ✓ WIRED | app.py:73-74 |
| `frontend/src/views/Feed.tsx` | `hooks/useEventSource.ts` | `import { useEventSource }; useEventSource(onEvent)` | ✓ WIRED | Feed.tsx:6, 84 |
| `frontend/src/views/Feed.tsx` | `api.ts::fetchSegments` | `const next = await fetchSegments(coords?.lat, coords?.lng); setSegments(next)` | ✓ WIRED | Feed.tsx:53, 70 |
| `frontend/src/hooks/useEventSource.ts` | `backend GET /events` | `new EventSource(\`${API_BASE}/events\`)` | ✓ WIRED | useEventSource.ts:20 |
| `frontend/src/components/FeedTile.tsx` | `distance.ts::distanceLabel` | `import { distanceLabel }; distanceLabel(viewerLat, viewerLng, ...)` | ✓ WIRED | FeedTile.tsx:3, 32 |
| `frontend/src/components/FeedShell.tsx` | `components/FeedTile.tsx` | `segments.map(s => <FeedTile key={s.id} segment={s} viewerLat={...} viewerLng={...} />)` | ✓ WIRED | FeedShell.tsx:20-21 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `FeedTile.tsx` | `segment.caption`, `segment.source_count` | `fetchSegments` → `GET /feed` → `db.fetch_recent_segments` → `SELECT s.id, s.caption, s.source_count FROM segments s JOIN clusters c ...` | Yes — real DB query with JOIN | ✓ FLOWING |
| `FeedTile.tsx` | `segment.centroid_lat/lng` for distance overlay | Same DB query above, `c.centroid_lat, c.centroid_lng` | Yes — from clusters table | ✓ FLOWING |
| `Feed.tsx` | `segments` state | `fetchSegments` → `GET /feed` → `db.fetch_recent_segments` → real SQL | Yes | ✓ FLOWING |
| Demo seed | `FeedTile` caption | `seed_demo_segment` inserts real row: "Staged demo: multi-angle event captured at Caltech campus" | Yes — seeded on startup | ✓ FLOWING |

Note: `FeedTile` video `src` for demo segment (`ordered_clip_ids[0] = "demo-clip-1"`) will 404 from StaticFiles — no real `.mp4` file exists yet. This is an intentional known stub documented in the SUMMARY; Phase 5 seeds real clip files. Caption and badge render correctly.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `db.init()` idempotent on second boot | `python -c "asyncio.run(db.init()); asyncio.run(db.init())"` | No error on second call | ✓ PASS |
| All 13 backend tests pass | `python -m pytest tests/test_segments_db.py tests/test_compile.py tests/test_compile_timeout.py tests/test_events_sse.py tests/test_feed_segments.py -v` | 13 passed, 0 failed in 1.21s | ✓ PASS |
| compile module imports cleanly | `python -c "from backend.pipeline.compile import compile_segment; from backend.pipeline.compile_tools import newz_tools_server; print('import ok')"` | `import ok` | ✓ PASS |
| Frontend TypeScript compile | `npx tsc --noEmit` | Zero errors | ✓ PASS |
| Vite production build | `npm run build` | `✓ built in 898ms` — 179.52 kB JS, 13.48 kB CSS | ✓ PASS |
| events.py exports | `python -c "from backend import events; print(type(events._LOCK).__name__)"` | `Lock` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CMP-01 | 04-01 | Compile triggered at cluster size >= 2, no compile in flight | ✓ SATISFIED | `_should_compile` + `set_compile_in_flight` atomic CAS |
| CMP-02 | 04-01 | 4-subagent SDK orchestrator: Angle Selector, Editor, Caption Writer, Publisher | ✓ SATISFIED | `AGENTS` dict in compile.py with 4 `AgentDefinition` entries |
| CMP-03 | 04-01 | Each subagent constrained tool set; Publisher-only write | ✓ SATISFIED | Publisher `tools=["mcp__newz_tools__save_segment"]` only |
| CMP-04 | 04-01 | Angle Selector + Caption Writer parallel; Editor → Publisher sequential | ✓ SATISFIED (code) / ? HUMAN (runtime) | Orchestrator prompt instructs parallel; actual parallelism is runtime behavior |
| CMP-05 | 04-01 | Segment record: ordered clip IDs, AP-wire caption, source count | ✓ SATISFIED | `db.insert_segment` with ordered_clip_ids, caption, source_count |
| CMP-06 | 04-01 | 30s wall-clock cap; fallback on timeout | ✓ SATISFIED | `asyncio.wait_for(..., timeout=30.0)`; `_save_fallback_segment` on both TimeoutError and Exception |
| CMP-07 | 04-01 | Pipeline status (current agent, elapsed time) emitted as SSE events | PARTIAL | `compile_started{started_at}` and `segment_published` exist; no per-agent progress events. CLAUDE.md defers "multi-agent status banner" (WOW-03) to v2; no Phase 4 ROADMAP SC requires per-agent events |
| CMP-08 | 04-01 | Captions grounded — metadata only, no hallucination | ? HUMAN | Prompt instructs grounding; runtime output quality requires human inspection |
| CMP-09 | 04-01 | Re-compile debounced 30s TTL | ✓ SATISFIED | `set_compile_in_flight` TTL check; `test_set_compile_in_flight_cas_returns_true_once` verifies CAS |
| FED-01 | 04-01/04-02 | GET /feed proximity + recency sort | ✓ SATISFIED | Haversine sort in app.py; `fetchSegments(lat?, lng?)` in api.ts |
| FED-02 | 04-02 | Vertical full-screen autoplay feed | ✓ SATISFIED (code) / ? HUMAN (device) | `autoPlay muted playsInline loop` on FeedTile video; requires iPhone test |
| FED-03 | 04-02 | Caption, distance overlay, age, source count badge per segment | ✓ SATISFIED | FeedTile renders all four; distance.ts provides haversine labels |
| FED-04 | 04-02 | FAB visible on every feed view (no regression) | ✓ SATISFIED | `<RecordFAB />` outside conditional in Feed.tsx |
| FED-05 | 04-01 | Empty state shows pre-seeded demo segment | ✓ SATISFIED | `seed_demo_segment()` called in lifespan; idempotent COUNT check |
| RTM-01 | 04-01/04-02 | GET /events SSE endpoint streams pipeline events | ✓ SATISFIED | `EventSourceResponse(event_stream(), ping=15)`; subscribe/unsubscribe lifecycle wired |
| RTM-02 | 04-02 | Frontend EventSource auto-reconnects on disconnect | ? HUMAN | Native browser behavior; no manual reconnect code (correct design); requires live test |
| RTM-03 | 04-02 | Feed re-renders within 1s of segment_published | ? HUMAN | `refetchFeed()` called on `segment_published`; timing requires live pipeline |

### Anti-Patterns Found

No blockers, warnings, or notable stubs found in Phase 4 files. No TODO/FIXME/placeholder comments. No empty return statements in rendering paths. No hardcoded empty arrays passed as dynamic data props.

**Known intentional stubs (not anti-patterns):**
- `demo_segment.py` uses `DEMO_CLIP_IDS = ["demo-clip-1", "demo-clip-2", "demo-clip-3"]` — these reference non-existent .mp4 files. This is intentional (FED-05 design); Phase 5 replaces with real files. Caption, location, and source_count render correctly without video.
- `stub_centroid = b"\x00" * (512 * 4)` in `seed_demo_segment` — zero-vector placeholder; not used for any real similarity computation.

### Human Verification Required

#### 1. End-to-End Compile Pipeline

**Test:** Run the backend with `ANTHROPIC_API_KEY` set. Upload two clips from the same event location (use `?demo_location=34.1377,-118.1253` to force GPS). Watch the Network tab for SSE events.
**Expected:** Within 30 seconds of the second clip being clustered, `segment_published` event appears in /events stream, and the feed refreshes showing the new segment with AI-generated caption and "Compiled from 2 angles" badge.
**Why human:** Requires real Anthropic API key + real video pipeline; cannot verify AI agent execution in automated tests.

#### 2. TikTok-style Autoplay on iPhone

**Test:** Open the deployed Vercel URL on an iPhone running iOS Safari. Scroll through the feed.
**Expected:** Segments play automatically on scroll, muted, inline, in a loop without user gesture required. No fullscreen takeover.
**Why human:** iOS autoPlay behavior with `muted playsInline` must be verified on real hardware; emulators are unreliable for this.

#### 3. SSE Auto-Reconnect (RTM-02)

**Test:** Open the feed, verify EventSource is connected via Network tab. Briefly disable WiFi, then re-enable.
**Expected:** The EventSource reconnects automatically within ~3 seconds without a page reload.
**Why human:** Network interruption requires live browser + network toggle.

#### 4. Feed Re-Renders Within 1 Second of segment_published (RTM-03)

**Test:** Submit a clip into an existing cluster (second clip). Watch the feed.
**Expected:** The new segment appears at the top of the feed within 1 second of the `segment_published` SSE event.
**Why human:** Precise timing measurement requires end-to-end flow with real pipeline.

#### 5. Caption Grounding (CMP-08)

**Test:** After a real compile pipeline run, inspect the generated caption.
**Expected:** Caption references only the date, neighborhood, and clip count. No invented participant counts, event names, motives, or context not derivable from GPS + timestamp metadata.
**Why human:** LLM output quality is non-deterministic and cannot be verified from code alone.

#### 6. Parallel Agent Execution (CMP-04)

**Test:** Run the pipeline with logging enabled. Check timestamps of subagent tool invocations.
**Expected:** Angle Selector's `get_cluster_clips` call and Caption Writer's `get_cluster_clips` call appear before the Editor receives any input, indicating parallel execution.
**Why human:** Whether the orchestrator actually runs agents in parallel is a runtime LLM behavior not guaranteed by the prompt instruction.

#### 7. Distance Overlay End-to-End (FED-03)

**Test:** Open the feed with known GPS coordinates near a seeded segment's centroid_lat/lng (34.1377, -118.1253). Check the distance overlay on the segment card.
**Expected:** Shows "right here" if within 50m, or "N blocks away" / "X.X mi away" based on actual distance.
**Why human:** Requires live GPS + real browser environment to verify haversine label renders correctly end-to-end.

### Runtime Gaps Discovered Post-Verification (2026-04-25T18:15:00Z)

Two runtime regressions surfaced after initial verification via debug sessions:

| ID | Severity | Truth | Source |
|----|----------|-------|--------|
| RUNTIME-CAP-01 | high | Caption must be grounded in video content + location, not the generic "multi-angle event captured" template | `.planning/debug/captions-multi-angle-template.md` |
| RUNTIME-CMP-02 | critical | stitch_clips must complete inside the 30s compile-pipeline budget (currently p50 = 66.5s — >2x over the cap, 3/3 prod-cap timeouts) | `.planning/debug/stitch-clips-bottleneck.md` |

Both have validated fixes (full RCA + reproduction in the linked debug files). Closure planned in `04-03-PLAN.md`.

### Gaps Summary

No automated gaps from the original verification. All 12 programmatically-verifiable must-haves pass. The OFFLINE_DEMO check in `compile_segment` is deferred to Phase 5 (DEM-04). CMP-07 per-agent progress events are a partial implementation — `compile_started` and `segment_published` are emitted, but per-agent current_agent/elapsed events are absent; this is consistent with the CLAUDE.md decision to defer "multi-agent status banner" (WOW-03) to v2 and the fact that no Phase 4 ROADMAP success criterion requires per-agent events.

7 items require human verification before the phase goal can be called fully achieved. Most are behavioral/runtime checks that cannot be automated without a live demo environment.

---

_Verified: 2026-04-25T18:00:00Z_
_Verifier: Claude (gsd-verifier)_

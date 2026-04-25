---
phase: 04-multi-agent-compile-real-time-feed
plan: "02"
subsystem: ui
tags: [react, typescript, sse, eventsource, feed, segment, distance, haversine]

# Dependency graph
requires:
  - phase: 04-multi-agent-compile-real-time-feed
    provides: "04-01 backend GET /events SSE bus and GET /feed returning Segment[] with ordered_clip_ids"

provides:
  - useEventSource hook opening a single EventSource('/events') on Feed mount, closing on unmount
  - distanceLabel formatter (haversine + 'right here' / 'N blocks away' / fractional miles / whole miles)
  - Segment and ServerEvent types in types.ts alongside existing Clip/IngestResponse/QueuedUpload
  - FeedTile rendering Segment with caption, distance overlay, age overlay, source-count badge, iOS-critical video attributes
  - FeedShell accepting Segment[] + viewerLat/viewerLng
  - Feed view using Segment[] state, fetchSegments, and useEventSource; refetches on segment_published event
  - fetchSegments(lat?, lng?) in api.ts replacing fetchFeed; injects synthetic url field per segment

affects:
  - 04-03 (Phase 5 demo hardening — OFFLINE_DEMO must serve segments not clips to this feed)
  - 05-demo-hardening (feed render path now Segment-based; staged demo clips need .mp4 files)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "handlerRef pattern for EventSource callbacks (stable ref, no effect re-run on every render)"
    - "GPS coords in useRef — fetched once on mount, available to fetch closures without re-triggering effects"
    - "Synthetic url field injected in api layer (not types.ts) — components stay path-agnostic"
    - "Discriminated union ServerEvent — exhaustive switch safe; unknown types ignored by feed handler"

key-files:
  created:
    - frontend/src/hooks/useEventSource.ts
    - frontend/src/distance.ts
  modified:
    - frontend/src/types.ts
    - frontend/src/components/FeedTile.tsx
    - frontend/src/components/FeedShell.tsx
    - frontend/src/views/Feed.tsx
    - frontend/src/api.ts

key-decisions:
  - "url field injected in fetchSegments (api.ts), not in Segment type — keeps types.ts free of backend URL construction logic"
  - "GPS stored in coordsRef (not state) — avoids triggering re-renders or effect re-runs on coord arrival"
  - "useEventSource callback in handlerRef — single EventSource per tab regardless of Feed re-renders"
  - "distanceLabel thresholds: <50m right here, 50-150m 1 block, 150-250m 2 blocks, 250-1600m fractional miles, >=1600m whole miles"

patterns-established:
  - "handlerRef pattern: keep latest callback in ref, run effect once — reusable for any event subscription"
  - "Segment & { url: string } intersection type: extend backend shape with client-only synthetic fields at the api layer"

requirements-completed:
  - FED-01
  - FED-02
  - FED-03
  - FED-04
  - RTM-01
  - RTM-02
  - RTM-03

# Metrics
duration: 2min
completed: "2026-04-25"
---

# Phase 4 Plan 02: Frontend Segment Feed + SSE Summary

**React feed upgraded from Clip[] to Segment[] with live EventSource SSE hook, haversine distance labels, and iOS-safe autoPlay video tiles**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-25T17:01:27Z
- **Completed:** 2026-04-25T17:03:21Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- EventSource hook (`useEventSource`) opens one persistent connection to `/events` on Feed mount, closes on unmount; browser auto-reconnects (RTM-02 free)
- `distanceLabel` formatter converts haversine meters to human-readable strings: "right here", "1 block away", "2 blocks away", "0.4 mi away", "3 mi away"
- `Segment` interface and `ServerEvent` discriminated union added to `types.ts` alongside all existing types
- `FeedTile` upgraded to render Segment: `autoPlay muted playsInline loop` video (iOS-critical), AP-style caption, distance/age overlay, "Compiled from N angles" badge
- `FeedShell` upgraded to accept `Segment[] + viewerLat/viewerLng`
- `Feed.tsx` upgraded: `Segment[]` state, `fetchSegments`, `useEventSource` fires `refetchFeed()` on `segment_published`, GPS in `coordsRef` for proximity sort, `RecordFAB` untouched (FED-04 no regression)
- `api.ts`: `fetchSegments(lat?, lng?)` replaces `fetchFeed`; parses `response.segments`; injects synthetic `url = ${API_BASE}/media/${ordered_clip_ids[0]}.mp4`; `postClip` and `API_BASE` exports unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: New files — useEventSource hook, distance.ts, Segment + ServerEvent types** - `5a62091` (feat)
2. **Task 2: Upgrade FeedTile, FeedShell, Feed, and api.ts to use Segment + EventSource** - `3776181` (feat)

**Plan metadata:** (committed separately below)

## Files Created/Modified

| File | Lines | Role |
|------|-------|------|
| `frontend/src/hooks/useEventSource.ts` | 40 | NEW — EventSource wrapper, handlerRef pattern, opens on mount, closes on unmount |
| `frontend/src/distance.ts` | 47 | NEW — haversineMeters + distanceLabel with 5-threshold ladder |
| `frontend/src/types.ts` | 80 | MODIFIED — added Segment interface + ServerEvent union (existing types unchanged) |
| `frontend/src/components/FeedTile.tsx` | 61 | MODIFIED — renders Segment; iOS-critical autoPlay muted playsInline loop; caption/distance/age/badge |
| `frontend/src/components/FeedShell.tsx` | 25 | MODIFIED — accepts Segment[] + viewerLat/viewerLng |
| `frontend/src/views/Feed.tsx` | 108 | MODIFIED — Segment[] state, fetchSegments, useEventSource, GPS coordsRef |
| `frontend/src/api.ts` | 54 | MODIFIED — fetchSegments replaces fetchFeed; injects url field; postClip + API_BASE unchanged |

## Decisions Made

- `url` field injected in `fetchSegments` (api.ts) via `Segment & { url: string }` intersection type, not added to `Segment` in `types.ts`. Rationale: keeps the types file backend-shape-only; URL construction is an API-layer concern.
- GPS stored in `coordsRef` (not `useState`) so coordinate arrival does not trigger re-renders or cause the `location.key` effect to re-run with stale GPS state.
- `useEventSource` uses `handlerRef` pattern: the `useEffect` runs once (empty dep array), the handler stays current via ref update on every render. This ensures one EventSource per tab regardless of Feed re-renders.
- `distanceLabel` thresholds calibrated to Caltech demo context: <50m "right here", 50-150m "1 block", 150-250m "2 blocks", 250-1600m fractional miles (`.toFixed(1)`), ≥1600m whole miles (`Math.round`).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. `npx tsc --noEmit` and `npm run build` both passed on first attempt after all 7 files were written.

## Threat Mitigations Applied

Per plan `<threat_model>`:
- **T-04-10 (Tampering — malformed SSE JSON):** `useEventSource` wraps `JSON.parse` in `try/catch`; malformed frames silently ignored; unknown event types don't match `segment_published` and are ignored.
- **T-04-12 (DoS — multiple EventSources):** `useEventSource` mounted only in `Feed.tsx`; documented in code comment; one EventSource per tab by architecture.
- **T-04-11, T-04-13, T-04-14:** Accepted risks per plan — no mitigations needed in this layer.

## Known Stubs

- `FeedTile` video `src` for demo segments (e.g. `ordered_clip_ids[0] = "demo-clip-1"`) will return a 404 from the backend StaticFiles mount until Phase 5 seeds real `.mp4` files. Video renders as black box; caption, distance, badge all render correctly. This is intentional and documented in the plan.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Frontend feed is fully wired to Segment type and SSE event bus
- Backend `GET /feed` must return `{ segments: Segment[] }` (04-01 deliverable) for end-to-end render
- Phase 5 (Demo Hardening): staged `.mp4` clip files must be seeded so `FeedTile` video renders non-black; `OFFLINE_DEMO=true` path must serve `segments` not `clips` from the feed endpoint

---
*Phase: 04-multi-agent-compile-real-time-feed*
*Completed: 2026-04-25*

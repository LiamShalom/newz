# Phase 03 — Summary: Feed Tabs (Global + Nearby)

**Phase:** 03-feed-tabs-nearby-global
**Branch:** `feature/feed-tabs-nearby-global`
**Owner:** Roan
**Status:** Shipped (pending real-iPhone UAT)
**Shipped:** 2026-05-02

## What Shipped

A two-tab segmented control above the feed: **Global** (default, recency-sorted, unfiltered) and **Nearby** (client-side adaptive-radius filter around the viewer's current location). The Nearby tab uses 5 km first, expands to 25 km if fewer than 5 segments match, and falls back to global with a dismissable banner if fewer than 1 segment matches at 25 km.

As a side effect of the redesign, the feed no longer sends viewer coordinates to the backend. `fetchSegments(lat?, lng?)` is now `fetchSegments()` — coordinates stay on the device for distance display only. The previous behavior leaked viewer coords into Vercel/CDN access logs on every feed fetch.

## Files

**New:**
- `frontend/src/feedFilter.ts` — pure adaptive-radius filter; exports `applyNearbyFilter` and the radius constants.
- `frontend/src/components/FeedTabs.tsx` — sticky text-only segmented control with coral underline on the active tab. ARIA tablist + arrow-key keyboard navigation. Disables Nearby when geolocation is unavailable.
- `.planning/phases/03-feed-tabs-nearby-global/{03-CONTEXT.md, 03-PLAN.md, 03-SUMMARY.md}`.

**Modified:**
- `frontend/src/types.ts` — added `FeedTab = "global" | "nearby"` discriminated string union.
- `frontend/src/api.ts` — `fetchSegments` no longer accepts or sends `lat`/`lng`.
- `frontend/src/views/Feed.tsx` — tab state with sessionStorage persistence, adaptive filter via `useMemo`, fallback banner, location-denied guard.

## Decisions Locked

1. **Two tabs only.** Global + Nearby. For You deferred — no signals to personalize on yet.
2. **Client-side filtering.** Backend untouched. `centroid_lat/lng` already present in the `/feed` response.
3. **Coords stay on device.** No more `?lat=...&lng=...` query string on `/feed`.
4. **Adaptive radius:** 5 km → 25 km → fallback to global with banner. Hyperlocal-first; doesn't strand pilot users in an empty tab.
5. **Tabs in component state, not URL.** No reload-on-switch.
6. **sessionStorage for tab persistence.** Survives reloads within a session, not across them. `localStorage` rejected as too close to identity.
7. **Default to Global.** Always populated; safe for funder demos in unfamiliar locations.

## Verification Done

- `pnpm tsc -b` clean.
- `pnpm vitest run` — all 31 existing tests pass; no regressions.
- `pnpm vite build` — production build clean (212 KB JS, 6.67 KB CSS gzipped — no meaningful bundle delta).
- Dev server starts, serves the SPA cleanly at `localhost:5173`.
- Grepped `frontend/src/` for any remaining `?lat=` / `?lng=` query params: none. Coords no longer leave the device on `/feed`.
- No `console.*` statements in new files. No `any` types.

## UAT Pending

Per CLAUDE.md: "iOS Safari is the primary surface. Verify on real iPhone before declaring camera/permission/upload work done." This phase doesn't touch camera or upload, but the tab strip's sticky behavior and the location-denied path need real-device confirmation:

- [ ] **iPhone Safari (production preview):**
  - Permission grant → Nearby tab enabled, switching feels instant.
  - Permission deny → Nearby tab visibly disabled, can't be selected.
  - Sticky tab strip survives iOS rubber-band scroll without flicker.
  - Banner renders correctly when nearby is empty (test by running app from a remote location vs. seeded clip locations).
- [ ] **iPhone Chrome:** regression check — no visual or behavioral differences from Safari.
- [ ] **MacBook Chrome / Safari:** keyboard arrow-key tab switch works; no layout shift.

## Surprises / Notes

- The existing feed *was* passing coords to the backend on every fetch — and the backend re-sorted by distance using haversine in Python. We assumed Global meant "recency only" all along; the actual behavior was distance-favoring whenever location was available. Dropping the coord param means Global is now genuinely recency-sorted as advertised. Visually subtle; semantically a real change.
- `centroid_lat` / `centroid_lng` are nullable on `Segment` (centroid can be null when GPS was unavailable for the first member clip). Filter excludes null-centroid segments from Nearby — they remain visible on Global.
- SSE events still broadcast globally. Nearby filtering is automatic via the `useMemo` re-running on `setSegments` — no special handling needed for incoming events outside the radius.

## Out of Plan / Deferred

- Backend distance filtering (`?radius_m=`) — premature at pilot scale; revisit at 10× current segment count.
- PostGIS spatial indexes — same.
- For You tab — separate phase, requires session-local interest signal design.
- Recent / Popular / Today temporal tabs (Non-mando #5) — separate phase.
- Reverse-geocoded labelled tabs ("Pasadena / Westwood") — backend reverse-geocoding dependency.
- WebSocket-based per-connection SSE filtering — not worth it at pilot scale.

## Commits on Branch

```
25f936a phase 03: scaffold CONTEXT and PLAN for feed tabs (global + nearby)
dfdf9fb feat(feed): add FeedTab type and adaptive nearby filter
3787907 feat(feed): add FeedTabs segmented control component
ccdb3b1 feat(feed): wire Global/Nearby tabs and stop leaking coords to backend
64d2411 chore(feed): refine tabs — drop dead coordsRef, cleaner filter result shape
```

---
*Drafted: 2026-05-02 from completed implementation*

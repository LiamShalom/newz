# Phase 03 — Feed Tabs (Global + Nearby)

**Milestone:** v1.1 Pilot MVP for funding
**Branch:** `feature/feed-tabs-nearby-global`
**Owner:** Roan
**Backlog ref:** New feature — distinct from Non-mando #5 ("Recent / Popular / Today" temporal tabs). This phase covers **geographic** tabs.
**Status:** Drafting

## Problem

The feed today is a single global recency-sorted stream. Every viewer sees the same content regardless of location. This collides with the project's hyperlocal positioning (PROJECT.md: *"Hyperlocal IS the differentiator"*) — when funders open the app for the first time in their city, they see whatever was most recently uploaded *anywhere*, which may be nothing relevant to them. A nearby filter surfaces the local moat directly.

A second issue: the current `/feed` call passes `lat` and `lng` as query params whenever geolocation is available (`api.ts:27`). This leaks viewer coordinates into Vercel/CDN access logs on every page load. Anonymity is load-bearing for Newz; coordinates leaving the device should be a deliberate choice, not a passive side effect.

## Decisions Made (locked)

1. **Two tabs, not three.** Global (default) + Nearby. For You is deferred — no signals to personalize on yet, and the design work (session-local interest tracking under the no-accounts constraint) is a phase of its own.
2. **Client-side filtering.** Backend stays untouched. The `/feed` response already includes `centroid_lat`/`centroid_lng` per segment. Filtering happens in React using the existing `haversineMeters` helper.
3. **Stop sending coords to the backend on `/feed`.** Both tabs fetch `/feed` with no query params. Nearby filtering is purely client-side. This removes the passive coordinate leak. Distance display (already in `SegmentCard`) continues to work — it reads viewer coords from `coordsRef` directly, not from the backend response.
4. **Adaptive radius for Nearby.** Start at 5 km. If fewer than 5 segments match, expand to 25 km. If still fewer than 1 segment, fall back to global with a banner ("No nearby clips yet — showing global"). Hyperlocal-first; doesn't strand users in an empty tab during the pilot when total segment counts are tiny.
5. **Tabs live above `FeedShell`, not in the `BottomTabBar`.** BottomTabBar is global app navigation (Camera ↔ Feed). Feed-internal segmentation is a separate UI concern and gets a separate component sticky-positioned below the Masthead.
6. **Default to Global.** A demo reviewer's location may have zero clips. Global is always populated. Tab choice persists in `sessionStorage` so a returning user keeps their selection within a tab/browser session — no `localStorage` (which crosses sessions and feels closer to identity).
7. **No backend change. No SSE change.** SSE continues to broadcast every event globally; the Nearby tab filters incoming events client-side using the same logic as the initial render.
8. **No URL routing for tabs.** Tab state is component state, not a route param. Avoids reload-on-switch and keeps the React Router surface small.

## Scope

**In:**
- `FeedTab` type (`"global" | "nearby"`).
- Pure filter helper that takes segments, viewer coords, and a radius and returns the subset within range.
- `FeedTabs.tsx` segmented-control component (Tailwind, matches existing brand tone).
- `Feed.tsx` integration: tab state, adaptive radius, empty-state banner when nearby is empty, sessionStorage persistence.
- Removal of the `lat`/`lng` query-param leak from `fetchSegments`.

**Out (deferred):**
- Backend distance filtering / `?radius_m=` param (premature at pilot scale; revisit at 10× current segment count).
- PostGIS / spatial indexes (same — premature).
- For You / personalized tab.
- Recent / Popular / Today temporal tabs (Non-mando #5; separate concern).
- City-bucketed "Pasadena / Westwood" labelled tabs (would require reverse geocoding on backend; out of scope).
- Per-connection SSE filtering (would require WebSocket; not worth it at pilot scale).

## Open Questions (non-blocking — call during build)

- **Should Nearby be hidden when the user has denied geolocation?** Default: hide the Nearby tab entirely if `coordsRef.current` is undefined after the 5 s permission window. Showing a tab the user can't use is bad UX. Confirm during build.
- **Should the radius constants live in a config file?** Default: inline as named constants in `Feed.tsx` for now. If we later want A/B-style radius experiments, lift them then.
- **Visual style for the tabs?** Default: text-only segmented control (uppercase, font-display tracking, coral underline on active) — matches existing `Masthead` brand voice. Pill-style would feel chat-app-y; this stays editorial.

## Constraints from PROJECT.md / CLAUDE.md

- **Anonymity is load-bearing.** Coords stay on device unless we have a deliberate reason to send them. This phase actively *removes* a passive leak (3.).
- **iOS Safari is the primary surface.** Tab switching must feel instant on a real iPhone — no jank, no layout shift. The sticky tab strip must survive iOS rubber-band scroll.
- **Reliability over polish.** Empty-state fallback is non-optional — funders cannot tap Nearby and see a blank screen.
- **Hyperlocal is the differentiator.** Nearby leans into the moat; this is *not* a regional/national feed (which is explicitly out of scope at PROJECT.md).
- **Roan-owned vertical slice.** Frontend only. No backend handoff to Liam.

## Dependencies / Sequence

- Independent of Liam's Phase 11 (moderation), 12 (reporting), 13 (observability).
- Depends only on the existing feed contract (already includes `centroid_lat/lng`). No backend change required for v1.
- Verification depends on the production preview backend being reachable for real-iPhone testing.

---
*Drafted: 2026-05-02 from feed code read + PROJECT.md scope check + brainstorm with user*

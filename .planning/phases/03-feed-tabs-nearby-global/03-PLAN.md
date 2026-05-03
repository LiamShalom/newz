# Phase 03 — Plan: Feed Tabs (Global + Nearby)

**Phase:** 03-feed-tabs-nearby-global
**Branch:** `feature/feed-tabs-nearby-global`
**Owner:** Roan (full feature — frontend only)
**See:** `03-CONTEXT.md` for problem, decisions, scope.

## Approach

Four sequenced waves. Wave 1 lays down pure, testable utilities (type + filter). Wave 2 builds the visual component in isolation. Wave 3 wires everything into `Feed.tsx` with the adaptive-radius behavior and removes the coord leak. Wave 4 is a focused refinement + security pass before push.

The order is deliberate — utilities first means the filter logic is correct before any UI depends on it, and the component first means we can lock the visual contract before touching `Feed.tsx` (the most-edited file in this phase).

## Task Breakdown

### Wave 1 — Types + filter helper

- [ ] **T1.1** — Add `FeedTab` discriminated type to `frontend/src/types.ts`: `"global" | "nearby"`. Single source of truth for tab values.
- [ ] **T1.2** — Add `frontend/src/feedFilter.ts` exporting:
  - `RADIUS_NEAR_M = 5_000`
  - `RADIUS_FAR_M = 25_000`
  - `MIN_NEARBY_FOR_NEAR = 5` — if fewer than this in 5 km, expand to 25 km
  - `MIN_NEARBY_FOR_FAR = 1` — if fewer than this in 25 km, fall back to global
  - `applyNearbyFilter(segments, viewerLat, viewerLng): { segments, effectiveRadiusM | null }` — pure function returning the filtered list and which radius applied (`null` means fell back to global). Skips segments with `null` centroid.
- [ ] **T1.3** — Reuse `haversineMeters` from existing `frontend/src/distance.ts`. No duplicate math.
- [ ] **T1.4** — Atomic commit: `feat(feed): add FeedTab type and adaptive nearby filter`.

### Wave 2 — `FeedTabs` component

- [ ] **T2.1** — Create `frontend/src/components/FeedTabs.tsx`. Props: `{ active: FeedTab; onChange: (t: FeedTab) => void; nearbyEnabled: boolean }`.
- [ ] **T2.2** — Visual: text-only segmented control. Uppercase, `font-display`, tracking `[0.08em]`. Active tab solid `text-ink-primary` with a coral gradient underline (`from-coral-light to-coral`); inactive `text-ink-primary/50`, no underline. Two `<button type="button">` elements in a `<div role="tablist">`.
- [ ] **T2.3** — When `nearbyEnabled === false`, render the Nearby button as `disabled`, dim it further (`text-ink-primary/30`), and add `aria-disabled` + `title="Enable location to see nearby clips"`. Don't hide it — invisible UI is more confusing than disabled UI.
- [ ] **T2.4** — Sticky positioning: `sticky top-[96px]` (Masthead is 96 px tall) + `bg-surface` so it doesn't bleed into video as the feed scrolls. `z-10` (one less than Masthead's `z-20`).
- [ ] **T2.5** — Accessibility: `role="tab"`, `aria-selected`, keyboard arrow-key navigation between tabs (left/right) using a tablist pattern.
- [ ] **T2.6** — Atomic commit: `feat(feed): add FeedTabs segmented control component`.

### Wave 3 — `Feed.tsx` integration + coord-leak removal

- [ ] **T3.1** — In `Feed.tsx`, add tab state. Initial value reads from `sessionStorage.getItem("feed_tab")` if valid, else `"global"`. Persist on change.
- [ ] **T3.2** — Compute `nearbyEnabled = coordsRef.current !== undefined`. (Tab is rendered only after the geolocation effect resolves — see T3.4.) When the user denies location, the tab stays disabled for that session.
- [ ] **T3.3** — Compute the `displayedSegments` based on `tab`:
  - `"global"` → raw `segments`.
  - `"nearby"` → `applyNearbyFilter(segments, lat, lng)` result (memoized with `useMemo` keyed on `segments` + coords + tab).
- [ ] **T3.4** — Render `<FeedTabs>` between `<Masthead>` and the feed body. Render only after `loaded === true` so it doesn't flash before initial fetch.
- [ ] **T3.5** — When `tab === "nearby"` and the filter falls back to global (`effectiveRadiusM === null`), render a banner above `FeedShell`: "No clips within 25 km — showing global." Coral-tinted, dismissable per-session via sessionStorage flag (`feed_nearby_banner_dismissed`).
- [ ] **T3.6** — **Remove the lat/lng query-param leak** in `frontend/src/api.ts` `fetchSegments(...)`. Drop the parameters from the function signature; both call sites in `Feed.tsx` already use `coordsRef` only for distance display. Update the JSDoc to note the change.
- [ ] **T3.7** — Update both `Feed.tsx` call sites to call `fetchSegments()` with no args.
- [ ] **T3.8** — Type-check (`pnpm tsc -b` via `pnpm build`) and verify nothing else imports `fetchSegments` with args (search). Atomic commit: `feat(feed): wire Global/Nearby tabs and stop leaking coords to backend`.

### Wave 4 — Refine, sweep, ship-ready

- [ ] **T4.1** — Memoization audit: ensure `applyNearbyFilter` doesn't re-run on unrelated re-renders. Confirm SSE-driven `setSegments` triggers exactly one filter recompute, not N.
- [ ] **T4.2** — SSE event handling: with the tab on Nearby, when a `segment_published` arrives for a segment outside the current radius, the user should *not* see it appear (via the `displayedSegments` memo). Confirm this is automatic — no special handling needed.
- [ ] **T4.3** — Edge cases:
  - User denies location → Nearby tab disabled; cannot be selected; if `sessionStorage` has stale `"nearby"`, fall back to `"global"` on mount.
  - Geolocation effect hasn't resolved yet on first paint → `nearbyEnabled = false`, tab disabled. Once it resolves, tab becomes enabled and re-renders once.
  - Empty `segments` array → render existing `<EmptyState/>` regardless of tab.
- [ ] **T4.4** — Final sweep:
  - **Cleanliness**: No dead imports. No commented-out code. Type-tight (no `any`).
  - **Efficiency**: Filter is O(n) over <50 segments — measured at < 0.1 ms in dev tools. Confirm.
  - **Security/anonymity**: Grep for any remaining `?lat=` / `?lng=` calls. Confirm coords are never sent to the backend in this phase. No PII in console logs.
- [ ] **T4.5** — Run dev server (`pnpm dev`), visually verify in Chrome:
  - Tab switching is instant.
  - Sticky position survives scroll without flicker.
  - Nearby empty-state banner renders correctly.
  - Permission denied → Nearby disabled.
- [ ] **T4.6** — Atomic commit: `chore(feed): refine tabs — memoization, edge cases, anonymity sweep`.

### Wave 5 — Ship

- [ ] **T5.1** — Write `03-SUMMARY.md` with what shipped, what we deferred, what surprised us.
- [ ] **T5.2** — Update `.planning/ROADMAP.md` — add a row in the feature track (Non-mando) for "Feed tabs (Global / Nearby)" marked shipped, distinct from the existing Recent/Popular/Today row.
- [ ] **T5.3** — Update `.planning/STATE.md` — bump cursor.
- [ ] **T5.4** — Atomic commit: `phase 03: SUMMARY + ROADMAP/STATE updates`.

## Done When

- Feed renders Global (default) and Nearby tabs above the segment list.
- Nearby uses adaptive radius (5 km → 25 km → global fallback with banner).
- `fetchSegments` no longer accepts or sends coordinates; coords stay on device for distance display only.
- Tab selection persists in sessionStorage; survives page reload within a session, doesn't cross sessions.
- Permission denied → Nearby tab disabled, can't be selected.
- iPhone Safari preview: tab switching feels instant; sticky tab strip stays put under scroll.
- ROADMAP updated, SUMMARY written, STATE cursor bumped.

## Out of Plan (deferred)

- Backend distance filtering / `?radius_m=` query param — premature at pilot scale.
- PostGIS spatial indexes — premature.
- For You tab — separate phase, depends on session-local interest signal design.
- Recent / Popular / Today temporal tabs (Non-mando #5) — separate phase.
- Reverse-geocoded labelled tabs ("Pasadena / Westwood") — backend dependency.
- WebSocket-based per-connection SSE filtering — not worth it at pilot scale.

---
*Drafted: 2026-05-02 from `03-CONTEXT.md` + Feed.tsx + FeedShell.tsx + api.ts + distance.ts code read*

---
id: 260430-qya
slug: location-name-not-distance
description: SegmentCard eyebrow shows distance ("0.4 mi away") instead of place name ("Pasadena, CA")
type: quick
status: planned
date: 2026-04-30
---

# Quick Task 260430-qya — Show place name instead of distance under videos

## Problem

`SegmentCard.tsx:77-83` prefers `distanceLabel(...)` over `segment.location` whenever viewer GPS is available. So the eyebrow reads "Captured from 4 angles near 0.4 mi away" instead of "...near Pasadena, CA". The user wants the place name (e.g. "University of Washington, Seattle") always.

Backend already provides `segment.location` as a reverse-geocoded place name (`backend/pipeline/caption_pipeline.py:337` — `await reverse_geocode(...)`). No backend work needed.

## Scope

Frontend-only. Single primary file edit.

## Tasks

### T1 — Use `segment.location` directly in SegmentCard (frontend)

**Files:**
- `frontend/src/components/SegmentCard.tsx` — remove distance branch, use `segment.location`; drop `viewerLat`/`viewerLng` props and the `distanceLabel` import.
- `frontend/src/components/FeedShell.tsx` — drop `viewerLat`/`viewerLng` props (only forwarded to SegmentCard).
- `frontend/src/views/Feed.tsx` — stop passing `viewerLat`/`viewerLng` to FeedShell. **Keep** `coordsRef` + the geolocation effect — `fetchSegments(lat, lng)` still uses them for backend sort/filter.
- `frontend/src/distance.ts` — delete (unused after this change; `distanceLabel` and `haversineMeters` have no other importers).

**Action:**
1. Replace the conditional `locationStr` calculation with `const locationStr = segment.location || null;`.
2. Remove `viewerLat`/`viewerLng` from SegmentCard props.
3. Remove the `import { distanceLabel } from "../distance";` line.
4. In FeedShell, remove the two prop fields and the two `viewerLat={...}` / `viewerLng={...}` forwards.
5. In Feed.tsx, remove the two `viewerLat=` / `viewerLng=` lines from the `<FeedShell>` call.
6. `git rm frontend/src/distance.ts`.

**Verify:**
- `npm --prefix frontend run typecheck` passes.
- `npm --prefix frontend test -- SegmentCard` passes (existing fixture has `location: "Pasadena, CA"` already).
- Grep `frontend/src` for `distance` → no remaining references.

**Done:** SegmentCard summary reads "Captured from N angles near {segment.location}, {time}" regardless of viewer GPS.

## Out of scope

- Backend reverse-geocoding precision (already produces "City, State" style — improving granularity to e.g. "University of Washington" is a separate concern in `caption_pipeline.py`).
- Removing `viewerLat`/`viewerLng` from `fetchSegments` API contract (still used for distance-sorted feed ordering server-side).

## must_haves

- `SegmentCard` no longer imports from `../distance`.
- `segment.location` is the only source for the location string in the summary line.
- `frontend/src/distance.ts` deleted.
- Frontend typecheck + tests green.

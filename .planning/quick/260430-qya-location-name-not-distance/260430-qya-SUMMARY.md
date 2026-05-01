---
id: 260430-qya
slug: location-name-not-distance
type: quick
status: complete
date: 2026-04-30
---

# Quick Task 260430-qya — Summary

## What changed

Frontend feed cards now display the reverse-geocoded place name (`segment.location`, e.g. "Pasadena, CA") in the eyebrow line instead of the haversine-derived distance ("0.4 mi away") whenever viewer GPS happened to be available.

Backend already produced `segment.location` via `caption_pipeline._reverse_geocode()`; only the frontend was overriding it with a distance label.

## Files

- `frontend/src/components/SegmentCard.tsx` — replaced the GPS-vs-fallback ternary with `const locationStr = segment.location || null;`. Removed `viewerLat` / `viewerLng` props and the `distanceLabel` import.
- `frontend/src/components/FeedShell.tsx` — dropped the `viewerLat` / `viewerLng` props (only forwarded into SegmentCard).
- `frontend/src/views/Feed.tsx` — stopped passing viewer coords to FeedShell. `coordsRef` + the geolocation effect remain because `fetchSegments(lat, lng)` still passes coords to the backend for feed ordering.
- `frontend/src/distance.ts` — deleted (unused after this change; no other importers of `distanceLabel` or `haversineMeters`).

## Verification

- `npx tsc --noEmit` (frontend): clean.
- `npx vitest run` (frontend): 31/31 tests pass — including the existing `SegmentCard.test.tsx` fixture which already used `location: "Pasadena, CA"`.
- `grep -rn "distance\|viewerLat\|viewerLng\|distanceLabel\|haversineMeters" frontend/src` → only an incidental `types.ts` doc comment about centroid coords for distance calc remains (still accurate; centroids are sent to backend via `fetchSegments`).

## Notes

- Backend reverse-geocode quality is unchanged; if you want "University of Washington, Seattle" instead of just a city/state pair, that's a separate change in `backend/pipeline/caption_pipeline.py` (and would also benefit the Gemini caption prompt that consumes the same string).
- `Segment.centroid_lat` / `Segment.centroid_lng` are kept on the type for backend distance-sort and any future use; they're just no longer consumed by the SegmentCard renderer.

/**
 * feedFilter.ts — pure adaptive-radius filter for the Nearby feed tab.
 *
 * Hyperlocal-first: 5 km radius. If too few segments match, expand to 25 km.
 * If still empty, signal a fall-back-to-global by returning effectiveRadiusM
 * = null. The Feed view renders a banner in that case.
 *
 * Segments missing centroid coords (centroid_lat or centroid_lng = null) are
 * excluded from Nearby — we cannot place them on the map, so they cannot be
 * "nearby".
 *
 * Haversine inlined (distance.ts was retired with the SegmentCard distance
 * label in quick task 260430-qya); this is the only remaining consumer.
 */

import type { Segment } from "./types";

function haversineMeters(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export const RADIUS_NEAR_M = 5_000;
export const RADIUS_FAR_M = 25_000;

/** Minimum count required before we accept the 5 km radius. */
export const MIN_NEARBY_FOR_NEAR = 5;

/** Minimum count required before we accept the 25 km radius. Below this we fall back to global. */
export const MIN_NEARBY_FOR_FAR = 1;

export interface NearbyFilterResult<T extends Segment> {
  /** Filtered list, or the original segments when falling back to global. */
  segments: (T & { url: string | null })[];
  /**
   * Which radius matched: 5_000, 25_000, or null when fallback-to-global
   * applied. The Feed view uses null to show a "nothing nearby — showing
   * global" banner.
   */
  effectiveRadiusM: number | null;
}

export function applyNearbyFilter<T extends Segment>(
  segments: (T & { url: string | null })[],
  viewerLat: number,
  viewerLng: number,
): NearbyFilterResult<T> {
  const withDistance = segments
    .map((s) => {
      if (s.centroid_lat === null || s.centroid_lng === null) return null;
      const d = haversineMeters(viewerLat, viewerLng, s.centroid_lat, s.centroid_lng);
      return { seg: s, d };
    })
    .filter((x): x is { seg: T & { url: string | null }; d: number } => x !== null);

  const within = (radius: number) =>
    withDistance.filter((x) => x.d <= radius).map((x) => x.seg);

  const near = within(RADIUS_NEAR_M);
  if (near.length >= MIN_NEARBY_FOR_NEAR) {
    return { segments: near, effectiveRadiusM: RADIUS_NEAR_M };
  }

  const far = within(RADIUS_FAR_M);
  if (far.length >= MIN_NEARBY_FOR_FAR) {
    return { segments: far, effectiveRadiusM: RADIUS_FAR_M };
  }

  return { segments, effectiveRadiusM: null };
}

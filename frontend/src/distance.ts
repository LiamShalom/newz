/**
 * distance.ts — haversine distance calculator and human-readable label formatter.
 *
 * "1 block ≈ 100m" approximation for hyperlocal display (FED-03).
 * No external geocoding API — inline math only (CLAUDE.md hard constraint).
 */

export function haversineMeters(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * Returns a human-readable distance string for display in FeedTile.
 * Examples: "right here", "1 block away", "0.4 mi away", "3 mi away"
 *
 * Thresholds:
 *   < 50m   → "right here"
 *   50-150m → "1 block away"
 *   150-250m → "2 blocks away"
 *   250m-1600m → "{X.X} mi away" (fractional)
 *   >= 1600m → "{N} mi away" (whole miles)
 */
export function distanceLabel(
  viewLat: number,
  viewLng: number,
  segLat: number,
  segLng: number,
): string {
  const m = haversineMeters(viewLat, viewLng, segLat, segLng);
  if (m < 50) return "right here";
  if (m < 150) return "1 block away";
  if (m < 250) return "2 blocks away";
  if (m < 1_600) return `${(m / 1_609).toFixed(1)} mi away`;
  return `${Math.round(m / 1_609)} mi away`;
}

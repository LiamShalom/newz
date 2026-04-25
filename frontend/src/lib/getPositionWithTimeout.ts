/**
 * D-07: GPS is BLOCKING in Phase 1. Resolve as a tagged union so callers can map
 * each failure mode to the matching PermissionErrorScreen state.
 *
 * CAP-07 conflict: CAP-07 says "5s timeout, never blocks." D-07 overrides — block on failure.
 */
export type PositionResult =
  | { kind: "ok"; lat: number; lng: number }
  | { kind: "denied" }
  | { kind: "unavailable" }
  | { kind: "timeout" }
  | { kind: "unsupported" };

export function getPositionWithTimeout(
  timeoutMs: number = 5000,
): Promise<PositionResult> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      resolve({ kind: "unsupported" });
      return;
    }
    let settled = false;
    const settle = (r: PositionResult) => {
      if (settled) return;
      settled = true;
      resolve(r);
    };

    // Wall-clock fallback in case the underlying API never fires (observed on some iOS
    // versions when permission is granted but the radio is asleep).
    const wall = setTimeout(() => settle({ kind: "timeout" }), timeoutMs + 250);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(wall);
        settle({
          kind: "ok",
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
      },
      (err) => {
        clearTimeout(wall);
        // err.code: 1 PERMISSION_DENIED, 2 POSITION_UNAVAILABLE, 3 TIMEOUT
        if (err.code === 1) settle({ kind: "denied" });
        else if (err.code === 2) settle({ kind: "unavailable" });
        else settle({ kind: "timeout" });
      },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}

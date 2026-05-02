/**
 * Soft-check primitive for browser permissions. Wraps `navigator.permissions.query`
 * so callers can decide whether to fire a prompt-triggering API (e.g.
 * `navigator.geolocation.getCurrentPosition`) without showing an unnecessary
 * dialog when the permission is already granted or already denied.
 *
 * iOS Safari notes:
 * - `navigator.permissions` is iOS 16+. Older Safari returns undefined — we
 *   resolve "unknown" so callers fall through to firing the actual API.
 * - The 'camera' / 'microphone' descriptors are iOS 16+ only and may return
 *   "prompt" even when the OS-level grant is already in place. Treat
 *   geolocation as the reliable case; treat camera/mic as best-effort.
 * - Even with state==='granted', iOS Safari can still re-prompt on a fresh
 *   session if the user has not upgraded the origin to "Allow" in Settings.
 *   The flag is a hint, not a guarantee.
 */

export type PermissionState = "granted" | "denied" | "prompt" | "unknown";

type QueryName = "geolocation" | "camera" | "microphone";

export async function checkPermission(name: QueryName): Promise<PermissionState> {
  if (typeof navigator === "undefined") return "unknown";
  const perms = navigator.permissions;
  if (!perms || typeof perms.query !== "function") return "unknown";
  try {
    const status = await perms.query({ name: name as PermissionName });
    return status.state as PermissionState;
  } catch {
    return "unknown";
  }
}

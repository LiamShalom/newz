// Domain types shared across views and components.
// Centralized here so Plan 04 (camera) and later phases reuse the same shape.

export interface Clip {
  id: string;
  /**
   * Path served by the backend StaticFiles mount, e.g. "/media/abc.mp4".
   * Server-emitted; treated as opaque on the client — never construct or parse
   * client-side. `fetchFeed` prefixes this with `API_BASE` if it's relative.
   */
  url: string;
  lat: number;
  lng: number;
  /** POSIX seconds; set client-side at submit time. */
  ts: number;
  /** POSIX seconds; set server-side at insert time. */
  created_at: number;
}

export interface IngestResponse {
  clip_id: string;
  status: "processing";
}

/**
 * Used by Plan 04 (camera) — declared here so types are centralized.
 * Blobs are not JSON-serializable, so the queue stores base64-encoded payloads.
 */
export interface QueuedUpload {
  /** Local UUID, distinct from server clip_id. */
  id: string;
  blobBase64: string;
  mimeType: string;
  lat: number;
  lng: number;
  ts: number;
  attempts: number;
  nextRetryAt: number;
}

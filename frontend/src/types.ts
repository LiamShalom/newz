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
  /** Phase 4: AP-wire headline written by Caption Writer subagent. */
  caption?: string;
  /** Phase 4: number of clips merged by the cluster ("4 angles"). */
  source_count?: number;
  /** Phase 4: reverse-geocoded neighborhood for the eyebrow. */
  neighborhood?: string;
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

/**
 * A compiled news segment produced by the 4-subagent pipeline (Phase 4, CMP-05).
 * Returned by GET /feed.
 */
export interface Segment {
  id: string;
  cluster_id: string;
  /** Ordered clip IDs chosen by Angle Selector + Editor subagents. */
  ordered_clip_ids: string[];
  /** AP-wire-style breaking-news headline (4-8 words). Written by Gemini caption pipeline. */
  title: string | null;
  /** AP-wire-style caption written by Caption Writer subagent (CMP-08). */
  caption: string;
  /** Human-readable location string, e.g. "Pasadena, CA". */
  location: string;
  /** Number of source clips compiled into this segment. */
  source_count: number;
  /** POSIX seconds; set server-side at insert time. */
  created_at: number;
  /** Cluster centroid coordinates for distance calculation (FED-03). Null when GPS unavailable. */
  centroid_lat: number | null;
  centroid_lng: number | null;
  /** Actual video file URL path (e.g. "/media/abc.webm"). Null for legacy/demo segments. */
  video_url: string | null;
  /** All ordered clip URL paths for sequential multi-angle playback. */
  video_urls: (string | null)[] | null;
}

/**
 * Anonymous comment on a montage (segment). Server never returns session_id —
 * if you ever see one client-side, that's an anonymity bug.
 */
export interface Comment {
  id: number;
  segment_id: string;
  text: string;
  /** POSIX seconds, server-side timestamp. */
  created_at: number;
}

/**
 * Discriminated union of all events emitted by GET /events (RTM-01).
 * Consumed by useEventSource hook in Feed.tsx.
 */
export type ServerEvent =
  | { type: "clip_added"; clip_id: string }
  | { type: "pipeline_progress"; clip_id: string; stage: "embedded" | "clustered" }
  | {
      type: "cluster_assigned";
      clip_id: string;
      cluster_id: string;
      is_new_cluster: boolean;
      member_count: number;
      score_breakdown: unknown;
    }
  | { type: "compile_started"; cluster_id: string; started_at: number }
  | { type: "segment_published"; cluster_id: string; segment_id: string }
  | { type: "pipeline_error"; clip_id: string; error: string }
  | { type: "comment_added"; segment_id: string; comment: Comment };

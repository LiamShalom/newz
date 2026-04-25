// Single source of truth for backend URL + headers.
// VITE_API_BASE is baked at build time on Vercel; falls back to localhost for dev.

import type { IngestResponse, Segment } from "./types";
import { getOrCreateSessionId } from "./session";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * Fetch compiled segments from GET /feed.
 * Passes viewer coordinates for proximity sort when available (FED-01).
 * Attaches a synthetic `url` field pointing to the first clip's video file
 * so FeedTile can render without knowing the backend path structure.
 */
export async function fetchSegments(
  lat?: number,
  lng?: number,
): Promise<(Segment & { url: string })[]> {
  let endpoint = `${API_BASE}/feed`;
  if (lat !== undefined && lng !== undefined) {
    endpoint += `?lat=${lat}&lng=${lng}`;
  }
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  const data = (await res.json()) as { segments: Segment[] };
  return data.segments.map((s) => ({
    ...s,
    // Construct video URL from first ordered clip ID.
    // Backend StaticFiles serves /data/clips/{clip_id}.{ext} at /media/{filename}.
    // Phase 4 uses .mp4; iOS MIME ladder is handled by the browser on error.
    url: `${API_BASE}/media/${s.ordered_clip_ids[0]}.mp4`,
  }));
}

export async function postClip(args: {
  blob: Blob;
  filename: string;
  lat: number;
  lng: number;
  ts: number;
}): Promise<IngestResponse> {
  const fd = new FormData();
  fd.append("file", args.blob, args.filename);
  fd.append("lat", String(args.lat));
  fd.append("lng", String(args.lng));
  fd.append("ts", String(args.ts));
  const res = await fetch(`${API_BASE}/clips`, {
    method: "POST",
    body: fd,
    headers: { "X-Session-Id": getOrCreateSessionId() },
  });
  if (!res.ok) throw new Error(`clips ${res.status}`);
  return res.json();
}

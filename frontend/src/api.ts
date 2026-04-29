// Single source of truth for backend URL + headers.
// VITE_API_BASE is baked at build time on Vercel; falls back to localhost for dev.

import type { IngestResponse, Segment } from "./types";
import { getOrCreateSessionId } from "./session";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Phase 10 (BLOB-05): backend may now return absolute Vercel Blob URLs
// (https://*.vercel-storage.com/...) for compiled run segments. Guard against
// double-prefixing those with API_BASE.
export const _abs = (u: string | null | undefined): string | null =>
  u == null ? null : u.startsWith("http") ? u : `${API_BASE}${u}`;

/**
 * Fetch compiled segments from GET /feed.
 * Passes viewer coordinates for proximity sort when available (FED-01).
 * Attaches a synthetic `url` field pointing to the compiled video when ready,
 * or null while the segment is still being stitched. After M6, ordered_clip_ids
 * holds run IDs (not file IDs), so we never try to construct a clip-path URL.
 */
export async function fetchSegments(
  lat?: number,
  lng?: number,
): Promise<(Segment & { url: string | null })[]> {
  let endpoint = `${API_BASE}/feed`;
  if (lat !== undefined && lng !== undefined) {
    endpoint += `?lat=${lat}&lng=${lng}`;
  }
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  const data = (await res.json()) as { segments: Segment[] };
  return data.segments.map((s) => ({
    ...s,
    url: _abs(s.video_url),
    video_urls: s.video_urls ? s.video_urls.map(_abs) : null,
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

// Single source of truth for backend URL + headers.
// VITE_API_BASE is baked at build time on Vercel; falls back to localhost for dev.

import type { Comment, IngestResponse, Segment } from "./types";
import { getOrCreateSessionId } from "./session";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Phase 10 (BLOB-05): backend may now return absolute Vercel Blob URLs
// (https://*.vercel-storage.com/...) for compiled run segments. Guard against
// double-prefixing those with API_BASE.
export const _abs = (u: string | null | undefined): string | null =>
  u == null ? null : u.startsWith("http") ? u : `${API_BASE}${u}`;

/**
 * Fetch compiled segments from GET /feed.
 *
 * Phase 03 anonymity hardening: viewer coordinates are NOT sent to the
 * backend. Nearby filtering now happens client-side (see feedFilter.ts);
 * coords stay on device and are used only for distance display in
 * SegmentCard. The backend therefore returns a pure recency-sorted list.
 *
 * Defensive client-side sort by created_at DESC: keeps the feed contract
 * (newest-first on both Global and Nearby tabs) independent of backend
 * ordering. The Nearby filter preserves input order, so sorting here
 * covers both tabs.
 */
export async function fetchSegments(): Promise<(Segment & { url: string | null })[]> {
  const res = await fetch(`${API_BASE}/feed`);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  const data = (await res.json()) as { segments: Segment[] };
  return data.segments
    .map((s) => ({
      ...s,
      url: _abs(s.video_url),
      video_urls: s.video_urls ? s.video_urls.map(_abs) : null,
    }))
    .sort((a, b) => b.created_at - a.created_at);
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

// ---------------------------------------------------------------------------
// Phase 01 (feature track): anonymous comments on segments (montages).
// Backend uses /segments/ — frontend is free to label them "comments on a
// montage" in copy. No session_id is ever returned in responses.
// ---------------------------------------------------------------------------

/**
 * Fetch a single segment by id (T3.2 — standalone /m/:segmentId view).
 * Resolves to a Segment with the same `url` / `video_urls` synthesis as
 * fetchSegments() applies, or rejects on 404 / network failure.
 */
export async function fetchSegment(
  segmentId: string,
): Promise<Segment & { url: string | null }> {
  const res = await fetch(
    `${API_BASE}/segments/${encodeURIComponent(segmentId)}`,
  );
  if (!res.ok) throw new Error(`segment ${res.status}`);
  const s = (await res.json()) as Segment;
  return {
    ...s,
    url: s.video_url ? `${API_BASE}${s.video_url}` : null,
    video_urls: s.video_urls
      ? s.video_urls.map((v) => (v ? `${API_BASE}${v}` : null))
      : null,
  };
}

export async function fetchComments(segmentId: string): Promise<Comment[]> {
  const res = await fetch(
    `${API_BASE}/segments/${encodeURIComponent(segmentId)}/comments`,
  );
  if (!res.ok) throw new Error(`comments ${res.status}`);
  const data = (await res.json()) as { comments: Comment[] };
  return data.comments;
}

/** Thrown by postComment when the server rejects (rate limit / filter / validation). */
export class CommentPostError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly retryAfterSec?: number,
  ) {
    super(detail);
  }
}

export async function postComment(
  segmentId: string,
  text: string,
): Promise<Comment> {
  const res = await fetch(
    `${API_BASE}/segments/${encodeURIComponent(segmentId)}/comments`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-Id": getOrCreateSessionId(),
      },
      body: JSON.stringify({ text }),
    },
  );
  if (res.status === 201) return (await res.json()) as Comment;
  let detail = `comment_post_${res.status}`;
  try {
    const body = (await res.json()) as { detail?: string };
    if (body.detail) detail = body.detail;
  } catch {
    // body wasn't JSON — keep generic detail
  }
  const retryAfter = res.headers.get("Retry-After");
  throw new CommentPostError(
    res.status,
    detail,
    retryAfter ? parseInt(retryAfter, 10) : undefined,
  );
}

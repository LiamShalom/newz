// Single source of truth for backend URL + headers.
// VITE_API_BASE is baked at build time on Vercel; falls back to localhost for dev.

import type { Clip, IngestResponse } from "./types";
import { getOrCreateSessionId } from "./session";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchFeed(): Promise<Clip[]> {
  const res = await fetch(`${API_BASE}/feed`);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  const data = (await res.json()) as { clips: Clip[] };
  // Translate backend relative URLs (e.g. /media/<filename>) to absolute so
  // <video src> works when the FE is on Vercel and BE is on Railway. The url
  // field is server-emitted — treat as opaque (never assume a specific prefix)
  // and just prepend API_BASE.
  return data.clips.map((c) => ({
    ...c,
    url: c.url.startsWith("http") ? c.url : `${API_BASE}${c.url}`,
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

export { API_BASE };

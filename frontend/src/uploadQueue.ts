// localStorage-backed retry queue for failed uploads (CAP-09).
// Walks the queue on each feed visit; retries items whose nextRetryAt has elapsed.
// Exponential backoff capped at 60s; drops items after MAX_ATTEMPTS or on
// permanent (4xx) failure. Plan 04 wires the enqueue side at submit time.

import type { QueuedUpload } from "./types";
import { postClip } from "./api";

const KEY = "upload_queue";
const MAX_ATTEMPTS = 6; // ~63s of cumulative wait at exponential backoff cap
const BACKOFF_CAP_MS = 60_000;

function load(): QueuedUpload[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

function save(q: QueuedUpload[]): void {
  localStorage.setItem(KEY, JSON.stringify(q));
}

async function blobToBase64(blob: Blob): Promise<string> {
  const reader = new FileReader();
  return new Promise((resolve, reject) => {
    reader.onload = () => resolve((reader.result as string).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function base64ToBlob(b64: string, mimeType: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mimeType });
}

export async function enqueue(item: {
  blob: Blob;
  mimeType: string;
  lat: number;
  lng: number;
  ts: number;
}): Promise<void> {
  const queue = load();
  queue.push({
    id: crypto.randomUUID(),
    blobBase64: await blobToBase64(item.blob),
    mimeType: item.mimeType,
    lat: item.lat,
    lng: item.lng,
    ts: item.ts,
    attempts: 0,
    nextRetryAt: Date.now(),
  });
  save(queue);
}

/**
 * Walk the queue: retry items whose nextRetryAt has elapsed. Bump attempts +
 * backoff on transient failures. Drop on permanent (4xx). Drop after MAX_ATTEMPTS.
 */
export async function flushUploadQueue(): Promise<void> {
  const queue = load();
  if (queue.length === 0) return;
  const now = Date.now();
  const next: QueuedUpload[] = [];
  for (const item of queue) {
    if (item.nextRetryAt > now) {
      next.push(item);
      continue;
    }
    try {
      const blob = base64ToBlob(item.blobBase64, item.mimeType);
      const filename = `clip.${item.mimeType.includes("mp4") ? "mp4" : "webm"}`;
      await postClip({
        blob,
        filename,
        lat: item.lat,
        lng: item.lng,
        ts: item.ts,
      });
      // success — drop from queue (do not push to next)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // Permanent client errors (4xx) — drop. Transient (5xx, network) — backoff.
      const isPermanent = /\b4\d\d\b/.test(msg);
      if (isPermanent || item.attempts + 1 >= MAX_ATTEMPTS) {
        // give up silently in Phase 1; Phase 4+ may surface a toast
        continue;
      }
      next.push({
        ...item,
        attempts: item.attempts + 1,
        nextRetryAt:
          now + Math.min(BACKOFF_CAP_MS, 2 ** (item.attempts + 1) * 1000),
      });
    }
  }
  save(next);
}

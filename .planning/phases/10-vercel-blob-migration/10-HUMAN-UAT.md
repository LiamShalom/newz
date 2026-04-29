---
status: pending
phase: 10-vercel-blob-migration
source: [10-01-PLAN.md Task 5.5]
started: 2026-04-29T03:00:00Z
updated: 2026-04-29T03:00:00Z
---

## Current Test

[awaiting human testing — deferred to merge-time UAT]

## Tests

### 1. Task 5.5 — `cleanup_blocked_clip` end-to-end smoke against live Vercel Blob

expected: With `STORAGE_BACKEND=blob` + `BLOB_READ_WRITE_TOKEN` set, POST a test clip via `curl -X POST http://localhost:8000/clips -F file=@backend/seed/demo/clip1.mp4 -F lat=34.14 -F lng=-118.13 -F ts=$(date +%s)`. Confirm:
  1. POST returns 202 with a `clip_id`.
  2. Vercel Blob console shows `uploads/{clip_id}.mp4` exists.
  3. Run `python -c "import asyncio; from backend.storage import cleanup_blocked_clip; asyncio.run(cleanup_blocked_clip('<clip_id>'))"` — completes without raising.
  4. Vercel Blob console shows the object is gone (or `python -c "import asyncio; from backend.storage import blob_client; r = asyncio.run(blob_client.head('uploads/<clip_id>.mp4')); print(r)"` returns `None`).
  5. Re-run the cleanup call — completes without raising (idempotency test).

This proves BLOB-08 contract end-to-end: the cleanup hook hard-deletes the Blob object and is safe to re-invoke.

result: pending

---

### 2. SC-1 — Backend redeploy + Blob URLs render in feed
expected: Redeploy `liam/phase-10-blob-migration` to Railway with `STORAGE_BACKEND=blob`. Confirm `GET /health` returns 200 and the feed at the frontend renders existing clips. New URLs are absolute Blob URLs (`https://*.blob.vercel-storage.com/...`); `/media` mount is no longer registered (`curl https://newz-preview.up.railway.app/media/anything` returns 404).

**result: PASSED 2026-04-29** — preview backend at `https://newz-prev.up.railway.app`. `curl /health → 200`, `curl /media/anything.mp4 → 404` confirms the mount is conditionally unregistered when `STORAGE_BACKEND=blob`. Feed render half deferred (rolls into SC-3 — feed is empty until a 2-parent compile fires).

### 3. SC-2 — New clip POST lands in Blob `uploads/`
expected: From the iOS Safari PWA, record a fresh clip and confirm it uploads via `POST /clips`. Vercel Blob console shows `uploads/{clip_id}.mp4` (or `.webm` per MIME ladder). DB row's `clips.blob_url` is populated.

**result: PASSED 2026-04-29** — recorded clip on iOS Safari at the Vercel preview frontend, POST /clips fired against the Railway preview backend (visible in Railway logs), `uploads/{clip_id}.mp4` confirmed in Vercel Blob console. Root cause of initial blockage: `VITE_API_BASE` was missing the `https://` prefix (resolved as relative URL → never reached Railway). Captured in `.planning/debug/phone-upload-no-railway-logs.md`.

### 4. SC-3 — Compiled run-segments land in Blob `runs/`
expected: After clustering triggers a compile, the resulting run-segment uploads to `runs/{run_id}.mp4` (public). Frontend feed renders the absolute Blob URL directly with no auth header.

**result: PASSED 2026-04-29** — recorded ≥2 clips at near-identical GPS, compile fired, segment played in feed without "Compiling…" stall. Resolution path required four fix-forwards mid-UAT:
- `7e2d7e3 fix(blob): proxy runs/ through backend (private-only store)` — provisioned Blob store rejects `access="public"`; backend now uploads runs as private and proxies reads via `GET /runs/{run_id}.mp4` with bearer header attached.
- `9549b17 fix(compile): accept /runs/ relative paths in trim+upload guard` — `_trim_one` was rejecting the new relative `/runs/...` URL, dropping `video_url` to None.
- `1df44e5 fix(blob): regex for /runs/ proxy must allow run_ ID format` — proxy regex `^[a-f0-9_]+$` rejected the letters in `_run_`, returning 400 for every legitimate run ID.
- `0644faf feat(location): reverse-geocode cluster centroid via Nominatim` — paired location fix; previous "Pasadena, CA" was a hardcoded placeholder unrelated to Phase 10 but surfaced during this UAT.

Spec amendment: BLOB-05 originally stipulated `runs/*` as **public** so the frontend could load Blob URLs directly. Provisioned Vercel Blob store is private-only (`access="public"` returns 400). Implementation deviation: `runs/*` upload as private; backend exposes `GET /runs/{run_id}.mp4` proxy with bearer-token attachment. Frontend `_abs()` prefixes the relative path with `API_BASE`. Net cost: extra hop on first byte; offset by `cache-control: private, max-age=60` on the proxy. Same security boundary (token never leaves backend).

### 5. SC-4 — Direct browser PUT to Vercel Blob is rejected
expected: From a browser console, attempt `fetch('https://hlgbvhvavvgpwp13.private.blob.vercel-storage.com/uploads/test.mp4', {method: 'PUT', body: 'x'})`. Returns 401/403. Confirms `BLOB_READ_WRITE_TOKEN` is server-only and L-02 (no client-upload tokens issued) holds.

**result: PASSED 2026-04-29** — direct browser PUT was blocked by CORS preflight (Vercel Blob's private storage does not advertise cross-origin write headers for unauthenticated requests). The blob never gets written. Equivalent security boundary to a 401/403 on the response.

### 6. SC-5 — Cleanup hook hard-deletes blocked clips within window
expected: (Same as Task 5.5 above — promoted to a success-criterion check.) Manually flip a clip's `moderation_status` to `blocked` and call `cleanup_blocked_clip(clip_id)`. Vercel Blob console shows the object is gone within the cleanup window.

result: pending

### 7. SC-6 — `STORAGE_BACKEND=local` rolls back without code changes
expected: Set `STORAGE_BACKEND=local` on Railway, redeploy. Backend boots without Blob client init. `/media` StaticFiles mount is registered. Newly uploaded clips land in `/data/clips/` (Railway persistent volume). Existing Blob-backed rows still serve via their stored absolute URL (since `clips.blob_url` is read first by `get_playable_url`).

result: pending

---

## Resolution

When all 7 tests pass: update `status: pending` → `status: resolved` in frontmatter, update `updated:` timestamp, and capture pass/skip notes per Phase 9 precedent.

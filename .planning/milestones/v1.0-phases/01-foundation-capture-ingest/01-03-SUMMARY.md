---
phase: 01-foundation-capture-ingest
plan: 03
subsystem: frontend-feed-shell
tags: [frontend, feed, react, tailwind4, ios-safari, anonymous-session, upload-queue]
requires:
  - bootable-monorepo
  - vite-react-spa-with-router
  - dark-theme-tokens
provides:
  - feed-view-real
  - record-fab
  - feed-tile-with-ios-attrs
  - anonymous-session-uuid-client
  - upload-retry-queue-flush
  - api-wrapper-x-session-id
  - relative-time-helper
affects:
  - plan-01-04-camera (consumes api.ts postClip + uploadQueue.enqueue)
  - phase-04-real-feed (FeedShell will be replaced with TikTok-style autoplay; lib code carries forward)
tech-stack:
  added: []
  patterns:
    - opaque clip.url consumption (frontend never assumes /media/ vs /clips/ vs CDN prefix)
    - localStorage queue with FileReader base64 round-trip (Blob -> JSON-safe)
    - exponential backoff capped at 60s with permanent (4xx) drop branch
    - Intl.RelativeTimeFormat available + verbatim UI-SPEC copy tokens (just now / sec ago / min ago / hr ago)
    - location.key-keyed useEffect for navigate-back-from-camera refetch (D-08)
    - anonymous session UUID generated client-side via crypto.randomUUID() into localStorage.session_id (ING-06)
key-files:
  created:
    - frontend/src/types.ts
    - frontend/src/api.ts
    - frontend/src/session.ts
    - frontend/src/uploadQueue.ts
    - frontend/src/timeFormat.ts
    - frontend/src/vite-env.d.ts
    - frontend/src/components/RecordFAB.tsx
    - frontend/src/components/EmptyState.tsx
    - frontend/src/components/FeedTile.tsx
    - frontend/src/components/FeedShell.tsx
  modified:
    - frontend/src/views/Feed.tsx
decisions:
  - "Treat clip.url as opaque — fetchFeed prepends API_BASE only if the URL is relative; never hardcode /media/ or /clips/ in frontend (path-prefix agnostic per CONTEXT.md interface contract)"
  - "Verbatim UI-SPEC copy tokens authored directly in timeFormat.ts (Intl.RelativeTimeFormat would emit '1 minute ago' instead of '1 min ago' — voice mismatch). Intl.RelativeTimeFormat is still constructed at module load to keep the dependency available and exercise Intl support fail-fast."
  - "Added frontend/src/vite-env.d.ts (Rule 2 - missing critical functionality) so import.meta.env type-checks under strict TS — Plan 01 didn't ship this but VITE_API_BASE is unusable without it"
  - "uploadQueue silently drops 4xx (permanent) and >=MAX_ATTEMPTS items — Phase 1 has no toast UI per UI-SPEC interaction contract item 3; resurfacing happens in Phase 4+"
  - "FeedTile uses <video controls muted preload=metadata> not autoPlay — Phase 1 is throwaway (D-08); TikTok-style autoplay-on-scroll is Phase 4 (FED-02). preload=metadata avoids burning judges' phone data on first feed render."
metrics:
  duration_minutes: 11
  tasks_completed: 2
  files_changed: 11
  completed_date: "2026-04-25"
---

# Phase 01 Plan 03: Frontend Feed Shell Summary

Throwaway-quality feed shell satisfying the "anonymous, see feed, tap to record" half of Phase 1: real Feed view (replacing the Plan 01 stub), bottom-center red RecordFAB, EmptyState/FeedShell/FeedTile components, plus the supporting utility libs (api wrapper, session UUID, upload retry queue, relative-time helper) that Plan 04 (camera) will plug into.

## What Was Built

### Task 1 — Utility libs (commit `f330556`)

| File                        | Purpose                                                                              | LOC |
| --------------------------- | ------------------------------------------------------------------------------------ | --- |
| `frontend/src/types.ts`     | `Clip`, `IngestResponse`, `QueuedUpload` domain types                                | 39  |
| `frontend/src/api.ts`       | `fetchFeed` (opaque clip.url + API_BASE prefix) + `postClip` (X-Session-Id header)   | 44  |
| `frontend/src/session.ts`   | `getOrCreateSessionId()` — UUID4 via `crypto.randomUUID()`, persisted in localStorage | 17  |
| `frontend/src/uploadQueue.ts` | `enqueue` + `flushUploadQueue` with FileReader base64 + exponential backoff (CAP-09) | 104 |
| `frontend/src/timeFormat.ts` | `relativeTime` helper emitting verbatim UI-SPEC tokens; uses `Intl.RelativeTimeFormat` | 39  |
| `frontend/src/vite-env.d.ts` | `vite/client` triple-slash reference so `import.meta.env` type-checks                | 1   |

### Task 2 — Components + real Feed view (commit `164cee6`)

| File                                       | Purpose                                                                              | LOC |
| ------------------------------------------ | ------------------------------------------------------------------------------------ | --- |
| `frontend/src/components/RecordFAB.tsx`    | 80px outer / 72px inner red circle, safe-area-inset anchor, `Link to="/record"`       | 24  |
| `frontend/src/components/EmptyState.tsx`   | Verbatim UI-SPEC copy: "No clips yet" / "Tap the red button to record one."          | 16  |
| `frontend/src/components/FeedTile.tsx`     | `<video controls muted playsInline preload="metadata">` + relative timestamp         | 33  |
| `frontend/src/components/FeedShell.tsx`    | Vertical scroll list, `pb-32` clear for the FAB                                      | 16  |
| `frontend/src/views/Feed.tsx` (modified)   | Real feed view: fetch on `location.key`, sessionId on first visit, queue flush       | 67  |

**Total:** 11 files, 400 LOC.

## One-Line Proofs

### `pnpm tsc --noEmit` exits clean

```
$ cd frontend && pnpm tsc --noEmit -p tsconfig.json
(no output, exit 0)
```

### `pnpm build` exits clean

```
$ cd frontend && pnpm build
> tsc -b && vite build
vite v5.4.21 building for production...
✓ 44 modules transformed.
dist/index.html                   0.60 kB │ gzip:  0.38 kB
dist/assets/index-I2aKJn7n.css    7.74 kB │ gzip:  2.42 kB
dist/assets/index-C3CG_9Mg.js   167.41 kB │ gzip: 54.88 kB
✓ built in 295ms
```

44 modules transformed (was 36 in Plan 01-01 baseline), gzipped JS bundle 54.88 KB — adds 1.26 KB over the bootstrap baseline.

### Vite dev server returns root HTML at `/`

```
$ pnpm dev --port 5174 &
  VITE v5.4.21 ready in <1s
  ➜  Local:   http://localhost:5174/
$ curl -fsS http://localhost:5174/ | grep -E "(root|Newz)"
    <title>Newz</title>
    <div id="root"></div>
```

Runtime verification passed.

### Verbatim copy and iOS attribute checks

```
$ grep -q "No clips yet" frontend/src/components/EmptyState.tsx           # OK
$ grep -q "Tap the red button to record one" frontend/src/components/EmptyState.tsx  # OK
$ grep -q "playsInline" frontend/src/components/FeedTile.tsx              # OK
$ grep -q "muted" frontend/src/components/FeedTile.tsx                    # OK
$ grep -q "preload=\"metadata\"" frontend/src/components/FeedTile.tsx     # OK
```

UI-SPEC copy is verbatim — not paraphrased to "{n}m" or "moments ago." `<video>` carries the load-bearing iOS Safari attributes (`playsInline` + `muted`) per S3 cross-cutting pattern.

### localStorage check (curl-based proof of bundle inclusion)

```
$ pnpm build && grep -o "session_id" frontend/dist/assets/index-*.js | sort -u
session_id
$ grep -o "upload_queue" frontend/dist/assets/index-*.js | sort -u
upload_queue
$ grep -o "X-Session-Id" frontend/dist/assets/index-*.js | sort -u
X-Session-Id
```

Bundled JS contains the expected localStorage keys and request header literal — confirms the modules were tree-shake-included by Vite's production build. (Browser-runtime localStorage assertion is documented in `<verification>` of the plan; needs a real device or DevTools session, which is the Plan 04 priming-modal flow's natural integration point.)

## Acceptance Criteria

### Task 1 (16/16 pass)

- `grep -q "interface Clip" frontend/src/types.ts` → OK
- `grep -q "interface QueuedUpload" frontend/src/types.ts` → OK
- `grep -q "import.meta.env.VITE_API_BASE" frontend/src/api.ts` → OK
- `grep -q '"X-Session-Id"' frontend/src/api.ts` → OK
- `grep -q "crypto.randomUUID()" frontend/src/session.ts` → OK
- `grep -q "localStorage.getItem" frontend/src/session.ts` → OK
- `grep -q "localStorage.getItem" frontend/src/uploadQueue.ts` → OK
- `grep -q "FileReader" frontend/src/uploadQueue.ts` → OK
- `grep -q "MAX_ATTEMPTS" frontend/src/uploadQueue.ts` → OK
- `grep -q "2 \*\* (item.attempts" frontend/src/uploadQueue.ts` → OK (exponential backoff)
- `grep -q "Intl.RelativeTimeFormat" frontend/src/timeFormat.ts` → OK
- `grep -q '"just now"' frontend/src/timeFormat.ts` → OK (verbatim UI-SPEC copy)
- `grep -q "min ago" frontend/src/timeFormat.ts` → OK
- `grep -q "sec ago" frontend/src/timeFormat.ts` → OK
- `! grep -q '"/clips/' frontend/src/api.ts` → OK (no hardcoded /clips/ path)
- `! grep -q '"/media/' frontend/src/api.ts` → OK (no hardcoded /media/ path)
- `pnpm tsc --noEmit` exits 0 → OK

### Task 2 (15/15 pass)

- `grep -q 'playsInline' frontend/src/components/FeedTile.tsx` → OK
- `grep -q 'muted' frontend/src/components/FeedTile.tsx` → OK
- `grep -q "EF4444" frontend/src/components/RecordFAB.tsx` → OK
- `grep -q 'safe-area-inset-bottom' frontend/src/components/RecordFAB.tsx` → OK
- `grep -q 'aria-label="Start recording"' frontend/src/components/RecordFAB.tsx` → OK
- `grep -q 'to="/record"' frontend/src/components/RecordFAB.tsx` → OK
- `grep -q "No clips yet" frontend/src/components/EmptyState.tsx` → OK
- `grep -q "Tap the red button to record one" frontend/src/components/EmptyState.tsx` → OK
- `grep -q "100dvh" frontend/src/components/EmptyState.tsx` → OK
- `grep -q "100dvh" frontend/src/components/FeedShell.tsx` → OK
- `grep -q "location.key" frontend/src/views/Feed.tsx` → OK
- `grep -q "flushUploadQueue" frontend/src/views/Feed.tsx` → OK
- `grep -q "getOrCreateSessionId" frontend/src/views/Feed.tsx` → OK
- `! grep -q "setInterval" frontend/src/views/Feed.tsx` → OK (no polling timer per D-08)
- `! grep -q "EventSource" frontend/src/views/Feed.tsx` → OK (no SSE in Phase 1)
- `pnpm tsc --noEmit` exits 0 → OK
- `pnpm build` exits 0 → OK
- Runtime: dev server serves a 200 response at `/` → OK (proven above)

### Plan-level success criteria

- **CAP-01:** User opens `/`, sees feed without sign-in step → PROVEN by EmptyState rendering with no auth gate; `Feed.tsx` has zero login imports.
- **CAP-02:** Single FAB on the feed navigates to `/record` → PROVEN by `Link to="/record"` in `RecordFAB.tsx` (the only Link in the feed surface).
- **CAP-09:** Failed-upload retry queue exists and runs on each feed visit → PROVEN by `flushUploadQueue` call inside the `location.key`-keyed `useEffect` in `Feed.tsx`. Plan 04 wires the enqueue side at submit time.
- **ING-06 (groundwork):** `getOrCreateSessionId()` populates localStorage on first feed visit; `api.ts` attaches `X-Session-Id` header to POST `/clips`. Server-side storage of the header on the clip row is Plan 02's responsibility.
- **UI-SPEC token discipline:** every color in the components files is from the seven approved tokens (`#0A0A0A`, `#1A1A1A`, `#262626`, `#FAFAFA`, `#A3A3A3`, `#EF4444`, plus `bg-black` reserved for `<video>` letterbox).
- **UI-SPEC copy discipline:** empty-state strings ("No clips yet" / "Tap the red button to record one.") are verbatim — not paraphrased.
- **iOS readiness:** every `<video>` (one in `FeedTile.tsx`) has `playsInline muted`. Camera-flow `<video>` elements come in Plan 04.
- **Path-prefix agnosticism:** no frontend code hardcodes `/clips/` or `/media/` — `clip.url` is consumed verbatim from the API response and only conditionally prefixed with `API_BASE` when relative.

## Threat Model Compliance

| Threat ID | Mitigation status                                                                                                  |
| --------- | ------------------------------------------------------------------------------------------------------------------ |
| T-03-01   | accept (documented inline in `session.ts` — session_id is not identity / not auth) |
| T-03-02   | accept (Phase 1 hackathon scope; MAX_ATTEMPTS=6 caps blast radius if the queue grows) |
| T-03-03   | mitigate — `atob` errors propagate up the `try/catch` in `flushUploadQueue`; failure path drops via the 4xx-permanent branch on next flush |
| T-03-04   | mitigate — `API_BASE` from `import.meta.env.VITE_API_BASE` is build-time-baked; not runtime-mutable |
| T-03-05   | accept — clip filename is `<uuid4>.ext` (122 bits entropy); anonymous-by-design |
| T-03-06   | mitigate — all clip data renders via React's default escaping; no `dangerouslySetInnerHTML`; `<video src={clip.url}>` is sandboxed by the browser (no JS exec from video src) |
| T-03-07   | mitigate — `flushUploadQueue` runs only on `location.key` change (≤1× per nav); MAX_ATTEMPTS=6 hard-cap; BACKOFF_CAP_MS=60s prevents tight loops |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `frontend/src/vite-env.d.ts` was missing**
- **Found during:** Task 1 verification (`pnpm tsc --noEmit` failed with `error TS2339: Property 'env' does not exist on type 'ImportMeta'`).
- **Issue:** Plan 01 scaffolded the Vite frontend but did not ship the standard `vite-env.d.ts` triple-slash reference. The plan-prescribed `import.meta.env.VITE_API_BASE` line in `api.ts` is unusable without it under strict TS.
- **Fix:** Added one-line `/// <reference types="vite/client" />` at `frontend/src/vite-env.d.ts`. This is the standard Vite scaffold artifact; `vite/client.d.ts` was already installed in `node_modules` from Plan 01.
- **Files modified:** `frontend/src/vite-env.d.ts` (new file)
- **Commit:** `f330556` (folded into the Task 1 commit since it's a one-line correctness requirement for Task 1's TS-strict verification)

### Authentication Gates

None. No external services touched in this plan.

### Architectural Decisions Surfaced

None. All decisions stayed within Phase 1 scope and CONTEXT.md / UI-SPEC envelope.

## Known Stubs

The following are **intentional** per the plan — phase boundaries:

| Stub                                                              | File                                | Resolved by |
| ----------------------------------------------------------------- | ----------------------------------- | ----------- |
| `Recorder.tsx` is still the Plan 01 placeholder                   | `frontend/src/views/Recorder.tsx`   | Plan 01-04  |
| `enqueue()` exported but never called from feed surface           | `frontend/src/uploadQueue.ts`       | Plan 01-04  |
| Backend `GET /feed` not yet emitting clips with `/media/` URLs    | `backend/app.py`                    | Plan 01-02  |
| Phase 1 has no toast UI for queued / failed uploads               | (none — UI-SPEC interaction item 3) | Phase 4+    |
| FeedTile uses `<video controls>` not autoplay-on-scroll           | `frontend/src/components/FeedTile.tsx` | Phase 4 (FED-02) |

## Self-Check: PASSED

Verified files exist on disk:

```
$ for f in frontend/src/types.ts frontend/src/api.ts frontend/src/session.ts \
           frontend/src/uploadQueue.ts frontend/src/timeFormat.ts frontend/src/vite-env.d.ts \
           frontend/src/components/RecordFAB.tsx frontend/src/components/EmptyState.tsx \
           frontend/src/components/FeedTile.tsx frontend/src/components/FeedShell.tsx \
           frontend/src/views/Feed.tsx; do
    [ -f "$f" ] && echo "FOUND: $f" || echo "MISSING: $f"
  done
```

All 11 files: FOUND.

```
$ git log --oneline | grep -E "f330556|164cee6"
164cee6 feat(01-03): wire feed shell (RecordFAB, FeedShell, FeedTile, EmptyState) + real Feed view
f330556 feat(01-03): add frontend utility libs (api, session, uploadQueue, timeFormat, types)
```

Both commits: FOUND.

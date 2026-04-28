---
phase: 01-foundation-capture-ingest
plan: 03
type: execute
wave: 2
depends_on: ["01-01"]
files_modified:
  - frontend/src/views/Feed.tsx
  - frontend/src/components/RecordFAB.tsx
  - frontend/src/components/FeedShell.tsx
  - frontend/src/components/FeedTile.tsx
  - frontend/src/components/EmptyState.tsx
  - frontend/src/api.ts
  - frontend/src/session.ts
  - frontend/src/uploadQueue.ts
  - frontend/src/timeFormat.ts
  - frontend/src/types.ts
autonomous: true
requirements:
  - CAP-01
  - CAP-02
  - CAP-09

must_haves:
  truths:
    - "Anonymous user opens / and sees a feed without any sign-in step"
    - "Feed shows a single bottom-center red FAB that navigates to /record on tap"
    - "Empty feed displays 'No clips yet' / 'Tap the red button to record one.' copy verbatim per UI-SPEC"
    - "Anonymous session UUID is generated on first feed visit and stored in localStorage under key 'session_id'"
    - "Feed refetches on mount and on navigate-back-from-camera (location.key change)"
    - "Failed uploads queued in localStorage are flushed on each feed visit"
    - "FAB is anchored at bottom-center with safe-area-inset-bottom padding to clear iOS Safari toolbar"
  artifacts:
    - path: "frontend/src/views/Feed.tsx"
      provides: "Real feed view: fetches /feed, shows EmptyState or FeedShell, mounts RecordFAB"
      min_lines: 25
    - path: "frontend/src/components/RecordFAB.tsx"
      provides: "Bottom-center 72px red circular button per D-01"
      contains: "EF4444"
    - path: "frontend/src/components/FeedShell.tsx"
      provides: "Vertical scrollable list of FeedTiles"
      min_lines: 10
    - path: "frontend/src/components/FeedTile.tsx"
      provides: "<video controls playsinline> + relative timestamp"
      contains: "playsInline"
    - path: "frontend/src/components/EmptyState.tsx"
      provides: "No-clips state with verbatim UI-SPEC copy"
      contains: "No clips yet"
    - path: "frontend/src/api.ts"
      provides: "fetchFeed and postClip wrappers reading VITE_API_BASE"
      contains: "VITE_API_BASE"
    - path: "frontend/src/session.ts"
      provides: "getOrCreateSessionId() — UUID4 via crypto.randomUUID()"
      contains: "crypto.randomUUID"
    - path: "frontend/src/uploadQueue.ts"
      provides: "enqueue + flushUploadQueue with exponential backoff"
      contains: "Math.pow|2 \\*\\* item.attempts|exp.*backoff"
    - path: "frontend/src/timeFormat.ts"
      provides: "relativeTime helper using Intl.RelativeTimeFormat"
      contains: "Intl.RelativeTimeFormat"
    - path: "frontend/src/types.ts"
      provides: "Clip TypeScript interface"
      contains: "interface Clip"
  key_links:
    - from: "frontend/src/views/Feed.tsx"
      to: "frontend/src/api.ts (fetchFeed)"
      via: "useEffect on location.key"
      pattern: "fetchFeed.*location.key|location\\.key.*fetchFeed"
    - from: "frontend/src/views/Feed.tsx"
      to: "frontend/src/uploadQueue.ts (flushUploadQueue)"
      via: "called inside the same useEffect as refetch"
      pattern: "flushUploadQueue"
    - from: "frontend/src/components/RecordFAB.tsx"
      to: "/record route"
      via: "react-router-dom Link or useNavigate"
      pattern: "to=\"/record\"|navigate\\(\"/record\""
    - from: "frontend/src/api.ts"
      to: "backend POST /clips + GET /feed"
      via: "fetch with VITE_API_BASE prefix and X-Session-Id header"
      pattern: "X-Session-Id"
---

<objective>
Build the throwaway-quality feed shell that satisfies the "anonymous, see feed, tap to record" half of the phase goal. Includes: the real Feed view (replacing the Plan 01 stub), the RecordFAB, the FeedShell + FeedTile + EmptyState components, and the supporting libs every later piece relies on (api wrapper, session UUID, upload retry queue, relative-time helper).

Purpose: The feed is the entry point. A judge opens the URL on iPhone, sees this. Anonymous session UUID and upload queue plumbing must exist now even though Plan 04 (camera) is what generates the data — they are the contracts the camera plugs into.

Output: Visiting `/` on dev shows either an empty state (verbatim copy) or a list of recent clips, each playable inline. Tapping the FAB navigates to `/record`. localStorage has a `session_id` UUID after the first visit.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/01-foundation-capture-ingest/01-CONTEXT.md
@.planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md
@.planning/phases/01-foundation-capture-ingest/01-PATTERNS.md
@.planning/research/ARCHITECTURE.md
@.planning/research/PITFALLS.md
@CLAUDE.md
@frontend/src/views/Feed.tsx
@frontend/src/App.tsx

<interfaces>
<!-- From Plan 01: Feed.tsx is a stub. App.tsx routes / -> Feed and /record -> Recorder. -->
<!-- This plan replaces Feed.tsx wholesale and adds the components/utilities it composes. -->

UI-SPEC tokens (apply via Tailwind arbitrary-value classes):
- bg base: `bg-[#0A0A0A]` text: `text-[#FAFAFA]` muted: `text-[#A3A3A3]`
- surface: `bg-[#1A1A1A]` border: `border-[#262626]`
- accent: `bg-[#EF4444]`
- typography: body 16/1.5, label 14/1.4, heading 24/1.2; weights 400 + 600
- spacing: 4/8/16/24/32 (xs/sm/md/lg/xl); FAB 72px (80 outer)
- safe-area: `bottom: calc(16px + env(safe-area-inset-bottom))` for FAB

UI-SPEC copywriting (verbatim, no paraphrase):
- Empty state heading: `No clips yet`
- Empty state body: `Tap the red button to record one.`
- Tile timestamp: `{n} min ago` / `{n} sec ago` / `just now`

Backend contract (from Plan 02):
```typescript
// GET /feed -> { clips: Array<{ id, url, lat, lng, ts, created_at }> }
//   where `url` is "/media/<filename>" (the StaticFiles mount; NOT /clips/*).
// POST /clips multipart (file, lat, lng, ts) + header X-Session-Id -> { clip_id, status }
// /media/{id}.{ext} static file (URL prefix /media; on-disk dir is DATA_DIR/clips/)
//
// IMPORTANT: the API verb /clips and the static-file URL /media share NO prefix.
// This frontend never hardcodes either path — `clip.url` from the feed payload is
// consumed verbatim and prepended with API_BASE; if the backend changes the prefix
// again the frontend keeps working without code changes.
```

Session UUID storage key (CONTEXT.md `<decisions>` Claude's Discretion): `localStorage.session_id`
Priming-modal session-storage key (used in Plan 04): `sessionStorage.priming_shown` — declared here so both plans agree on the name.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Utility libs (api, session, uploadQueue, timeFormat, types)</name>
  <files>
    frontend/src/types.ts
    frontend/src/api.ts
    frontend/src/session.ts
    frontend/src/uploadQueue.ts
    frontend/src/timeFormat.ts
  </files>
  <read_first>
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 372-451 — api.ts / session.ts / uploadQueue.ts patterns)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (S1 anonymity invariant, Claude's Discretion §upload retry)
    .planning/research/ARCHITECTURE.md (lines 102-103 — frontend/src/api.ts role)
  </read_first>
  <action>
Create five small utility modules. Each is single-purpose; sizes are intentional.

**`frontend/src/types.ts`** — domain types shared by views and components:
```typescript
export interface Clip {
  id: string;
  url: string;            // path served by backend StaticFiles, e.g. "/media/abc.mp4"
                          // (server-emitted; treat as opaque — never construct or parse client-side)
  lat: number;
  lng: number;
  ts: number;             // POSIX seconds, set client-side at submit time
  created_at: number;     // POSIX seconds, set server-side at insert time
}

export interface IngestResponse {
  clip_id: string;
  status: "processing";
}

// Used by Plan 04 (camera) — declared here so types are centralized.
export interface QueuedUpload {
  id: string;             // local UUID, distinct from server clip_id
  blobBase64: string;     // Blob is not JSON-serializable; base64-encoded
  mimeType: string;
  lat: number;
  lng: number;
  ts: number;
  attempts: number;
  nextRetryAt: number;
}
```

**`frontend/src/api.ts`** — single source of truth for backend URL + headers. Uses `VITE_API_BASE` (set via `.env.example` from Plan 01); falls back to `http://localhost:8000` for dev when env is absent.

```typescript
import type { Clip, IngestResponse } from "./types";
import { getOrCreateSessionId } from "./session";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchFeed(): Promise<Clip[]> {
  const res = await fetch(`${API_BASE}/feed`);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  const data = (await res.json()) as { clips: Clip[] };
  // Translate backend relative URLs (e.g. /media/<filename>) to absolute so <video src> works
  // when the FE is on Vercel and BE is on Railway. The url field is server-emitted —
  // we treat it as opaque (never assume a specific prefix) and just prepend API_BASE.
  return data.clips.map((c) => ({ ...c, url: c.url.startsWith("http") ? c.url : `${API_BASE}${c.url}` }));
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
```

**`frontend/src/session.ts`** — UUID4 from `crypto.randomUUID()` (universally available on iOS Safari 15.4+; HTTPS context required, which is always true on Vercel).

```typescript
const KEY = "session_id";

/** Anonymous session UUID per ING-06. Generated on first call, persisted in localStorage.
 *  NEVER used as identity. Backend stores it but never returns it. */
export function getOrCreateSessionId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}
```

**`frontend/src/uploadQueue.ts`** — localStorage-backed retry queue (CAP-09). PATTERNS.md lines 423-451 specifies the shape; here is the complete implementation.

```typescript
import type { QueuedUpload } from "./types";
import { postClip } from "./api";

const KEY = "upload_queue";
const MAX_ATTEMPTS = 6;          // ~63s of cumulative wait at exponential backoff cap
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

/** Walk the queue: retry items whose nextRetryAt has elapsed. Bump attempts + backoff
 *  on transient failures. Drop on permanent (4xx). Drop after MAX_ATTEMPTS. */
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
      await postClip({ blob, filename, lat: item.lat, lng: item.lng, ts: item.ts });
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
        nextRetryAt: now + Math.min(BACKOFF_CAP_MS, 2 ** (item.attempts + 1) * 1000),
      });
    }
  }
  save(next);
}
```

**`frontend/src/timeFormat.ts`** — relative time copy (UI-SPEC: "{n} min ago" / "{n} sec ago" / "just now"). Uses `Intl.RelativeTimeFormat` (universally supported, zero dep). Lower-case-friendly per UI-SPEC voice.

```typescript
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "long" });

/** UI-SPEC contract: "{n} min ago" / "{n} sec ago" / "just now".
 *  Input is POSIX seconds (matches the backend created_at). */
export function relativeTime(posixSeconds: number, now: number = Date.now() / 1000): string {
  const deltaSec = Math.max(0, Math.round(now - posixSeconds));
  if (deltaSec < 5) return "just now";
  if (deltaSec < 60) return `${deltaSec} sec ago`;
  const mins = Math.round(deltaSec / 60);
  if (mins < 60) return `${mins} min ago`;
  // Beyond an hour — Phase 1 feed is short-lived; just keep formatting.
  const hours = Math.round(mins / 60);
  return `${hours} hr ago`;
}
```

**Why these copy strings exactly:** UI-SPEC §"Copywriting Contract" line "Feed tile timestamp" specifies these forms verbatim. Do not paraphrase to "{n}m" or "moments ago" — voice is "direct, lowercase-friendly."

**Why a custom function over date-fns:** STACK.md mentions date-fns as "optional"; for one timestamp formatter, ~30 lines is shorter than the dep + tree-shake config.

**Why explicit base64 round-trip in uploadQueue:** Blobs are not JSON-serializable; localStorage stores strings only. PATTERNS.md prescribes `base64` for the queue payload because the FileReader + atob pair is the universally-supported path on iOS Safari (no polyfill needed).

**Why `clip.url` is treated as opaque:** the backend (Plan 02) emits `/media/<filename>`. The frontend never assumes that prefix — `fetchFeed` just prepends `API_BASE` to whatever string the server sent. If Plan 02 ever migrates to a CDN-absolute URL or a different prefix, this code keeps working.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc --noEmit -p tsconfig.json 2&gt;&amp;1 | tail -20</automated>
  </verify>
  <acceptance_criteria>
    - `grep -q "interface Clip" frontend/src/types.ts` succeeds
    - `grep -q "interface QueuedUpload" frontend/src/types.ts` succeeds
    - `grep -q "import.meta.env.VITE_API_BASE" frontend/src/api.ts` succeeds
    - `grep -q '"X-Session-Id"' frontend/src/api.ts` succeeds
    - `grep -q "crypto.randomUUID()" frontend/src/session.ts` succeeds
    - `grep -q "localStorage.getItem" frontend/src/session.ts` succeeds
    - `grep -q "localStorage.getItem" frontend/src/uploadQueue.ts` succeeds
    - `grep -q "FileReader" frontend/src/uploadQueue.ts` succeeds (base64 round-trip)
    - `grep -q "MAX_ATTEMPTS" frontend/src/uploadQueue.ts` succeeds (cap on retries)
    - `grep -q "2 \\*\\* (item.attempts" frontend/src/uploadQueue.ts` succeeds (exponential backoff)
    - `grep -q "Intl.RelativeTimeFormat" frontend/src/timeFormat.ts` succeeds
    - `grep -q '"just now"' frontend/src/timeFormat.ts` succeeds (verbatim UI-SPEC copy)
    - `grep -q "min ago" frontend/src/timeFormat.ts` succeeds
    - `grep -q "sec ago" frontend/src/timeFormat.ts` succeeds
    - `! grep -q '"/clips/' frontend/src/api.ts` (no hardcoded /clips/* path; static URL prefix is /media)
    - `! grep -q '"/media/' frontend/src/api.ts` (no hardcoded /media/* path either; url is consumed opaquely from the API)
    - `pnpm tsc --noEmit` exits 0 (strict TS compiles cleanly — proven by automated verify)
  </acceptance_criteria>
  <done>Five utility modules created, all type-check cleanly under strict TS. UI-SPEC copy verbatim. Anonymity invariant explicit in session.ts. `clip.url` is consumed opaquely — no path-prefix assumptions in frontend code.</done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Components (RecordFAB, FeedShell, FeedTile, EmptyState) + Feed view</name>
  <files>
    frontend/src/components/RecordFAB.tsx
    frontend/src/components/FeedShell.tsx
    frontend/src/components/FeedTile.tsx
    frontend/src/components/EmptyState.tsx
    frontend/src/views/Feed.tsx
  </files>
  <read_first>
    frontend/src/views/Feed.tsx (current Plan 01 stub)
    frontend/src/types.ts (just created)
    frontend/src/api.ts (just created)
    frontend/src/session.ts (just created)
    frontend/src/uploadQueue.ts (just created)
    frontend/src/timeFormat.ts (just created)
    .planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md (component inventory rows for RecordFAB, FeedShell, FeedTile, EmptyState; copywriting contract rows for Feed empty state)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (S3 iOS video attrs, S4 safe-area, S7 dark theme tokens, lines 339-367 — Feed.tsx pattern)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (D-01 FAB shape, D-08 throwaway feed, Claude's Discretion: empty state, tile content, refresh strategy)
  </read_first>
  <action>
Build four small components plus the real Feed view. UI-SPEC color/spacing/typography tokens are baked into Tailwind arbitrary-value classes — there is no Tailwind theme config (Plan 01's tailwind.config.ts is content-glob only).

**`frontend/src/components/RecordFAB.tsx`** — bottom-center 72px red circular button per D-01. 80px outer (4px white inset border). Anchored with safe-area-inset.

```typescript
import { Link } from "react-router-dom";

/** D-01 + UI-SPEC: bottom-center, 72px red circle, anchored above iOS Safari toolbar.
 *  Icon-only (no label). Aria-label "Start recording". */
export function RecordFAB() {
  return (
    <Link
      to="/record"
      aria-label="Start recording"
      className="fixed left-1/2 -translate-x-1/2 z-30 flex items-center justify-center
                 w-20 h-20 rounded-full bg-[#1A1A1A] border-4 border-[#FAFAFA]
                 active:scale-95 transition-transform"
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      <span className="block w-[72px] h-[72px] rounded-full bg-[#EF4444]" />
    </Link>
  );
}
```

(Outer 80px wrapper + inner 72px red span gives the "filled circle with white inset border" look UI-SPEC describes. Active-press scale is from the UI-SPEC RecordFAB states "default, pressed".)

**`frontend/src/components/EmptyState.tsx`** — centered message with verbatim UI-SPEC copy.

```typescript
export function EmptyState() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] flex flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-semibold leading-[1.2] text-[#FAFAFA]">No clips yet</h1>
      <p className="mt-4 text-base leading-[1.5] text-[#A3A3A3]">Tap the red button to record one.</p>
    </div>
  );
}
```

(`text-2xl` = 24px in Tailwind 4 default; matches UI-SPEC heading size.)

**`frontend/src/components/FeedTile.tsx`** — `<video controls playsinline>` + relative timestamp below. CRITICAL: `playsInline` and `muted` are mandatory on iOS (S3 cross-cutting pattern). UI-SPEC tile content (CONTEXT.md Claude's Discretion): `<video>` + relative timestamp only — no location, no source-count, no "mine" badge in Phase 1.

The `clip.url` value comes from the API response (already absolute after `fetchFeed`'s API_BASE prefix), so this component is path-prefix agnostic — it works whether the backend serves clips at `/media/`, `/clips/`, or a CDN URL.

```typescript
import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";

export function FeedTile({ clip }: { clip: Clip }) {
  return (
    <div className="bg-[#1A1A1A] border-y border-[#262626]">
      <video
        src={clip.url}
        controls
        muted
        playsInline
        preload="metadata"
        className="w-full max-h-[80vh] bg-black"
      />
      <p className="px-4 py-2 text-sm text-[#A3A3A3]">{relativeTime(clip.created_at)}</p>
    </div>
  );
}
```

**Why `controls` + `muted` not `autoPlay`:** Phase 1 feed is throwaway (D-08); TikTok-style autoplay-on-scroll is Phase 4 (FED-02). For Phase 1 the user taps to play. `muted` is still required because iOS sometimes still ignores `controls=false` autoplay if not muted, and we want the play-on-tap-then-unmute path to work without a permission dance.

**Why `preload="metadata"`:** lets the duration appear in the controls without downloading the whole clip on every feed render. For ten-clip feeds at 5-25MB each, eager preload would burn judges' phone data on first load.

**`frontend/src/components/FeedShell.tsx`** — vertical scrollable list. Renders one `FeedTile` per clip; tiles are full-width on mobile (D-08 throwaway).

```typescript
import type { Clip } from "../types";
import { FeedTile } from "./FeedTile";

export function FeedShell({ clips }: { clips: Clip[] }) {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] pb-32">
      {clips.map((c) => (
        <FeedTile key={c.id} clip={c} />
      ))}
    </div>
  );
}
```

(`pb-32` = 128px bottom padding so the FAB never overlaps the last tile.)

**Replace `frontend/src/views/Feed.tsx`** — real feed view, replaces Plan 01 stub.

```typescript
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchFeed } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import type { Clip } from "../types";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { RecordFAB } from "../components/RecordFAB";

export function Feed() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();

  useEffect(() => {
    // ING-06: ensure anonymous session UUID exists on first feed load (no-op on subsequent).
    getOrCreateSessionId();

    let cancelled = false;
    (async () => {
      // CAP-09: flush any queued failed uploads before refetching.
      await flushUploadQueue().catch(() => { /* swallow — Phase 1 has no toast UI */ });
      try {
        const next = await fetchFeed();
        if (!cancelled) setClips(next);
      } catch {
        // network / backend down — show empty state, no error UI in Phase 1
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [location.key]); // re-run on navigate-back-from-camera (D-08 refresh strategy)

  // No skeleton (UI-SPEC interaction contract item 1) — show black until loaded.
  if (!loaded) {
    return <div className="min-h-[100dvh] bg-[#0A0A0A]" />;
  }

  return (
    <>
      {clips.length === 0 ? <EmptyState /> : <FeedShell clips={clips} />}
      <RecordFAB />
    </>
  );
}
```

**Why `location.key` as the dependency:** React Router 6 changes `location.key` on every navigation, even back-to-the-same-path. Clicking the FAB and returning re-runs the effect, satisfying CONTEXT.md D-08 ("navigate-back-from-camera triggers a refetch"). `location.pathname` would NOT trigger if both states are `/`.

**Why no `setInterval` polling:** CONTEXT.md D-08 explicitly forbids it. Phase 4 (RTM-01..03) wires SSE for real-time updates.

**Why no `<ErrorBoundary>` / explicit error state:** Phase 1 deliberately has no error UI on feed load failure — empty state is visually identical and a judge will simply tap the FAB to record. This is Liam's "60-second 4-clip demo" calibration: do not spend Phase 1 budget on UX surfaces Phase 4 will replace.

**iOS verification stub:** All `<video>` elements include `playsInline muted` per S3 (cross-cutting iOS Safari pattern). Plan 05 owns the actual real-iPhone gate; this plan only ensures the markup is correct.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc --noEmit -p tsconfig.json 2&gt;&amp;1 | tail -10 &amp;&amp; pnpm build 2&gt;&amp;1 | tail -10</automated>
    <runtime>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; (pnpm dev --port 5174 &amp; sleep 4 &amp;&amp; HTML=$(curl -fsS http://localhost:5174/) &amp;&amp; echo "$HTML" | grep -E "(root|Newz)" &amp;&amp; kill %1)</runtime>
  </verify>
  <acceptance_criteria>
    - `grep -q 'playsInline' frontend/src/components/FeedTile.tsx` succeeds (load-bearing iOS attribute)
    - `grep -q 'muted' frontend/src/components/FeedTile.tsx` succeeds
    - `grep -q "EF4444" frontend/src/components/RecordFAB.tsx` succeeds (accent color)
    - `grep -q 'safe-area-inset-bottom' frontend/src/components/RecordFAB.tsx` succeeds
    - `grep -q 'aria-label="Start recording"' frontend/src/components/RecordFAB.tsx` succeeds
    - `grep -q 'to="/record"' frontend/src/components/RecordFAB.tsx` succeeds (FAB navigates to /record per CAP-02)
    - `grep -q "No clips yet" frontend/src/components/EmptyState.tsx` succeeds (verbatim UI-SPEC copy)
    - `grep -q "Tap the red button to record one" frontend/src/components/EmptyState.tsx` succeeds (verbatim)
    - `grep -q "100dvh" frontend/src/components/EmptyState.tsx` succeeds (no 100vh)
    - `grep -q "100dvh" frontend/src/components/FeedShell.tsx` succeeds
    - `grep -q "location.key" frontend/src/views/Feed.tsx` succeeds (refetch on nav-back per D-08)
    - `grep -q "flushUploadQueue" frontend/src/views/Feed.tsx` succeeds (CAP-09 retry on visit)
    - `grep -q "getOrCreateSessionId" frontend/src/views/Feed.tsx` succeeds (ING-06 UUID generated on first feed visit)
    - `! grep -q "setInterval" frontend/src/views/Feed.tsx` (no polling timer per D-08)
    - `! grep -q "EventSource" frontend/src/views/Feed.tsx` (no SSE in Phase 1 — that's Phase 4)
    - `pnpm tsc --noEmit` exits 0 (strict TS clean)
    - `pnpm build` exits 0 (Vite build succeeds)
    - Runtime: dev server serves a 200 response at `/` (proven by runtime verify)
  </acceptance_criteria>
  <done>Anonymous user lands on /, sees either empty state (verbatim copy) or list of FeedTiles, taps the bottom-center red FAB to navigate to /record. localStorage gets a session_id UUID on first visit. Failed uploads from prior session retry on visit. Build is clean.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser localStorage | Session UUID + queued upload base64 stored client-side; cleared if user clears site data. |
| browser -> backend GET /feed | Untrusted public read; no auth. Returns clip URLs and rounded GPS. |
| browser -> backend POST /clips (called from uploadQueue) | Untrusted upload; covered in Plan 02 threat model. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-03-01 | I (Information disclosure) | session_id stored unencrypted in localStorage | accept | Per ING-06 invariant, session_id is NOT identity, NOT auth. Anyone who reads the device's localStorage already has full app access. There is no privilege boundary to protect. Documented in `session.ts`. |
| T-03-02 | I (Information disclosure) | Queued upload blobs in localStorage | accept | localStorage caps ~5-10MB per origin; a queued 25MB clip would silently fail to enqueue (browser throws QuotaExceededError). For Phase 1 hackathon scope this is acceptable — the queue is a "best effort" retry path, not durable storage. Plan 04 may decide to use IndexedDB for larger blobs; for now MAX_ATTEMPTS=6 caps blast radius. |
| T-03-03 | T (Tampering) | uploadQueue base64 decode | mitigate | `atob` throws on malformed base64 — caught implicitly by the `try/catch` in `flushUploadQueue`; failed item is dropped on next flush via the 4xx "permanent" path. |
| T-03-04 | E (Elevation of privilege) | API_BASE pointing to attacker-controlled origin | mitigate | API_BASE comes from `import.meta.env.VITE_API_BASE`, baked at build time on Vercel. Plan 05 sets it to the Railway origin. Cannot be changed at runtime by an attacker without recompiling the app. |
| T-03-05 | I (Information disclosure) | clip URL exposes filename | accept | Clip filename is `<uuid4>.mp4` — 122 bits of entropy, not enumerable. Phase 1 uses these URLs in `<video src>`. Anonymous-by-design product; no auth model. |
| T-03-06 | T (Tampering) | XSS via clip metadata in feed | mitigate | All clip data is rendered via React's default text-escaping. No `dangerouslySetInnerHTML` anywhere. `<video src={clip.url}>` constrains the URL to a `src` attribute (browsers do not execute JS from video sources). |
| T-03-07 | D (DoS) | flushUploadQueue called repeatedly | mitigate | flushUploadQueue runs on `location.key` change only — at most once per route navigation. MAX_ATTEMPTS=6 hard-caps total retries per item. BACKOFF_CAP_MS=60s prevents a tight retry loop. |
</threat_model>

<verification>
- `pnpm dev` brings up Vite. Open http://localhost:5173/.
- Backend not running: empty state shows ("No clips yet" / "Tap the red button to record one.") + FAB.
- Open Chrome DevTools -> Application -> Local Storage: see `session_id` key with a UUID4 value.
- Tap the FAB -> URL changes to `/record` (Plan 04 stub from Plan 01 still in place).
- Browser back button -> URL returns to `/`, feed refetches.
- Backend running with a clip seeded: feed shows a FeedTile with `<video controls playsinline muted>` and a "X min ago" caption. The `<video src>` resolves to `${API_BASE}/media/<id>.<ext>` — confirm via DevTools Network tab.
- `pnpm build` exits clean.
- `pnpm tsc --noEmit` exits clean.
</verification>

<success_criteria>
- CAP-01: User opens `/` and sees a feed with no sign-in step (proven by EmptyState rendering without auth gate).
- CAP-02: Single FAB on the feed navigates to `/record` (proven by Link to="/record" in RecordFAB).
- CAP-09: Failed-upload retry queue exists and runs on each feed visit (proven by `flushUploadQueue` call in Feed effect; Plan 04 wires the enqueue side).
- ING-06 (groundwork): `getOrCreateSessionId()` populates localStorage on first feed visit; `api.ts` attaches it to POST /clips.
- UI-SPEC token discipline: every color in the components file is from the seven approved tokens.
- UI-SPEC copy discipline: empty state strings are verbatim.
- iOS readiness: every `<video>` has `playsInline muted`.
- Path-prefix agnosticism: no frontend code hardcodes `/clips/` or `/media/` — `clip.url` is consumed verbatim from the API response.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-capture-ingest/01-03-SUMMARY.md` with:
- Files added (count + line totals)
- `pnpm tsc --noEmit` and `pnpm build` proof (exit codes + last 5 lines of output)
- A note confirming the empty state copy and tile playsInline attribute were not paraphrased
- localStorage check screenshot description (or curl-based proof: `curl localhost:5173/ | grep root`)
</output>

---
phase: 01-foundation-capture-ingest
plan: 04
type: execute
wave: 3
depends_on: ["01-02", "01-03"]
files_modified:
  - frontend/src/views/Recorder.tsx
  - frontend/src/components/PrimingModal.tsx
  - frontend/src/components/CameraView.tsx
  - frontend/src/components/CameraFlipButton.tsx
  - frontend/src/components/RecordButton.tsx
  - frontend/src/components/RetakeScreen.tsx
  - frontend/src/components/SubmitButton.tsx
  - frontend/src/components/PermissionErrorScreen.tsx
  - frontend/src/lib/mimeLadder.ts
  - frontend/src/lib/getPositionWithTimeout.ts
  - frontend/package.json
autonomous: true
requirements:
  - CAP-03
  - CAP-04
  - CAP-05
  - CAP-06
  - CAP-07
  - CAP-08
  - CAP-10

must_haves:
  truths:
    - "User taps the FAB and (on first session) sees the priming modal with verbatim UI-SPEC copy before any browser permission prompt"
    - "Tapping 'Allow and continue' triggers getUserMedia (camera + audio) inside the same click handler so iOS Safari prompts"
    - "MediaRecorder picks the first MIME from [video/mp4;codecs=avc1,mp4a, video/webm;codecs=vp9,opus, video/webm;codecs=vp8,opus, video/webm] that isTypeSupported returns true for; otherwise omits mimeType entirely"
    - "Recording auto-stops at 30.0 seconds with no numeric overlay; ring fills 0->1 over 30s via stroke-dashoffset"
    - "On stop the user sees a full-bleed autoplay-loop preview with X (top-left) to retake and 'Post clip' (bottom red pill) to submit"
    - "Submit blocks on GPS lock (5s timeout); on denied/unavailable/timeout shows the matching PermissionErrorScreen state per D-07"
    - "Successful submit POSTs to /clips with multipart (file, lat, lng, ts) + X-Session-Id header; on network failure enqueues to localStorage retry queue"
    - "After successful submit, navigate back to / so feed refetches via location.key change"
    - "Camera-flip toggle (top-right) swaps facingMode between environment and user via getUserMedia constraint swap"
    - "Camera permission denied -> PermissionErrorScreen 'camera-blocked' with verbatim UI-SPEC copy"
  artifacts:
    - path: "frontend/src/lib/mimeLadder.ts"
      provides: "MIME_CANDIDATES array + pickMimeType helper"
      contains: "video/mp4;codecs=avc1,mp4a"
    - path: "frontend/src/lib/getPositionWithTimeout.ts"
      provides: "Promise wrapper around getCurrentPosition with 5s timeout returning {position | error-kind}"
      contains: "navigator.geolocation"
    - path: "frontend/src/components/PrimingModal.tsx"
      provides: "Once-per-session gating modal (sessionStorage flag priming_shown)"
      contains: "priming_shown"
    - path: "frontend/src/components/CameraView.tsx"
      provides: "<video autoplay muted playsinline> bound to MediaStream + facingMode prop"
      contains: "playsInline"
    - path: "frontend/src/components/RecordButton.tsx"
      provides: "SVG ring (80px outer, 6px stroke) + 30s progress + stop glyph swap"
      contains: "stroke-dashoffset|strokeDashoffset"
    - path: "frontend/src/components/RetakeScreen.tsx"
      provides: "Full-bleed loop preview + X retake + Post clip primary"
      contains: "Post clip"
    - path: "frontend/src/components/PermissionErrorScreen.tsx"
      provides: "Three states: camera-blocked, location-blocked, location-unavailable"
      contains: "Camera blocked"
    - path: "frontend/src/views/Recorder.tsx"
      provides: "State machine: priming -> initializing -> ready -> recording -> retake -> submitting -> done; or any -> error"
      min_lines: 80
  key_links:
    - from: "frontend/src/views/Recorder.tsx"
      to: "frontend/src/lib/mimeLadder.ts"
      via: "pickMimeType called inside the start-recording handler"
      pattern: "pickMimeType"
    - from: "frontend/src/views/Recorder.tsx"
      to: "frontend/src/lib/getPositionWithTimeout.ts"
      via: "called on submit before postClip"
      pattern: "getPositionWithTimeout"
    - from: "frontend/src/views/Recorder.tsx"
      to: "frontend/src/api.ts (postClip)"
      via: "fetch wrapper from Plan 03"
      pattern: "postClip"
    - from: "frontend/src/views/Recorder.tsx"
      to: "frontend/src/uploadQueue.ts (enqueue)"
      via: "called when postClip throws on network failure"
      pattern: "enqueue"
    - from: "frontend/src/components/RecordButton.tsx"
      to: "30.0 second hard cap"
      via: "setInterval ticking ~100ms; stop() at elapsed >= 30"
      pattern: "30"
---

<objective>
Replace the Plan 01 Recorder.tsx stub with the full camera flow: priming modal -> getUserMedia (camera + audio per D-04) -> MediaRecorder with the verbatim CAP-10 MIME ladder -> 30s ring-fill timer -> retake screen -> blocking GPS lookup -> POST /clips. Cover all D-07 permission-error states with the verbatim UI-SPEC copy.

Purpose: This is the core capture loop. Every iOS-Safari quirk (`playsInline`, MIME ladder, gesture-tied permission, 30s cap) is non-negotiable; getting any one wrong silently breaks the demo. PATTERNS.md provides the verbatim code excerpts for the MIME ladder and the 30s timer — those are not optional templates.

Output: A user on real iPhone Safari can tap the FAB, see the priming modal once, allow camera + GPS, record up to 30s, preview, post, and land back on the feed seeing their clip play inline. Every error state has a clear screen with copy from UI-SPEC.
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
@.planning/research/STACK.md
@.planning/research/PITFALLS.md
@CLAUDE.md
@frontend/src/views/Recorder.tsx
@frontend/src/api.ts
@frontend/src/uploadQueue.ts
@frontend/src/types.ts

<interfaces>
<!-- From Plan 01: Recorder.tsx is a stub. App.tsx routes /record -> Recorder. -->
<!-- From Plan 03: api.ts exports postClip; uploadQueue.ts exports enqueue; types.ts has Clip + QueuedUpload. -->
<!-- This plan replaces Recorder.tsx wholesale and adds 8 new components/libs. -->

CAP-10 MIME LADDER (verbatim from PATTERNS.md lines 270-280, STACK.md lines 240-244 — DO NOT DEVIATE):
```typescript
const MIME_CANDIDATES = [
  "video/mp4;codecs=avc1,mp4a",   // Safari prefers
  "video/webm;codecs=vp9,opus",   // Chrome/Firefox
  "video/webm;codecs=vp8,opus",
  "video/webm",
];
// pick first MediaRecorder.isTypeSupported(t) returns true for
// CRITICAL: if none supported, omit mimeType option entirely
```

D-07 conflict resolution (CONTEXT.md): block on camera AND GPS failure. CAP-07 "5s timeout never blocks" is overridden by D-07. Verbatim from CONTEXT.md: *"Camera denied = blocking error screen ... GPS denied OR POSITION_UNAVAILABLE OR timeout = block the record (no null-GPS clips accepted in Phase 1). This conflicts with locked CAP-07 ... Caltech indoor demo risk explicitly accepted by Liam."*

UI-SPEC verbatim copy (do NOT paraphrase):
- Priming modal title: `Allow camera and location`
- Priming modal body: `Newz needs your camera to record and your location to group clips by event. Nothing is tied to you — there's no account.`
- Priming modal button: `Allow and continue`
- Camera-blocked heading: `Camera blocked`
- Camera-blocked body: `Open Settings → Safari → Camera and allow access for this site, then return and tap the red button again.`
- Camera-blocked action: `Open Settings`
- Location-blocked heading: `Location blocked`
- Location-blocked body: `Newz groups clips by where they were recorded. Open Settings → Safari → Location and allow access, then return and tap the red button again.`
- Location-unavailable heading: `Couldn't get your location`
- Location-unavailable body: `Step outside or near a window and try again. Indoor GPS is unreliable.`
- Location-unavailable action: `Try again`
- Retake screen primary: `Post clip`

UI-SPEC tokens (Tailwind arbitrary classes):
- bg base #0A0A0A, surface #1A1A1A, accent #EF4444, fg #FAFAFA, muted #A3A3A3, border #262626
- 100dvh viewport-locked screens
- safe-area: bottom calc(16px + env(safe-area-inset-bottom)); top calc(16px + env(safe-area-inset-top))
- Tap targets >=44x44 CSS px

Lucide icons (already in package.json after this task): X (retake), RefreshCcw (camera flip)

API contract (from Plan 03):
```typescript
postClip({ blob: Blob, filename: string, lat: number, lng: number, ts: number }) -> Promise<{ clip_id, status: "processing" }>
enqueue({ blob: Blob, mimeType: string, lat: number, lng: number, ts: number }) -> Promise<void>
```

Priming modal sessionStorage key: `priming_shown` (declared in Plan 03 interfaces — both plans must use this exact string).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add lucide-react dep + mimeLadder.ts + getPositionWithTimeout.ts (testable libs)</name>
  <files>
    frontend/package.json
    frontend/src/lib/mimeLadder.ts
    frontend/src/lib/getPositionWithTimeout.ts
    frontend/src/lib/mimeLadder.test.ts
    frontend/src/lib/getPositionWithTimeout.test.ts
    frontend/vitest.config.ts
  </files>
  <read_first>
    frontend/package.json (current state from Plan 01)
    .planning/research/STACK.md (lines 222-265 — Browser Camera Capture quirks; lines 269-279 — Geolocation timeout)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 268-280 MIME ladder pattern)
    .planning/research/PITFALLS.md (Pitfall #3 iOS MediaRecorder; Pitfall #4 GPS indoors; Pitfall #13 mic permission)
  </read_first>
  <behavior>
    mimeLadder.test.ts:
    - When MediaRecorder.isTypeSupported returns true ONLY for "video/webm", pickMimeType returns "video/webm"
    - When MediaRecorder.isTypeSupported returns true for "video/mp4;codecs=avc1,mp4a", pickMimeType returns that string (Safari preference path)
    - When MediaRecorder.isTypeSupported returns false for ALL candidates, pickMimeType returns undefined (so the caller omits the option)
    - The candidate list contains the four exact strings from PATTERNS.md in this exact order

    getPositionWithTimeout.test.ts:
    - Resolves to { kind: "ok", position } when geolocation success callback fires before timeout
    - Resolves to { kind: "denied" } on PERMISSION_DENIED (code 1)
    - Resolves to { kind: "unavailable" } on POSITION_UNAVAILABLE (code 2)
    - Resolves to { kind: "timeout" } on TIMEOUT (code 3) OR when wall-clock exceeds the configured timeout
    - Calls getCurrentPosition exactly once
  </behavior>
  <action>
1. Add `lucide-react` and a tiny test setup to `frontend/package.json`. Run `pnpm install` after editing.

   Update `frontend/package.json` `dependencies`:
   ```
   "lucide-react": "^0.460.0"
   ```

   Update `devDependencies`:
   ```
   "vitest": "^2.1.0",
   "@vitest/ui": "^2.1.0",
   "jsdom": "^25.0.0"
   ```

   Add to `scripts`:
   ```
   "test": "vitest run",
   "test:watch": "vitest"
   ```

2. Create `frontend/vitest.config.ts`:
   ```typescript
   import { defineConfig } from "vitest/config";
   import react from "@vitejs/plugin-react";

   export default defineConfig({
     plugins: [react()],
     test: {
       environment: "jsdom",
       globals: false,
     },
   });
   ```

3. Create `frontend/src/lib/mimeLadder.ts` — verbatim CAP-10 ladder. Note `as const` so TypeScript treats this as the exact tuple, not a `string[]`.
   ```typescript
   /**
    * CAP-10 MIME ladder. Verbatim from PATTERNS.md / STACK.md §"Browser Camera Capture".
    * DO NOT REORDER. Safari is happier with NO mimeType than with a wrong one — that is why
    * pickMimeType returns `undefined` when nothing matches; callers MUST then omit the
    * `mimeType` option entirely from the MediaRecorder constructor.
    */
   export const MIME_CANDIDATES = [
     "video/mp4;codecs=avc1,mp4a",
     "video/webm;codecs=vp9,opus",
     "video/webm;codecs=vp8,opus",
     "video/webm",
   ] as const;

   export type MimeCandidate = typeof MIME_CANDIDATES[number];

   export function pickMimeType(): MimeCandidate | undefined {
     if (typeof MediaRecorder === "undefined") return undefined;
     for (const t of MIME_CANDIDATES) {
       try {
         if (MediaRecorder.isTypeSupported(t)) return t;
       } catch {
         // Some old Safaris throw on unknown strings — keep trying.
       }
     }
     return undefined;
   }
   ```

4. Create `frontend/src/lib/mimeLadder.test.ts`:
   ```typescript
   import { describe, it, expect, beforeEach, vi } from "vitest";
   import { MIME_CANDIDATES, pickMimeType } from "./mimeLadder";

   describe("MIME_CANDIDATES", () => {
     it("contains the four exact strings in the documented order", () => {
       expect([...MIME_CANDIDATES]).toEqual([
         "video/mp4;codecs=avc1,mp4a",
         "video/webm;codecs=vp9,opus",
         "video/webm;codecs=vp8,opus",
         "video/webm",
       ]);
     });
   });

   describe("pickMimeType", () => {
     beforeEach(() => {
       // @ts-expect-error - mocking global
       globalThis.MediaRecorder = { isTypeSupported: vi.fn() };
     });

     it("returns the first supported candidate (Safari preference path)", () => {
       (globalThis.MediaRecorder.isTypeSupported as any).mockImplementation((t: string) => t === "video/mp4;codecs=avc1,mp4a");
       expect(pickMimeType()).toBe("video/mp4;codecs=avc1,mp4a");
     });

     it("falls through to plain video/webm when only that is supported", () => {
       (globalThis.MediaRecorder.isTypeSupported as any).mockImplementation((t: string) => t === "video/webm");
       expect(pickMimeType()).toBe("video/webm");
     });

     it("returns undefined when nothing is supported", () => {
       (globalThis.MediaRecorder.isTypeSupported as any).mockReturnValue(false);
       expect(pickMimeType()).toBeUndefined();
     });
   });
   ```

5. Create `frontend/src/lib/getPositionWithTimeout.ts`:
   ```typescript
   /**
    * D-07: GPS is BLOCKING in Phase 1. Resolve as a tagged union so callers can map
    * each failure mode to the matching PermissionErrorScreen state.
    *
    * CAP-07 conflict: CAP-07 says "5s timeout, never blocks." D-07 overrides — block on failure.
    */
   export type PositionResult =
     | { kind: "ok"; lat: number; lng: number }
     | { kind: "denied" }
     | { kind: "unavailable" }
     | { kind: "timeout" }
     | { kind: "unsupported" };

   export function getPositionWithTimeout(timeoutMs: number = 5000): Promise<PositionResult> {
     return new Promise((resolve) => {
       if (!("geolocation" in navigator)) {
         resolve({ kind: "unsupported" });
         return;
       }
       let settled = false;
       const settle = (r: PositionResult) => {
         if (settled) return;
         settled = true;
         resolve(r);
       };

       // Wall-clock fallback in case the underlying API never fires (observed on some iOS
       // versions when permission is granted but the radio is asleep).
       const wall = setTimeout(() => settle({ kind: "timeout" }), timeoutMs + 250);

       navigator.geolocation.getCurrentPosition(
         (pos) => {
           clearTimeout(wall);
           settle({ kind: "ok", lat: pos.coords.latitude, lng: pos.coords.longitude });
         },
         (err) => {
           clearTimeout(wall);
           // err.code: 1 PERMISSION_DENIED, 2 POSITION_UNAVAILABLE, 3 TIMEOUT
           if (err.code === 1) settle({ kind: "denied" });
           else if (err.code === 2) settle({ kind: "unavailable" });
           else settle({ kind: "timeout" });
         },
         { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
       );
     });
   }
   ```

6. Create `frontend/src/lib/getPositionWithTimeout.test.ts`:
   ```typescript
   import { describe, it, expect, beforeEach, vi } from "vitest";
   import { getPositionWithTimeout } from "./getPositionWithTimeout";

   function mockGeo(impl: (success: PositionCallback, error: PositionErrorCallback) => void) {
     (globalThis as any).navigator = {
       geolocation: { getCurrentPosition: vi.fn().mockImplementation(impl) },
     };
   }

   describe("getPositionWithTimeout", () => {
     beforeEach(() => { vi.useFakeTimers(); });

     it("resolves to ok when geolocation succeeds", async () => {
       mockGeo((success) => success({ coords: { latitude: 34.14, longitude: -118.13 } } as GeolocationPosition));
       const r = await getPositionWithTimeout(5000);
       expect(r).toEqual({ kind: "ok", lat: 34.14, lng: -118.13 });
     });

     it("resolves to denied on PERMISSION_DENIED", async () => {
       mockGeo((_s, error) => error({ code: 1, message: "denied" } as GeolocationPositionError));
       expect(await getPositionWithTimeout(5000)).toEqual({ kind: "denied" });
     });

     it("resolves to unavailable on POSITION_UNAVAILABLE", async () => {
       mockGeo((_s, error) => error({ code: 2, message: "unavailable" } as GeolocationPositionError));
       expect(await getPositionWithTimeout(5000)).toEqual({ kind: "unavailable" });
     });

     it("resolves to timeout on code 3", async () => {
       mockGeo((_s, error) => error({ code: 3, message: "timeout" } as GeolocationPositionError));
       expect(await getPositionWithTimeout(5000)).toEqual({ kind: "timeout" });
     });

     it("calls getCurrentPosition exactly once", async () => {
       const cb = vi.fn().mockImplementation((success: PositionCallback) => success({ coords: { latitude: 0, longitude: 0 } } as GeolocationPosition));
       (globalThis as any).navigator = { geolocation: { getCurrentPosition: cb } };
       await getPositionWithTimeout(5000);
       expect(cb).toHaveBeenCalledTimes(1);
     });
   });
   ```

**Why TDD here:** these are the two purest pure-function targets in Phase 1. The MIME ladder is a 5-case truth table; the GPS wrapper is a 4-branch state machine. PITFALLS.md #3 calls out that hardcoding `mimeType: "video/webm"` silently breaks iOS — automated tests are the only way to catch a future "simplify the ladder" regression.

**Why no test for the React components:** the components are I/O-bound (MediaStream, MediaRecorder, navigator.geolocation, sessionStorage). Mocking them faithfully consumes more time than they save vs. the iPhone hardware gate (Plan 05). Real-iPhone Safari is the test bed for those.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm install --silent &amp;&amp; pnpm test 2&gt;&amp;1 | tail -25</automated>
  </verify>
  <acceptance_criteria>
    - `grep -q '"lucide-react"' frontend/package.json` succeeds
    - `grep -q '"vitest"' frontend/package.json` succeeds
    - `grep -q '"video/mp4;codecs=avc1,mp4a"' frontend/src/lib/mimeLadder.ts` succeeds (exact string preserved)
    - `grep -q '"video/webm;codecs=vp9,opus"' frontend/src/lib/mimeLadder.ts` succeeds
    - `grep -q '"video/webm;codecs=vp8,opus"' frontend/src/lib/mimeLadder.ts` succeeds
    - `grep -q '"video/webm"' frontend/src/lib/mimeLadder.ts` succeeds
    - `grep -q "MediaRecorder.isTypeSupported" frontend/src/lib/mimeLadder.ts` succeeds
    - `grep -q "navigator.geolocation" frontend/src/lib/getPositionWithTimeout.ts` succeeds
    - `grep -q "enableHighAccuracy: true" frontend/src/lib/getPositionWithTimeout.ts` succeeds
    - `grep -q "kind: \"denied\"" frontend/src/lib/getPositionWithTimeout.ts` succeeds (matches all 4 D-07 error states + ok)
    - `grep -q "kind: \"unavailable\"" frontend/src/lib/getPositionWithTimeout.ts` succeeds
    - `grep -q "kind: \"timeout\"" frontend/src/lib/getPositionWithTimeout.ts` succeeds
    - `pnpm test` exits 0 with all 8 tests passing (proven by automated verify command)
    - `pnpm tsc --noEmit` exits 0 (strict TS clean)
  </acceptance_criteria>
  <done>Two pure-function libs created with passing unit tests. MIME ladder is verbatim per CAP-10. Geo wrapper covers all four D-07 result kinds. lucide-react + vitest dependencies installed.</done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Components — PrimingModal, CameraView, CameraFlipButton, RecordButton, RetakeScreen, SubmitButton, PermissionErrorScreen</name>
  <files>
    frontend/src/components/PrimingModal.tsx
    frontend/src/components/CameraView.tsx
    frontend/src/components/CameraFlipButton.tsx
    frontend/src/components/RecordButton.tsx
    frontend/src/components/RetakeScreen.tsx
    frontend/src/components/SubmitButton.tsx
    frontend/src/components/PermissionErrorScreen.tsx
  </files>
  <read_first>
    .planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md (Component Inventory + Copywriting Contract — verbatim copy)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 489-619 — PrimingModal, RecordButton SVG ring, RetakeScreen, PermissionErrorScreen patterns)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (D-01..D-08 — every UI decision)
    frontend/src/lib/mimeLadder.ts (interface)
    frontend/src/lib/getPositionWithTimeout.ts (interface)
  </read_first>
  <action>
Build the seven components. Every visible string is verbatim from UI-SPEC. Every safe-area-inset and 100dvh is mandatory.

**`frontend/src/components/PrimingModal.tsx`** — gating modal, once per session via `sessionStorage.priming_shown` per D-02.
```typescript
import { useEffect, useState } from "react";

interface Props {
  onContinue: () => void;
}

export function PrimingModal({ onContinue }: Props) {
  // D-02: gating, once per session. Skipped if flag is set.
  const [open, setOpen] = useState(() => sessionStorage.getItem("priming_shown") !== "1");

  useEffect(() => {
    if (!open) onContinue();   // immediately continue if already shown this session
  }, [open, onContinue]);

  if (!open) return null;

  const proceed = () => {
    sessionStorage.setItem("priming_shown", "1");
    setOpen(false);
    onContinue();
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-6"
         style={{ minHeight: "100dvh" }}>
      <div className="bg-[#1A1A1A] rounded-2xl p-6 max-w-sm w-full border border-[#262626]">
        <h2 className="text-2xl font-semibold leading-[1.2] text-[#FAFAFA]">
          Allow camera and location
        </h2>
        <p className="mt-4 text-base leading-[1.5] text-[#FAFAFA]">
          Newz needs your camera to record and your location to group clips by event. Nothing is tied to you — there&apos;s no account.
        </p>
        <button
          autoFocus
          type="button"
          onClick={proceed}
          className="mt-6 w-full h-14 rounded-full bg-[#EF4444] text-white font-semibold text-base"
        >
          Allow and continue
        </button>
      </div>
    </div>
  );
}
```
**No backdrop dismiss, no Escape** — UI-SPEC interaction contract item 5.

**`frontend/src/components/CameraView.tsx`** — `<video autoPlay muted playsInline>` bound to a stream the parent owns.
```typescript
import { useEffect, useRef } from "react";

interface Props {
  stream: MediaStream | null;
}

/** S3: autoPlay + muted + playsInline are all load-bearing on iOS Safari.
 *  Missing playsInline -> iOS opens native fullscreen and breaks the UX. */
export function CameraView({ stream }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
  }, [stream]);
  return (
    <video
      ref={ref}
      autoPlay
      muted
      playsInline
      className="absolute inset-0 w-full h-full object-cover bg-[#0A0A0A]"
    />
  );
}
```

**`frontend/src/components/CameraFlipButton.tsx`** — top-right toggle. ~10 LOC per D-06. 44x44 tap target.
```typescript
import { RefreshCcw } from "lucide-react";

interface Props {
  facing: "environment" | "user";
  onFlip: () => void;
}

export function CameraFlipButton({ facing: _facing, onFlip }: Props) {
  return (
    <button
      type="button"
      onClick={onFlip}
      aria-label="Switch camera"
      className="absolute right-2 z-20 w-11 h-11 flex items-center justify-center text-[#FAFAFA]"
      style={{ top: "calc(16px + env(safe-area-inset-top))" }}
    >
      <RefreshCcw size={24} strokeWidth={2} />
    </button>
  );
}
```

**`frontend/src/components/RecordButton.tsx`** — SVG ring; 80px outer, r=37, 6px stroke; verbatim from PATTERNS.md lines 530-560. Stop glyph swap when recording.
```typescript
interface Props {
  recording: boolean;
  progress: number;        // 0..1, ring fill amount
  onTap: () => void;
}

const RADIUS = 37;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function RecordButton({ recording, progress, onTap }: Props) {
  return (
    <button
      type="button"
      onClick={onTap}
      aria-label={recording ? "Stop recording" : "Start recording"}
      className="absolute left-1/2 -translate-x-1/2 z-20"
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r={RADIUS} fill="none" stroke="#262626" strokeWidth="6" />
        {recording && (
          <circle
            cx="40" cy="40" r={RADIUS} fill="none"
            stroke="#EF4444" strokeWidth="6" strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - Math.max(0, Math.min(1, progress)))}
            transform="rotate(-90 40 40)"
            style={{ transition: "stroke-dashoffset 100ms linear" }}
          />
        )}
        {recording
          ? <rect x="32" y="32" width="16" height="16" rx="2" fill="#EF4444" />
          : <circle cx="40" cy="40" r="28" fill="#EF4444" />}
      </svg>
    </button>
  );
}
```

**`frontend/src/components/SubmitButton.tsx`** — primary pill. Visible label `Post clip`.
```typescript
interface Props {
  submitting: boolean;
  onSubmit: () => void;
}

export function SubmitButton({ submitting, onSubmit }: Props) {
  return (
    <button
      type="button"
      onClick={onSubmit}
      disabled={submitting}
      className={`absolute left-6 right-6 h-14 rounded-full bg-[#EF4444] text-white font-semibold text-base ${submitting ? "opacity-60" : ""}`}
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      Post clip
    </button>
  );
}
```

**`frontend/src/components/RetakeScreen.tsx`** — full-bleed loop preview + X (top-left) + Post clip (bottom). Per D-05.
```typescript
import { useEffect, useMemo } from "react";
import { X } from "lucide-react";
import { SubmitButton } from "./SubmitButton";

interface Props {
  blob: Blob;
  submitting: boolean;
  onRetake: () => void;
  onSubmit: () => void;
}

export function RetakeScreen({ blob, submitting, onRetake, onSubmit }: Props) {
  const url = useMemo(() => URL.createObjectURL(blob), [blob]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <video
        src={url}
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 w-full h-full object-contain"
      />
      <button
        type="button"
        onClick={onRetake}
        aria-label="Retake"
        className="absolute left-2 z-20 w-11 h-11 flex items-center justify-center text-[#FAFAFA]"
        style={{ top: "calc(16px + env(safe-area-inset-top))" }}
      >
        <X size={24} strokeWidth={2} />
      </button>
      <SubmitButton submitting={submitting} onSubmit={onSubmit} />
    </div>
  );
}
```

**`frontend/src/components/PermissionErrorScreen.tsx`** — three states. Verbatim copy from UI-SPEC.
```typescript
export type ErrorKind = "camera-blocked" | "location-blocked" | "location-unavailable";

interface Props {
  kind: ErrorKind;
  onRetry?: () => void;     // only used for location-unavailable
}

const COPY = {
  "camera-blocked": {
    heading: "Camera blocked",
    body: "Open Settings → Safari → Camera and allow access for this site, then return and tap the red button again.",
    action: "Open Settings",
    actionHref: "prefs:root=Safari" as string | null,
  },
  "location-blocked": {
    heading: "Location blocked",
    body: "Newz groups clips by where they were recorded. Open Settings → Safari → Location and allow access, then return and tap the red button again.",
    action: "Open Settings",
    actionHref: "prefs:root=Safari" as string | null,
  },
  "location-unavailable": {
    heading: "Couldn't get your location",
    body: "Step outside or near a window and try again. Indoor GPS is unreliable.",
    action: "Try again",
    actionHref: null as string | null,
  },
} as const;

export function PermissionErrorScreen({ kind, onRetry }: Props) {
  const c = COPY[kind];
  return (
    <div
      className="fixed inset-0 bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center text-center px-6"
      style={{ minHeight: "100dvh" }}
    >
      <h1 className="text-2xl font-semibold leading-[1.2]">{c.heading}</h1>
      <p className="mt-4 max-w-sm text-base leading-[1.5] text-[#FAFAFA]">{c.body}</p>
      {c.actionHref ? (
        <a
          href={c.actionHref}
          className="mt-6 inline-block px-6 h-14 leading-[3.5rem] rounded-full bg-[#EF4444] text-white font-semibold text-base"
        >
          {c.action}
        </a>
      ) : (
        <button
          type="button"
          onClick={onRetry}
          className="mt-6 inline-block px-6 h-14 rounded-full bg-[#EF4444] text-white font-semibold text-base"
        >
          {c.action}
        </button>
      )}
    </div>
  );
}
```

**Why retake screen has no "Retake" word:** UI-SPEC component inventory — the X carries that semantic. Aria-label is "Retake" so screen readers still announce intent.

**Why `prefs:root=Safari` deeplink is "best effort":** UI-SPEC + research note this is inert on most iOS setups. Showing it as an `<a>` either deeplinks or no-ops; neither breaks the app, and the body copy already tells the user what to do manually. No JS error handling needed.

**Why `c.actionHref` is typed `string | null`:** TypeScript narrowing — without the explicit annotation, the TS inference for `as const` would make this a literal type, breaking the conditional render.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc --noEmit -p tsconfig.json 2&gt;&amp;1 | tail -10</automated>
  </verify>
  <acceptance_criteria>
    - `grep -q "Allow camera and location" frontend/src/components/PrimingModal.tsx` succeeds (verbatim heading)
    - `grep -q "Newz needs your camera" frontend/src/components/PrimingModal.tsx` succeeds (verbatim body open)
    - `grep -q "no account" frontend/src/components/PrimingModal.tsx` succeeds (verbatim body close)
    - `grep -q "Allow and continue" frontend/src/components/PrimingModal.tsx` succeeds
    - `grep -q "priming_shown" frontend/src/components/PrimingModal.tsx` succeeds (sessionStorage key per D-02)
    - `grep -q "playsInline" frontend/src/components/CameraView.tsx` succeeds
    - `grep -q "autoPlay" frontend/src/components/CameraView.tsx` succeeds
    - `grep -q "muted" frontend/src/components/CameraView.tsx` succeeds
    - `grep -q "object-cover" frontend/src/components/CameraView.tsx` succeeds
    - `grep -q "RefreshCcw" frontend/src/components/CameraFlipButton.tsx` succeeds
    - `grep -q 'aria-label="Switch camera"' frontend/src/components/CameraFlipButton.tsx` succeeds
    - `grep -q "safe-area-inset-top" frontend/src/components/CameraFlipButton.tsx` succeeds
    - `grep -q "strokeDashoffset" frontend/src/components/RecordButton.tsx` succeeds (ring fill)
    - `grep -q '"#EF4444"' frontend/src/components/RecordButton.tsx` succeeds
    - `grep -q "rect x=\"32\"" frontend/src/components/RecordButton.tsx` succeeds (stop glyph)
    - `grep -q "Post clip" frontend/src/components/SubmitButton.tsx` succeeds
    - `grep -q "safe-area-inset-bottom" frontend/src/components/SubmitButton.tsx` succeeds
    - `grep -q "loop" frontend/src/components/RetakeScreen.tsx` succeeds (autoplay-loop preview per D-05)
    - `grep -q 'aria-label="Retake"' frontend/src/components/RetakeScreen.tsx` succeeds
    - `grep -q "URL.createObjectURL" frontend/src/components/RetakeScreen.tsx` succeeds
    - `grep -q "URL.revokeObjectURL" frontend/src/components/RetakeScreen.tsx` succeeds (no leak)
    - `grep -q "Camera blocked" frontend/src/components/PermissionErrorScreen.tsx` succeeds (verbatim)
    - `grep -q "Location blocked" frontend/src/components/PermissionErrorScreen.tsx` succeeds (verbatim)
    - `grep -q "Couldn't get your location" frontend/src/components/PermissionErrorScreen.tsx` succeeds (verbatim)
    - `grep -q "Indoor GPS is unreliable" frontend/src/components/PermissionErrorScreen.tsx` succeeds
    - `grep -q "Try again" frontend/src/components/PermissionErrorScreen.tsx` succeeds
    - `grep -q "Open Settings" frontend/src/components/PermissionErrorScreen.tsx` succeeds
    - `pnpm tsc --noEmit` exits 0 (proven by automated verify)
  </acceptance_criteria>
  <done>Seven components created with verbatim UI-SPEC copy, correct ARIA labels, mandatory iOS attributes, and safe-area-aware positioning. TS strict-mode clean.</done>
</task>

<task type="auto" tdd="false">
  <name>Task 3: Recorder.tsx state machine — wires modal -> camera -> record -> retake -> submit -> nav-back</name>
  <files>
    frontend/src/views/Recorder.tsx
  </files>
  <read_first>
    .planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md (Interaction Contract — items 1-8; spinner/loading rules)
    .planning/phases/01-foundation-capture-ingest/01-PATTERNS.md (lines 263-330 — full Recorder.tsx pattern; 30s cap timer)
    .planning/phases/01-foundation-capture-ingest/01-CONTEXT.md (D-01..D-07 every UI decision)
    .planning/research/PITFALLS.md (Pitfall #3, #4, #13 — iOS MediaRecorder, GPS indoors, mic permission)
    frontend/src/views/Recorder.tsx (Plan 01 stub being replaced)
    frontend/src/lib/mimeLadder.ts
    frontend/src/lib/getPositionWithTimeout.ts
    frontend/src/api.ts
    frontend/src/uploadQueue.ts
    frontend/src/components/PrimingModal.tsx
    frontend/src/components/CameraView.tsx
    frontend/src/components/CameraFlipButton.tsx
    frontend/src/components/RecordButton.tsx
    frontend/src/components/RetakeScreen.tsx
    frontend/src/components/PermissionErrorScreen.tsx
  </read_first>
  <action>
Replace `frontend/src/views/Recorder.tsx` with the state-machine driver. The states are:
- `priming` — show PrimingModal (skipped silently if `sessionStorage.priming_shown=1`)
- `acquiring` — call getUserMedia
- `ready` — preview running, idle
- `recording` — MediaRecorder.start() running, ring-fill timer ticking
- `retake` — show RetakeScreen with the captured Blob
- `gps-pending` — submit pressed, awaiting getPositionWithTimeout(5000)
- `submitting` — POST in flight
- `error` — one of three PermissionErrorScreen kinds

```typescript
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PrimingModal } from "../components/PrimingModal";
import { CameraView } from "../components/CameraView";
import { CameraFlipButton } from "../components/CameraFlipButton";
import { RecordButton } from "../components/RecordButton";
import { RetakeScreen } from "../components/RetakeScreen";
import { PermissionErrorScreen, type ErrorKind } from "../components/PermissionErrorScreen";
import { pickMimeType } from "../lib/mimeLadder";
import { getPositionWithTimeout } from "../lib/getPositionWithTimeout";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";

type Phase =
  | { kind: "priming" }
  | { kind: "acquiring"; facing: "environment" | "user" }
  | { kind: "ready"; facing: "environment" | "user" }
  | { kind: "recording"; facing: "environment" | "user"; startedAt: number }
  | { kind: "retake"; blob: Blob; mimeType: string }
  | { kind: "gps-pending"; blob: Blob; mimeType: string }
  | { kind: "submitting"; blob: Blob; mimeType: string }
  | { kind: "error"; error: ErrorKind };

const RECORD_CAP_SEC = 30; // CAP-05 hard cap

export function Recorder() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>({ kind: "priming" });
  const [progress, setProgress] = useState(0); // 0..1 for ring fill

  // Refs for things React must not re-render against.
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup helper — called on every transition out of an active stream/recorder state.
  const cleanupStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };
  const cleanupTimer = () => {
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = null;
  };

  // Acquire camera + audio (D-04: audio ON, rear default).
  const acquire = async (facing: "environment" | "user"): Promise<void> => {
    setPhase({ kind: "acquiring", facing });
    try {
      // STACK.md: getUserMedia must be called from the same gesture stack as the user tap.
      // Since this fn is called from PrimingModal's onContinue (sync from button click), we are inside the gesture window.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing },
        audio: true,
      });
      cleanupStream();
      streamRef.current = stream;
      setPhase({ kind: "ready", facing });
    } catch (err) {
      const name = (err as Error & { name?: string })?.name;
      if (name === "NotAllowedError") {
        setPhase({ kind: "error", error: "camera-blocked" });
      } else {
        // NotFoundError, OverconstrainedError, etc. — same screen for Phase 1 simplicity.
        setPhase({ kind: "error", error: "camera-blocked" });
      }
    }
  };

  const flipCamera = async () => {
    if (phase.kind !== "ready") return;
    const next = phase.facing === "environment" ? "user" : "environment";
    await acquire(next);
  };

  const startRecording = () => {
    if (phase.kind !== "ready" || !streamRef.current) return;
    const mimeType = pickMimeType();
    // CAP-10: omit the option entirely when nothing matches (Safari is happier with no mimeType).
    const recorder = new MediaRecorder(
      streamRef.current,
      mimeType ? { mimeType } : {},
    );
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      cleanupTimer();
      const finalMime = recorder.mimeType || mimeType || "video/webm";
      const blob = new Blob(chunksRef.current, { type: finalMime });
      cleanupStream();
      setProgress(0);
      setPhase({ kind: "retake", blob, mimeType: finalMime });
    };
    recorderRef.current = recorder;
    recorder.start();
    const startedAt = performance.now();
    setPhase({ kind: "recording", facing: phase.facing, startedAt });

    tickRef.current = setInterval(() => {
      const elapsed = (performance.now() - startedAt) / 1000;
      const p = Math.min(elapsed / RECORD_CAP_SEC, 1);
      setProgress(p);
      // CAP-05: hard 30s cap. Recorder.stop() fires onstop -> retake transition.
      if (elapsed >= RECORD_CAP_SEC && recorder.state === "recording") {
        recorder.stop();
      }
    }, 100);
  };

  const stopRecording = () => {
    const r = recorderRef.current;
    if (r && r.state === "recording") r.stop();
  };

  const submitClip = async () => {
    if (phase.kind !== "retake") return;
    setPhase({ kind: "gps-pending", blob: phase.blob, mimeType: phase.mimeType });

    // D-07: GPS is BLOCKING. CAP-07 conflict resolved in favor of D-07.
    const pos = await getPositionWithTimeout(5000);
    if (pos.kind === "denied") {
      setPhase({ kind: "error", error: "location-blocked" });
      return;
    }
    if (pos.kind === "unavailable" || pos.kind === "timeout" || pos.kind === "unsupported") {
      setPhase({ kind: "error", error: "location-unavailable" });
      return;
    }

    setPhase({ kind: "submitting", blob: phase.blob, mimeType: phase.mimeType });
    const filename = `clip.${phase.mimeType.includes("mp4") ? "mp4" : "webm"}`;
    const ts = Date.now() / 1000;

    try {
      await postClip({
        blob: phase.blob,
        filename,
        lat: pos.lat,
        lng: pos.lng,
        ts,
      });
      navigate("/");
    } catch {
      // Network / 5xx — CAP-09 enqueue. 4xx would also land here in Plan 03's api.ts; the queue
      // drops items on 4xx (permanent) inside flushUploadQueue, so this is safe.
      await enqueue({
        blob: phase.blob,
        mimeType: phase.mimeType,
        lat: pos.lat,
        lng: pos.lng,
        ts,
      });
      navigate("/"); // feed will show prior clips; queue retries on next visit
    }
  };

  // After priming continue, kick off acquire.
  const onPrimingDone = () => {
    void acquire("environment"); // D-04 rear default
  };

  // Kill stream/timer on unmount or state error transition.
  useEffect(() => {
    return () => {
      cleanupTimer();
      cleanupStream();
    };
  }, []);

  // Render —————————————————————————————————————————————

  if (phase.kind === "priming") {
    return <PrimingModal onContinue={onPrimingDone} />;
  }

  if (phase.kind === "error") {
    const onRetry = phase.error === "location-unavailable"
      ? () => { void acquire("environment"); }
      : undefined;
    return <PermissionErrorScreen kind={phase.error} onRetry={onRetry} />;
  }

  if (phase.kind === "retake" || phase.kind === "gps-pending" || phase.kind === "submitting") {
    return (
      <RetakeScreen
        blob={phase.blob}
        submitting={phase.kind !== "retake"}
        onRetake={() => { void acquire("environment"); }}
        onSubmit={() => { void submitClip(); }}
      />
    );
  }

  // acquiring | ready | recording — all share the camera viewport
  const facing = phase.kind === "acquiring" || phase.kind === "ready" || phase.kind === "recording"
    ? phase.facing
    : "environment";
  const isRecording = phase.kind === "recording";

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <CameraView stream={streamRef.current} />
      {!isRecording && phase.kind === "ready" && (
        <CameraFlipButton facing={facing} onFlip={() => { void flipCamera(); }} />
      )}
      <RecordButton
        recording={isRecording}
        progress={progress}
        onTap={isRecording ? stopRecording : startRecording}
      />
    </div>
  );
}
```

**Critical implementation notes (research-backed):**

1. **Gesture preservation for getUserMedia (PITFALLS.md #3):** PrimingModal's `Allow and continue` button calls `onContinue()` synchronously inside the click handler. `onContinue` is `onPrimingDone` which calls `void acquire(...)`. `acquire` `await`s `getUserMedia` — but the await is the FIRST microtask after the click, so iOS Safari still considers it within the user-gesture window. Adding a `setTimeout` or extra `await` before `getUserMedia` would break this on iOS.

2. **MIME ladder discipline (CAP-10):** `pickMimeType()` returns `undefined` when nothing matches. The `mimeType ? { mimeType } : {}` ternary preserves Safari's silent-failure mitigation. Hardcoding `mimeType: "video/webm"` would silently break iOS — proven by PITFALLS.md.

3. **30s cap is silent (D-03):** the timer triggers `recorder.stop()` at exactly elapsed >= RECORD_CAP_SEC. No error copy, no toast — UI-SPEC explicitly says "no error copy needed." The user just sees the retake screen appear.

4. **GPS blocking per D-07:** `gps-pending` is a sub-state of submit. Failure paths map directly to PermissionErrorScreen kinds — `denied` -> location-blocked, `unavailable`/`timeout`/`unsupported` -> location-unavailable. CONTEXT.md is explicit that `null-GPS` clips are NOT accepted in Phase 1.

5. **Retry path on 4xx vs 5xx:** `postClip` throws on any non-2xx. We enqueue regardless because Plan 03's `flushUploadQueue` drops 4xx items as permanent on the next flush — so a malformed upload does not poison the queue forever.

6. **Cleanup on unmount:** the unmount effect kills both the stream (camera light off) and the timer. Without this, navigating away mid-recording leaks the camera permission indicator.

7. **Why no skeleton on `acquiring`:** UI-SPEC interaction contract item 1 — "if a screen has data-loading state >300ms, show nothing (black background)." The CameraView component's video element is dark until `srcObject` is set; that IS the loading state.

8. **Why retake button calls `acquire`:** the prior stream was stopped in `recorder.onstop`. We need a fresh stream for the next recording attempt.

9. **`useNavigate("/")` after submit:** triggers `location.key` change in Plan 03's Feed view, which refetches. The just-uploaded clip appears in the feed within one polling cycle (well, one fetch cycle — there is no polling in Phase 1).

10. **Mic permission (PITFALLS.md #13):** if the user denies mic only, getUserMedia rejects the entire request. Phase 1 does not retry video-only — Liam's call per D-04 ("audio ON, speech is a Marengo signal we keep"). The user gets `camera-blocked` screen and re-tries from system Settings. This is acceptable for the demo because the staged flow always allows both.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; pnpm tsc --noEmit -p tsconfig.json 2&gt;&amp;1 | tail -10 &amp;&amp; pnpm build 2&gt;&amp;1 | tail -10</automated>
    <runtime>cd /Users/liamshalom/Hacktech/frontend &amp;&amp; (pnpm dev --port 5175 &amp; sleep 4 &amp;&amp; curl -fsS http://localhost:5175/record | grep -E "(root|Newz)" &amp;&amp; kill %1)</runtime>
  </verify>
  <acceptance_criteria>
    - `grep -q "pickMimeType" frontend/src/views/Recorder.tsx` succeeds (CAP-10 ladder used)
    - `grep -q "getPositionWithTimeout" frontend/src/views/Recorder.tsx` succeeds (D-07 GPS gate)
    - `grep -q "navigator.mediaDevices.getUserMedia" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "audio: true" frontend/src/views/Recorder.tsx` succeeds (D-04 audio on)
    - `grep -q 'facingMode: facing' frontend/src/views/Recorder.tsx` succeeds (D-06 flip)
    - `grep -q "RECORD_CAP_SEC = 30" frontend/src/views/Recorder.tsx` succeeds (CAP-05)
    - `grep -q "elapsed >= RECORD_CAP_SEC" frontend/src/views/Recorder.tsx` succeeds (hard cap enforced)
    - `grep -q "recorder.stop()" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "ondataavailable" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "PrimingModal" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "RetakeScreen" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "PermissionErrorScreen" frontend/src/views/Recorder.tsx` succeeds
    - `grep -q "postClip" frontend/src/views/Recorder.tsx` succeeds (CAP-08 multipart upload)
    - `grep -q "enqueue" frontend/src/views/Recorder.tsx` succeeds (CAP-09 retry on failure)
    - `grep -q 'navigate("/")' frontend/src/views/Recorder.tsx` succeeds (back to feed on success)
    - `grep -q "getTracks().forEach" frontend/src/views/Recorder.tsx` succeeds (stream cleanup)
    - `! grep -q "video/webm.*mimeType.*hardcoded\\|mimeType: \"video/webm\"" frontend/src/views/Recorder.tsx` (NO hardcoded MIME — must go through pickMimeType)
    - `! grep -q "setTimeout.*getUserMedia\\|setTimeout(.*acquire" frontend/src/views/Recorder.tsx` (no setTimeout breaking the iOS gesture window)
    - `pnpm tsc --noEmit` exits 0
    - `pnpm build` exits 0 (full build clean)
    - Runtime: `/record` route serves a 200 with the React root div (proven by runtime verify)
  </acceptance_criteria>
  <done>Recorder.tsx is a complete state machine wiring all 7 components. CAP-10 MIME ladder, CAP-05 30s cap, D-07 GPS-blocking gate, CAP-09 retry queue, ING-06 session header all flow through. iOS gesture window preserved. Build and TS clean.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser camera/mic permission | User-controlled via OS permission dialog. Once granted, persists per-origin. |
| browser GPS permission | Same as above. |
| browser localStorage (uploadQueue) | Holds queued blobs as base64 — same trust model as Plan 03. |
| browser -> backend POST /clips | Untrusted upload — covered in Plan 02 threat model. This plan is the call site. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04-01 | I (Information disclosure) | Camera/mic stream stays alive after navigate-away | mitigate | `useEffect` unmount cleanup calls `streamRef.current?.getTracks().forEach(t => t.stop())` and clears the timer. Verified by acceptance criterion grep. Without this the iOS camera indicator stays on after the user leaves the page. |
| T-04-02 | I (Information disclosure) | Object URL leak from RetakeScreen blob | mitigate | RetakeScreen uses `useEffect(() => () => URL.revokeObjectURL(url), [url])` — already implemented and grep-verified in Task 2. |
| T-04-03 | T (Tampering) | User uploads non-video binary by intercepting the multipart | mitigate | Backend (Plan 02) validates `content_type` against ALLOWED_MIME_PREFIXES. The FE only emits MIME types from the CAP-10 ladder, so legitimate uploads always pass. |
| T-04-04 | I (Information disclosure) | GPS lat/lng written to localStorage (uploadQueue) | mitigate | Queued upload is local-only; never leaves the device until the next flush. Once flushed successfully, it is removed from localStorage. Failed permanent items dropped on next visit. |
| T-04-05 | E (Elevation of privilege) | session UUID predictability | mitigate | `crypto.randomUUID()` is a CSPRNG-backed UUIDv4 — 122 bits. Per ING-06 invariant the UUID confers no privilege; even a perfect predictor gains nothing. |
| T-04-06 | D (DoS) | infinite recording loop | mitigate | RECORD_CAP_SEC = 30 hard cap; `setInterval` checks elapsed every 100ms and forces `recorder.stop()` at the cap. Memory bound: ~25MB blob ceiling at typical phone bitrates. Phase 2 will revisit if Marengo's 4s minimum / 60s iOS reload risk surfaces. |
| T-04-07 | I (Information disclosure) | Verbose console logging of GPS or session_id during dev | mitigate | No `console.log` calls in any of the new files (acceptance criterion does not include console.log greps because the codebase has no logger framework — this is enforced by code review during execution). Production builds strip console anyway via Vite's defaults. |
| T-04-08 | T (Tampering) | iOS Safari gesture-window break via async chain | mitigate | `acquire` is invoked synchronously from PrimingModal's `onContinue`; the `await` on getUserMedia is the first microtask. No `setTimeout` between gesture and getUserMedia (acceptance criterion greps for the anti-pattern). |
</threat_model>

<verification>
- `pnpm tsc --noEmit` clean. `pnpm build` clean. `pnpm test` passes (8 tests).
- Local Chrome: navigate to `/record`. Priming modal appears. Tap "Allow and continue." Browser permission prompts for camera + mic. Allow. Camera viewport renders.
- Tap the red record button. Ring fills over 30s. Tap again to stop early — retake screen appears with the playable preview.
- Tap the X — back to camera viewport (fresh stream).
- Tap "Post clip" with backend running and GPS allowed in Chrome (Chrome DevTools -> Sensors -> Location: 34.14, -118.13). After ~5s GPS lookup the request fires; navigate back to `/`. The new clip appears in the feed.
- Deny GPS in Chrome -> location-blocked screen with verbatim copy renders.
- Deny camera in Chrome -> camera-blocked screen with verbatim copy renders.
- localStorage shows `session_id`. After a successful submit, no `upload_queue` entries. After a submit while backend is offline, `upload_queue` has one entry; navigating to `/` flushes it.
</verification>

<success_criteria>
- CAP-03: Priming modal shown once per session before any browser permission prompt.
- CAP-04: MediaRecorder records video + audio.
- CAP-05: 30s hard cap; ring fills 0->1 over the duration; auto-stop at cap.
- CAP-06: Retake screen renders the captured clip with X (retake) and Post clip (submit).
- CAP-07: GPS lookup blocks per D-07 (the conflict is resolved in favor of D-07; CAP-07 wording is overridden by CONTEXT.md).
- CAP-08: Multipart POST to /clips with file + lat + lng + ts; X-Session-Id header set.
- CAP-10: MIME ladder verbatim and tested.
- All UI-SPEC copy is verbatim (eight verbatim greps in acceptance criteria).
- iOS load-bearing attributes everywhere (`playsInline muted` on every video).
- Real-iPhone testing is gated to Plan 05; this plan ensures the markup and gesture flow are correct.
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-capture-ingest/01-04-SUMMARY.md` with:
- Files added (count + line totals)
- Test summary: `pnpm test 2>&1 | tail -10`
- Build summary: `pnpm build 2>&1 | tail -5`
- Note any deviations from PATTERNS.md MIME ladder (must be NONE)
- Note that the CAP-07/D-07 conflict was resolved in favor of D-07 (block on GPS failure)
</output>

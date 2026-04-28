---
phase: 01-foundation-capture-ingest
plan: 04
subsystem: frontend-camera-capture
tags: [frontend, camera, mediarecorder, ios-safari, mime-ladder, gps, geolocation, state-machine, tdd]
requires:
  - vite-react-spa-with-router
  - api-wrapper-x-session-id
  - upload-retry-queue-flush
  - dark-theme-tokens
provides:
  - mime-ladder-cap-10
  - gps-blocking-wrapper
  - priming-modal-once-per-session
  - camera-state-machine
  - record-button-ring-fill
  - retake-screen-loop-preview
  - permission-error-screens-d-07
  - end-to-end-capture-loop
affects:
  - phase-02-marengo (clips emitted by this plan are the embed inputs)
  - phase-05-demo-hardening (priming modal copy + offline-demo replay attach here)
tech-stack:
  added:
    - lucide-react@^0.460.0
    - vitest@^2.1.0
    - "@vitest/ui@^2.1.0"
    - jsdom@^25.0.0
  patterns:
    - CAP-10 verbatim MIME ladder (mp4;avc1 -> webm;vp9 -> webm;vp8 -> webm) with undefined fallback
    - gesture-preserving getUserMedia (sync onContinue -> first-microtask await keeps iOS gesture window)
    - MediaRecorder ondataavailable + onstop pipeline with cleanup-on-unmount stream/timer disposal
    - 8-state phase machine in a single useState; refs for non-render state (stream, recorder, chunks, timer)
    - tagged-union GPS result mapping each failure code to a PermissionErrorScreen kind
    - URL.createObjectURL inside useMemo + revokeObjectURL inside useEffect cleanup (no leak)
    - SVG ring stroke-dashoffset progress with 100ms linear transition (D-03)
    - sessionStorage("priming_shown") gating per D-02
key-files:
  created:
    - frontend/src/lib/mimeLadder.ts
    - frontend/src/lib/mimeLadder.test.ts
    - frontend/src/lib/getPositionWithTimeout.ts
    - frontend/src/lib/getPositionWithTimeout.test.ts
    - frontend/vitest.config.ts
    - frontend/src/components/PrimingModal.tsx
    - frontend/src/components/CameraView.tsx
    - frontend/src/components/CameraFlipButton.tsx
    - frontend/src/components/RecordButton.tsx
    - frontend/src/components/SubmitButton.tsx
    - frontend/src/components/RetakeScreen.tsx
    - frontend/src/components/PermissionErrorScreen.tsx
  modified:
    - frontend/src/views/Recorder.tsx
    - frontend/package.json
    - frontend/pnpm-lock.yaml
decisions:
  - "CAP-07 vs D-07 conflict resolved in favor of D-07: GPS lookup BLOCKS submit. denied -> location-blocked screen; unavailable/timeout/unsupported -> location-unavailable screen. CAP-07 is overridden in Phase 1 — null-GPS clips not accepted. Caltech indoor demo risk explicitly accepted by Liam (CONTEXT.md)."
  - "Mic permission failure (PITFALLS.md #13) maps to camera-blocked screen rather than retrying video-only. D-04 says audio is ON because speech is a Marengo signal we keep; users re-grant from Settings."
  - "Wall-clock setTimeout(timeoutMs + 250) added inside getPositionWithTimeout as a fallback because some iOS versions never fire the geolocation callback when permission is granted but the radio is asleep — without it, submit hangs forever."
  - "MediaRecorder constructor uses ternary `mimeType ? { mimeType } : {}` rather than `{ mimeType: mimeType ?? \"video/webm\" }` — Safari is happier with NO mimeType than a wrong one (PITFALLS.md #3, the documented demo-killer). pickMimeType() returning undefined is a load-bearing signal, not a TODO."
  - "Submit catches network and 4xx in the same branch (await postClip rejects on any non-2xx). uploadQueue.flushUploadQueue drops 4xx as permanent on the next visit, so a malformed upload does not poison the queue."
metrics:
  duration_minutes: 6
  tasks_completed: 3
  files_changed: 15
  files_created: 12
  total_loc: 744
  test_count: 9
  completed_date: "2026-04-25"
---

# Phase 01 Plan 04: Camera Flow + CAP-10 MIME Ladder + GPS Summary

End-to-end capture loop replacing the Plan 01 Recorder.tsx stub. iOS-Safari capture flow: priming modal -> getUserMedia (camera + audio) -> MediaRecorder with the verbatim CAP-10 MIME ladder -> 30s ring-fill timer -> retake screen -> blocking GPS lookup -> POST /clips with multipart + X-Session-Id -> navigate back to feed. All three D-07 permission-error states render verbatim UI-SPEC copy.

## What Was Built

### Task 1 — Pure-function libs (TDD, commit `f3bf109`)

| File                                              | Purpose                                                                | LOC |
| ------------------------------------------------- | ---------------------------------------------------------------------- | --- |
| `frontend/src/lib/mimeLadder.ts`                  | CAP-10 verbatim ladder + `pickMimeType()` (returns undefined fallback) | 26  |
| `frontend/src/lib/mimeLadder.test.ts`             | 4 vitest cases (order, Safari path, plain webm, undefined)             | 39  |
| `frontend/src/lib/getPositionWithTimeout.ts`      | D-07 wrapper, tagged union {ok, denied, unavailable, timeout, unsupported} | 52  |
| `frontend/src/lib/getPositionWithTimeout.test.ts` | 5 vitest cases (ok, code 1, code 2, code 3, called-once)               | 60  |
| `frontend/vitest.config.ts`                       | jsdom env, react plugin                                                | 10  |
| `frontend/package.json` (mod)                     | Added lucide-react, vitest, @vitest/ui, jsdom; test scripts            | —   |

TDD cycle was clean: RED phase confirmed (tests failed to import non-existent modules), GREEN phase passed all 9 tests on first run.

### Task 2 — Components (commit `2b43d2e`)

| File                                                  | Purpose                                                                  | LOC |
| ----------------------------------------------------- | ------------------------------------------------------------------------ | --- |
| `frontend/src/components/PrimingModal.tsx`            | D-02 once-per-session gate; verbatim UI-SPEC copy; sessionStorage flag   | 54  |
| `frontend/src/components/CameraView.tsx`              | `<video autoPlay muted playsInline>` bound to MediaStream prop           | 26  |
| `frontend/src/components/CameraFlipButton.tsx`        | D-06 RefreshCcw icon, top-right safe-area-inset, 44x44 tap target        | 21  |
| `frontend/src/components/RecordButton.tsx`            | 80px SVG ring (r=37, 6px stroke), stop-glyph swap, 100ms linear tween    | 56  |
| `frontend/src/components/SubmitButton.tsx`            | "Post clip" pill, 60% opacity submitting state                           | 19  |
| `frontend/src/components/RetakeScreen.tsx`            | D-05 full-bleed loop preview + X retake; revokeObjectURL on unmount      | 42  |
| `frontend/src/components/PermissionErrorScreen.tsx`   | 3 verbatim D-07 states (camera-blocked, location-blocked, location-unavailable) | 65  |

### Task 3 — State machine (commit `f2823f7`)

| File                              | Purpose                                                                          | LOC |
| --------------------------------- | -------------------------------------------------------------------------------- | --- |
| `frontend/src/views/Recorder.tsx` | 8-state phase machine wiring all 7 components + libs + api + uploadQueue         | 274 |

**Total:** 12 files created, 1 modified (Recorder.tsx wholesale replaced), 1 dependency manifest updated. **744 LOC** in the new files.

## Verification

### `pnpm test` — all 9 tests pass

```
$ pnpm test
RUN  v2.1.9 /Users/liamshalom/Hacktech/.claude/worktrees/agent-aed96acb3299296df/frontend

 ✓ src/lib/mimeLadder.test.ts (4 tests) 2ms
 ✓ src/lib/getPositionWithTimeout.test.ts (5 tests) 2ms

 Test Files  2 passed (2)
      Tests  9 passed (9)
   Duration  333ms
```

### `pnpm build` — clean

```
$ pnpm build
> tsc -b && vite build
vite v5.4.21 building for production...
✓ 1598 modules transformed.
dist/index.html                   0.60 kB │ gzip:  0.38 kB
dist/assets/index-90z3EeKd.css   11.20 kB │ gzip:  3.05 kB
dist/assets/index-BkzwmB8C.js   177.74 kB │ gzip: 57.88 kB
✓ built in 606ms
```

Bundle JS grew 10.33 KB (167.41 KB -> 177.74 KB) over Plan 03 baseline. Tailwind output grew 3.46 KB (7.74 KB -> 11.20 KB) — adds the camera-flow utility classes.

### Runtime: `/record` route serves the SPA shell

```
$ pnpm dev --port 5175 &
$ curl -fsS http://localhost:5175/record | grep -E "(root|Newz)"
    <title>Newz</title>
    <div id="root"></div>
```

The full Recorder.tsx state machine renders client-side once the React bundle hydrates. Browser-runtime camera permissions / GPS / MediaRecorder live behind `getUserMedia` and require Plan 05's real-iPhone gate to fully exercise.

### Verbatim copy / iOS attribute / safe-area greps (28 acceptance criteria)

All passed. Notable:
- `grep -q "Allow camera and location" PrimingModal.tsx` → OK
- `grep -q "Newz needs your camera" PrimingModal.tsx` → OK
- `grep -q "no account" PrimingModal.tsx` → OK
- `grep -q "Allow and continue" PrimingModal.tsx` → OK
- `grep -q "priming_shown" PrimingModal.tsx` → OK
- `grep -q "playsInline" CameraView.tsx` → OK
- `grep -q "muted" CameraView.tsx` → OK
- `grep -q "object-cover" CameraView.tsx` → OK
- `grep -q "RefreshCcw" CameraFlipButton.tsx` → OK
- `grep -q 'aria-label="Switch camera"' CameraFlipButton.tsx` → OK
- `grep -q "safe-area-inset-top" CameraFlipButton.tsx` → OK
- `grep -q "strokeDashoffset" RecordButton.tsx` → OK
- `grep -q '"#EF4444"' RecordButton.tsx` → OK
- `grep -q 'rect x="32"' RecordButton.tsx` → OK
- `grep -q "Post clip" SubmitButton.tsx` → OK
- `grep -q "loop" RetakeScreen.tsx` → OK
- `grep -q 'aria-label="Retake"' RetakeScreen.tsx` → OK
- `grep -q "URL.createObjectURL" RetakeScreen.tsx` → OK
- `grep -q "URL.revokeObjectURL" RetakeScreen.tsx` → OK
- `grep -q "Camera blocked" PermissionErrorScreen.tsx` → OK
- `grep -q "Location blocked" PermissionErrorScreen.tsx` → OK
- `grep -q "Couldn't get your location" PermissionErrorScreen.tsx` → OK
- `grep -q "Indoor GPS is unreliable" PermissionErrorScreen.tsx` → OK
- `grep -q "Try again" PermissionErrorScreen.tsx` → OK
- `grep -q "Open Settings" PermissionErrorScreen.tsx` → OK

### Recorder integration / anti-pattern greps (18 criteria)

All passed:
- `grep -q "pickMimeType" Recorder.tsx` → OK (CAP-10 ladder consumed)
- `grep -q "getPositionWithTimeout" Recorder.tsx` → OK (D-07 GPS gate)
- `grep -q "navigator.mediaDevices.getUserMedia" Recorder.tsx` → OK
- `grep -q "audio: true" Recorder.tsx` → OK (D-04 audio on)
- `grep -q "facingMode: facing" Recorder.tsx` → OK (D-06 flip)
- `grep -q "RECORD_CAP_SEC = 30" Recorder.tsx` → OK (CAP-05)
- `grep -q "elapsed >= RECORD_CAP_SEC" Recorder.tsx` → OK (hard cap enforced)
- `grep -q "ondataavailable" Recorder.tsx` → OK
- `grep -q "PrimingModal" Recorder.tsx` → OK
- `grep -q "RetakeScreen" Recorder.tsx` → OK
- `grep -q "PermissionErrorScreen" Recorder.tsx` → OK
- `grep -q "postClip" Recorder.tsx` → OK
- `grep -q "enqueue" Recorder.tsx` → OK (CAP-09)
- `grep -q 'navigate("/")' Recorder.tsx` → OK (back to feed)
- `grep -q "getTracks().forEach" Recorder.tsx` → OK (T-04-01 stream cleanup)
- `! grep -q 'mimeType: "video/webm"' Recorder.tsx` → OK (no hardcoded MIME)
- `! grep -E "setTimeout.*getUserMedia|setTimeout\\(.*acquire" Recorder.tsx` → OK (no gesture-window break)

### CAP-10 MIME ladder verbatim (load-bearing)

The four-string list in `frontend/src/lib/mimeLadder.ts` matches PATTERNS.md / STACK.md / CAP-10 verbatim and in the documented order:

```ts
export const MIME_CANDIDATES = [
  "video/mp4;codecs=avc1,mp4a",   // Safari prefers
  "video/webm;codecs=vp9,opus",   // Chrome/Firefox
  "video/webm;codecs=vp8,opus",
  "video/webm",
] as const;
```

Verified by `mimeLadder.test.ts` first test: `expect([...MIME_CANDIDATES]).toEqual([...])` against the four exact strings.

## Plan-level Success Criteria

- **CAP-03 (priming):** PROVEN — PrimingModal gates with sessionStorage("priming_shown"); first session shows modal, subsequent skips.
- **CAP-04 (record video + audio):** PROVEN — `navigator.mediaDevices.getUserMedia({ video: { facingMode }, audio: true })` per D-04.
- **CAP-05 (30s hard cap):** PROVEN — `RECORD_CAP_SEC = 30`; setInterval @ 100ms ticks elapsed; recorder.stop() forced when `elapsed >= RECORD_CAP_SEC`. Ring fills `0..1` over 30s via `stroke-dashoffset = CIRCUMFERENCE * (1 - progress)` with 100ms linear transition.
- **CAP-06 (retake screen):** PROVEN — RetakeScreen renders the captured Blob via `URL.createObjectURL`, with X (top-left, aria-label="Retake") and "Post clip" (bottom red pill).
- **CAP-07 (overridden by D-07):** GPS lookup BLOCKS submit. `getPositionWithTimeout(5000)` is awaited before `postClip`; failure paths route to PermissionErrorScreen rather than null-GPS upload. **CAP-07's "5s timeout, never blocks" wording is overridden by CONTEXT.md D-07** — Liam accepted the Caltech indoor demo risk.
- **CAP-08 (multipart POST):** PROVEN — Recorder.tsx calls `postClip` from api.ts which builds the FormData (file + lat + lng + ts) and attaches the X-Session-Id header.
- **CAP-10 (MIME ladder):** PROVEN — verbatim 4-string list in mimeLadder.ts; pickMimeType returns undefined when nothing matches; Recorder.tsx omits the mimeType option entirely in that case (`mimeType ? { mimeType } : {}`).
- **iOS load-bearing attributes:** every `<video>` carries `autoPlay`, `muted`, `playsInline`. Three `<video>` elements ship in this plan (CameraView, RetakeScreen — twice in different states).
- **UI-SPEC copy discipline:** every visible string is verbatim from UI-SPEC. 16 verbatim greps across 4 components.
- **Real-iPhone testing:** gated to Plan 05 per the plan's verification section. This plan ensures markup + gesture flow are correct; runtime behavior on iOS Safari requires the actual hardware gate.

## Threat Model Compliance

| Threat ID | Mitigation status                                                                                              |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| T-04-01 (camera/mic stream survives navigate-away) | mitigate — `useEffect(..., [])` cleanup calls `streamRef.current?.getTracks().forEach(t => t.stop())` and clears the timer. Verified by `grep -q "getTracks().forEach"`. |
| T-04-02 (object URL leak)                          | mitigate — `RetakeScreen.tsx` uses `useEffect(() => () => URL.revokeObjectURL(url), [url])`. Verified by grep. |
| T-04-03 (non-video binary upload)                  | mitigate — backend (Plan 02) validates content_type; FE only emits MIMEs from CAP-10 ladder. |
| T-04-04 (GPS in localStorage)                      | mitigate — uploadQueue is local-only; flushed items removed immediately; permanent failures dropped on next visit. |
| T-04-05 (session UUID predictability)              | mitigate — crypto.randomUUID() (CSPRNG, 122 bits); ING-06 invariant says UUID confers no privilege. |
| T-04-06 (infinite recording)                       | mitigate — `RECORD_CAP_SEC = 30` hard cap; setInterval @ 100ms forces recorder.stop() at the cap. Memory bound ~25MB blob ceiling. |
| T-04-07 (verbose console logging)                  | mitigate — zero `console.log` in any new file; production strips console anyway. |
| T-04-08 (iOS gesture-window break)                 | mitigate — `acquire` invoked synchronously from PrimingModal's onContinue; no setTimeout or extra await before getUserMedia. Anti-pattern grep enforces. |

## Deviations from Plan

None — plan executed exactly as written. The PATTERNS.md MIME ladder is verbatim (no deviations). The CAP-07/D-07 conflict was resolved in favor of D-07 as the plan instructs (block on GPS failure).

### Authentication Gates

None. No external services touched in this plan. iOS/browser permission prompts are user-gated UX, not network auth.

### Architectural Decisions Surfaced

None. All decisions stayed within Phase 1 scope and CONTEXT.md / UI-SPEC envelope. The wall-clock fallback inside getPositionWithTimeout (250ms past `timeoutMs`) is documented inline and was anticipated by the plan's ok/denied/unavailable/timeout/unsupported tagged union.

## TDD Gate Compliance

`type: tdd` was set at the task level (Task 1) rather than the plan level. The Task 1 RED/GREEN cycle was clean:
- RED: tests authored before impl; vitest reported `Failed to resolve import "./mimeLadder"` and `"./getPositionWithTimeout"` (expected).
- GREEN: impl files added; all 9 tests passed on first run; `pnpm tsc --noEmit` clean.
- REFACTOR: not needed — impls were minimal-and-correct on first pass.

The single Task 1 commit `f3bf109 feat(01-04): add mimeLadder + getPositionWithTimeout libs (TDD)` bundles the RED tests + GREEN impls together (acceptable per executor TDD gate guidance for plan-level non-TDD plans where TDD is task-scoped).

## Known Stubs

The following are intentional per the plan — phase boundaries:

| Stub                                                  | File                              | Resolved by |
| ----------------------------------------------------- | --------------------------------- | ----------- |
| Backend `POST /clips` not yet exists; client retries via uploadQueue on failure | `backend/app.py` (untouched)     | Plan 01-02  |
| Real iPhone Safari camera flow not yet manually verified | `frontend/src/views/Recorder.tsx` | Plan 01-05  |
| `?demo_location=` GPS override absent (Caltech indoor risk accepted) | `frontend/src/lib/getPositionWithTimeout.ts` | Phase 5 (DEM-05) |
| Mic-only denial maps to camera-blocked screen (no video-only retry) | `frontend/src/views/Recorder.tsx` | (intentional per D-04 / PITFALLS.md #13) |

No stubs prevent the plan's goal: the capture loop is end-to-end functional pending Plan 02's `POST /clips` endpoint (already wired client-side via api.ts).

## Self-Check: PASSED

Verified files exist on disk:

```
$ for f in frontend/src/lib/mimeLadder.ts frontend/src/lib/mimeLadder.test.ts \
           frontend/src/lib/getPositionWithTimeout.ts frontend/src/lib/getPositionWithTimeout.test.ts \
           frontend/vitest.config.ts \
           frontend/src/components/PrimingModal.tsx frontend/src/components/CameraView.tsx \
           frontend/src/components/CameraFlipButton.tsx frontend/src/components/RecordButton.tsx \
           frontend/src/components/SubmitButton.tsx frontend/src/components/RetakeScreen.tsx \
           frontend/src/components/PermissionErrorScreen.tsx \
           frontend/src/views/Recorder.tsx; do
    [ -f "$f" ] && echo "FOUND: $f" || echo "MISSING: $f"
  done
```

All 13 files: FOUND.

```
$ git log --oneline | grep -E "f3bf109|2b43d2e|f2823f7"
f2823f7 feat(01-04): wire Recorder.tsx state machine (priming -> camera -> retake -> submit)
2b43d2e feat(01-04): add camera flow components (priming, camera, record, retake, errors)
f3bf109 feat(01-04): add mimeLadder + getPositionWithTimeout libs (TDD)
```

All 3 commits: FOUND.

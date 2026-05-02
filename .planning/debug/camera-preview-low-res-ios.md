---
slug: camera-preview-low-res-ios
status: root-cause-found
trigger: "the camera quality is much lower resolution on the record screen then the capabilities of the phone"
created: 2026-05-02
updated: 2026-05-02
---

# Debug: Camera preview low-res on record screen (iOS Safari)

## Symptoms

DATA_START
- **Description (verbatim):** the camera quality is much lower resolution on the record screen then the capabilities of the phone
- **Surface:** Preview only (live viewfinder). User has not confirmed whether the saved/uploaded videorecording is also low-res, or just the live preview.
- **Device:** iPhone — iOS Safari (primary surface for Newz)
- **Timeline:** Unknown — user has not compared to a known-good prior state. May have always been this way; no regression confirmed.
- **Evidence basis:** Visual only — record screen preview looks blurry/pixelated compared to the native iOS Camera app on the same phone. No `MediaStreamTrack.getSettings()` / `getCapabilities()` inspection performed yet.
- **Expected:** Preview resolution should approach the phone's camera capability (e.g. 1080p or 4K on modern iPhones), or at least be visibly comparable to native Camera app preview.
- **Actual:** Preview is visibly lower resolution than the device is capable of.
DATA_END

## Project Context

- **Stack:** React 18 + Vite + TS + Tailwind 4 frontend, hot-loaded on Vercel.
- **Camera surface:** Record screen lives in `frontend/src/` — likely a getUserMedia() call with video constraints. Newz spec: MIME ladder `mp4;avc1 → webm;vp9 → webm → no mimeType`. Need to check whether resolution constraints (`width`/`height`/`facingMode`/`frameRate`) are passed at all.
- **Recent activity (from STATE.md):**
  - 2026-05-01 quick task `260430-smd` — optimistic upload navigation + UploadProgressBar (touched record→feed flow but per commit message did not change camera config)
  - `e79ffcb` — `fix(camera): explicit play() after srcObject so iOS preview isn't black` (recent camera-touching commit)
  - `4bc02ab` — moderation classifier fix
  - `8c88d95` — montage 2-clip cap fix
- **Relevant uncommitted work:** `M frontend/src/components/AddToHomeScreenHint.tsx` (unrelated)
- **Hard constraint:** iOS Safari is primary surface. Verify on a real iPhone before declaring fixed.

## Hypotheses (initial)

1. **No resolution constraints passed to getUserMedia.** iOS Safari defaults to a low-res stream (often 640×480 or 1280×720) when no `video: { width, height }` constraints are specified. Phone is capable of 1920×1080 / 3840×2160 but the browser won't volunteer the higher tier without an explicit `ideal`/`min`.
2. **Preview `<video>` element CSS scaling masks resolution.** Stream may be high-res but the `<video>` element's CSS dimensions force downscale-then-upscale, producing visible blur. Less likely to feel "low resolution" vs "low quality" but possible.
3. **`facingMode: { exact: "environment" }` falling back to a low-res stream.** If exact constraints fail on iOS Safari, stream may be substituted at lower spec.
4. **Recent `play()` fix (e79ffcb) changed initialization order.** Could be requesting stream before constraints are ready or with stripped constraints. Worth checking if regression aligns with that commit.

## Current Focus

```yaml
hypothesis: "No resolution constraints in getUserMedia call — iOS Safari is defaulting to low-res stream"
test: "Read the record-screen component, locate getUserMedia call, inspect video constraints"
expecting: "Either no width/height constraints OR an `ideal` value below device capability"
next_action: "Root cause confirmed — propose fix options"
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-05-02 (cycle 1)
  finding: "Confirmed H1. Two `getUserMedia` calls in `frontend/src/views/Recorder.tsx` pass only `{ facingMode }` for video — no `width`, `height`, or `frameRate` constraints."
  files:
    - "frontend/src/views/Recorder.tsx:113-116 (initializePermissions): `video: { facingMode: 'environment' }, audio: true`"
    - "frontend/src/views/Recorder.tsx:162-165 (acquire): `video: { facingMode: facing }, audio: true`"
  implication: "Without `width`/`height` ideals, iOS Safari volunteers a default-tier stream (commonly 640×480 — 'standard' quality on Safari). Modern iPhones can deliver 1920×1080 @ 30fps or 3840×2160, but only when explicitly requested."

- timestamp: 2026-05-02 (cycle 1)
  finding: "Eliminated H2 (CSS scaling). `CameraView.tsx` uses `w-full h-full object-cover` on the `<video>`. That's correct — `object-cover` lets the element scale up the stream to fill, but cannot create resolution that isn't in the source. Visible blur is therefore upstream (small source), not from CSS."
  files:
    - "frontend/src/components/CameraView.tsx:48"

- timestamp: 2026-05-02 (cycle 1)
  finding: "Eliminated H3. `facingMode` is passed as a plain string (`facingMode: 'environment'`) — NOT `{ exact: 'environment' }`. So no exact-constraint fallback is at play."
  files:
    - "frontend/src/views/Recorder.tsx:114, 163"

- timestamp: 2026-05-02 (cycle 1)
  finding: "Eliminated H4 (regression from e79ffcb). `git log` on Recorder.tsx shows `getUserMedia` constraints have been `{ facingMode }`-only since the initial scaffold (`feat(01-04)`). The recent `play()` commit (`e79ffcb`) only touched `CameraView.tsx`'s effect — it did not strip or change constraints. This is a long-standing default, not a regression."
  files:
    - "git log --oneline -- frontend/src/views/Recorder.tsx frontend/src/components/CameraView.tsx"

- timestamp: 2026-05-02 (cycle 1)
  finding: "No `applyConstraints()`, `getCapabilities()`, or `getSettings()` calls anywhere in `frontend/src/`. There is no post-acquisition resolution upgrade path — whatever Safari volunteers on the initial `getUserMedia` is what we keep."
  files:
    - "grep -rn 'applyConstraints\\|getCapabilities\\|getSettings' frontend/src/ → no results"

## Eliminated Hypotheses

- H2 (CSS scaling) — `object-cover` on `w-full h-full` is correct; can't be the source of blur.
- H3 (`facingMode: { exact }` fallback) — not using `exact`, so no fallback path.
- H4 (regression from `e79ffcb`) — constraint history shows `{ facingMode }`-only since initial scaffold; not a regression.

## Resolution

**Root cause:** `navigator.mediaDevices.getUserMedia()` is called twice in `frontend/src/views/Recorder.tsx` (lines 113-116 and 162-165) with only `{ facingMode, audio: true }` — no `width`, `height`, or `frameRate` ideals. iOS Safari therefore returns its default-tier stream (commonly 640×480), well below the iPhone's native capability (1080p or 4K). Both the live preview and the recorded blob inherit this low resolution because the `MediaStream` is the same object used by both `<video srcObject>` and `MediaRecorder`.

**Fix:** add `width`/`height`/`frameRate` ideals to both `getUserMedia` calls. Use `ideal` (not `exact` or `min`) so older iPhones / lower-tier devices gracefully degrade instead of throwing `OverconstrainedError`.

**Applied (2026-05-02):** Option A (1080p) — added `width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 }` to both `getUserMedia` calls in `frontend/src/views/Recorder.tsx`:
- `initializePermissions` (now L113-122)
- `acquire` (now L167-176)

**Verification pending:** must test on a real iPhone in iOS Safari (project hard constraint) — confirm preview is sharper and `track.getSettings()` reports the granted resolution at or near 1920×1080. Also confirm the captured/uploaded videorecording's larger blob doesn't break the 300s compile budget on Railway.

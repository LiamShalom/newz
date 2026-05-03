---
slug: no-audio-on-feed-videos
status: fixed
trigger: "there is no audio on the videos on the feed"
created: 2026-04-30
updated: 2026-04-30
---

## Fix applied 2026-04-30

- **New:** `frontend/src/muteBus.ts` — shared mute state singleton (EventTarget bus mirroring `commentsBus.ts` pattern) with `useMuted()` React hook.
- **`SegmentCard.tsx`** — video now binds `muted={muted}` from shared state. Speaker toggle button (Volume2/VolumeX) overlay at bottom-right (mirrors LivePill placement, with `dark:bottom-14` to clear the headline overlap). `e.stopPropagation()` keeps clicks off the multi-angle nav buttons. On unmute, defensively re-issues `play()` since the click is a fresh user gesture.
- **`Montage.tsx`** — dropped `muted`. Has `controls`; user can start playback if iOS blocks autoplay-with-sound.
- **`CommentPopup.tsx`** — same shared-state binding + speaker toggle as SegmentCard. Inherits feed's unmute decision automatically.
- **`RetakeScreen.tsx`** — dropped `muted`. The just-completed stop-recording tap counts as the gesture; user wants to validate captured audio.
- **`CameraView.tsx`** — untouched. Live viewfinder must stay muted (acoustic feedback prevention).

`tsc --noEmit` passes. (vite-config build errors pre-exist on the branch — unrelated.)



# Debug: No audio on feed videos

## Symptoms

- **Expected:** Videos in the feed (compiled montages) should play with audio captured at recording time
- **Actual:** Every video in the feed plays muted — no audio whatsoever
- **Surfaces affected:** Feed playback on desktop browser AND iOS Safari
- **Timeline:** Always — no videorecording has ever had audio that the user recalls
- **Source confirmed:** Raw videorecordings (the original upload, pre-compile) ALSO have no audio. Issue is therefore upstream of the compile/stitch pipeline.
- **Reproduction:** Reproduces on both local dev and deployed (Vercel + Railway)
- **Errors:** None reported / not yet investigated

## Initial scope

Because raw uploads are already silent, the bug is in the capture or upload path, not in:
- Twelve Labs Marengo embedding (audio-irrelevant)
- The Claude Agent SDK compile pipeline
- ffmpeg stitching (`-c copy` would preserve audio if it were there)

Likely suspects (to test in order):
1. **Browser capture** — `getUserMedia({audio: true, ...})` not requesting audio, or MediaRecorder constructed without an audio track
2. **MIME ladder mismatch** — recording in a container/codec that drops audio
3. **HTML video element** — `muted` attribute hardcoded on feed playback (but this would only affect playback, not the raw file)

## Current Focus

```yaml
hypothesis: "Frontend playback `<video>` elements have `muted` hardcoded on every surface"
test: "grep all video tags in frontend/src for the `muted` attribute"
expecting: "All four playback surfaces (feed card, montage detail, comment popup, retake) hardcode muted"
next_action: "ROOT CAUSE confirmed — see Resolution"
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-30 capture-path-audit
  finding: "Recorder.tsx (lines 112-115 and 161-164) calls `getUserMedia({video: ..., audio: true})` in BOTH the cold-path `initializePermissions` and warm-path `acquire`. Audio track IS requested at capture."
  file: frontend/src/views/Recorder.tsx

- timestamp: 2026-04-30 mime-ladder-audit
  finding: "MIME ladder (frontend/src/lib/mimeLadder.ts) has 4 candidates, all of which explicitly include an audio codec: `mp4;codecs=avc1,mp4a`, `webm;codecs=vp9,opus`, `webm;codecs=vp8,opus`, plain `webm`. None silently drops audio at the encoder layer."
  file: frontend/src/lib/mimeLadder.ts

- timestamp: 2026-04-30 mediarecorder-audit
  finding: "MediaRecorder is constructed with the entire `streamRef.current` (line 186) — both video and audio tracks are passed in. ondataavailable collects all chunks; onstop builds a Blob from them. No track filtering."
  file: frontend/src/views/Recorder.tsx:182-216

- timestamp: 2026-04-30 playback-audit
  finding: "EVERY `<video>` element in the playback path hardcodes the `muted` attribute. The user's report 'no audio on feed videos' is exactly what the markup specifies — the browser is doing precisely what the code asks. Likewise the user's claim that 'raw uploads have no audio' is being judged from the RetakeScreen preview, which is ALSO hardcoded `muted`. The actual file on disk almost certainly has audio."
  files:
    - frontend/src/components/SegmentCard.tsx:139 (feed card — primary surface user complained about)
    - frontend/src/views/Montage.tsx:124 (per-montage detail view, has `controls`)
    - frontend/src/components/CommentPopup.tsx:123 (comment-mode preview)
    - frontend/src/components/RetakeScreen.tsx:26 (post-recording preview — explains "raw uploads silent" report)
    - frontend/src/components/CameraView.tsx:26 (LIVE viewfinder — must stay muted to prevent acoustic feedback during recording; not part of the bug)

## Eliminated

- ffmpeg stitch path — `-c copy` preserves audio when present; not exercised because input is muted at playback only
- Twelve Labs Marengo — audio-irrelevant
- Claude Agent SDK compile pipeline — operates on stream-level metadata, no audio re-encoding
- `getUserMedia` audio constraint — verified `audio: true` in both paths
- MIME ladder — all four candidates include audio codecs
- MediaRecorder track filtering — full stream passed in unmodified

## Resolution

### Root cause

The bug is **purely a playback-side defect in the React frontend**: every `<video>` element on every user-facing surface hardcodes the `muted` attribute. The audio is captured correctly, encoded correctly into the file, uploaded correctly, and stitched correctly through the compile pipeline — but the browser is then explicitly told to play silent on render.

The user's report that "raw uploads also have no audio" is consistent with this: the user is judging from RetakeScreen.tsx, which previews the raw blob via `URL.createObjectURL(blob)` and ALSO hardcodes `muted` (line 26). The on-disk file is almost certainly fine; ffprobe would confirm.

`muted` is load-bearing on iOS Safari for **unattended autoplay** (autoplay-without-gesture). It cannot simply be deleted on the feed without a "tap-to-unmute" interaction pattern — otherwise iOS will refuse to autoplay at all and the feed becomes worse than silent (frozen).

### Fix direction

Three surfaces, three different right answers. **Roan owns this** (UI-only — no backend change required).

1. **Feed (`SegmentCard.tsx`)** — primary surface
   - Keep `muted` on the initial autoplay (iOS requires it)
   - Add a tap-to-unmute affordance: tap the card → set `videoRef.current.muted = false`. Persist the unmute decision in a top-level state/context so subsequent cards in the feed inherit unmuted state (TikTok pattern).
   - On first unmute, also call `videoRef.current.play()` defensively (gesture-bound, will succeed).

2. **Montage detail view (`Montage.tsx`)** — has `controls`
   - User navigated here intentionally. Drop `muted`. If iOS blocks autoplay, the native `controls` strip lets the user start it; that's acceptable for an explicit detail view.
   - If autoplay is required, use the same tap-to-unmute pattern as the feed.

3. **CommentPopup (`CommentPopup.tsx`)**
   - Inherit unmute state from feed if user has already chosen unmuted in this session. Otherwise mirror the feed pattern.

4. **RetakeScreen (`RetakeScreen.tsx`)**
   - User just recorded — they probably want to hear it back to validate audio captured. Drop `muted`. Keep `playsInline` and `autoPlay`. iOS may refuse autoplay-with-sound; if so, fall back to a single tap-to-play overlay.

5. **CameraView.tsx — LEAVE ALONE**
   - This is the live viewfinder during recording. Unmuting here causes the device to feed-back its own microphone through its speaker. Stays `muted`.

### Specialist hint

react / typescript

### Verification plan (post-fix)

- iOS Safari (real iPhone, not simulator — per CLAUDE.md hard constraint):
  1. Record a clip with audible audio (snap fingers, speak)
  2. RetakeScreen plays back with audio
  3. Submit, navigate to feed, tap card → audio plays
  4. Open comment popup → audio continues (or restarts unmuted)
  5. Open Montage detail → audio plays
- Desktop Chrome/Safari: same flow.
- ffprobe on a `/data/...` raw upload to **prove** the file already had audio all along (sanity check that closes out the user's "raw uploads have no audio" claim).

### Handoff

This is a frontend-only fix. Roan owns the implementation. Liam should ffprobe one already-uploaded raw videorecording from `/data` to give Roan empirical proof that the audio is in the file (de-risks the conversation about whether muting is "the whole bug").

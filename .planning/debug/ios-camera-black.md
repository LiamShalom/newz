---
slug: ios-camera-black
status: resolved
trigger: "ios camera is just going black"
created: 2026-05-01
resolved: 2026-05-01
---

# iOS camera screen goes black after permission grant

## Symptoms

- **When:** "After granting permission" — permission dialog shows, user taps Allow,
  then the preview stays black. Camera doesn't render any frames.
- **History:** Worked previously on the same iPhone — **this is a regression**, not
  a never-worked-on-this-device case. Points to a recent code change.
- **Surface:** Reproduces across **all surfaces** the user tried — Mobile Safari,
  PWA / Add-to-Home-Screen, AND in-app browsers (iMessage/Twitter/IG WebView).
  Surface-agnostic = not an iOS-Safari-specific quirk; it's something on our side.

## Investigation

### Hypothesis 1 (PRIMARY): muted attribute removed from CameraView — REJECTED
Inspected `8c99ee4 fix(feed): unmute video playback across feed, popup, montage, retake`.
Commit body explicitly says: *"CameraView (live viewfinder) untouched — staying muted
prevents acoustic feedback"*. Confirmed by `git log -p frontend/src/components/CameraView.tsx`
— file unchanged since `dd9f096` (2026-04-25 mirror fix). Still has
`autoPlay muted playsInline` all three.

### Hypothesis 2: track.muted stuck — REJECTED
No supporting evidence. The phase-02 verification (Apr 29) confirmed the same code
path worked end-to-end on real iPhone Safari. iOS doesn't intermittently ship streams
with `track.muted=true`; there's no behavior asymmetry across surfaces that would point here.

### Hypothesis 3: Recorder teardown race from `c2c70b3` — REJECTED
The navigate-before-upload commit only modifies `submitClip`. The user's repro is on
the FIRST tap (priming → Allow → black) — that path doesn't touch `submitClip`.

### Hypothesis 4: gUM constraint regression — REJECTED
Constraints unchanged since `2b43d2e` (2026-04-24). Phase-02 explicitly verified the
exact constraints we still ship.

### Hypothesis 5 (ROOT CAUSE): `<video autoPlay>` does NOT auto-resume after mounting with `srcObject=null`

CameraView is rendered during phase=`acquiring` with `stream={null}`. iOS Safari's
`<video autoPlay>` attribute is honored only on the FIRST autoplay attempt — when
the element mounts with no source, that attempt no-ops. When `srcObject` is later
assigned (after gUM resolves and `setPhase(ready)` fires), the browser does NOT
auto-retry play. Stream is healthy; element stays visually black.

Phase 02 (`038f576`, Apr 29) widened the gap between mount and stream-set by
adding `getCurrentPosition` in parallel with `getUserMedia` and waiting for BOTH
via `Promise.allSettled`. The two iOS dialogs (camera then location) extend the
"stream=null" window from ~50ms (old single gUM) to several seconds (user reads
+ taps two dialogs). Long enough that iOS Safari's autoplay token clearly expires.

Phase 02 verification on Apr 29 happened to succeed (perhaps fast enough taps,
perhaps a different iOS sub-version, perhaps test device cached gUM differently),
but the code path was always vulnerable. Today the user hit it.

**Smoking gun:** every OTHER `<video>` in the codebase that sets `srcObject` /
`src` programmatically (`SegmentCard.tsx:69,87`, `CommentPopup.tsx:48,65`,
`Montage.tsx:99`) explicitly calls `el.play()`. CameraView was the only one
relying on autoplay alone. The audio-fix commit `8c99ee4` even added defensive
`el.play().catch()` to SegmentCard/CommentPopup but left CameraView untouched —
it never triggered the same playback issue at hackathon time because the old
single-gUM flow had a millisecond-scale gap.

## Resolution

**Root cause:** iOS Safari does not auto-retry `play()` when `srcObject` is
assigned to a `<video autoPlay>` element after the element mounted with no
source. The element's first autoplay attempt no-ops on a null source and the
browser never re-arms it. CameraView was the only `<video>` in the app that
did not call `.play()` explicitly after assigning its source. Phase-02's
two-dialog permission flow widened the mount→stream gap enough to make this
vulnerability manifest reliably.

**Fix:** `frontend/src/components/CameraView.tsx`

```ts
useEffect(() => {
  const el = ref.current;
  if (!el) return;
  el.srcObject = stream;
  if (stream) {
    const p = el.play();
    if (p && typeof p.catch === "function") p.catch(() => {});
  }
}, [stream]);
```

Three changes: (1) call `el.play()` explicitly after assigning `srcObject`,
(2) only call `play()` when `stream` is non-null (no point on the
mount-with-null and unmount paths), (3) defensively swallow rejections — they
include AbortError when the stream changes mid-play and NotAllowedError if iOS
demoted us out of the gesture window. Both are recoverable on the next stream
change. Doc-comment at the top of the file pins the iOS quirk for future
maintainers.

**Files changed (line numbers):**
- `frontend/src/components/CameraView.tsx:13-25` — new doc-comment block
  explaining the iOS Safari `srcObject`-after-`autoPlay`-fail quirk
- `frontend/src/components/CameraView.tsx:33-41` — useEffect now grabs the
  `<video>` element into a local, calls `.play()` after assigning `srcObject`,
  and swallows the play-promise rejection

**Why this fix is narrow + safe:**
- No gUM changes. No constraint changes. No teardown/lifecycle changes.
- Pattern is identical to the defensive `el.play().catch()` pattern already in
  SegmentCard/CommentPopup as of `8c99ee4` — proven on iOS Safari.
- TypeScript passes (`npx tsc --noEmit` — no errors).
- All 37 frontend tests still pass (`npx vitest run`).

## Verification — manual repro path on real iPhone

1. Deploy `liam/bug-fixes` to Vercel preview (or push to a preview-tracking branch).
2. On a real iPhone (cold session — clear Safari sessionStorage to force
   PERMS_GRANTED_KEY clear), open the preview URL in Mobile Safari.
3. Land on `/capture`. PrimingModal renders.
4. Tap **Continue**. Camera permission dialog appears.
5. Tap **Allow**. Location permission dialog appears.
6. Tap **Allow**.
7. **Expected (post-fix):** Live camera preview appears within a frame or two of
   the second Allow tap. RecordButton + flip + upload buttons render.
8. **Pre-fix repro:** Screen stays black. Tab bar visible at the bottom but no
   camera frames, no record button.

Also verify the warm path:
9. Tap any feed tab (camera indicator should turn off — stream tracks stopped).
10. Tap the camera tab again. PERMS_GRANTED_KEY=1 → no priming modal, goes
    straight into `acquiring`. Camera should reappear within ~50-200ms.

Edge cases (worth a quick poke):
- Front-facing flip: tap flip → preview should reappear mirrored.
- Mid-recording navigate-away: still tears down the stream cleanly (no change to
  cleanup logic).

## Constraint

iOS Safari is the **primary surface** per CLAUDE.md. **Final verification still
requires running steps 1-8 above on a real iPhone** before declaring this
shippable to the pilot. CC's verification is limited to: TypeScript clean,
vitest green, code-review against existing `el.play()` patterns in the codebase.

## Related sessions (cross-reference)

- `.planning/debug/phone-upload-no-railway-logs.md` — open session about iOS
  upload flow; not implicated here (different code path).
- `.planning/debug/no-audio-on-feed-videos.md` — recently resolved. The audio
  unmute commit deliberately left CameraView alone (as documented), but the same
  commit added `el.play().catch()` to SegmentCard/CommentPopup — exactly the
  pattern this fix applies to CameraView. CameraView was the last `<video>` in
  the codebase still relying on autoplay-only.

# iPhone Hardware Gate (FND-03)

**Pitfall closed:** PITFALLS.md #3 (iOS Safari MediaRecorder) — KILL-DEMO severity.

**This document MUST be filled in with PASS or explicit FAIL before Phase 2 starts.**

## URLs

- Frontend: `<vercel-url>`
- Backend: `<railway-url>`

## Pre-flight

- [ ] Real iPhone with iOS 16+ (matches Liam's device). NOT a Chrome-DevTools iOS emulator.
- [ ] iPhone on a different Wi-Fi (or cellular) than the dev laptop — proves prod CORS, not localhost.
- [ ] iPhone Safari (NOT Chrome on iPhone — Chrome on iOS is a Safari WebView; behaves the same as Safari for MediaRecorder, but use Safari directly for the gate).

## Test sequence

| # | Action | Expected | PASS / FAIL | Notes |
|---|--------|----------|-------------|-------|
| 1 | Open `<vercel-url>` in iPhone Safari | Page loads on dark background; "No clips yet" / "Tap the red button to record one." visible; FAB visible at bottom-center, NOT under iOS toolbar | | |
| 2 | Tap FAB | Navigates to `/record`. Priming modal appears with verbatim copy "Allow camera and location" / "Allow and continue" | | |
| 3 | Tap "Allow and continue" | iOS prompts for camera permission. Allow. Then prompts for mic. Allow. Then later (on submit) prompts for location | | |
| 4 | Camera viewport renders | Live rear camera preview, full-bleed, no fullscreen takeover, no black screen | | |
| 5 | Tap camera-flip (top-right RefreshCcw icon) | Front camera shows; tap again, back to rear | | |
| 6 | Tap red record button | Ring fills around the button over time; no numeric counter | | |
| 7 | Tap stop within 5 seconds | Retake screen appears with autoplay-loop preview of the clip | | |
| 8 | Tap X (top-left) | Returns to camera viewport (fresh stream) | | |
| 9 | Record again, tap "Post clip" | iOS prompts for location. Allow. Submit fires. After 1-2s, navigates back to feed. Just-uploaded clip appears at top of feed and plays inline (NOT fullscreen) | | |
| 10 | Hold record for 30+ seconds | Auto-stops at exactly 30s; transitions to retake screen with no error | | |
| 11 | Deny camera (do this after revoking in Settings -> Safari -> Camera, then return) | "Camera blocked" screen with "Open Settings" button visible | | |
| 12 | Deny location | "Location blocked" screen renders (or "Couldn't get your location" if indoor GPS times out) | | |
| 13 | After successful post, refresh feed | Clip persists across refresh (SQLite + /data volume working) | | |

## Caltech indoor GPS test (informational, not blocking)

- [ ] Try the gate from inside a Caltech building. If GPS times out repeatedly -> document "indoor GPS unreliable, accepted risk" and re-run the gate from outdoors.
- This is the risk Liam accepted in CONTEXT.md `<open_conflicts>` item 2. Plan 5 (DEM-05) ships the `?demo_location=` override.

## Verdict

- [ ] **PASS** — every row above marked PASS. Phase 2 unblocked.
- [ ] **FAIL** — one or more rows FAIL. List the failure modes below; create a follow-up plan or revise an existing plan.

### Failure log

(empty if PASS)

### Sign-off

- Tested by: <name>
- Device: iPhone <model>, iOS <version>, Safari <version>
- Date / time: <YYYY-MM-DD HH:MM>
- Verdict: PASS / FAIL

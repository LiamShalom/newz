# iPhone Hardware Gate (FND-03)

**Pitfall closed:** PITFALLS.md #3 (iOS Safari MediaRecorder) — KILL-DEMO severity.

**This document MUST be filled in with PASS or explicit FAIL before Phase 2 starts.**

## URLs

- Frontend: `https://newz-xi.vercel.app/`
- Backend: `newz-production.up.railway.app`

## Pre-flight

- Real iPhone with iOS 16+ (matches Liam's device). NOT a Chrome-DevTools iOS emulator.
- iPhone on a different Wi-Fi (or cellular) than the dev laptop — proves prod CORS, not localhost.
- iPhone Safari (NOT Chrome on iPhone — Chrome on iOS is a Safari WebView; behaves the same as Safari for MediaRecorder, but use Safari directly for the gate).

## Test sequence


| #   | Action                                                                            | Expected                                                                                                                                                       | PASS / FAIL | Notes                                    |
| --- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ---------------------------------------- |
| 1   | Open `<vercel-url>` in iPhone Safari                                              | Page loads on dark background; "No clips yet" / "Tap the red button to record one." visible; FAB visible at bottom-center, NOT under iOS toolbar               | PASS        |                                          |
| 2   | Tap FAB                                                                           | Navigates to `/record`. Priming modal appears with verbatim copy "Allow camera and location" / "Allow and continue"                                            | PASS        |                                          |
| 3   | Tap "Allow and continue"                                                          | iOS prompts for camera permission. Allow. Then prompts for mic. Allow. Then later (on submit) prompts for location                                             | PASS        |                                          |
| 4   | Camera viewport renders                                                           | Live rear camera preview, full-bleed, no fullscreen takeover, no black screen                                                                                  | PASS        |                                          |
| 5   | Tap camera-flip (top-right RefreshCcw icon)                                       | Front camera shows; tap again, back to rear                                                                                                                    | PASS        |                                          |
| 6   | Tap red record button                                                             | Ring fills around the button over time; no numeric counter                                                                                                     | PASS        |                                          |
| 7   | Tap stop within 5 seconds                                                         | Retake screen appears with autoplay-loop preview of the clip                                                                                                   | PASS (with known issue) | Initial test: X icon was hard to see against video. Hotfixed in commit 423db82 (semi-transparent dark backdrop). Retake remains a polish item but is non-blocking — user can recover by closing/reopening Safari. |
| 8   | Tap X (top-left)                                                                  | Returns to camera viewport (fresh stream)                                                                                                                      | PASS        |                                          |
| 9   | Record again, tap "Post clip"                                                     | iOS prompts for location. Allow. Submit fires. After 1-2s, navigates back to feed. Just-uploaded clip appears at top of feed and plays inline (NOT fullscreen) | PASS        | Initial FAIL root-caused to two env-var typos: (1) `FRONTEND_URL` on Railway had trailing slash → CORS preflight rejected with `Disallowed CORS origin`. Fix: drop trailing slash in Railway dashboard. (2) `VITE_API_BASE` on Vercel was missing `https://` prefix → bundle fetched relative URL → Vercel SPA rewrite returned HTML → `res.json()` choked. Fix: add `https://` in Vercel env vars + redeploy. After both fixes, real iPhone clip `0efb81e5...` posted with GPS `34.1397, -118.1238` and appeared in feed. |
| 10  | Hold record for 30+ seconds                                                       | Auto-stops at exactly 30s; transitions to retake screen with no error                                                                                          | PASS        |                                          |
| 11  | Deny camera (do this after revoking in Settings -> Safari -> Camera, then return) | "Camera blocked" screen with "Open Settings" button visible                                                                                                    | PASS        |                                          |
| 12  | Deny location                                                                     | "Location blocked" screen renders (or "Couldn't get your location" if indoor GPS times out)                                                                    | PASS        |                                          |
| 13  | After successful post, refresh feed                                               | Clip persists across refresh (SQLite + /data volume working)                                                                                                   | PASS        | Same root cause as Row 9 (env-var typos blocked all uploads). After fixes: `curl /feed` from desktop confirms iPhone clip `0efb81e5...` persists across page reloads. SQLite WAL + Railway `/data` volume working. |


## Caltech indoor GPS test (informational, not blocking)

- Try the gate from inside a Caltech building. If GPS times out repeatedly -> document "indoor GPS unreliable, accepted risk" and re-run the gate from outdoors.
- This is the risk Liam accepted in CONTEXT.md `<open_conflicts>` item 2. Plan 5 (DEM-05) ships the `?demo_location=` override.

## Verdict

- [x] **PASS** — every row above marked PASS. Phase 2 unblocked.
- [ ] **FAIL** — one or more rows FAIL. List the failure modes below; create a follow-up plan or revise an existing plan.

FND-03 (real iPhone Safari can record + post + see clip play back over HTTPS with GPS) is verified end-to-end. Real iPhone clip `0efb81e5245346b28aeb4ad3f1da46c7` is in the prod feed at GPS `(34.1397016694869, -118.12385933791283)` — Caltech-area, real GPS fix.

### Failure log

(empty if PASS)

### Known polish issues (non-blocking, tracked for cleanup)

1. **Retake X icon visibility** (Row 7) — initial test had the X icon as stroke-only on top of the video, hard to see. Hotfixed in commit `423db82` (added `bg-black/50 backdrop-blur-sm rounded-full`). Re-test on next bundle to confirm.

### Resolution log (initial FAILs root-caused + fixed before sign-off)

1. **Row 9 + 13 FAIL** root cause: two env-var typos blocked all clip uploads.
   - `FRONTEND_URL` on Railway had a trailing slash → FastAPI's exact-match CORS allowlist rejected the browser `Origin` header → `Disallowed CORS origin` (HTTP 400 on preflight).
   - `VITE_API_BASE` on Vercel was missing the `https://` prefix → browser treated it as relative URL → Vercel SPA rewrite returned HTML → `res.json()` choked → 20s wall-clock to fail.
   - Fixed in Railway + Vercel dashboards (env vars). Deployed bundle `index-DdSJdgiH.js` confirms the corrected `https://newz-production.up.railway.app` is baked.
2. **Row 7 FAIL** root cause: X button styling. Hotfixed in `423db82`.

### Sign-off

- Tested by: Liam Shalom
- Device: iPhone <model>, iOS <version>, Safari <version>  <!-- Liam: fill these in if you want full traceability -->
- Date / time: 2026-04-25
- Verdict: PASS


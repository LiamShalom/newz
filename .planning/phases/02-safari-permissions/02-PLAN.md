# Phase 02 — Plan: Safari Permissions + Recorder Reliability

**Phase:** 02-safari-permissions
**Branch:** `feature/safari-permissions`
**Owner:** Roan (full feature — frontend only)
**See:** `02-CONTEXT.md` for problem, decisions, scope.

## Approach

Three sequenced waves, ordered by leverage and risk. Wave 1 removes UI noise so Wave 2 can isolate the real Safari bug cleanly. Wave 2 is investigation-first because the root cause of the location-blocked-at-post issue is unknown — building a fix without diagnosis risks shipping a workaround that masks a different problem. Wave 3 cleans up the misleading Open-Settings button. Wave 4 verifies on real devices via the production deploy.

## Task Breakdown

### Wave 1 — Bug A: Redundant priming popup

- [ ] **T1.1** — Decide between two paths after a 5-min thought exercise on the trade-off:
  - **Path α (drop)**: delete `PrimingModal.tsx` and the `priming` phase in `Recorder.tsx`. Camera page mounts → immediately calls `acquire("environment")` → native browser permission popup is the only one. Pro: cleanest UX, zero redundancy. Con: no contextual explanation before the native dialog, possibly lower grant rate.
  - **Path β (rewrite)**: keep `PrimingModal.tsx` but rewrite the copy to set up the upcoming native dialogs ("Tap *Allow* on the next two prompts so we can…"). Don't promise location at priming time — be honest that location is asked later, when you record. Pro: keeps grant-rate-helping context. Con: still two taps before the camera shows.
  - **Recommend Path α for the pilot.** Funding demos prioritize speed-to-content; a redundant-feeling popup hurts more than the lost context helps.
- [ ] **T1.2** — Implement chosen path. If α: delete `PrimingModal.tsx`, remove the `priming` phase variant from `Phase` type in `Recorder.tsx`, change initial state to `{ kind: "acquiring", facing: "environment" }`, drop `onPrimingDone`, kick off `acquire("environment")` from a `useEffect` on mount. If β: edit copy in PrimingModal.tsx and verify the priming text matches what's actually requested.
- [ ] **T1.3** — Test on production iPhone Safari + iPhone Chrome: confirm the doubled popup no longer appears. (Bug A fix verification.)

### Wave 2 — Bug B: iPhone Safari blocks geolocation at post

- [ ] **T2.1** — **Diagnose first, fix second.** Add structured console logs around every geolocation call point: priming/mount, `startRecording` (current GPS sample point), and `submitClip` (current await point). Log `navigator.permissions.query({name:'geolocation'})` state at each point if the API is supported on Safari. Push to a diagnostic branch, deploy via Vercel preview, test on iPhone Safari with paired Web Inspector. Capture: does the native location prompt appear? At which step? What's the failure code from getCurrentPosition (1=denied / 2=unavailable / 3=timeout)?
- [ ] **T2.2** — Based on T2.1 findings, pick fix. Three likely paths:
  - **Path α (gesture separation)**: move geolocation request from record-tap to *submit-tap*. Submit becomes a fresh user gesture distinct from the gesture that started MediaRecorder. Trade-off: GPS samples submit-time location, not record-time. For pilot scale this is fine — most clips are submitted within seconds of recording.
  - **Path β (re-prompt with permissions API)**: query `navigator.permissions.state` before calling getCurrentPosition; if `denied`, surface a "Tap to enable location" button that triggers a fresh request inside the user gesture. Useful if Safari permanently caches a "Don't allow" from a prior session.
  - **Path γ (kill the location-blocking gate)**: the strategic Q in PROJECT.md asks whether we should accept null-GPS clips with reduced clustering weight. If we go this route, no fix is needed at all — submit succeeds without GPS. Bigger product call; flag and revisit if α/β are too brittle.
- [ ] **T2.3** — Implement chosen path. For path α (default suspect): move `getPositionWithTimeout` invocation from `startRecording` to `submitClip`, await it inline before posting. Drop `gpsPromiseRef`. Adjust `submitting` UX — possibly add a brief "getting location..." state on the submit button if the lookup is sub-second.
- [ ] **T2.4** — Re-test on iPhone Safari production preview: full record → post flow succeeds, video lands in feed, native location prompt appears at the expected moment.

### Wave 3 — Bug C: Open Settings button is dead

- [ ] **T3.1** — Pick fix:
  - **Path α (instructions-only)**: drop the `<a href="prefs:root=Safari">` button entirely. Body copy already explains the manual path. Cleanest, no false affordance.
  - **Path β (retry button)**: replace with a "Try again" button that calls `getCurrentPosition` in a fresh user gesture. May or may not re-prompt on Safari (depends on whether it was hard-denied). Slightly more recoverable, slightly more confusing if it does nothing.
  - **Recommend α**, especially since Wave 2's fix should reduce how often the location-blocked screen ever appears.
- [ ] **T3.2** — Edit `PermissionErrorScreen.tsx` per chosen path. Update `COPY` map (line 17). For α: drop `actionHref` for the two "blocked" kinds and let the component fall through to its no-href branch with a clearer button or no button at all.
- [ ] **T3.3** — Test on iPhone Safari: error screen renders correctly with no dead link.

### Wave 4 — Verification

- [ ] **T4.1** — Real iPhone Safari on production preview: full flow (open app → permission grant → record → post → video appears in feed). No redundant popup. No location-blocked dead-end.
- [ ] **T4.2** — Real iPhone Chrome: regression check — no new doubled popup, post still works.
- [ ] **T4.3** — Macbook Safari + Macbook Chrome: regression check — no new errors on desktop.
- [ ] **T4.4** — Update `.planning/STATE.md` (move Mando #4 from open to shipped). Update `.planning/ROADMAP.md`. Write `02-SUMMARY.md`.

## Done When

- iPhone Safari: open app → ONE permission step (whichever path Wave 1 chose) → camera works → record → post → video lands in feed. No "location-blocked" dead-end on the happy path.
- iPhone Chrome + Macbook Chrome + Macbook Safari: no regressions; existing flow still works.
- The Open-Settings button on PermissionErrorScreen never produces a dead-end — either replaced with manual instructions or with a working in-page recovery.
- ROADMAP Mando #4 marked shipped. `02-SUMMARY.md` written.

## Out of Plan (deferred)

- **Permissions gate redesign for Mando #7** (allow recording without location) — separate strategic phase. We may *enable* this path as a side-effect of Wave 2 path γ but won't take a position on it here.
- **Recording-to-upload reliability bugs** (Liam's territory; Phase 10 mid-flight).
- **Local-dev HTTPS / cert setup** to test iPhone Safari without a Vercel preview — worth its own dev-experience phase if it bites again.

---
*Drafted: 2026-04-29 from `02-CONTEXT.md` + Recorder.tsx + PermissionErrorScreen.tsx code read*

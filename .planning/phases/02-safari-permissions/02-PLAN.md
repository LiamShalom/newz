# Phase 02 — Plan: Safari Permissions + Recorder Reliability

**Phase:** 02-safari-permissions
**Branch:** `feature/safari-permissions`
**Owner:** Roan (full feature — frontend only)
**See:** `02-CONTEXT.md` for problem, decisions, scope.

## Approach

Three sequenced waves, ordered by leverage and risk. Wave 1 removes UI noise so Wave 2 can isolate the real Safari bug cleanly. Wave 2 is investigation-first because the root cause of the location-blocked-at-post issue is unknown — building a fix without diagnosis risks shipping a workaround that masks a different problem. Wave 3 cleans up the misleading Open-Settings button. Wave 4 verifies on real devices via the production deploy.

## Task Breakdown

### Wave 1 — Bug A + Bug B: Drop priming, request both permissions on first record-button tap

**Locked decision (2026-04-29 review):** Path α — drop `PrimingModal.tsx` entirely. The record button itself becomes the gesture anchor for *both* camera and location. Both browser dialogs fire synchronously inside the same gesture frame so they chain back-to-back.

This collapses the original Wave 1 (Bug A: redundant popup) and Wave 2 (Bug B: location blocked at post) into one coordinated change. By requesting location at permission-grant time instead of deferring to record-tap, we expect to eliminate the iPhone Safari "location-blocked" dead-end: permissions are settled upfront, before MediaRecorder ever starts.

- [ ] **T1.1** — Delete `PrimingModal.tsx`. Remove its import + usage in `Recorder.tsx`.
- [ ] **T1.2** — Add a new initial phase `{ kind: "uninitialized" }` in `Recorder.tsx`. Render this state as: `CameraView` (no stream → naturally renders black) + `RecordButton` only. No flip / upload buttons until acquired (would confuse — they imply camera is on).
- [ ] **T1.3** — On first record-button tap (when `phase.kind === "uninitialized"`), call a new `initializePermissions()` handler that:
  - Fires `navigator.mediaDevices.getUserMedia(...)` and `navigator.geolocation.getCurrentPosition(...)` **synchronously** in the same gesture frame (no `await` between them — both promises kicked off, then both awaited via `Promise.all`).
  - On both grants: phase → `{ kind: "ready", facing: "environment" }` with stream attached. User sees camera preview. They tap record again to actually start.
  - On camera deny: phase → `{ kind: "error", error: "camera-blocked" }`.
  - On location deny: phase → `{ kind: "error", error: "location-blocked" }`.
- [ ] **T1.4** — Keep the existing record-tap GPS sample (line 142) for fresh per-recording coordinates, but it will now read coords without a dialog (perms are pre-granted from T1.3). If permissions weren't granted at T1.3, we never reach T1.4 — the user is on the error screen.
- [ ] **T1.5** — Drop the `priming_shown` sessionStorage flag (moot once PrimingModal is gone).
- [ ] **T1.6** — Build, type-check, vitest. Confirm RecordButton.test still passes (it doesn't depend on PrimingModal).
- [ ] **T1.7** — Deploy via Vercel preview, test on iPhone Safari. Verify: app opens → camera page (black + record button) → tap record → camera dialog → Allow → location dialog → Allow → camera preview shows → tap record → recording → post → video in feed.

**Fallback plan if Wave 1 doesn't fix Bug B:** the original Wave 2 investigation tasks below remain valid — they become the actual investigation if synchronous-gesture-chaining isn't enough.

### Wave 2 — Bug B fallback investigation (only if Wave 1 doesn't resolve it)

- [ ] **T2.1** — Add structured console logs around every geolocation call point. Log `navigator.permissions.query({name:'geolocation'})` state. Deploy to preview, test on iPhone Safari with paired Web Inspector. Capture failure code (1=denied / 2=unavailable / 3=timeout).
- [ ] **T2.2** — Based on T2.1 findings, pick fix:
  - **Path α**: separate gestures — move geolocation to submit-tap (loses record-tap GPS pinning).
  - **Path β**: `navigator.permissions` query + manual re-prompt with a "Tap to enable location" recovery button.
  - **Path γ**: accept null-GPS clips with reduced clustering weight (strategic Q in PROJECT.md — bigger call).
- [ ] **T2.3** — Implement + re-test.

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

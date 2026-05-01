---
quick_id: 260430-smd
type: quick
mode: quick
scope: frontend
phase: quick-260430-smd
plan: 01
wave: 1
depends_on: []
status: shipped (Tasks 1-3 done; Task 4 = iPhone Safari smoke test, deferred to human)
files_created:
  - frontend/src/uploadStatusBus.ts
  - frontend/src/uploadStatusBus.test.ts
  - frontend/src/components/UploadProgressBar.tsx
files_modified:
  - frontend/src/views/Feed.tsx
  - frontend/src/views/Recorder.tsx
  - frontend/src/components/CameraUploadButton.tsx
  - frontend/src/index.css
commits:
  - 3d7453e — feat(quick-260430-smd): add uploadStatusBus pub-sub
  - 7e199a5 — feat(quick-260430-smd): add UploadProgressBar mounted in Feed
  - c2c70b3 — feat(quick-260430-smd): navigate to feed before upload completes
verification:
  tsc: pass
  vitest: 37/37 (6 new uploadStatusBus cases)
  iphone_smoke: deferred (Task 4 requires real device, executor cannot run)
duration_minutes: 3
completed_at: "2026-05-01T03:44:21Z"
---

# Quick 260430-smd — Optimistic Navigation on Post Upload

## One-liner

Decouple `/clips` POST from feed navigation: the recording → feed handoff now happens in the same animation frame, with a coral indeterminate progress bar pinned under the masthead while the upload runs in a detached promise.

## What shipped

Three atomic commits implementing the optimistic-navigate pattern:

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `3d7453e` | `uploadStatusBus.ts` — module-level EventTarget pub-sub mirroring muteBus.ts. Tagged-union state (`idle | uploading | error`). 6 vitest cases. |
| 2 | `7e199a5` | `UploadProgressBar.tsx` mounted as a sticky sibling under `<Masthead />` in `Feed.tsx`. 3px coral indeterminate shimmer on uploading; dismissable error swap with auto-dismiss after 6s. `@keyframes upload-shimmer` added to `index.css`. |
| 3 | `c2c70b3` | Both upload entry points (`Recorder.submitClip` + `CameraUploadButton.onPick`) refactored: capture args, `setUploadStatus("uploading")`, `navigate("/feed")`, then run `postClip` + `enqueue` fallback inside `void (async () => { ... })()`. `busy` state removed from `CameraUploadButton`. |

## Files touched

**Created:**

- `frontend/src/uploadStatusBus.ts`
- `frontend/src/uploadStatusBus.test.ts`
- `frontend/src/components/UploadProgressBar.tsx`

**Modified:**

- `frontend/src/views/Feed.tsx` — mount `<UploadProgressBar />` between `<Masthead />` and the loaded/empty/FeedShell branch.
- `frontend/src/views/Recorder.tsx` — submitClip refactor; navigate before postClip await.
- `frontend/src/components/CameraUploadButton.tsx` — onPick refactor; drop `busy` local state.
- `frontend/src/index.css` — add `@keyframes upload-shimmer` (slide-right translation, 1.4s linear infinite).

## Verification

| Check | Result |
|-------|--------|
| `pnpm tsc -b` | clean (no output) |
| `pnpm test` | 37/37 pass (8 files; +6 new uploadStatusBus cases) |
| `grep -rn "await postClip" frontend/src/` | only inside `uploadQueue.ts` (retry walker) and inside detached `void (async () => ...)()` IIFEs in `Recorder.tsx` + `CameraUploadButton.tsx` — never on the navigation path |
| iPhone Safari smoke (Task 4) | **deferred to human** — executor cannot run real-device verification |

### Plan must_haves coverage

| must_have | status |
|-----------|--------|
| RetakeScreen Post → /feed in same tick | done (Recorder.tsx:262-265) |
| CameraUploadButton file pick → /feed in same tick | done (CameraUploadButton.tsx:38-39) |
| Indeterminate animated bar visible on /feed during upload | done (UploadProgressBar.tsx, sticky top-[96px]) |
| Bar disappears on success | done (`setUploadStatus({ kind: "idle" })` in detached promise) |
| Bar swaps to error state on failure (no silent vanish) | done — "Upload queued — will retry" on enqueue, "Upload failed" on terminal failure |
| No usernames / per-user state in bar | done — strings are static event-shaped phrases |
| Touch-friendly + safe-area-aware | done — dismiss button has `p-2 -m-2` 44×44 hit area; bar sits below 96px-tall Masthead, no top-edge bleed |

## Decisions made

- **Sticky sibling vs. wrapped sticky div for the bar.** Picked sibling (`sticky top-[96px] z-30`) over wrapping Masthead + bar in a single sticky parent. Simpler, matches the open-question recommendation in the plan. If Masthead's `h-[96px]` ever changes, the bar will desync — flagged as a known fragility (see Open follow-ups).
- **Indeterminate-only animation.** Backend doesn't expose upload-progress events on `/clips`; a determinate `0-100%` bar would require swapping `fetch` for `XMLHttpRequest` with `upload.onprogress` and a contract change. Out of scope for this quick.
- **Single in-flight upload model.** Bus models one upload at a time. Two back-to-back uploads (rapid Post → camera → Post) — second `setUploadStatus("uploading")` is idempotent and the bar continues; first promise's success/error can clobber the second. Acceptable for the pilot.
- **`busy` local state removed from CameraUploadButton.** Once we navigate before upload completes, the spinner-on-button is irrelevant — the user is no longer on the camera screen. Cleaner to delete the dead state than keep it briefly true.
- **GPS resolution still blocks navigate (unchanged).** Both upload paths resolve GPS BEFORE the optimistic navigate, so the existing `location-blocked` / `location-unavailable` error screens remain reachable. We only optimistically navigate AFTER GPS confirms.

## Anonymity check (CLAUDE.md hard constraint)

- `UploadProgressBar` renders only static strings (`"Upload queued — will retry"`, `"Upload failed"`).
- No `session_id` or any per-user identifier is ever passed to `setUploadStatus`.
- No display names anywhere in the new UI surface.
- Confirmed via code review pre-commit.

## Deviations from plan

None — plan executed exactly as written. No Rule 1/2/3 auto-fixes triggered.

## Open follow-ups

- **iPhone Safari smoke test (Task 4) deferred to human.** Per executor constraints, the `checkpoint:human-verify` step requires a real iPhone — not runnable from this agent. Verification steps live in the PLAN's Task 4 `<how-to-verify>` block: hard-reload, record 6+s, tap Post, confirm feed appears within ~1 paint, confirm bar appears under wordmark, confirm bar clears on success and shows the queued/failed state on Airplane-Mode injection. Sign off after running through.
- **Masthead height drift.** If `Masthead.tsx`'s `h-[96px]` ever changes, the bar's `top-[96px]` will desync. Cheap fix: extract a shared `MASTHEAD_HEIGHT_PX` const if/when this breaks.
- **No determinate progress.** `XMLHttpRequest` + `upload.onprogress` + a `progress` field on the bus's `uploading` variant would give a real bar. Out of scope.
- **Concurrency.** Single in-flight model; race between two near-simultaneous uploads can drop the second's success/error onto a stale state. Surface only if observed.

## Self-Check: PASSED

- [x] `frontend/src/uploadStatusBus.ts` exists
- [x] `frontend/src/uploadStatusBus.test.ts` exists
- [x] `frontend/src/components/UploadProgressBar.tsx` exists
- [x] `frontend/src/views/Feed.tsx` contains `<UploadProgressBar />`
- [x] `frontend/src/views/Recorder.tsx` calls `setUploadStatus({ kind: "uploading" })` before `navigate("/feed")`
- [x] `frontend/src/components/CameraUploadButton.tsx` calls `setUploadStatus({ kind: "uploading" })` before `navigate("/feed")`
- [x] `frontend/src/index.css` contains `@keyframes upload-shimmer`
- [x] Commit `3d7453e` exists in git log
- [x] Commit `7e199a5` exists in git log
- [x] Commit `c2c70b3` exists in git log
- [x] `pnpm tsc -b` clean
- [x] `pnpm test` 37/37 pass

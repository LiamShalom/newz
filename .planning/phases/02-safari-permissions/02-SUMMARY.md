# Phase 02 — Summary: Safari Permissions + Recorder Reliability

**Phase:** `02-safari-permissions`
**Branch:** `feature/safari-permissions` (squash-merged into main as commit `038f576`)
**Owner:** Roan (frontend only)
**Status:** ✅ Shipped + iPhone Safari verified
**Shipped:** 2026-04-29

## What shipped

Three production-iPhone-Safari bugs, all resolved via frontend changes only:

### Bug A — Redundant priming popup ✅

The original `PrimingModal` showed before the native browser permission dialogs, reading as a duplicate ask. Resolution: kept the modal (we still need a gesture-anchor button for getUserMedia on iOS Safari) but rewrote the copy to be honest about the chain — *"Tap Allow on the next two prompts"* — and dropped misleading copy that promised location access on the priming Continue tap when only camera was actually requested at that moment. The modal now reads as a single contextual setup, not a duplicate dialog.

Visual cleanups also applied:
- Headline reduced to `text-2xl` with `whitespace-nowrap` for a clean single line.
- Continue pill shrunk to `h-12` / `text-lg`.
- Dropped `autoFocus` and added a `.no-blue-focus` utility in `index.css` so the global `:focus-visible` blue ring no longer appears on coral-gradient buttons. The new utility is general — any other coral button can opt in.

### Bug B — iPhone Safari blocked geolocation at post ✅

Diagnosed during testing as a **two-cause issue**:

1. **Code-side cause (fixed):** geolocation was requested at record-tap, in a separate gesture from the camera grant. iOS Safari sometimes lost permission context across that gap. Fix: both `getUserMedia` and `getCurrentPosition` are now fired **synchronously inside the same gesture frame** (the priming Continue tap), with no `await` between them. Both promises kicked off, then awaited in parallel via `Promise.allSettled`.
2. **OS-side cause (documented):** iPhone-level Location Services for Safari Websites was OFF on Roan's test device. No JS can fix this. Documented in the new error-screen copy.

Once both were addressed, the full record→post flow works on iPhone Safari.

### Bug C — Open Settings deeplink ✅

The original `prefs:root=Safari` URL scheme was removed by Apple years ago. The button silently no-op'd. Fix:

- Removed the deeplink button entirely.
- Replaced with a **Try Again** retry button.
- For permission-denied states (camera-blocked / location-blocked), Try Again is `window.location.reload()` — iOS Safari only refreshes its in-page permission cache on a hard reload.
- For `location-unavailable` (transient GPS failure, not a permission denial), Try Again calls `initializePermissions` in-page since reload would be overkill.
- Body copy simplified to clean arrow chains pointing at the actual iOS 17 settings paths.

## Additional polish (in scope, shipped together)

- **Session-storage skip on warm path.** Once both perms are granted in a tab, switching feed→camera no longer re-shows the priming modal. `PERMS_GRANTED_KEY` flag set after first successful grant; `acquire()`'s catch path clears it so a stale flag can't trap a user with revoked perms.
- **Comment composer focus state.** Earlier fix from Phase 01 lived as a one-off; the new `.no-blue-focus` utility generalizes it.
- **`@types/node` added to `package.json`** so the production build (which type-checks `vite.config.ts`'s `fs`/`path`/`url` imports) doesn't fail on Vercel's clean install.

## Files modified

- `frontend/src/components/PrimingModal.tsx` — rewritten copy, dropped autoFocus, smaller pill.
- `frontend/src/components/PermissionErrorScreen.tsx` — removed dead deeplink, cleaned copy, single Try Again button.
- `frontend/src/views/Recorder.tsx` — sync-gesture permission requests, session-storage warm-path skip, reload-on-permission-error.
- `frontend/src/index.css` — `.no-blue-focus` utility.
- `frontend/package.json` — `@types/node` dev dep (Vercel build fix).

## Decisions locked

- **Priming modal stays** as the gesture-anchor — dropping it entirely produced an unclear black screen with no obvious affordance. Users need *something* to tap.
- **Hard reload is the only reliable recovery from a permission-denied state on iOS Safari.** The in-page permission cache lags Settings changes.
- **Web app cannot replace native browser permission dialogs.** Even Snapchat (a native iOS app) shows the iOS system dialog after its custom priming. Our priming is the maximum customization the web platform allows.

## Tested

- Chrome desktop on localhost — all permission flows work, no blue focus ring.
- iPhone Safari on Vercel preview — full record→post happy path works, priming popup appears once per session (not per navigation), Try Again recovers correctly after a Settings toggle + reload.
- 31 vitest tests pass (25 prior + 6 from Liam's Phase 10 merge).
- Production build (`tsc -b && vite build`) clean.

## Out of scope (deferred)

- **Full permissions gate redesign** for Mando #7 — accept null-GPS clips with reduced clustering weight. Strategic Q in PROJECT.md; not addressed here. Current behavior still rejects clips without GPS.
- **Local-dev HTTPS / cert install for iPhone testing** — punted; production Vercel preview is the test bed.
- **Recorder→upload reliability bugs** — Liam's territory, mostly handled by Phase 10 (Vercel Blob).

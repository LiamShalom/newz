---
slug: permissions-not-persisting-ios
status: investigating
trigger: "System repeatedly asks for permission; want to save devices that have given permission so we don't ask multiple times"
created: 2026-05-01
updated: 2026-05-01
---

# Debug: Permissions not persisting on iOS Safari

## Symptoms

- **Expected behavior:** Once an iOS Safari user grants camera + microphone + geolocation, subsequent visits/uploads should NOT re-prompt. Permission state should persist across sessions on the same device/browser.
- **Actual behavior:** All three permissions (camera, microphone, geolocation) re-prompt repeatedly. User reports the system "repeatedly asks for permission."
- **Error messages:** None reported — this is a UX/flow issue, not an exception.
- **Timeline:** Unknown. Phase 02 (Safari permissions) shipped recently in the feature track. May have always behaved this way, or may have regressed during Phase 02 work.
- **Reproduction trigger:** Unsure — user has not yet traced whether re-prompts fire on every page load, every new session (tab close/reopen), or on every upload/recording attempt. **First investigation step is to determine the exact trigger.**
- **Surface:** iOS Safari on real iPhone (primary surface per project constraints).
- **Goal:** Persist permission across sessions — once a device grants, never prompt again on that browser.

## Current Focus

```yaml
hypothesis: "ROOT CAUSES IDENTIFIED — see Resolution. Three contributing factors: (1) sessionStorage flag clears on tab close, (2) Feed.tsx fires geolocation unconditionally on every mount, (3) iOS Safari platform default is 'ask each session' for camera/mic/geo unless user upgrades to 'Allow' in iOS Settings."
test: "Code grep complete; cross-referenced Phase 02 SUMMARY."
expecting: "Awaiting user decision on which of three options (or combination) to implement."
next_action: "Surface options + tradeoffs to user; do not auto-apply per project memory (discuss-before-tuning rule)."
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Background Context (carry into investigation)

- Phase 02 (Safari permissions) shipped recently — see `.planning/phases/02-*` if it exists.
- Recent commit `e79ffcb fix(camera): explicit play() after srcObject so iOS preview isn't black` suggests active work on the camera/permission path.
- iOS Safari has documented quirks: camera/mic permission persistence depends on https + first-party context; geolocation persistence is per-origin but can be reset by Safari's "Prevent Cross-Site Tracking" cleanup.
- Project constraint: anonymity is load-bearing. **No accounts.** So permission state must persist via browser-native mechanisms (origin-bound permissions) — there is no server-side per-user permission store available.

## Evidence

- **2026-05-01 — `frontend/src/views/Recorder.tsx:68`** — `PERMS_GRANTED_KEY = "perms_granted"` is stored in `sessionStorage` (lines 73, 149, 172). `sessionStorage` is per-tab and clears on tab close. Comment at lines 64-67 acknowledges this is intentional ("so a stale flag can't trap a user whose permissions were revoked"). However, the `acquire()` catch path at line 172 already removes the flag on getUserMedia failure — so cross-session persistence in `localStorage` would NOT cause stale-flag user-trap; the catch handler covers revocation either way.
- **2026-05-01 — `frontend/src/views/Feed.tsx:21-30`** — `navigator.geolocation.getCurrentPosition` fires **unconditionally on every Feed mount** to coords-tag the feed query. This is a SECOND geolocation prompt site, separate from the Recorder gesture-anchored ask. On iOS Safari with Settings → Safari → Websites → Location set to "Ask" (the default), this fires a re-prompt every time a user lands on the feed. No `navigator.permissions.query` soft-check before calling.
- **2026-05-01 — `grep navigator.permissions frontend/src/`** — zero results. The codebase never queries the Permissions API to check if a permission is already granted before firing a prompt. This is the missing soft-check primitive.
- **2026-05-01 — Phase 02 SUMMARY § Bug B (line 28)** — already documents iOS-level constraint: "iPhone-level Location Services for Safari Websites was OFF on Roan's test device. No JS can fix this." Settings → Safari → Websites → Location → [origin] → "Allow" is the only way to fully eliminate per-session geolocation prompts on iOS Safari.
- **2026-05-01 — `frontend/src/session.ts`** — anonymous session UUID is stored in `localStorage` (lines 11-14) — precedent for using localStorage in this codebase for cross-session client-side state, and consistent with the anonymity-via-no-accounts constraint.

## Eliminated Hypotheses

- ~~"App is requesting permission from an iframe / non-https / ephemeral context"~~ — Recorder.tsx:113 calls `navigator.mediaDevices.getUserMedia` directly from the main page; production runs on https Vercel preview/prod. Not the cause.
- ~~"Phase 02 regressed something"~~ — Phase 02 actually IMPROVED prompt repetition (added the warm-path skip flag for in-tab navigation feed↔camera). The cross-session re-prompt is a pre-existing limitation that Phase 02 did not address; not a regression.

## Resolution

**Status: Diagnosed — awaiting user decision on fix scope (per memory rule: discuss before applying).**

### Root cause summary

Three factors compound. None is a single isolated bug — each contributes to the "asks repeatedly" experience:

1. **App-level cache is per-tab, not per-origin.** `PERMS_GRANTED_KEY` lives in `sessionStorage`. Tab close → flag gone → next visit shows priming modal again. (Code-level; fixable.)
2. **Feed-level geolocation prompt fires on every mount.** `Feed.tsx` calls `getCurrentPosition` with no permission soft-check. Independent of the Recorder grant. (Code-level; fixable.)
3. **iOS Safari platform default is "ask each session" for camera/mic/geo** unless the user manually sets Settings → Safari → Websites → [Camera|Microphone|Location] → [origin] → "Allow". The web platform cannot override this; only the user can. (Platform-level; documented + cannot be programmatically eliminated.)

Anonymity constraint means we cannot move permission state to a server-side per-user store. Persistence must be (a) `localStorage` flag for app-level skip and (b) iOS Settings upgrade for platform-level skip.

### Specialist hint

`frontend-engineer` — fix involves React state, browser permission APIs, iOS Safari behavior.

### Files involved

- `frontend/src/views/Recorder.tsx` (lines 68-76, 149, 172) — sessionStorage → localStorage migration site
- `frontend/src/views/Feed.tsx` (lines 21-30) — geolocation soft-check site
- (new util) `frontend/src/lib/permissionsCheck.ts` — `navigator.permissions.query` wrapper for the soft-check primitive
- `frontend/src/components/PermissionErrorScreen.tsx` — copy update for "set to Allow in iOS Settings" guidance (already partly there)

### Next step

Surface fix options A / B / C to user. Apply selected fix(es), regenerate session-storage tests if migrating, verify on real iPhone Safari per project constraints.

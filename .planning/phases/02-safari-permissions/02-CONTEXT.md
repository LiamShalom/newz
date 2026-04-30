# Phase 02 — Safari Permissions + Recorder Reliability

**Milestone:** v1.1 Pilot MVP for funding
**Branch:** `feature/safari-permissions`
**Owner:** Roan
**Backlog ref:** ROADMAP.md Mando #4 ("Safari location services bug + permissions gate decision")
**Status:** Drafting

## Problem

Production iPhone testing (Vercel preview) showed three distinct permission-flow bugs that block the recorder pipeline on iOS Safari. iPhone Chrome and desktop Chrome both succeed; only iPhone Safari fails to post videos.

Cross-device matrix as observed 2026-04-29:

| Device / Browser | Custom priming popup? | Native browser popup? | Record? | Post? | Notes |
|---|---|---|---|---|---|
| iPhone Safari | ✅ shown | ✅ shown (cam/mic) | ✅ | ❌ "location blocked" | Open-Settings button is dead |
| iPhone Chrome | ✅ shown (redundant) | ✅ shown (cam/mic) | ✅ | ✅ | No third popup; just works |
| MacBook Chrome | ✅ shown (only one) | (none — pre-granted via prior test) | ✅ | ✅ | Single popup |

## The three bugs

**Bug A — Redundant priming popup.**
On iPhone (both browsers), users see two consecutive permission popups: ours ("Allow camera and location") then the native one ("newz-xi.vercel.app would like to access microphone and camera"). The custom popup is a *priming* dialog meant to explain context before the native one; in practice it reads as a duplicate. Compounded by the fact that our priming text mentions **location**, but only **camera + microphone** is requested when the user taps "Allow and continue" — location is deferred to record-tap (Recorder.tsx line 142). The priming copy overpromises and the user ends up clicking Allow twice for what feels like the same thing.

**Bug B — iPhone Safari blocks geolocation at post time.**
On iPhone Safari only, after a successful camera grant + recording, tapping Post lands on the "Location blocked" error screen. Same flow on iPhone Chrome succeeds. The current code requests geolocation at record-tap (`startRecording` → `getPositionWithTimeout`), which should be inside the gesture window. Root cause is unknown — could be:
- Safari rejecting geolocation when MediaRecorder.start() and getCurrentPosition share a single gesture handler.
- Site-level Safari permissions previously set to "Don't allow" (no prompt re-shown).
- iOS Settings → Privacy → Location Services → Safari Websites set to "Never" globally.
- Safari requiring `getCurrentPosition` from a fresh, separate user gesture rather than chained off recording start.

Investigation in Wave 2 will pin this down before deciding the fix.

**Bug C — "Open Settings" button is inert.**
PermissionErrorScreen (line 22, 28) uses `prefs:root=Safari` as the deeplink for the Open Settings button. This URL scheme was removed by Apple years ago and silently no-ops on modern iOS. The body copy explains the manual path, but the button's presence misleads users into expecting an automated jump. Either rephrase as instruction-only, or replace with a JS-based recovery (re-request via `getCurrentPosition` in a fresh gesture, which sometimes re-prompts in Safari).

## Decisions Made (locked)

1. **Drop the redundant priming popup, OR re-scope it as a single accurate priming.** Decision pending in Wave 1 — depends on whether removing it materially hurts grant rates. Default lean: drop it. iOS users are familiar with browser permission UX; the priming adds friction without information.
2. **Geolocation timing must be revisited.** Whether to keep the "GPS at record-tap, await at submit" pattern or switch to "GPS at submit-tap (fresh gesture)" depends on Wave 2 findings on Safari semantics.
3. **`prefs:root=Safari` deeplink is removed.** Apple-side bug, can't be worked around.
4. **No code change to the priming sessionStorage gate.** "Once per session" stays.

## Scope

**In:**
- Remove or restructure `PrimingModal.tsx` to fix Bug A.
- Investigate + fix iPhone Safari geolocation behavior (Bug B).
- Replace the dead Open-Settings deeplink with copy or a JS recovery flow (Bug C).
- Verify all flows on Vercel-deployed production (NOT local) on iPhone Safari, iPhone Chrome, MacBook Chrome, MacBook Safari.

**Out (deferred):**
- Recording → upload pipeline reliability (Liam — backend connection issues, current Phase 10 Vercel Blob migration).
- Local development HTTPS/cert setup for iPhone testing (worth a separate "dev-experience" phase if it bites again).
- Permissions gate redesign for Mando #7 (a separate, larger phase: "if no location, allow recording with reduced clustering weight" — the strategic Q in PROJECT.md).

## Open Questions (non-blocking — resolve during Wave 2)

- **Does iPhone Safari fire the native location prompt at all on first record-tap, or does it silently deny?** Diagnostic via DevTools (paired Web Inspector) or by clearing Safari site data and re-trying.
- **Does requesting geolocation from a separate gesture (the Post button) bypass the issue?** Likely yes on Safari — the cost is moving the GPS sample from "where you pressed record" to "where you pressed submit". Acceptable given Pilot scope.
- **Does this affect Liam's Mando #4 ("UW shows Pasadena") or is that strictly the geocoding side?** Liam's bug shipped as PR #2; assumed unrelated, but verify the diagnostic doesn't surface anything overlapping.

## Constraints from PROJECT.md

- Anonymity is load-bearing — geolocation may be omitted but never tied to identity.
- iOS Safari is the **primary surface**. Recorder must work end-to-end on iPhone Safari, not just iPhone Chrome.
- Reliability over polish — fix the post-blocking bug before redesigning copy.
- Roan-owned full vertical slice (frontend only — no backend touch expected).

## Dependencies / Sequence

- Independent of Liam's Phase 10 (Vercel Blob) and Phase 11 (Moderation gate). Frontend-only.
- Verification depends on Liam's preview/prod backend being reachable (currently in flux mid-Postgres-migration). Wave 4 verification waits if backend is down.

---
*Drafted: 2026-04-29 from cross-device test results + Recorder.tsx code read*

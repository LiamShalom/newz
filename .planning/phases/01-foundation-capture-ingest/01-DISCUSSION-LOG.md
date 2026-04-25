# Phase 1: Foundation, Capture & Ingest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 01-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 01-foundation-capture-ingest
**Areas discussed:** Camera capture flow, Pre-AI feed UX

---

## Camera capture flow

### Q1: FAB placement and style

| Option | Description | Selected |
|--------|-------------|----------|
| Bottom-center, big circular red | TikTok/Instagram pattern. Thumb-friendly, unmistakable. May conflict with iOS Safari bottom toolbar. | ✓ |
| Bottom-right, smaller circular | Material-style FAB. Out of the way of swipe gestures. Less obvious as primary action. | |
| Top-right, camera icon | Doesn't conflict with iOS Safari chrome. Less thumb-reachable on a held phone. | |

**User's choice:** Bottom-center, big circular red

### Q2: Pre-permission priming modal — gating behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Gating, once per session | Tapping FAB opens modal first; user taps "Continue" to trigger native prompts. Skipped on subsequent FAB taps in the same session. Highest grant rate. | ✓ |
| Gating, every time | Modal always shows before camera. Annoying after first record but deterministic. | |
| Non-gating banner | Modal fires once on first feed open, not on FAB tap. Cleaner camera flow but native prompts may surprise the user. | |

**User's choice:** Gating, once per session

### Q3: Recording UI

| Option | Description | Selected |
|--------|-------------|----------|
| Numeric counter + ring fill | Big '0:14' centered above stop, ring fills as 30s approaches, color shifts orange@25s/red@28s. | |
| Numeric counter only | Just '0:14 / 0:30' text overlay. Simpler, less polished. | |
| Ring fill only, no number | Pure visual ring around stop button. Cleanest, matches Instagram. Less explicit about cap. | ✓ |

**User's choice:** Ring fill only, no number

### Q4: Audio + camera defaults at record start

| Option | Description | Selected |
|--------|-------------|----------|
| Audio ON, rear camera | Mic + camera permissions. Rear default (event capture, not selfie). Matches news clip framing. | ✓ |
| Audio OFF, rear camera | One fewer prompt, no permission denial risk. Loses speech as a Marengo signal. | |
| Audio ON, front camera default | Selfie-style framing. Wrong default for the value prop. | |

**User's choice:** Audio ON, rear camera

### Q5: Retake/submit screen layout

| Option | Description | Selected |
|--------|-------------|----------|
| Full-screen playback + bottom action bar | Recorded clip autoplays inline (loops), 'Retake' on left + 'Submit' on right. Submit primary (filled red), Retake secondary. | |
| Full-screen playback + top X + bottom Submit | X in top-left dismisses to camera (counts as retake), single big Submit at bottom. Fewer buttons. | ✓ |
| Side-by-side thumbnails on a confirm card | Smaller preview, more chrome. More 'app-like' but less cinematic. | |

**User's choice:** Full-screen playback + top X + bottom Submit

### Q6: Camera-flip toggle

| Option | Description | Selected |
|--------|-------------|----------|
| Rear-only, no flip toggle | Simpler UI, faster to build, matches "capture the event" value prop. | |
| Rear default + flip button top-right | Standard camera UX. Adds one icon, ~10 lines for getUserMedia constraint swap. | ✓ |

**User's choice:** Rear default + flip button top-right

### Q7: Permission denial behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Camera deny = blocking error; GPS deny = continue with null GPS | Camera required (no clip without it). GPS soft (CAP-07/CLU-06 aligned). Honest on camera, graceful on GPS. | |
| Both soft — record without GPS, fail open with on-screen toast | If camera denied, show toast + 'Open Settings'. GPS denied = silent null. | |
| Both blocking — don't allow record without GPS either | Forces both grants for clean data. Highest demo failure risk indoors. Conflicts with CAP-07. | ✓ |

**User's choice:** Both blocking — don't allow record without GPS either
**Notes:** Claude pushed back twice citing CAP-07 (locked: "5s timeout, never blocks"), CLU-06 (Marengo-only fallback when GPS unavailable), and Pitfall #4 (KILL-DEMO indoor GPS at Caltech). User chose to accept the indoor demo risk rather than implement an escape hatch (DEM-05 demo_location override) or soften to "block only on user-denied, allow null GPS on indoor unavailable." CAP-07 must be revised to match.

### Q7-followup: Resolution path for the GPS-blocking conflict

| Option | Description | Selected |
|--------|-------------|----------|
| Block + pull DEM-05 demo_location into Phase 1 | Keep blocking, implement ?demo_location override now (was Phase 5). Update CAP-07. Demo survives. | |
| Block + accept Caltech indoor risk | Stick with blocking, no escape hatch. Pitfall #4 stays unmitigated for Phase 1. | ✓ |
| Soft on indoor-unavailable, block on user-denied only | User-deny = block; permission granted but GPS fails to lock = submit with null. Indoor demo survives. | |

**User's choice:** Block + accept Caltech indoor risk
**Notes:** Risk accepted explicitly. Outdoor demo or later DEM-05 pull-forward are the workarounds.

---

## Pre-AI feed UX

### Q1 (reframed): Phase 1 feed shell vs. throwaway

| Option | Description | Selected |
|--------|-------------|----------|
| Throwaway: scrollable list of <video> tiles | 30-60 min. Records play back, that's it. Phase 4 rebuilds for real. Fastest Phase 1 path. | ✓ |
| Build TikTok-style vertical full-screen now | +~2hr in Phase 1. Phase 4 swaps in AI segment data, no UI rewrite. Less rework total. | |

**User's choice:** Throwaway: scrollable list of <video> tiles
**Notes:** First batch of feed questions (tile content, empty state, refresh mechanism) was rejected by user as production-app framing for a 60-second hackathon demo with 3-4 staged clips. Reframed to a single decision-impact question. Remaining defaults captured under Claude's Discretion in CONTEXT.md.

---

## Claude's Discretion

Within the throwaway-feed scope, Claude defaults the following:
- Empty-state copy: "Tap red button to record" (no animated arrow, no pre-seeded staged clip — staged clip lands in Phase 5)
- Tile content: `<video>` + relative timestamp ("4 min ago"). No other overlays.
- Feed refresh: refetch on submit-redirect + manual pull-to-refresh. No polling, no SSE in Phase 1.
- Anonymous session UUID: generated on first feed-page load, persisted to `localStorage.session_id`, sent as request header on POST `/clips`. Not exposed in UI in Phase 1.
- Failed upload retry: localStorage queue + exponential backoff, retried on next feed visit. No persistent retry-toast UI in Phase 1.

## Deferred Ideas

None — both areas stayed within Phase 1 scope.

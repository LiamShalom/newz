---
phase: quick-260430-s4p-fix-header-transparency
plan: 01
type: execute
wave: 1
status: complete
files_modified: [frontend/src/components/Masthead.tsx]
requirements: [bug-fix-masthead-bleed]
completed: 2026-04-30
---

# Quick Task 260430-s4p — Fix Header Transparency Summary

## One-liner

Bumped Masthead `z-index` from `z-20` to `z-30` so SegmentCard h2 titles (also `z-20`, with intentional negative top margin in dark mode) no longer paint over the sticky header on scroll.

## Change

Single-character edit on `frontend/src/components/Masthead.tsx` line 7:

```diff
- <header className="sticky top-0 z-20 bg-surface">
+ <header className="sticky top-0 z-30 bg-surface">
```

## Why this works

- Masthead `bg-surface` is already opaque (`#0A0A0A` dark / `#FFFFFF` light) — never was a real transparency bug.
- Root cause was a z-index tie: Masthead at `z-20` + SegmentCard h2 at `relative z-20` with `dark:-mt-8 dark:sm:-mt-10` → DOM-order paint wins → h2 paints over Masthead.
- The h2 negative margin is load-bearing dark-mode video overlap design — must NOT be touched.
- Bumping Masthead to `z-30` aligns it with `BottomTabBar` (already `z-30`), establishing a consistent global-chrome z-index convention.
- No upward conflict: floating action chrome (`z-40`) and modals (`z-50`) still paint above Masthead.

## Verification

- `grep -n "sticky top-0 z-30 bg-surface" frontend/src/components/Masthead.tsx` → line 7 match.
- `grep -n "z-20" frontend/src/components/Masthead.tsx` → no matches.
- `bg-surface` unchanged.
- `SegmentCard.tsx` untouched (h2 negative margin preserved).
- No other files modified.

## Deviations from Plan

None — plan executed exactly as written.

## Manual UAT (deferred to Roan / on-device)

- Dark mode iOS Safari: scroll feed; verify Masthead wordmark stays solid, no h2 ghost text bleeding through.
- Light mode: same behavior expected.
- BottomTabBar (also `z-30`, fixed-position) — different stacking context from sticky header; no actual overlap, but spot-check.
- Floating action buttons (`z-40`, e.g. CameraUploadButton, RecordButton) still paint above Masthead.
- Modals (`z-50`, e.g. CommentSheet, PrimingModal) still paint above Masthead.

## Self-Check: PASSED

- File `frontend/src/components/Masthead.tsx` exists with `z-30` on line 7.
- No `z-20` remains in the file.
- SUMMARY.md exists at expected path.

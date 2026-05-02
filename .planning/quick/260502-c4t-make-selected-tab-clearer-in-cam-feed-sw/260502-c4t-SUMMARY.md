---
phase: quick-260502-c4t
plan: 01
subsystem: ui/navigation
tags: [ui, a11y, ios-safari, tab-bar, contrast]
requirements:
  - QUICK-260502-c4t
key-files:
  modified:
    - frontend/src/components/BottomTabBar.tsx
decisions:
  - Use `bg-surface-elevated` filled pill for selected tab (avoids reusing coral, which is reserved for the record CTA).
  - Drop unselected from `text-ink-primary/70` to `text-ink-tertiary` — token-defined "muted but legible" rung that survives bright daylight.
  - Apply pill geometry (`rounded-xl mx-2 my-1.5`) to BOTH active and inactive states so the only thing that changes on tab switch is bg + text color — no layout shift.
  - Pass `aria-current="page"` on both `<NavLink>` elements; react-router-dom v6 only emits the attribute on the rendered DOM when the link is active, so this is the idiomatic single-attribute pattern.
metrics:
  files_modified: 1
  diff_lines: ~24
  completed_date: 2026-05-02
---

# Quick 260502-c4t: Selected cam/feed tab visibility Summary

Tightened bottom tab bar so the active destination is unambiguous on a bright iPhone screen and announces itself to assistive tech via `aria-current="page"`.

## What changed

Single-file diff in `frontend/src/components/BottomTabBar.tsx`. No new files, no new deps, no backend touch.

### Selected vs unselected — final tokens

| State      | Text/icon color    | Background           | Icon stroke (Cam / Feed) |
| ---------- | ------------------ | -------------------- | ------------------------ |
| Selected   | `text-ink-primary` | `bg-surface-elevated` | 2.5 / 2                  |
| Unselected | `text-ink-tertiary`| transparent           | 1.5 / 1.25               |

Token values resolve to:

- `--color-ink-primary`: `#FFFFFF` dark / `#0A0A0A` light
- `--color-ink-tertiary`: `#6B6B6B` dark / `#6E6E73` light
- `--color-surface-elevated`: `#141414` dark / `#F5F5F5` light

### Before / after class strings

`tabClass` return value before:

```
"<TAB_BASE> text-ink-primary"          // active
"<TAB_BASE> text-ink-primary/70"       // inactive
```

`tabClass` return value after:

```
"<TAB_BASE> text-ink-primary bg-surface-elevated"   // active
"<TAB_BASE> text-ink-tertiary"                      // inactive
```

`TAB_BASE` before / after — added `rounded-xl mx-2 my-1.5` (applied to both states, so geometry is identical between active/inactive — no layout shift on switch):

```
// before
"flex flex-col items-center justify-center gap-0.5 flex-1 h-14 \
text-[11px] font-black tracking-wide uppercase \
transition-colors"

// after
"flex flex-col items-center justify-center gap-0.5 flex-1 h-14 \
text-[11px] font-black tracking-wide uppercase \
rounded-xl mx-2 my-1.5 \
transition-colors"
```

### Icon stroke widths

- `CameraLens`: active `2.25 → 2.5`, inactive `1.75 → 1.5` (wider gap between active/inactive for at-a-glance read).
- `FeedIcon`: active `1.5 → 2`, inactive unchanged at `1.25`.

### A11y

- `aria-current="page"` added as a prop to both `<NavLink>` elements. react-router-dom v6's `NavLink` only emits the attribute on the rendered DOM when the link is active, so passing it on both is the documented pattern — no conditional logic needed.
- Existing `aria-label="Camera"` / `aria-label="Feed"` retained on the NavLinks; `aria-label="Primary"` retained on the `<nav>`.
- Still navigation landmarks; still keyboard-focusable; still respects safe-area inset.

## What did NOT change

- Routes, `to` paths, `end` prop on the `/` link.
- Fixed positioning, `z-30`, `pb-[env(safe-area-inset-bottom)]`, `border-t border-hairline`, `bg-surface`.
- Coral / record-button styling (intentionally not reused — would conflict with the record CTA).
- No edits outside `frontend/src/components/BottomTabBar.tsx`.

## Verification

- `cd frontend && npx tsc --noEmit` passes against the main repo's installed deps (EXIT=0). The worktree has no `node_modules` installed locally; running `tsc` there reports module-resolution errors for `react`, `react/jsx-runtime`, and `react-router-dom` for every `.tsx` file in the project — these are environment-only, not code issues. The identical file content in the main repo's `frontend/` (where `node_modules` is installed) typechecks clean.
- Diff confined to the one component file as required.
- iOS Safari visual verification (Task 2 checkpoint) is owed to Roan post-merge — this summary captures the implementation; bright-daylight sign-off lives with the human on a real iPhone per project rule (emulator does not count).

## Deviations from Plan

None substantive — plan executed as written. One operational note:

- Plan asked for `npx tsc --noEmit` as automated verification. Worktree has no `node_modules`, so the run reports global "cannot find module" errors. Re-ran the same check against the main repo (where deps are installed) with the identical file content — clean exit. No code-level type issues.

## Self-Check: PASSED

- `frontend/src/components/BottomTabBar.tsx` modified — confirmed via `git status --short` showing ` M frontend/src/components/BottomTabBar.tsx`.
- `aria-current="page"` present on both `<NavLink>` elements — confirmed via Read of post-edit file (lines 74, 82).
- `bg-surface-elevated` applied only on active branch of `tabClass` — confirmed (line 12).
- `text-ink-tertiary` applied on inactive branch — confirmed (line 13).
- Pill geometry (`rounded-xl mx-2 my-1.5`) added to `TAB_BASE` so it applies to both states — confirmed (line 6).
- Stroke widths updated as specified (CameraLens 2.5/1.5, FeedIcon 2/1.25) — confirmed (lines 25, 35).

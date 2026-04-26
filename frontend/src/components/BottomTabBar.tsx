import { NavLink } from "react-router-dom";

const TAB_BASE =
  "flex flex-col items-center justify-center gap-0.5 flex-1 h-14 " +
  "text-[11px] font-black tracking-wide uppercase " +
  "transition-colors";

function tabClass({ isActive }: { isActive: boolean }) {
  return `${TAB_BASE} ${isActive ? "text-ink-primary" : "text-ink-primary/70"}`;
}

function CameraLens({ size = 28, active }: { size?: number; active: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={active ? 2.25 : 1.75}
    >
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="5" fill="currentColor" stroke="none" />
      <circle cx="10" cy="10" r="1.2" fill="var(--color-surface)" stroke="none" />
    </svg>
  );
}

function FeedIcon({ size = 28, active }: { size?: number; active: boolean }) {
  const sw = active ? 1.5 : 1.25;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="3" width="18" height="19" rx="2" />
      <rect x="7" y="7" width="10" height="4" rx="0.5" />
      <line x1="7" y1="14" x2="17" y2="14" />
      <line x1="7" y1="17" x2="13" y2="17" />
    </svg>
  );
}

/**
 * Snap-style bottom navigation. Two destinations: Camera (/) and Feed (/feed).
 * Solid surface so it reads cleanly against either the camera viewport or the
 * feed scroll. Hidden while recording — Recorder controls visibility via
 * conditional render.
 */
export function BottomTabBar() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 flex items-stretch
                 bg-surface border-t border-hairline
                 pb-[env(safe-area-inset-bottom)]"
      aria-label="Primary"
    >
      <NavLink to="/" end className={tabClass} aria-label="Camera">
        {({ isActive }) => <CameraLens active={isActive} />}
      </NavLink>
      <NavLink to="/feed" className={tabClass} aria-label="Feed">
        {({ isActive }) => <FeedIcon active={isActive} />}
      </NavLink>
    </nav>
  );
}

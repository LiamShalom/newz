import { NavLink } from "react-router-dom";
import { Camera, Newspaper } from "lucide-react";

const TAB_BASE =
  "flex flex-col items-center justify-center gap-0.5 flex-1 h-14 " +
  "text-[11px] font-semibold tracking-wide uppercase " +
  "transition-colors";

function tabClass({ isActive }: { isActive: boolean }) {
  return `${TAB_BASE} ${isActive ? "text-ink-primary" : "text-ink-tertiary"}`;
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
        {({ isActive }) => (
          <>
            <Camera size={22} strokeWidth={isActive ? 2.25 : 1.75} />
            <span>Camera</span>
          </>
        )}
      </NavLink>
      <NavLink to="/feed" className={tabClass} aria-label="Feed">
        {({ isActive }) => (
          <>
            <Newspaper size={22} strokeWidth={isActive ? 2.25 : 1.75} />
            <span>Feed</span>
          </>
        )}
      </NavLink>
    </nav>
  );
}

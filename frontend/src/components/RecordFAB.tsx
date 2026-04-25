import { Link } from "react-router-dom";

// Bottom-center FAB anchored above iOS Safari's toolbar via safe-area-inset.
// Outer ring uses surface + hairline so it reads cleanly on light or dark.
export function RecordFAB() {
  return (
    <Link
      to="/record"
      aria-label="Start recording"
      className="fixed left-1/2 -translate-x-1/2 z-30 flex items-center justify-center
                 w-16 h-16 rounded-full bg-surface border-2 border-hairline
                 shadow-[0_2px_12px_rgba(0,0,0,0.08)]
                 active:scale-95 transition-transform
                 focus-visible:outline-2 focus-visible:outline-accent-link focus-visible:outline-offset-4"
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      <span className="block w-14 h-14 rounded-full bg-accent-record" />
    </Link>
  );
}

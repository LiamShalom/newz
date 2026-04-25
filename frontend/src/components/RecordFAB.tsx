import { Link } from "react-router-dom";

/**
 * D-01 + UI-SPEC: bottom-center, 72px red circle, anchored above iOS Safari
 * toolbar via safe-area-inset-bottom. Icon-only — aria-label per UI-SPEC.
 *
 * Outer 80px wrapper + inner 72px red span gives the "filled circle with
 * white inset border" look UI-SPEC describes. Active-press scale matches
 * UI-SPEC RecordFAB states "default, pressed".
 */
export function RecordFAB() {
  return (
    <Link
      to="/record"
      aria-label="Start recording"
      className="fixed left-1/2 -translate-x-1/2 z-30 flex items-center justify-center
                 w-20 h-20 rounded-full bg-[#1A1A1A] border-4 border-[#FAFAFA]
                 active:scale-95 transition-transform"
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      <span className="block w-[72px] h-[72px] rounded-full bg-[#EF4444]" />
    </Link>
  );
}

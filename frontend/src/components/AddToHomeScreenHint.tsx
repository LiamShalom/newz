import { useEffect, useState } from "react";

const AUTO_DISMISS_MS = 15_000;
const APPEAR_DELAY_MS = 1500;

function isInstalled(): boolean {
  if (typeof window === "undefined") return false;
  if ((window.navigator as Navigator & { standalone?: boolean }).standalone === true) return true;
  if (window.matchMedia("(display-mode: standalone)").matches) return true;
  if (window.matchMedia("(display-mode: minimal-ui)").matches) return true;
  return false;
}

interface Props {
  /** When flips true, the hint dismisses itself for this session (e.g. user started recording). */
  dismiss: boolean;
}

/**
 * iOS Add-to-Home-Screen suggestion. Auto-dismisses after 15s, on X tap, or
 * when `dismiss` flips true. Shown on every app open unless the page was
 * launched from the home screen.
 */
export function AddToHomeScreenHint({ dismiss }: Props) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (isInstalled()) return;
    const t = setTimeout(() => setVisible(true), APPEAR_DELAY_MS);
    return () => clearTimeout(t);
  }, []);

  const close = () => setVisible(false);

  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(close, AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [visible]);

  useEffect(() => {
    if (visible && dismiss) close();
  }, [visible, dismiss]);

  if (!visible) return null;

  return (
    <div
      className="fixed left-1/2 -translate-x-1/2 z-40 w-[calc(100%-32px)] max-w-[280px] pointer-events-none"
      style={{ top: "calc(16px + env(safe-area-inset-top))" }}
    >
      <div className="pointer-events-auto bg-[#1A1A1A]/95 backdrop-blur rounded-2xl px-4 py-3 border border-[#262626] flex items-center gap-3 shadow-xl">
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#F88B7A"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className="shrink-0"
        >
          <path d="M5 12v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7" />
          <path d="M12 3v13" />
          <path d="m8 7 4-4 4 4" />
        </svg>
        <div className="flex-1 text-[13px] leading-[1.35] text-[#FAFAFA]">
          <div className="font-semibold">Add Newz to Home Screen</div>
          <div className="text-[#A3A3A3]">Tap Share, then “Add to Home Screen”</div>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label="Dismiss"
          className="shrink-0 w-7 h-7 -mr-1 flex items-center justify-center rounded-full text-[#A3A3A3]"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";

const AUTO_DISMISS_MS = 15_000;
const APPEAR_DELAY_MS = 1500;
const TUTORIAL_STEP_MS = 2200;

function isInstalled(): boolean {
  if (typeof window === "undefined") return false;
  if ((window.navigator as Navigator & { standalone?: boolean }).standalone === true) return true;
  if (window.matchMedia("(display-mode: standalone)").matches) return true;
  if (window.matchMedia("(display-mode: minimal-ui)").matches) return true;
  return false;
}

// iOS Safari is the only browser where Add-to-Home-Screen lives in the Share
// sheet. Chrome (CriOS), Firefox (FxiOS), and Edge (EdgiOS) on iOS render the
// share button without that row, and Android/desktop don't need this hint.
function isIOSSafari(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  const isIOS =
    /iPad|iPhone|iPod/.test(ua) &&
    !(window as unknown as { MSStream?: unknown }).MSStream;
  if (!isIOS) return false;
  return /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

interface Props {
  /** When flips true, the hint dismisses itself for this session (e.g. user started recording). */
  dismiss: boolean;
}

/**
 * iOS Add-to-Home-Screen suggestion. Pill auto-dismisses after 15s, X tap, or
 * `dismiss` flip. Tapping the pill opens an animated walkthrough — iOS Safari
 * does not expose a programmatic A2HS API, so the best we can do is show the
 * exact two-tap path through the Share sheet.
 */
export function AddToHomeScreenHint({ dismiss }: Props) {
  const [visible, setVisible] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(false);

  useEffect(() => {
    if (isInstalled() || !isIOSSafari()) return;
    const t = setTimeout(() => setVisible(true), APPEAR_DELAY_MS);
    return () => clearTimeout(t);
  }, []);

  const close = () => {
    setVisible(false);
    setTutorialOpen(false);
  };

  // Auto-dismiss timer pauses while tutorial is open.
  useEffect(() => {
    if (!visible || tutorialOpen) return;
    const t = setTimeout(() => setVisible(false), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [visible, tutorialOpen]);

  useEffect(() => {
    if (visible && dismiss) close();
  }, [visible, dismiss]);

  if (!visible) return null;

  return (
    <>
      <div
        className="fixed left-1/2 -translate-x-1/2 z-40 w-[calc(100%-32px)] max-w-[280px] pointer-events-none"
        style={{ top: "calc(16px + env(safe-area-inset-top))" }}
      >
        <div
          role="button"
          tabIndex={0}
          onClick={() => setTutorialOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setTutorialOpen(true);
            }
          }}
          className="pointer-events-auto bg-[#1A1A1A]/95 backdrop-blur rounded-2xl px-4 py-3 border border-[#262626] flex items-center gap-3 shadow-xl cursor-pointer active:scale-[0.98] transition-transform"
        >
          <ShareGlyph className="shrink-0 text-[#F88B7A]" size={22} />
          <div className="flex-1 text-[13px] leading-[1.35] text-[#FAFAFA]">
            <div className="font-semibold">Add Newz to Home Screen</div>
            <div className="text-[#A3A3A3]">Tap to see how</div>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setVisible(false);
            }}
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
      {tutorialOpen && <InstallTutorial onClose={() => setTutorialOpen(false)} />}
    </>
  );
}

function InstallTutorial({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<0 | 1>(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setStep((s) => (s === 0 ? 1 : 0));
    }, TUTORIAL_STEP_MS);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center px-6"
      style={{ minHeight: "100dvh" }}
      onClick={onClose}
    >
      <div
        className="bg-[#1A1A1A] rounded-2xl p-6 max-w-sm w-full border border-[#262626]"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold leading-[1.15] text-[#FAFAFA]">
          Add Newz to Home Screen
        </h2>
        <p className="mt-2 text-sm leading-[1.45] text-[#B5B5B5]">
          Two taps in Safari — no account needed. iOS doesn’t let apps do this for you.
        </p>

        <div className="mt-5 bg-[#0A0A0A] rounded-xl border border-[#1F1F1F] h-44 relative overflow-hidden">
          <TutorialStage step={step} />
        </div>

        <ol className="mt-5 space-y-3">
          <TutorialStep active={step === 0} index={1}>
            Tap the <ShareGlyph className="inline-block align-[-3px] mx-1 text-[#F88B7A]" size={14} /> Share button
          </TutorialStep>
          <TutorialStep active={step === 1} index={2}>
            Choose <span className="font-semibold text-[#FAFAFA]">Add to Home Screen</span>
          </TutorialStep>
        </ol>

        <button
          type="button"
          onClick={onClose}
          className="no-blue-focus mt-6 w-full h-11 rounded-full bg-gradient-to-r from-coral-light to-coral text-white font-semibold text-base"
        >
          Got it
        </button>
      </div>
    </div>
  );
}

function TutorialStep({
  active,
  index,
  children,
}: {
  active: boolean;
  index: number;
  children: React.ReactNode;
}) {
  return (
    <li
      className={`flex items-start gap-3 text-[13px] leading-[1.4] transition-colors ${
        active ? "text-[#FAFAFA]" : "text-[#737373]"
      }`}
    >
      <span
        className={`shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-semibold transition-colors ${
          active ? "bg-coral text-white" : "bg-[#262626] text-[#A3A3A3]"
        }`}
      >
        {index}
      </span>
      <span className="pt-px">{children}</span>
    </li>
  );
}

function TutorialStage({ step }: { step: 0 | 1 }) {
  return (
    <div className="absolute inset-0">
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{ opacity: step === 0 ? 1 : 0 }}
      >
        <SafariBarFrame />
      </div>
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{ opacity: step === 1 ? 1 : 0 }}
      >
        <ShareSheetFrame />
      </div>
    </div>
  );
}

// Frame 1: stylized iOS Safari bottom toolbar with Share button pulsing.
function SafariBarFrame() {
  return (
    <div className="absolute inset-0 flex flex-col justify-end p-3">
      <div className="rounded-xl bg-[#161616] border border-[#262626] px-3 py-2 flex items-center justify-between text-[#737373]">
        <ToolbarIcon path="M15 6l-6 6 6 6" />
        <ToolbarIcon path="M9 6l6 6-6 6" />
        <div className="relative">
          <span className="absolute inset-0 -m-1 rounded-lg bg-coral/30 animate-ping" aria-hidden="true" />
          <span className="relative w-9 h-9 rounded-lg border border-coral flex items-center justify-center text-[#F88B7A]">
            <ShareGlyph size={18} />
          </span>
        </div>
        <ToolbarIcon path="M4 6h16M4 12h16M4 18h16" />
        <ToolbarIcon path="M4 7h16v10H4z" stroke />
      </div>
      <div className="mt-2 text-center text-[11px] uppercase tracking-wide text-[#A3A3A3]">
        Step 1 — tap Share
      </div>
    </div>
  );
}

// Frame 2: stylized share-sheet excerpt with "Add to Home Screen" highlighted.
function ShareSheetFrame() {
  const rows = [
    { label: "Copy", glyph: "copy" as const, active: false },
    { label: "Add to Home Screen", glyph: "add" as const, active: true },
    { label: "Add Bookmark", glyph: "bookmark" as const, active: false },
  ];
  return (
    <div className="absolute inset-0 flex flex-col p-3">
      <div className="rounded-xl bg-[#161616] border border-[#262626] divide-y divide-[#1F1F1F] flex-1 overflow-hidden">
        {rows.map((r) => (
          <div
            key={r.label}
            className={`flex items-center justify-between px-3 h-10 ${
              r.active ? "bg-coral/15" : ""
            }`}
          >
            <span
              className={`text-[12px] ${
                r.active ? "text-[#FAFAFA] font-semibold" : "text-[#737373]"
              }`}
            >
              {r.label}
            </span>
            <span
              className={`w-6 h-6 rounded-md flex items-center justify-center ${
                r.active
                  ? "border border-coral text-[#F88B7A] animate-pulse"
                  : "border border-[#2A2A2A] text-[#525252]"
              }`}
            >
              <SheetGlyph kind={r.glyph} />
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 text-center text-[11px] uppercase tracking-wide text-[#A3A3A3]">
        Step 2 — Add to Home Screen
      </div>
    </div>
  );
}

function ToolbarIcon({ path, stroke }: { path: string; stroke?: boolean }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={path} fill={stroke ? "none" : undefined} />
    </svg>
  );
}

function SheetGlyph({ kind }: { kind: "copy" | "add" | "bookmark" }) {
  if (kind === "copy") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <path d="M5 15V6a2 2 0 0 1 2-2h9" />
      </svg>
    );
  }
  if (kind === "add") {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
        <path d="M12 5v14M5 12h14" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="M6 4h12v17l-6-4-6 4z" />
    </svg>
  );
}

// iOS-style share glyph: rounded box with up-arrow leaving the top.
function ShareGlyph({ className, size = 20 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M5 12v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7" />
      <path d="M12 3v13" />
      <path d="m8 7 4-4 4 4" />
    </svg>
  );
}

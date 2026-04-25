import { useEffect, useState } from "react";

interface Props {
  onContinue: () => void;
}

/**
 * D-02: gating, once per session via sessionStorage("priming_shown") key.
 * Skipped (immediately calls onContinue) if the flag is already set.
 *
 * Interaction contract item 5: no backdrop dismiss, no Escape key. The Allow-and-continue
 * button is the only exit. iOS Safari has no keyboard, so Escape is a non-issue.
 */
export function PrimingModal({ onContinue }: Props) {
  const [open, setOpen] = useState(
    () => sessionStorage.getItem("priming_shown") !== "1",
  );

  useEffect(() => {
    if (!open) onContinue();
  }, [open, onContinue]);

  if (!open) return null;

  const proceed = () => {
    sessionStorage.setItem("priming_shown", "1");
    setOpen(false);
    onContinue();
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-6"
      style={{ minHeight: "100dvh" }}
    >
      <div className="bg-[#1A1A1A] rounded-2xl p-6 max-w-sm w-full border border-[#262626]">
        <h2 className="text-2xl font-semibold leading-[1.2] text-[#FAFAFA]">
          Allow camera and location
        </h2>
        <p className="mt-4 text-base leading-[1.5] text-[#FAFAFA]">
          Newz needs your camera to record and your location to group clips by event. Nothing is tied to you — there&apos;s no account.
        </p>
        <button
          autoFocus
          type="button"
          onClick={proceed}
          className="mt-6 w-full h-14 rounded-full bg-[#EF4444] text-white font-semibold text-base"
        >
          Allow and continue
        </button>
      </div>
    </div>
  );
}

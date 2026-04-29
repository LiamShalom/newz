interface Props {
  onContinue: () => void;
}

/**
 * Phase 02 (2026-04-29): single-tap priming. Tapping "Allow and continue"
 * fires getUserMedia + getCurrentPosition synchronously in the same gesture
 * frame (see Recorder.tsx initializePermissions). Both browser permission
 * dialogs chain back-to-back from this one tap.
 *
 * Copy is honest about what's coming next so the two system dialogs read as
 * step 2 of a single flow, not duplicate asks.
 */
export function PrimingModal({ onContinue }: Props) {
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
        <p className="mt-3 text-sm leading-[1.4] text-[#B5B5B5]">
          Tap <span className="text-[#FAFAFA] font-semibold">Allow</span> on the next two prompts.
        </p>
        <button
          autoFocus
          type="button"
          onClick={onContinue}
          className="mt-6 w-full h-14 rounded-full bg-gradient-to-r from-coral-light to-coral text-white font-semibold text-base"
        >
          Allow and continue
        </button>
      </div>
    </div>
  );
}

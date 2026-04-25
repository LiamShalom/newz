interface Props {
  submitting: boolean;
  onSubmit: () => void;
}

/** Primary "Post clip" pill on retake screen. UI-SPEC interaction item 2: 60% opacity while submitting; no spinner. */
export function SubmitButton({ submitting, onSubmit }: Props) {
  return (
    <button
      type="button"
      onClick={onSubmit}
      disabled={submitting}
      className={`absolute left-6 right-6 h-14 rounded-full bg-[#EF4444] text-white font-semibold text-base ${submitting ? "opacity-60" : ""}`}
      style={{ bottom: "calc(16px + env(safe-area-inset-bottom))" }}
    >
      Post clip
    </button>
  );
}

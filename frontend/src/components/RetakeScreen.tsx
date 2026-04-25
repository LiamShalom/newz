import { useEffect, useMemo } from "react";
import { X } from "lucide-react";
import { SubmitButton } from "./SubmitButton";

interface Props {
  blob: Blob;
  submitting: boolean;
  onRetake: () => void;
  onSubmit: () => void;
}

/**
 * D-05 retake screen: full-bleed autoplay-loop preview + X (top-left) + Post clip (bottom).
 * No "Retake" word — the X carries that semantic; aria-label="Retake" preserves accessibility.
 */
export function RetakeScreen({ blob, submitting, onRetake, onSubmit }: Props) {
  const url = useMemo(() => URL.createObjectURL(blob), [blob]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <video
        src={url}
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 w-full h-full object-contain"
      />
      <button
        type="button"
        onClick={onRetake}
        aria-label="Retake"
        className="absolute left-2 z-20 w-11 h-11 flex items-center justify-center text-[#FAFAFA]"
        style={{ top: "calc(16px + env(safe-area-inset-top))" }}
      >
        <X size={24} strokeWidth={2} />
      </button>
      <SubmitButton submitting={submitting} onSubmit={onSubmit} />
    </div>
  );
}

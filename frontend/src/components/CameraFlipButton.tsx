import { RefreshCcw } from "lucide-react";

interface Props {
  facing: "environment" | "user";
  onFlip: () => void;
}

/** D-06: top-right flip toggle. 44x44 tap target (Apple HIG). */
export function CameraFlipButton({ facing: _facing, onFlip }: Props) {
  return (
    <button
      type="button"
      onClick={onFlip}
      aria-label="Switch camera"
      className="absolute right-2 z-20 w-11 h-11 flex items-center justify-center text-[#FAFAFA]"
      style={{ top: "calc(16px + env(safe-area-inset-top))" }}
    >
      <RefreshCcw size={24} strokeWidth={2} />
    </button>
  );
}

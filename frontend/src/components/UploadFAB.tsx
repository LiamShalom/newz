import { useRef, useState } from "react";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";
import { getPositionWithTimeout } from "../lib/getPositionWithTimeout";

type Props = {
  fallbackLat?: number;
  fallbackLng?: number;
};

// Secondary FAB next to RecordFAB — picks an existing video file from the
// device and ships it through the same /clips ingest path. Mirrors Recorder's
// submit logic: try GPS, fall back to viewer coords, then enqueue on failure.
export function UploadFAB({ fallbackLat, fallbackLng }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;

    setBusy(true);
    try {
      const pos = await getPositionWithTimeout(5000);
      const lat = pos.kind === "ok" ? pos.lat : (fallbackLat ?? 0);
      const lng = pos.kind === "ok" ? pos.lng : (fallbackLng ?? 0);
      const ts = Date.now() / 1000;
      const mimeType = file.type || "video/mp4";
      const filename = file.name || `clip.${mimeType.includes("mp4") ? "mp4" : "webm"}`;

      try {
        await postClip({ blob: file, filename, lat, lng, ts });
      } catch {
        await enqueue({ blob: file, mimeType, lat, lng, ts });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => {
          void onPick(e);
        }}
      />
      <button
        type="button"
        aria-label="Upload video"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        className="fixed z-30 flex items-center justify-center
                   w-12 h-12 rounded-full bg-surface border-2 border-hairline
                   shadow-[0_2px_12px_rgba(0,0,0,0.08)]
                   active:scale-95 transition-transform disabled:opacity-50
                   focus-visible:outline-2 focus-visible:outline-accent-link focus-visible:outline-offset-4"
        style={{
          bottom: "calc(28px + env(safe-area-inset-bottom))",
          right: "calc(50% - 88px)",
        }}
      >
        {busy ? (
          <span className="block w-4 h-4 rounded-full border-2 border-hairline border-t-transparent animate-spin" />
        ) : (
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M12 4v12" />
            <path d="m6 10 6-6 6 6" />
            <path d="M4 20h16" />
          </svg>
        )}
      </button>
    </>
  );
}

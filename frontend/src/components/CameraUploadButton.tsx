import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ImagePlus } from "lucide-react";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";
import { getPositionWithTimeout } from "../lib/getPositionWithTimeout";

/**
 * Snap-style "memories" affordance — bottom-left of the camera screen.
 * Lets the user post an existing video file through the same /clips ingest path
 * as Recorder. After a successful (or queued) upload navigates to /feed so the
 * user lands where their contribution will appear.
 */
export function CameraUploadButton() {
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    setBusy(true);
    try {
      const pos = await getPositionWithTimeout(5000);
      const lat = pos.kind === "ok" ? pos.lat : 0;
      const lng = pos.kind === "ok" ? pos.lng : 0;
      const ts = Date.now() / 1000;
      const mimeType = file.type || "video/mp4";
      const filename =
        file.name || `clip.${mimeType.includes("mp4") ? "mp4" : "webm"}`;

      try {
        await postClip({ blob: file, filename, lat, lng, ts });
      } catch {
        await enqueue({ blob: file, mimeType, lat, lng, ts });
      }
      navigate("/feed");
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
        aria-label="Upload from camera roll"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        className="absolute z-40 w-12 h-12 flex items-center justify-center
                   rounded-full bg-black/45 backdrop-blur-md text-white
                   active:scale-95 transition-transform disabled:opacity-50"
        style={{
          left: "20px",
          bottom: "calc(88px + env(safe-area-inset-bottom))",
        }}
      >
        {busy ? (
          <span className="block w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin" />
        ) : (
          <ImagePlus size={22} strokeWidth={2} />
        )}
      </button>
    </>
  );
}

import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowUp } from "lucide-react";
import { postClip } from "../api";
import { enqueue } from "../uploadQueue";
import { getPositionWithTimeout } from "../lib/getPositionWithTimeout";
import { setUploadStatus } from "../uploadStatusBus";

/**
 * Snap-style "memories" affordance — bottom-left of the camera screen.
 * Lets the user post an existing video file through the same /clips ingest path
 * as Recorder. After picking a file we navigate to /feed in the same gesture
 * frame and run the upload as a detached promise; progress + failure surface
 * via the top-of-feed UploadProgressBar (uploadStatusBus).
 *
 * `busy` local state was removed — the spinner-on-button is irrelevant once
 * the user has already left this view by the time the upload runs.
 */
export function CameraUploadButton() {
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    const pos = await getPositionWithTimeout(5000);
    const lat = pos.kind === "ok" ? pos.lat : 0;
    const lng = pos.kind === "ok" ? pos.lng : 0;
    const ts = Date.now() / 1000;
    const mimeType = file.type || "video/mp4";
    const filename =
      file.name || `clip.${mimeType.includes("mp4") ? "mp4" : "webm"}`;

    // Optimistic-navigate: bus + navigate first, upload as detached promise.
    setUploadStatus({ kind: "uploading" });
    navigate("/feed");

    void (async () => {
      try {
        await postClip({ blob: file, filename, lat, lng, ts });
        setUploadStatus({ kind: "idle" });
      } catch (err) {
        console.error("[camera-upload] postClip failed; enqueuing locally:", err);
        try {
          await enqueue({ blob: file, mimeType, lat, lng, ts });
          setUploadStatus({
            kind: "error",
            message: "Upload queued — will retry",
          });
        } catch {
          setUploadStatus({ kind: "error", message: "Upload failed" });
        }
      }
    })();
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
        onClick={() => inputRef.current?.click()}
        className="group absolute z-40 h-16 w-16 hover:w-48 flex items-center overflow-hidden
                   rounded-full bg-gradient-to-r from-coral-light to-coral text-white shadow-lg
                   active:scale-95
                   transition-[width,transform] duration-300 ease-out"
        style={{
          left: "20px",
          bottom: "calc(88px + env(safe-area-inset-bottom))",
        }}
      >
        <span className="absolute inset-0 flex items-center justify-center opacity-100 group-hover:opacity-0 transition-opacity duration-200">
          <ArrowUp size={28} strokeWidth={2.25} />
        </span>
        <span className="absolute inset-0 flex items-center justify-center text-xl font-bold whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-200 group-hover:delay-150">
          Upload
        </span>
      </button>
    </>
  );
}

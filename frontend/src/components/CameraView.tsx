import { useEffect, useRef } from "react";

interface Props {
  stream: MediaStream | null;
  mirrored?: boolean;
}

/**
 * S3: autoPlay + muted + playsInline are all load-bearing on iOS Safari.
 * Missing playsInline -> iOS opens native fullscreen and breaks the UX.
 * Missing muted -> iOS blocks autoplay entirely.
 *
 * iOS Safari quirk (2026-04-30 regression — debug/ios-camera-black.md): the
 * `<video autoPlay>` attribute is only honored on FIRST mount. Recorder mounts
 * us with `stream={null}` during the "acquiring" phase (waiting for
 * getUserMedia + getCurrentPosition to resolve), then re-renders with the
 * actual MediaStream. Setting `srcObject` AFTER the initial autoplay attempt
 * failed (no source) does NOT auto-resume on iOS Safari — the element stays
 * black even though the stream is healthy. Explicit `.play()` is required.
 *
 * `play()` returns a promise that can reject (e.g. AbortError when srcObject
 * changes mid-play, or NotAllowedError if iOS unexpectedly demoted us out of
 * the gesture window). We swallow rejections defensively because there's no
 * useful UI state for them — the next stream change will trigger another
 * play() attempt.
 *
 * `mirrored` flips the preview horizontally for the front-facing camera so the
 * user sees a mirror image (matches iOS Camera / Snapchat). The underlying
 * MediaStream is not flipped, so the recorded blob is unmirrored.
 */
export function CameraView({ stream, mirrored = false }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.srcObject = stream;
    if (stream) {
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    }
  }, [stream]);
  return (
    <video
      ref={ref}
      autoPlay
      muted
      playsInline
      className={`absolute inset-0 w-full h-full object-cover bg-[#0A0A0A] ${mirrored ? "-scale-x-100" : ""}`}
    />
  );
}

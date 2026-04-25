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
 * `mirrored` flips the preview horizontally for the front-facing camera so the
 * user sees a mirror image (matches iOS Camera / Snapchat). The underlying
 * MediaStream is not flipped, so the recorded blob is unmirrored.
 */
export function CameraView({ stream, mirrored = false }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
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

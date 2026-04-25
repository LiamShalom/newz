import { useEffect, useRef } from "react";

interface Props {
  stream: MediaStream | null;
}

/**
 * S3: autoPlay + muted + playsInline are all load-bearing on iOS Safari.
 * Missing playsInline -> iOS opens native fullscreen and breaks the UX.
 * Missing muted -> iOS blocks autoplay entirely.
 */
export function CameraView({ stream }: Props) {
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
      className="absolute inset-0 w-full h-full object-cover bg-[#0A0A0A]"
    />
  );
}

import { Link } from "react-router-dom";

export function Recorder() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center p-6">
      <p className="text-[#A3A3A3] text-base">Plan 04 will build the camera here.</p>
      <Link to="/" className="mt-6 underline text-[#FAFAFA]">Back to feed</Link>
    </div>
  );
}

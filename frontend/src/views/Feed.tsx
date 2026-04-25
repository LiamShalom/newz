import { Link } from "react-router-dom";

export function Feed() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] text-[#FAFAFA] flex flex-col items-center justify-center p-6">
      <p className="text-[#A3A3A3] text-base">Plan 03 will build the feed here.</p>
      <Link
        to="/record"
        className="mt-6 px-6 py-3 rounded-full bg-[#EF4444] text-white font-semibold"
      >
        Go to /record
      </Link>
    </div>
  );
}

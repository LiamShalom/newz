import { Link } from "react-router-dom";

export function EmptyState() {
  return (
    <main className="mx-auto max-w-[640px] px-5 pt-10">
      <h1 className="font-display uppercase text-[40px] leading-[0.95] tracking-[-0.005em] text-ink-primary">
        The feed is quiet
      </h1>
      <p className="mt-4 text-[15px] leading-[1.5] text-ink-secondary">
        Anonymous footage near you will appear here. Tap record to start one.
      </p>
      <Link
        to="/"
        className="inline-flex items-center mt-6 bg-accent-record text-white text-[13px] font-bold uppercase tracking-[0.08em] px-4 py-2.5 rounded-md"
      >
        Record a clip
      </Link>
    </main>
  );
}

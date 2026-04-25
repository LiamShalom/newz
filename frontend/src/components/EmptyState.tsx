import { Link } from "react-router-dom";

export function EmptyState() {
  return (
    <main className="mx-auto max-w-[640px] px-5 pt-8">
      <h1 className="font-display font-bold text-[36px] leading-[1.1] tracking-[-0.01em] text-ink-primary">
        The feed is quiet.
      </h1>
      <p className="mt-3 text-base leading-[1.5] text-ink-tertiary">
        Anonymous footage near you will appear here. Tap record to start one.
      </p>
      <Link
        to="/record"
        className="inline-block mt-6 text-base font-medium text-accent-link hover:underline"
      >
        Record a clip →
      </Link>
    </main>
  );
}

import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";
import { fallbackHeadline } from "../headlineFallback";

// Reading-list row: square thumbnail (left) with "WATCH VIDEO" overlay,
// uppercase relative-time + condensed headline (right). Native <video controls>
// is the tap-to-play affordance.
export function StoryTile({ clip, isLast }: { clip: Clip; isLast: boolean }) {
  const headline = clip.caption ?? fallbackHeadline(clip);
  return (
    <li className={isLast ? "py-5" : "py-5 border-b border-hairline"}>
      <div className="flex gap-4 items-start">
        <div className="relative flex-none w-28 h-28 overflow-hidden rounded-md bg-black">
          <video
            src={clip.url}
            controls
            muted
            playsInline
            preload="metadata"
            className="absolute inset-0 w-full h-full object-cover"
          />
          <span
            aria-hidden
            className="pointer-events-none absolute bottom-1.5 left-1.5 bg-black/70 backdrop-blur-sm text-white text-[9px] font-bold uppercase tracking-[0.08em] px-1.5 py-0.5 rounded"
          >
            Watch Video
          </span>
        </div>
        <div className="flex-1 min-w-0 pt-0.5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-tertiary tabular-nums">
            {clip.neighborhood ? `${clip.neighborhood} · ` : ""}
            {relativeTime(clip.created_at).toUpperCase()}
          </p>
          <h3 className="mt-2 font-display uppercase text-[20px] leading-[1.05] tracking-[-0.005em] text-ink-primary line-clamp-3">
            {headline}
          </h3>
        </div>
      </div>
    </li>
  );
}

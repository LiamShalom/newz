import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";
import { fallbackHeadline } from "../headlineFallback";

// Reading-list row: thumbnail-left / headline-right. Native <video controls>
// is the tap-to-play affordance (no custom poster overlay). preload="metadata"
// keeps the feed light on first load.
export function StoryTile({ clip, isLast }: { clip: Clip; isLast: boolean }) {
  const headline = clip.caption ?? fallbackHeadline(clip);
  const sourceCount = clip.source_count ?? 1;
  return (
    <li className={isLast ? "py-5" : "py-5 border-b border-hairline"}>
      <div className="flex gap-4 items-start">
        <video
          src={clip.url}
          controls
          muted
          playsInline
          preload="metadata"
          className="w-28 h-28 flex-none object-cover bg-black"
        />
        <div className="flex-1 min-w-0">
          {clip.neighborhood && (
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-tertiary">
              {clip.neighborhood}
            </p>
          )}
          <h3 className="mt-1 font-display font-medium text-[20px] leading-[1.25] tracking-[-0.005em] text-ink-primary line-clamp-3">
            {headline}
          </h3>
          <p className="mt-2 text-[13px] text-ink-tertiary tabular-nums">
            {sourceCount > 1 && <>{sourceCount} angles · </>}
            {relativeTime(clip.created_at)}
          </p>
        </div>
      </div>
    </li>
  );
}

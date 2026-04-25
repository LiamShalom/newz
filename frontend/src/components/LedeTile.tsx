import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";
import { fallbackHeadline } from "../headlineFallback";

// Hero / lede tile — first item in the reading list. Auto-plays muted per
// product spec. iOS Safari requires playsInline + muted for inline autoplay;
// without playsInline the video opens fullscreen and breaks the feed.
export function LedeTile({ clip }: { clip: Clip }) {
  const headline = clip.caption ?? fallbackHeadline(clip);
  const sourceCount = clip.source_count ?? 1;
  return (
    <article className="pt-6">
      <video
        src={clip.url}
        autoPlay
        muted
        playsInline
        preload="metadata"
        className="w-full aspect-video bg-black"
      />
      <div className="mt-3">
        {clip.neighborhood && (
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-tertiary">
            {clip.neighborhood}
          </p>
        )}
        <h2 className="mt-2 font-display font-bold text-[36px] leading-[1.1] tracking-[-0.01em] text-ink-primary">
          {headline}
        </h2>
        <p className="mt-2 text-[13px] text-ink-tertiary tabular-nums">
          {sourceCount > 1 && <>{sourceCount} angles · </>}
          {relativeTime(clip.created_at)}
        </p>
      </div>
    </article>
  );
}

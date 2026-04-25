import { Clock, Layers, MapPin } from "lucide-react";
import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";
import { fallbackHeadline } from "../headlineFallback";
import { LivePill } from "./LivePill";

// Hero / lede tile. Rounded video, LIVE pill overlay bottom-left, big
// condensed-uppercase headline (Anton), meta-icon row (source-count, location,
// time). Auto-plays muted inline; iOS Safari requires playsInline + muted.
export function LedeTile({ clip }: { clip: Clip }) {
  const headline = clip.caption ?? fallbackHeadline(clip);
  const sourceCount = clip.source_count ?? 1;
  return (
    <article className="pt-5">
      <div className="relative overflow-hidden rounded-2xl bg-black">
        <video
          src={clip.url}
          autoPlay
          muted
          playsInline
          preload="metadata"
          className="w-full aspect-[4/5] object-cover"
        />
        <div className="absolute bottom-4 left-4">
          <LivePill />
        </div>
      </div>
      <h2 className="mt-5 font-display uppercase text-[40px] leading-[0.95] tracking-[-0.005em] text-ink-primary">
        {headline}
      </h2>
      <div className="mt-5 flex items-center gap-5 text-ink-tertiary">
        {sourceCount > 1 && (
          <span className="flex items-center gap-1.5 text-[13px] tabular-nums">
            <Layers size={15} strokeWidth={2} />
            {sourceCount}
          </span>
        )}
        {clip.neighborhood && (
          <span className="flex items-center gap-1.5 text-[13px]">
            <MapPin size={15} strokeWidth={2} />
            {clip.neighborhood}
          </span>
        )}
        <span className="flex items-center gap-1.5 text-[13px] tabular-nums">
          <Clock size={15} strokeWidth={2} />
          {relativeTime(clip.created_at)}
        </span>
      </div>
    </article>
  );
}

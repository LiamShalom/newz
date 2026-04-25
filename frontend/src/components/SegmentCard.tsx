import { useState, useCallback } from "react";
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";
import { LivePill } from "./LivePill";

const FRESH_WINDOW_SEC = 600;

function deriveSummary(s: Segment, locationStr: string | null): string {
  const angles = s.source_count > 1 ? `Captured from ${s.source_count} angles` : "Single-angle footage";
  const where = locationStr ? ` near ${locationStr}` : "";
  return `${angles}${where}, ${relativeTime(s.created_at)}.`;
}

export function SegmentCard({
  segment,
  viewerLat,
  viewerLng,
  priority = false,
}: {
  segment: Segment & { url: string };
  viewerLat?: number;
  viewerLng?: number;
  priority?: boolean;
}) {
  const urls = segment.video_urls?.filter(Boolean) as string[] | undefined;
  const hasMultiple = urls && urls.length > 1;
  const [angleIdx, setAngleIdx] = useState(0);
  const currentUrl = hasMultiple ? urls[angleIdx] : segment.url;

  const handleEnded = useCallback(() => {
    if (!hasMultiple) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls]);

  const locationStr =
    viewerLat !== undefined &&
    viewerLng !== undefined &&
    segment.centroid_lat !== null &&
    segment.centroid_lng !== null
      ? distanceLabel(viewerLat, viewerLng, segment.centroid_lat, segment.centroid_lng)
      : segment.location;

  const isFresh = Date.now() / 1000 - segment.created_at < FRESH_WINDOW_SEC;
  const summary = deriveSummary(segment, locationStr ?? null);

  return (
    <article>
      <div className="relative overflow-hidden rounded-2xl bg-black aspect-[4/5]">
        <video
          key={currentUrl}
          src={currentUrl}
          autoPlay={priority}
          muted
          playsInline
          preload={priority ? "auto" : "metadata"}
          onEnded={handleEnded}
          className="absolute inset-0 w-full h-full object-cover"
        />

        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-2/3 pointer-events-none"
          style={{
            background:
              "linear-gradient(to top, rgba(0,0,0,0.92) 0%, rgba(0,0,0,0.55) 45%, rgba(0,0,0,0) 100%)",
          }}
        />

        {isFresh && (
          <div className="absolute bottom-4 left-4 z-10">
            <LivePill />
          </div>
        )}

        {hasMultiple && (
          <span className="absolute top-3 right-3 z-10 bg-black/60 text-white text-[11px] font-semibold tabular-nums tracking-wide px-2 py-0.5 rounded-full">
            {angleIdx + 1}/{urls.length}
          </span>
        )}

        <h2
          className={`absolute bottom-4 right-4 left-4 z-10 font-display uppercase text-[28px] sm:text-[32px] leading-[0.95] tracking-[-0.01em] text-white ${
            isFresh ? "pl-[68px]" : ""
          }`}
        >
          {segment.caption}
        </h2>
      </div>

      <p className="mt-3 text-[15px] leading-[1.45] text-ink-secondary">{summary}</p>
    </article>
  );
}

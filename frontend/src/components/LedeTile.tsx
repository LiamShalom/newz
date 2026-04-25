import { useState, useCallback } from "react";
import { Clock, Layers, MapPin } from "lucide-react";
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";
import { LivePill } from "./LivePill";

export function LedeTile({
  segment,
  viewerLat,
  viewerLng,
}: {
  segment: Segment & { url: string };
  viewerLat?: number;
  viewerLng?: number;
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

  return (
    <article className="pt-5">
      <div className="relative overflow-hidden rounded-2xl bg-black">
        <video
          key={currentUrl}
          src={currentUrl}
          autoPlay
          muted
          playsInline
          preload="metadata"
          onEnded={handleEnded}
          className="w-full aspect-[4/5] object-cover"
        />
        <div className="absolute bottom-4 left-4">
          <LivePill />
        </div>
        {hasMultiple && (
          <span className="absolute top-3 right-3 bg-black/60 text-white text-xs px-2 py-0.5 rounded-full">
            {angleIdx + 1}/{urls.length}
          </span>
        )}
      </div>
      <h2 className="mt-5 font-display uppercase text-[40px] leading-[0.95] tracking-[-0.005em] text-ink-primary">
        {segment.caption}
      </h2>
      <div className="mt-5 flex items-center gap-5 text-ink-tertiary">
        {segment.source_count > 1 && (
          <span className="flex items-center gap-1.5 text-[13px] tabular-nums">
            <Layers size={15} strokeWidth={2} />
            {segment.source_count}
          </span>
        )}
        {locationStr && (
          <span className="flex items-center gap-1.5 text-[13px]">
            <MapPin size={15} strokeWidth={2} />
            {locationStr}
          </span>
        )}
        <span className="flex items-center gap-1.5 text-[13px] tabular-nums">
          <Clock size={15} strokeWidth={2} />
          {relativeTime(segment.created_at)}
        </span>
      </div>
    </article>
  );
}

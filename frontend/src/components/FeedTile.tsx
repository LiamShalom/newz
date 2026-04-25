import { useState, useCallback } from "react";
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";

export function FeedTile({
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

  const currentUrl = hasMultiple
    ? `${urls[angleIdx]}`
    : segment.url;

  const handleEnded = useCallback(() => {
    if (!hasMultiple) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls]);

  const distanceStr =
    viewerLat !== undefined &&
    viewerLng !== undefined &&
    segment.centroid_lat !== null &&
    segment.centroid_lng !== null
      ? distanceLabel(viewerLat, viewerLng, segment.centroid_lat, segment.centroid_lng)
      : segment.location;

  return (
    <div className="bg-[#1A1A1A] border-y border-[#262626]">
      <div className="relative">
        <video
          key={currentUrl}
          src={currentUrl}
          autoPlay
          muted
          playsInline
          preload="metadata"
          onEnded={handleEnded}
          className="w-full max-h-[80vh] bg-black"
        />
        {hasMultiple && (
          <span className="absolute top-3 right-3 bg-black/60 text-white text-xs px-2 py-0.5 rounded-full">
            {angleIdx + 1}/{urls.length}
          </span>
        )}
      </div>
      <div className="px-4 py-3 space-y-2">
        <p className="text-white text-base leading-snug">{segment.caption}</p>
        <div className="flex justify-between items-center text-xs text-[#A3A3A3]">
          <span>
            {distanceStr}
            {" · "}
            {relativeTime(segment.created_at)}
          </span>
          <span className="bg-[#262626] px-2 py-0.5 rounded-full whitespace-nowrap">
            Compiled from {segment.source_count} angles
          </span>
        </div>
      </div>
    </div>
  );
}

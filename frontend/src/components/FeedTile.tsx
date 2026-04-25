import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";

/**
 * Segment card for the compiled-news feed (Phase 4, FED-03).
 *
 * iOS load-bearing attributes: autoPlay, muted, playsInline are all required.
 * - autoPlay: starts playback without user gesture (required for TikTok-style feed)
 * - muted: required for autoPlay to work in iOS Safari without user interaction
 * - playsInline: prevents iOS Safari from fullscreening the player
 * - loop: continuous autoplay
 *
 * Source count badge: "Compiled from N angles" — visible proof of multi-angle pipeline.
 * Distance overlay: human-readable ("2 blocks away") when GPS available; location string fallback.
 * Age overlay: relative time ("4 min ago").
 */
export function FeedTile({
  segment,
  viewerLat,
  viewerLng,
}: {
  segment: Segment & { url: string };
  viewerLat?: number;
  viewerLng?: number;
}) {
  const distanceStr =
    viewerLat !== undefined &&
    viewerLng !== undefined &&
    segment.centroid_lat !== null &&
    segment.centroid_lng !== null
      ? distanceLabel(viewerLat, viewerLng, segment.centroid_lat, segment.centroid_lng)
      : segment.location;

  return (
    <div className="bg-[#1A1A1A] border-y border-[#262626]">
      <video
        src={segment.url}
        autoPlay
        muted
        playsInline
        loop
        preload="metadata"
        className="w-full max-h-[80vh] bg-black"
      />
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

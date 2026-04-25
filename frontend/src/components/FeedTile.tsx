import type { Clip } from "../types";
import { relativeTime } from "../timeFormat";

/**
 * Single clip preview. <video controls playsInline muted> + relative timestamp.
 *
 * iOS load-bearing attributes (S3): playsInline + muted are mandatory. Without
 * playsInline iOS Safari fullscreens the player and breaks the feed UX.
 *
 * preload="metadata" lets the duration appear in controls without downloading
 * the whole clip on every feed render — protects judges' phone data on first load.
 *
 * clip.url is consumed verbatim from fetchFeed (already absolute after API_BASE
 * prefix), so this component is path-prefix agnostic — works whether the backend
 * serves clips at /media/, /clips/, or a CDN.
 */
export function FeedTile({ clip }: { clip: Clip }) {
  return (
    <div className="bg-[#1A1A1A] border-y border-[#262626]">
      <video
        src={clip.url}
        controls
        muted
        playsInline
        preload="metadata"
        className="w-full max-h-[80vh] bg-black"
      />
      <p className="px-4 py-2 text-sm text-[#A3A3A3]">
        {relativeTime(clip.created_at)}
      </p>
    </div>
  );
}

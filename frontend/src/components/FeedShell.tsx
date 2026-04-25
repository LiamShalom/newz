import type { Segment } from "../types";
import { FeedTile } from "./FeedTile";

/**
 * Vertical scrollable list of compiled segment FeedTiles (Phase 4, FED-02).
 * pb-32 (128px) keeps the FAB from overlapping the last tile.
 * viewerLat/viewerLng passed down for distance overlay in each tile.
 */
export function FeedShell({
  segments,
  viewerLat,
  viewerLng,
}: {
  segments: (Segment & { url: string })[];
  viewerLat?: number;
  viewerLng?: number;
}) {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] pb-32">
      {segments.map((s) => (
        <FeedTile key={s.id} segment={s} viewerLat={viewerLat} viewerLng={viewerLng} />
      ))}
    </div>
  );
}

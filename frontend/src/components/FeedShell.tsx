import type { Clip } from "../types";
import { FeedTile } from "./FeedTile";

/**
 * Vertical scrollable list of FeedTiles (D-08 throwaway). Full-width tiles on
 * mobile. pb-32 (128px) keeps the FAB from overlapping the last tile.
 */
export function FeedShell({ clips }: { clips: Clip[] }) {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] pb-32">
      {clips.map((c) => (
        <FeedTile key={c.id} clip={c} />
      ))}
    </div>
  );
}

import type { Segment } from "../types";
import { LedeTile } from "./LedeTile";
import { StoryTile } from "./StoryTile";

// Hero pick: largest cluster wins; ties broken by backend ordering (newest
// first). Pre-Phase-4 source_count is undefined on every segment, so the sort
// collapses to stable order = newest first.
function pickHero(segments: (Segment & { url: string })[]): {
  hero: Segment & { url: string };
  rest: (Segment & { url: string })[];
} {
  const sorted = [...segments].sort(
    (a, b) => (b.source_count ?? 1) - (a.source_count ?? 1),
  );
  const hero = sorted[0];
  const rest = segments.filter((s) => s.id !== hero.id);
  return { hero, rest };
}

export function FeedShell({
  segments,
  viewerLat,
  viewerLng,
}: {
  segments: (Segment & { url: string })[];
  viewerLat?: number;
  viewerLng?: number;
}) {
  const { hero, rest } = pickHero(segments);
  return (
    <main className="mx-auto max-w-[640px] px-5 pb-32">
      <LedeTile segment={hero} viewerLat={viewerLat} viewerLng={viewerLng} />
      {rest.length > 0 && (
        <ol className="mt-6 border-t border-hairline">
          {rest.map((s, i) => (
            <StoryTile key={s.id} segment={s} isLast={i === rest.length - 1} />
          ))}
        </ol>
      )}
    </main>
  );
}

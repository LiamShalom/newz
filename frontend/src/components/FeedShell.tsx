import type { Clip } from "../types";
import { LedeTile } from "./LedeTile";
import { StoryTile } from "./StoryTile";

// Hero pick: largest cluster wins; ties broken by backend ordering (newest
// first). Pre-Phase-4 source_count is undefined on every clip, so the sort
// collapses to stable order = newest first.
function pickHero(clips: Clip[]): { hero: Clip; rest: Clip[] } {
  const sorted = [...clips].sort(
    (a, b) => (b.source_count ?? 1) - (a.source_count ?? 1),
  );
  const hero = sorted[0];
  const rest = clips.filter((c) => c.id !== hero.id);
  return { hero, rest };
}

export function FeedShell({ clips }: { clips: Clip[] }) {
  const { hero, rest } = pickHero(clips);
  return (
    <main className="mx-auto max-w-[640px] px-5 pb-32">
      <LedeTile clip={hero} />
      {rest.length > 0 && (
        <ol className="mt-6 border-t border-hairline">
          {rest.map((c, i) => (
            <StoryTile key={c.id} clip={c} isLast={i === rest.length - 1} />
          ))}
        </ol>
      )}
    </main>
  );
}

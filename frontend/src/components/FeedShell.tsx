import type { Segment } from "../types";
import { SegmentCard } from "./SegmentCard";

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
    <main className="mx-auto max-w-[640px] px-5 pb-32 pt-5">
      <ol className="space-y-10">
        {segments.map((s, i) => (
          <li key={s.id}>
            <SegmentCard
              segment={s}
              viewerLat={viewerLat}
              viewerLng={viewerLng}
              priority={i === 0}
            />
          </li>
        ))}
      </ol>
    </main>
  );
}

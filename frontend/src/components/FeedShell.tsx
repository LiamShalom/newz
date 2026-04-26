import { useRef } from "react";
import type { Segment } from "../types";
import { SegmentCard } from "./SegmentCard";
import { useMostVisibleIndex } from "../hooks/useMostVisibleIndex";

export function FeedShell({
  segments,
  viewerLat,
  viewerLng,
}: {
  segments: (Segment & { url: string })[];
  viewerLat?: number;
  viewerLng?: number;
}) {
  const itemRefs = useRef<(HTMLLIElement | null)[]>([]);
  const activeIdx = useMostVisibleIndex(itemRefs, segments.length);
  // Until the observer reports anything, default to the top card so the
  // feed isn't silent on first paint.
  const resolvedActive = activeIdx === -1 ? 0 : activeIdx;

  return (
    <main
      className="mx-auto max-w-[640px] px-5 pt-5"
      style={{ paddingBottom: "calc(80px + env(safe-area-inset-bottom))" }}
    >
      <ol className="space-y-10">
        {segments.map((s, i) => (
          <li
            key={s.id}
            ref={(el) => {
              itemRefs.current[i] = el;
            }}
          >
            <SegmentCard
              segment={s}
              viewerLat={viewerLat}
              viewerLng={viewerLng}
              active={i === resolvedActive}
            />
          </li>
        ))}
      </ol>
    </main>
  );
}

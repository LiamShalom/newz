import { useEffect, useRef, useState, type RefObject } from "react";
import { pickMaxRatioIndex } from "./pickMaxRatioIndex";

/**
 * Watches a fixed-length array of element refs and returns the index
 * of the one currently with the highest IntersectionObserver ratio.
 *
 * Returns -1 when nothing is visible (e.g. before first paint).
 *
 * `refs.current` is read on every observer callback, so callers
 * should populate it via `ref={(el) => { refs.current[i] = el; }}`.
 */
export function useMostVisibleIndex(
  refs: RefObject<(HTMLElement | null)[]>,
  count: number,
): number {
  const [activeIdx, setActiveIdx] = useState(-1);
  const ratiosRef = useRef<number[]>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    if (count === 0) {
      setActiveIdx(-1);
      return;
    }

    ratiosRef.current = new Array(count).fill(0);

    const observer = new IntersectionObserver(
      (entries) => {
        const list = refs.current ?? [];
        for (const entry of entries) {
          const idx = list.indexOf(entry.target as HTMLElement);
          if (idx !== -1) {
            ratiosRef.current[idx] = entry.intersectionRatio;
          }
        }
        setActiveIdx(pickMaxRatioIndex(ratiosRef.current));
      },
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    );

    const list = refs.current ?? [];
    for (const el of list) {
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [count, refs]);

  return activeIdx;
}

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchSegments } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import { useEventSource } from "../hooks/useEventSource";
import type { Segment, ServerEvent } from "../types";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { RecordFAB } from "../components/RecordFAB";

/**
 * Feed view — Phase 4 upgrade.
 *
 * Replaces Clip[] with Segment[] (compiled segments from the AI pipeline).
 * Replaces polling with native EventSource (RTM-01..03):
 *   - useEventSource opens GET /events on mount (one connection per tab)
 *   - On segment_published event → refetchFeed() (RTM-03: <1s re-render)
 *
 * Still refetches on location.key change (navigate-back-from-camera trigger,
 * Phase 1 D-08) — this is a navigation refresh, not a polling timer.
 *
 * GPS coords fetched once on mount and stored in a ref for proximity sort (FED-01).
 * FAB remains visible on every feed view (FED-04).
 *
 * Out of scope: status banner (WOW-03), snap animation (WOW-01), streaming tokens (WOW-02).
 */
export function Feed() {
  const [segments, setSegments] = useState<(Segment & { url: string })[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();
  const coordsRef = useRef<{ lat: number; lng: number } | undefined>(undefined);

  // Fetch GPS once on mount — stored in ref so fetchFeed closure sees it without
  // re-running the effect on coord change.
  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        coordsRef.current = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      },
      () => {
        /* GPS unavailable — feed falls back to recency sort */
      },
      { timeout: 5000, enableHighAccuracy: false },
    );
    // getCurrentPosition does not return an ID — no cleanup needed
  }, []);

  const refetchFeed = useCallback(async () => {
    const coords = coordsRef.current;
    try {
      const next = await fetchSegments(coords?.lat, coords?.lng);
      setSegments(next);
    } catch {
      // network / backend down — keep current state
    }
  }, []);

  // Flush upload queue + initial fetch on mount and on navigate-back (D-08)
  useEffect(() => {
    // ING-06: ensure anonymous session UUID exists
    getOrCreateSessionId();

    let cancelled = false;
    (async () => {
      await flushUploadQueue().catch(() => {});
      try {
        const coords = coordsRef.current;
        const next = await fetchSegments(coords?.lat, coords?.lng);
        if (!cancelled) setSegments(next);
      } catch {
        // show empty state, no error UI
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [location.key]);

  // RTM-01/RTM-03: subscribe to pipeline events; refetch on new segment
  useEventSource((ev: ServerEvent) => {
    if (ev.type === "segment_published") {
      void refetchFeed();
    }
  });

  if (!loaded) {
    return <div className="min-h-[100dvh] bg-[#0A0A0A]" />;
  }

  return (
    <>
      {segments.length === 0 ? (
        <EmptyState />
      ) : (
        <FeedShell
          segments={segments}
          viewerLat={coordsRef.current?.lat}
          viewerLng={coordsRef.current?.lng}
        />
      )}
      <RecordFAB />
    </>
  );
}

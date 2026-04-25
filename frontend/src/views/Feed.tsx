import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchFeed } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import type { Clip } from "../types";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { RecordFAB } from "../components/RecordFAB";

/**
 * Real Feed view — replaces the Plan 01 stub. Fetches /feed on mount + on
 * every navigate-back-from-camera (location.key change, per CONTEXT D-08).
 * No polling timer (CONTEXT D-08); SSE lands in Phase 4 (RTM-01..03).
 *
 * Side effects on mount:
 *   1. ING-06: ensures anonymous session UUID exists in localStorage.
 *   2. CAP-09: flushes any failed uploads queued from a prior session.
 *   3. Refetches /feed.
 *
 * No skeleton (UI-SPEC interaction contract item 1) — show black background
 * until first fetch resolves.
 */
export function Feed() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();

  useEffect(() => {
    // ING-06: ensure anonymous session UUID exists on first feed load (no-op
    // on subsequent visits).
    getOrCreateSessionId();

    let cancelled = false;
    (async () => {
      // CAP-09: flush any queued failed uploads before refetching. Swallow
      // errors silently — Phase 1 has no toast UI for the queued case.
      await flushUploadQueue().catch(() => {
        /* swallow */
      });
      try {
        const next = await fetchFeed();
        if (!cancelled) setClips(next);
      } catch {
        // network / backend down — show empty state, no error UI in Phase 1
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // location.key changes on every navigation, even back-to-the-same-path —
    // satisfies D-08 "navigate-back-from-camera triggers a refetch."
  }, [location.key]);

  if (!loaded) {
    return <div className="min-h-[100dvh] bg-[#0A0A0A]" />;
  }

  return (
    <>
      {clips.length === 0 ? <EmptyState /> : <FeedShell clips={clips} />}
      <RecordFAB />
    </>
  );
}

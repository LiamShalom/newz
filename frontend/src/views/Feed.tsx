import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchFeed } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import type { Clip } from "../types";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { Masthead } from "../components/Masthead";
import { RecordFAB } from "../components/RecordFAB";

/**
 * Home page. Fetches /feed on mount + on every navigate-back-from-camera
 * (location.key changes on every navigation, even back-to-the-same-path —
 * satisfies D-08 "navigate-back-from-camera triggers a refetch").
 *
 * Side effects on mount:
 *   1. ING-06: ensures anonymous session UUID exists in localStorage.
 *   2. CAP-09: flushes any failed uploads queued from a prior session.
 *   3. Refetches /feed.
 */
export function Feed() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();

  useEffect(() => {
    getOrCreateSessionId();

    let cancelled = false;
    (async () => {
      // CAP-09: flush queued failed uploads before refetching. Swallow errors —
      // Phase 1 has no toast UI for the queued case.
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
  }, [location.key]);

  return (
    <>
      <Masthead />
      {!loaded ? (
        <div className="min-h-[calc(100dvh-52px)]" />
      ) : clips.length === 0 ? (
        <EmptyState />
      ) : (
        <FeedShell clips={clips} />
      )}
      <RecordFAB />
    </>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchSegments } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import { useEventSource } from "../hooks/useEventSource";
import { dispatchCommentAdded } from "../commentsBus";
import { checkPermission } from "../lib/permissionsCheck";
import type { Segment, ServerEvent } from "../types";
import { BottomTabBar } from "../components/BottomTabBar";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { Masthead } from "../components/Masthead";
import { UploadProgressBar } from "../components/UploadProgressBar";

export function Feed() {
  const [segments, setSegments] = useState<(Segment & { url: string | null })[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();
  const coordsRef = useRef<{ lat: number; lng: number } | undefined>(undefined);

  useEffect(() => {
    if (!navigator.geolocation) return;
    let cancelled = false;
    void (async () => {
      // Soft-check via Permissions API before firing getCurrentPosition.
      // - granted: safe to read coords without surfacing a dialog
      // - denied:  skip silently; feed falls back to non-coords fetch
      // - prompt / unknown: fire and let the browser decide. Recorder is the
      //   primary gesture-anchored prompt site, so by the time a returning
      //   user lands on the feed this is usually 'granted'.
      const state = await checkPermission("geolocation");
      if (cancelled || state === "denied") return;
      if (state !== "granted" && state !== "prompt" && state !== "unknown") return;
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          coordsRef.current = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        },
        () => {},
        { timeout: 5000, enableHighAccuracy: false },
      );
    })();
    return () => {
      cancelled = true;
    };
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

  useEffect(() => {
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
    return () => { cancelled = true; };
  }, [location.key]);

  useEventSource((ev: ServerEvent) => {
    if (ev.type === "segment_published" || ev.type === "cluster_assigned") {
      void refetchFeed();
    } else if (ev.type === "comment_added") {
      dispatchCommentAdded(ev.segment_id, ev.comment);
    }
  });

  return (
    <>
      <Masthead />
      <UploadProgressBar />
      {!loaded ? (
        <div className="min-h-[calc(100dvh-52px)]" />
      ) : segments.length === 0 ? (
        <EmptyState />
      ) : (
        <FeedShell segments={segments} />
      )}
      <BottomTabBar />
    </>
  );
}

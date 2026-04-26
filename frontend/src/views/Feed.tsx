import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchSegments } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import { useEventSource } from "../hooks/useEventSource";
import type { Segment, ServerEvent } from "../types";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { Masthead } from "../components/Masthead";
import { RecordFAB } from "../components/RecordFAB";
import { UploadFAB } from "../components/UploadFAB";

export function Feed() {
  const [segments, setSegments] = useState<(Segment & { url: string })[]>([]);
  const [loaded, setLoaded] = useState(false);
  const location = useLocation();
  const coordsRef = useRef<{ lat: number; lng: number } | undefined>(undefined);

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        coordsRef.current = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      },
      () => {},
      { timeout: 5000, enableHighAccuracy: false },
    );
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
    }
  });

  return (
    <>
      <Masthead />
      {!loaded ? (
        <div className="min-h-[calc(100dvh-52px)]" />
      ) : segments.length === 0 ? (
        <EmptyState />
      ) : (
        <FeedShell
          segments={segments}
          viewerLat={coordsRef.current?.lat}
          viewerLng={coordsRef.current?.lng}
        />
      )}
      <RecordFAB />
      <UploadFAB
        fallbackLat={coordsRef.current?.lat}
        fallbackLng={coordsRef.current?.lng}
      />
    </>
  );
}

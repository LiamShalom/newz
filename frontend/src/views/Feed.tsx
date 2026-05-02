import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchSegments } from "../api";
import { getOrCreateSessionId } from "../session";
import { flushUploadQueue } from "../uploadQueue";
import { useEventSource } from "../hooks/useEventSource";
import { dispatchCommentAdded } from "../commentsBus";
import { applyNearbyFilter, RADIUS_FAR_M } from "../feedFilter";
import type { FeedTab, Segment, ServerEvent } from "../types";
import { BottomTabBar } from "../components/BottomTabBar";
import { EmptyState } from "../components/EmptyState";
import { FeedShell } from "../components/FeedShell";
import { FeedTabs } from "../components/FeedTabs";
import { Masthead } from "../components/Masthead";

const TAB_STORAGE_KEY = "feed_tab";
const BANNER_DISMISSED_KEY = "feed_nearby_banner_dismissed";

function readInitialTab(): FeedTab {
  try {
    const raw = sessionStorage.getItem(TAB_STORAGE_KEY);
    if (raw === "nearby" || raw === "global") return raw;
  } catch {
    // sessionStorage may throw in private browsing — silently default.
  }
  return "global";
}

export function Feed() {
  const [segments, setSegments] = useState<(Segment & { url: string | null })[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<FeedTab>(readInitialTab);
  const [coords, setCoords] = useState<{ lat: number; lng: number } | undefined>(undefined);
  const [bannerDismissed, setBannerDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(BANNER_DISMISSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const location = useLocation();
  // Mirror state in a ref so the SSE callback (stable across renders) can read
  // the latest coords without forcing the EventSource to reconnect.
  const coordsRef = useRef<{ lat: number; lng: number } | undefined>(undefined);
  coordsRef.current = coords;

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
      },
      () => {
        // Permission denied / unavailable / timeout — Nearby tab stays disabled.
      },
      { timeout: 5000, enableHighAccuracy: false },
    );
  }, []);

  const refetchFeed = useCallback(async () => {
    try {
      const next = await fetchSegments();
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
        const next = await fetchSegments();
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

  const nearbyEnabled = coords !== undefined;

  // If the persisted tab is "nearby" but location is unavailable, fall back
  // to global without persisting (so the choice is restored if location
  // later becomes available within the session).
  const effectiveTab: FeedTab = tab === "nearby" && !nearbyEnabled ? "global" : tab;

  const filterResult = useMemo(() => {
    if (effectiveTab !== "nearby" || !coords) {
      return { segments, effectiveRadiusM: -1 as const };
    }
    return applyNearbyFilter(segments, coords.lat, coords.lng);
  }, [effectiveTab, segments, coords]);

  const displayedSegments = filterResult.segments;
  const showFallbackBanner =
    effectiveTab === "nearby" && filterResult.effectiveRadiusM === null && !bannerDismissed;

  const handleTabChange = useCallback((next: FeedTab) => {
    setTab(next);
    try {
      sessionStorage.setItem(TAB_STORAGE_KEY, next);
    } catch {
      // private browsing — ignore
    }
  }, []);

  const handleDismissBanner = useCallback(() => {
    setBannerDismissed(true);
    try {
      sessionStorage.setItem(BANNER_DISMISSED_KEY, "1");
    } catch {
      // ignore
    }
  }, []);

  return (
    <>
      <Masthead />
      {loaded && (
        <FeedTabs active={effectiveTab} onChange={handleTabChange} nearbyEnabled={nearbyEnabled} />
      )}
      {!loaded ? (
        <div className="min-h-[calc(100dvh-52px)]" />
      ) : segments.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          {showFallbackBanner && (
            <div className="mx-auto max-w-[640px] px-5 pt-4">
              <div className="flex items-center justify-between gap-3 rounded-lg bg-gradient-to-r from-coral-light/15 to-coral/15 border border-coral/30 px-4 py-2.5 text-[13px] text-ink-primary">
                <span>
                  No clips within {Math.round(RADIUS_FAR_M / 1000)} km — showing global.
                </span>
                <button
                  type="button"
                  onClick={handleDismissBanner}
                  aria-label="Dismiss"
                  className="text-ink-primary/60 hover:text-ink-primary text-[15px] leading-none"
                >
                  &times;
                </button>
              </div>
            </div>
          )}
          <FeedShell
            segments={displayedSegments}
            viewerLat={coords?.lat}
            viewerLng={coords?.lng}
          />
        </>
      )}
      <BottomTabBar />
    </>
  );
}

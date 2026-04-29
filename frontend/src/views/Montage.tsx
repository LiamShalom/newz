import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchComments, fetchSegment } from "../api";
import {
  dispatchCommentAdded,
  subscribeToCommentsFor,
} from "../commentsBus";
import { useEventSource } from "../hooks/useEventSource";
import type { Comment, Segment, ServerEvent } from "../types";
import { BottomTabBar } from "../components/BottomTabBar";
import { CommentComposer } from "../components/CommentComposer";
import { CommentList } from "../components/CommentList";
import { LivePill } from "../components/LivePill";
import { Masthead } from "../components/Masthead";
import { relativeTime } from "../timeFormat";

type LoadedSegment = Segment & { url: string | null };

// Standalone page rendered when a user lands on a shared link
// (`/m/:segmentId`). Self-contained: opens its own SSE connection (Feed isn't
// mounted here) and inlines the comments instead of using the popup/sheet flow.
export function Montage() {
  const { segmentId } = useParams<{ segmentId: string }>();
  const [segment, setSegment] = useState<LoadedSegment | null>(null);
  const [error, setError] = useState<"not_found" | "network" | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoaded, setCommentsLoaded] = useState(false);

  const [angleIdx, setAngleIdx] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Initial fetch of the segment + its comments. Two parallel requests.
  useEffect(() => {
    if (!segmentId) return;
    let cancelled = false;
    setError(null);
    setSegment(null);
    setComments([]);
    setCommentsLoaded(false);
    setAngleIdx(0);

    fetchSegment(segmentId)
      .then((s) => {
        if (!cancelled) setSegment(s);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message.endsWith("404") ? "not_found" : "network");
      });

    fetchComments(segmentId)
      .then((cs) => {
        if (!cancelled) {
          setComments(cs);
          setCommentsLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setCommentsLoaded(true);
      });

    return () => {
      cancelled = true;
    };
  }, [segmentId]);

  // Subscribe to live comment_added events for this segment via the bus.
  useEffect(() => {
    if (!segmentId) return;
    return subscribeToCommentsFor(segmentId, (c) => {
      setComments((prev) =>
        prev.some((x) => x.id === c.id) ? prev : [c, ...prev],
      );
    });
  }, [segmentId]);

  // Feed.tsx normally owns the SSE connection — mount our own here since the
  // user landed directly on this route (Feed isn't rendered).
  useEventSource((ev: ServerEvent) => {
    if (ev.type === "comment_added") {
      dispatchCommentAdded(ev.segment_id, ev.comment);
    }
  });

  const urls = segment?.video_urls?.filter(Boolean) as string[] | undefined;
  const hasMultiple = urls && urls.length > 1;
  const currentUrl = hasMultiple ? urls[angleIdx] : segment?.url ?? null;

  const handleEnded = useCallback(() => {
    if (!hasMultiple || !urls) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls]);

  // Auto-play when the segment loads. iOS Safari may reject without a gesture;
  // swallow rejection so a stale promise doesn't spam the console.
  useEffect(() => {
    const el = videoRef.current;
    if (!el || !currentUrl) return;
    const p = el.play();
    if (p && typeof p.catch === "function") p.catch(() => {});
  }, [currentUrl]);

  if (!segmentId) {
    return <NotFound />;
  }

  return (
    <>
      <Masthead />
      <main className="mx-auto max-w-[640px] px-4 pb-24">
        {error === "not_found" ? (
          <NotFound />
        ) : !segment ? (
          <div className="min-h-[60dvh]" aria-label="loading montage" />
        ) : (
          <>
            <article className="relative">
              <div className="relative overflow-hidden rounded-2xl bg-surface aspect-[4/5]">
                {currentUrl ? (
                  <video
                    ref={videoRef}
                    key={currentUrl}
                    src={currentUrl}
                    muted
                    playsInline
                    controls
                    preload="auto"
                    onEnded={handleEnded}
                    className="absolute inset-0 w-full h-full object-cover"
                  />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center text-ink-secondary text-sm">
                    Compiling…
                  </div>
                )}

                {hasMultiple && urls && (
                  <div className="absolute top-3 left-3 right-3 z-10 flex gap-1.5 pointer-events-none">
                    {urls.map((_, i) => (
                      <span
                        key={i}
                        className={`flex-1 h-[3px] rounded-full transition-colors ${
                          i === angleIdx ? "bg-white/75" : "bg-white/30"
                        }`}
                      />
                    ))}
                  </div>
                )}

                <div className="absolute bottom-3 left-4 z-10">
                  <LivePill />
                </div>
              </div>

              <h1 className="mt-4 font-display uppercase text-[40px] sm:text-[48px] leading-[0.92] tracking-[-0.005em] text-ink-primary">
                {segment.title || segment.caption}
              </h1>

              <p className="mt-3 text-[13px] font-semibold leading-[1.35] bg-gradient-to-r from-coral-light to-coral bg-clip-text text-transparent">
                {segment.source_count > 1
                  ? `Captured from ${segment.source_count} angles`
                  : "Single-angle footage"}
                {segment.location ? ` near ${segment.location}` : ""}
                , {relativeTime(segment.created_at)}.
              </p>

              <p className="mt-3 text-[13px] leading-[1.5] text-ink-primary">
                {segment.caption}
              </p>
            </article>

            <section
              aria-label="comments"
              className="mt-8 rounded-2xl border border-hairline bg-surface"
            >
              <header className="flex items-center justify-between border-b border-hairline px-4 py-3">
                <h2 className="text-[15px] font-semibold text-ink-primary">
                  {commentsLoaded
                    ? comments.length === 0
                      ? "comments"
                      : `${comments.length} comment${comments.length === 1 ? "" : "s"}`
                    : "comments"}
                </h2>
              </header>

              {commentsLoaded ? (
                <CommentList comments={comments} />
              ) : (
                <div className="grid place-items-center px-4 py-10 text-sm text-ink-secondary">
                  loading…
                </div>
              )}

              <CommentComposer
                segmentId={segmentId}
                onPosted={(c) =>
                  setComments((prev) =>
                    prev.some((x) => x.id === c.id) ? prev : [c, ...prev],
                  )
                }
              />
            </section>
          </>
        )}
      </main>
      <BottomTabBar />
    </>
  );
}

function NotFound() {
  return (
    <main className="mx-auto max-w-[640px] px-5 pt-10">
      <h1 className="font-display uppercase text-[40px] leading-[0.95] tracking-[-0.005em] text-ink-primary">
        Montage not found
      </h1>
      <p className="mt-4 text-[15px] leading-[1.5] text-ink-primary">
        This share link is broken or the montage was removed.
      </p>
      <Link
        to="/feed"
        className="inline-flex items-center mt-6 bg-gradient-to-r from-coral-light to-coral text-white text-[13px] font-bold uppercase tracking-[0.08em] px-4 py-2.5 rounded-md"
      >
        Open the feed
      </Link>
    </main>
  );
}

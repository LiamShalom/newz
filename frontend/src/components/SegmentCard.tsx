import { useState, useCallback, useEffect, useRef } from "react";
import { MessageCircle } from "lucide-react";

/** Fizz-style share arrow: a clean curved stem ending in a chevron
 *  arrowhead pointing up-right. Uniform stroke (width 2), round caps and
 *  joins so it reads at the same visual weight as Lucide's MessageCircle. */
function ShareArrowIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
      className={className}
    >
      <path d="M4 20c1-7 6-12 14-13" />
      <path d="M13 3l5 4-5 4" />
    </svg>
  );
}
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";
import { LivePill } from "./LivePill";
import { Comments } from "./Comments";
import { API_BASE, fetchComments } from "../api";
import { subscribeToCommentsFor } from "../commentsBus";

const CAN_SHARE =
  typeof navigator !== "undefined" && typeof navigator.share === "function";

function deriveSummary(s: Segment, locationStr: string | null): string {
  const angles = s.source_count > 1 ? `Captured from ${s.source_count} angles` : "Single-angle footage";
  const where = locationStr ? ` near ${locationStr}` : "";
  return `${angles}${where}, ${relativeTime(s.created_at)}.`;
}

export function SegmentCard({
  segment,
  viewerLat,
  viewerLng,
  active = false,
}: {
  segment: Segment & { url: string | null };
  viewerLat?: number;
  viewerLng?: number;
  /** True when this card is the most-visible one in the viewport. */
  active?: boolean;
}) {
  const urls = segment.video_urls?.filter(Boolean) as string[] | undefined;
  const hasMultiple = urls && urls.length > 1;
  const [angleIdx, setAngleIdx] = useState(0);
  const currentUrl = hasMultiple ? urls[angleIdx] : segment.url;
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const handleEnded = useCallback(() => {
    if (!hasMultiple) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls]);

  // iOS Safari may reject play() without a user gesture in some states —
  // swallow the rejection so a stale promise doesn't spam the console.
  useEffect(() => {
    const el = videoRef.current;
    if (!el || !currentUrl) return;
    if (active) {
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } else {
      el.pause();
    }
  }, [active, currentUrl]);

  const locationStr =
    viewerLat !== undefined &&
    viewerLng !== undefined &&
    segment.centroid_lat !== null &&
    segment.centroid_lng !== null
      ? distanceLabel(viewerLat, viewerLng, segment.centroid_lat, segment.centroid_lng)
      : segment.location;

  const summary = deriveSummary(segment, locationStr ?? null);

  const [commentsOpen, setCommentsOpen] = useState(false);
  const [commentCount, setCommentCount] = useState<number | undefined>(undefined);

  const handleShare = useCallback(async () => {
    // Backend /m/<id> serves OG tags + redirects browsers to FRONTEND_URL/m/<id>.
    // We share the backend URL so iMessage/Twitter unfurlers see the meta tags;
    // humans following the link land on the SPA route via the JS redirect.
    const url = `${API_BASE}/m/${encodeURIComponent(segment.id)}`;
    const title = segment.title || "Newz montage";
    const text = segment.caption || "";
    try {
      await navigator.share({ title, text, url });
    } catch (err) {
      // User cancelled — AbortError is expected, swallow it. Other errors are
      // rare (permissions denied) and we have no error UI for them at pilot.
      if ((err as DOMException)?.name !== "AbortError") {
        // eslint-disable-next-line no-console
        console.warn("share failed:", err);
      }
    }
  }, [segment.id, segment.title, segment.caption]);

  // Lazy: fetch the count once per card. Pilot scale; revisit if N gets large.
  useEffect(() => {
    let cancelled = false;
    fetchComments(segment.id)
      .then((cs) => {
        if (!cancelled) setCommentCount(cs.length);
      })
      .catch(() => {
        // Network blip — leave undefined so the badge stays hidden, no error UI.
      });
    return () => {
      cancelled = true;
    };
  }, [segment.id]);

  // Live SSE increments — works whether the sheet is open or not.
  useEffect(() => {
    return subscribeToCommentsFor(segment.id, () => {
      setCommentCount((c) => (c ?? 0) + 1);
    });
  }, [segment.id]);

  return (
    <article className="relative">
      <div className="relative overflow-hidden rounded-2xl bg-surface aspect-[4/5]">
        {currentUrl ? (
          <video
            ref={videoRef}
            key={currentUrl}
            src={currentUrl}
            muted
            playsInline
            preload={active ? "auto" : "metadata"}
            onEnded={handleEnded}
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-ink-secondary text-sm">
            Compiling…
          </div>
        )}

        <div
          aria-hidden
          className="absolute inset-x-0 top-0 h-1/3 pointer-events-none"
          style={{
            background:
              "linear-gradient(to bottom, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0) 100%)",
          }}
        />

        <div
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-1/2 pointer-events-none"
          style={{ background: "var(--gradient-fade-bottom)" }}
        />

        {hasMultiple && (
          <>
            <button
              type="button"
              onClick={() =>
                setAngleIdx((i) => (i - 1 + urls.length) % urls.length)
              }
              aria-label="Previous angle"
              className="absolute top-0 bottom-0 left-0 w-1/2 z-[5]"
            />
            <button
              type="button"
              onClick={() => setAngleIdx((i) => (i + 1) % urls.length)}
              aria-label="Next angle"
              className="absolute top-0 bottom-0 right-0 w-1/2 z-[5]"
            />

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
          </>
        )}

        <div className="absolute bottom-3 dark:bottom-14 left-4 z-10">
          <LivePill />
        </div>
      </div>

      <h2
        className="relative z-20 mt-3 dark:-mt-8 dark:sm:-mt-10 px-4 font-display uppercase text-[40px] sm:text-[48px] leading-[0.92] tracking-[-0.005em] text-ink-primary"
      >
        {segment.title || segment.caption}
      </h2>

      <p className="mt-3 text-[13px] font-semibold leading-[1.35] px-4 bg-gradient-to-r from-coral-light to-coral bg-clip-text text-transparent">
        {summary}
      </p>

      <p className="mt-3 px-4 text-[13px] leading-[1.5] text-ink-primary">
        {segment.caption}
      </p>

      <div className="mt-4 px-4 flex items-center gap-4">
        <button
          type="button"
          onClick={() => setCommentsOpen(true)}
          aria-label="open comments"
          className="inline-flex items-center gap-1.5 text-ink-primary"
        >
          <MessageCircle className="h-6 w-6" />
          {commentCount !== undefined && (
            <span className="text-[13px]">{commentCount}</span>
          )}
        </button>
        {CAN_SHARE && (
          <button
            type="button"
            onClick={handleShare}
            aria-label="share"
            className="inline-flex items-center text-ink-primary"
          >
            <ShareArrowIcon className="h-6 w-6" />
          </button>
        )}
      </div>

      <Comments
        segmentId={segment.id}
        videoUrls={segment.video_urls ?? (currentUrl ? [currentUrl] : null)}
        open={commentsOpen}
        onClose={() => setCommentsOpen(false)}
      />
    </article>
  );
}

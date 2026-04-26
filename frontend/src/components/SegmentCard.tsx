import { useState, useCallback, useEffect, useRef } from "react";
import type { Segment } from "../types";
import { relativeTime } from "../timeFormat";
import { distanceLabel } from "../distance";
import { LivePill } from "./LivePill";

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
        {segment.caption}
      </h2>

      <p className="mt-3 text-[13px] font-semibold leading-[1.35] px-4 bg-gradient-to-r from-coral-light to-coral bg-clip-text text-transparent">
        {summary}
      </p>

      <p className="mt-3 px-4 text-[13px] leading-[1.5] text-ink-primary">
        Two contributors uploaded footage from adjacent vantage points within a 90-second window.
        Visual and audio analysis confirms a shared scene; angles complement rather than duplicate.
        No vehicles or additional bystanders detected. Compiled into a single segment with
        temporal alignment across sources.
      </p>
    </article>
  );
}

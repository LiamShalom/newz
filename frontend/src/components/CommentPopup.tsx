import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, Volume2, VolumeX } from "lucide-react";
import { fetchComments } from "../api";
import { subscribeToCommentsFor } from "../commentsBus";
import { useMuted } from "../muteBus";
import type { Comment } from "../types";
import { CommentList } from "./CommentList";
import { CommentComposer } from "./CommentComposer";

/**
 * Desktop modal variant of the comment UI.
 *
 * Instagram-style: portrait video left at full popup height, comments column
 * right at a fixed width. Video reuses the feed card's chrome — no controls,
 * no duration bar, autoplay+muted, multi-angle bars on top, tap-left/right
 * to nav angles, auto-advance on `ended`.
 */
export function CommentPopup({
  segmentId,
  videoUrls,
  open,
  onClose,
}: {
  segmentId: string;
  videoUrls: (string | null)[] | null;
  open: boolean;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loaded, setLoaded] = useState(false);

  const urls = (videoUrls?.filter(Boolean) as string[] | undefined) ?? [];
  const hasMultiple = urls.length > 1;
  const [angleIdx, setAngleIdx] = useState(0);
  const currentUrl = urls[angleIdx] ?? null;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [muted, setMuted] = useMuted();

  const toggleMute = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      const next = !muted;
      setMuted(next);
      const el = videoRef.current;
      if (el && !next) {
        el.muted = false;
        const p = el.play();
        if (p && typeof p.catch === "function") p.catch(() => {});
      }
    },
    [muted, setMuted],
  );

  const handleEnded = useCallback(() => {
    if (!hasMultiple) return;
    setAngleIdx((i) => (i + 1) % urls.length);
  }, [hasMultiple, urls.length]);

  // Autoplay the active angle. Swallow rejected play() promises (some browsers
  // block without a gesture even when muted).
  useEffect(() => {
    const el = videoRef.current;
    if (!el || !currentUrl || !open) return;
    const p = el.play();
    if (p && typeof p.catch === "function") p.catch(() => {});
  }, [currentUrl, open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoaded(false);
    fetchComments(segmentId)
      .then((cs) => {
        if (!cancelled) {
          setComments(cs);
          setLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    const unsub = subscribeToCommentsFor(segmentId, (c) => {
      setComments((prev) =>
        prev.some((x) => x.id === c.id) ? prev : [c, ...prev],
      );
    });
    return () => {
      cancelled = true;
      unsub();
    };
  }, [open, segmentId]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="comments"
      className="fixed inset-0 z-50 grid place-items-center p-3 sm:p-6"
    >
      <button
        type="button"
        aria-label="close comments"
        onClick={onClose}
        className="absolute inset-0 bg-black/70"
      />
      <div
        className="relative flex overflow-hidden rounded-2xl bg-surface shadow-2xl"
        style={{
          height: "min(92dvh, 900px)",
          maxWidth: "min(96vw, 1200px)",
        }}
      >
        <div className="relative h-full aspect-[4/5] flex-shrink-0 bg-black">
          {currentUrl ? (
            <video
              ref={videoRef}
              key={currentUrl}
              src={currentUrl}
              muted={muted}
              playsInline
              preload="auto"
              onEnded={handleEnded}
              className="absolute inset-0 h-full w-full object-cover"
            />
          ) : (
            <div className="absolute inset-0 grid place-items-center text-sm text-ink-secondary">
              video unavailable
            </div>
          )}

          {currentUrl && (
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? "unmute" : "mute"}
              aria-pressed={!muted}
              className="absolute bottom-3 right-3 z-20 grid h-9 w-9 place-items-center rounded-full bg-black/45 backdrop-blur-sm text-white"
            >
              {muted ? (
                <VolumeX className="h-4 w-4" />
              ) : (
                <Volume2 className="h-4 w-4" />
              )}
            </button>
          )}

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
        </div>

        <div className="flex w-[380px] min-w-[320px] flex-col">
          <header className="flex items-center justify-between border-b border-hairline px-4 py-3">
            <h2 className="text-[15px] font-semibold text-ink-primary">
              {loaded
                ? comments.length === 0
                  ? "comments"
                  : `${comments.length} comment${comments.length === 1 ? "" : "s"}`
                : "comments"}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="close"
              className="grid h-8 w-8 place-items-center rounded-full text-ink-secondary hover:text-ink-primary"
            >
              <X className="h-5 w-5" />
            </button>
          </header>

          {loaded ? (
            <CommentList comments={comments} />
          ) : (
            <div className="flex-1 grid place-items-center text-sm text-ink-secondary">
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
        </div>
      </div>
    </div>,
    document.body,
  );
}

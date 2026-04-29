import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { fetchComments } from "../api";
import { subscribeToCommentsFor } from "../commentsBus";
import type { Comment } from "../types";
import { CommentList } from "./CommentList";
import { CommentComposer } from "./CommentComposer";

/**
 * Desktop modal variant of the comment UI.
 *
 * Two-column layout: video left (~60%), comment panel right (~40%). The video
 * is a plain controlled <video> — no autoplay-on-scroll multi-angle stack
 * (this is a deliberate user-opened dialog, not the feed). Same CommentList +
 * CommentComposer internals as the mobile sheet.
 */
export function CommentPopup({
  segmentId,
  videoUrl,
  open,
  onClose,
}: {
  segmentId: string;
  videoUrl: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loaded, setLoaded] = useState(false);

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
      className="fixed inset-0 z-50 grid place-items-center p-6"
    >
      <button
        type="button"
        aria-label="close comments"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div className="relative grid w-full max-w-[960px] grid-cols-[3fr_2fr] overflow-hidden rounded-2xl bg-surface shadow-2xl">
        <div className="relative aspect-video bg-black">
          {videoUrl ? (
            <video
              src={videoUrl}
              controls
              playsInline
              className="absolute inset-0 h-full w-full object-contain"
            />
          ) : (
            <div className="absolute inset-0 grid place-items-center text-sm text-ink-secondary">
              video unavailable
            </div>
          )}
        </div>

        <div className="flex flex-col" style={{ maxHeight: "min(80dvh, 720px)" }}>
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

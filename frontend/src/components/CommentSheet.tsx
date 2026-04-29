import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { fetchComments } from "../api";
import { subscribeToCommentsFor } from "../commentsBus";
import type { Comment } from "../types";
import { CommentList } from "./CommentList";
import { CommentComposer } from "./CommentComposer";

/**
 * Mobile bottom-sheet variant of the comment UI.
 *
 * Slides up from the bottom; takes ~70dvh so the original montage video stays
 * visible above. dvh (not vh) so iOS Safari shrinks the sheet when the
 * keyboard slides in instead of pushing the input off-screen — that's the T2.8
 * keyboard handling.
 *
 * Always rendered into document.body via portal so the sheet escapes any
 * transformed/overflow-hidden ancestor in the feed list.
 */
export function CommentSheet({
  segmentId,
  open,
  onClose,
}: {
  segmentId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loaded, setLoaded] = useState(false);

  // Initial fetch + live SSE subscription, only while open.
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

  // Lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Esc closes.
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
      className="fixed inset-0 z-50"
    >
      <button
        type="button"
        aria-label="close comments"
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <div
        className="absolute inset-x-0 bottom-0 flex flex-col rounded-t-2xl bg-surface shadow-2xl"
        style={{ height: "70dvh", maxHeight: "70dvh" }}
      >
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
    </div>,
    document.body,
  );
}

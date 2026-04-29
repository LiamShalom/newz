import { Ghost } from "lucide-react";
import type { Comment } from "../types";
import { relativeTime } from "../timeFormat";

/**
 * Shared scrollable comment list — used by both CommentSheet (mobile) and
 * CommentPopup (desktop). Renders the same ghost-icon + relative-time row for
 * every comment; no name field, no avatar (anonymity is load-bearing).
 */
export function CommentList({ comments }: { comments: Comment[] }) {
  if (comments.length === 0) {
    return (
      <div className="flex-1 grid place-items-center px-4 py-10 text-center text-sm text-ink-secondary">
        Be the first to comment.
      </div>
    );
  }
  return (
    <ol className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      {comments.map((c) => (
        <li key={c.id} className="flex items-start gap-3">
          <div className="relative h-6 w-6 shrink-0">
            <Ghost
              aria-hidden
              className="absolute inset-0 h-6 w-6 text-ink-secondary"
            />
            {c.commenter_index ? (
              <span
                aria-label={`commenter ${c.commenter_index}`}
                style={{ right: "-2px", bottom: "-2px" }}
                className="absolute grid h-3.5 min-w-[14px] place-items-center rounded-full bg-coral px-1 text-[9px] font-semibold leading-none text-white ring-2 ring-surface"
              >
                {c.commenter_index}
              </span>
            ) : null}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-wide text-ink-secondary">
              anonymous · {relativeTime(c.created_at)}
            </div>
            <p className="mt-0.5 text-[15px] leading-snug text-ink-primary break-words">
              {c.text}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

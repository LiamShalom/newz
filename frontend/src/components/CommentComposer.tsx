import { useState, useRef, type FormEvent } from "react";
import { Send } from "lucide-react";
import { CommentPostError, postComment } from "../api";
import type { Comment } from "../types";

const MAX_LENGTH = 300;

/**
 * Shared text input + send button — used by both CommentSheet (mobile) and
 * CommentPopup (desktop). Owns the local draft state; calls onPosted after
 * a successful POST so the parent can append to the visible list.
 */
export function CommentComposer({
  segmentId,
  onPosted,
}: {
  segmentId: string;
  onPosted: (c: Comment) => void;
}) {
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const trimmed = draft.trim();
  const canSubmit = !submitting && trimmed.length > 0 && trimmed.length <= MAX_LENGTH;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const comment = await postComment(segmentId, trimmed);
      onPosted(comment);
      setDraft("");
    } catch (err) {
      if (err instanceof CommentPostError) {
        if (err.status === 429) {
          const wait = err.retryAfterSec ?? 60;
          setErrorMsg(`Slow down — try again in ${wait}s.`);
        } else if (err.status === 400) {
          setErrorMsg(err.detail);
        } else {
          setErrorMsg("couldn't post — try again");
        }
      } else {
        setErrorMsg("couldn't post — try again");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-t border-hairline bg-surface px-3 py-2"
      style={{ paddingBottom: "max(8px, env(safe-area-inset-bottom))" }}
    >
      {errorMsg && (
        <div className="mb-2 px-1 text-[12px] text-coral">{errorMsg}</div>
      )}
      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value.slice(0, MAX_LENGTH))}
          placeholder="add a comment"
          rows={1}
          aria-label="comment text"
          className="flex-1 resize-none rounded-2xl border border-hairline bg-surface-elevated px-3 py-2 text-[15px] leading-snug text-ink-primary placeholder:text-ink-secondary focus:outline-none focus:ring-1 focus:ring-coral focus:border-coral"
          style={{ maxHeight: "120px" }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSubmit) void handleSubmit(e as unknown as FormEvent);
            }
          }}
        />
        <button
          type="submit"
          disabled={!canSubmit}
          aria-label="send comment"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-coral text-white transition-opacity disabled:opacity-30"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-1 px-1 text-right text-[11px] text-ink-secondary">
        {trimmed.length}/{MAX_LENGTH}
      </div>
    </form>
  );
}

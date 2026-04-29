// Tiny pub-sub for live `comment_added` SSE events.
//
// Reason: useEventSource is mounted exactly once (in Feed.tsx) — see the
// "HTTP/1.1 6-connection limit" note in hooks/useEventSource.ts. Comment
// sheets/popups can't open their own EventSource. Instead, Feed dispatches
// comment_added events into this bus and any open sheet/popup subscribes.
//
// Implementation is a thin wrapper around EventTarget so listeners get
// auto-cleanup via removeEventListener and we don't reinvent ref-tracking.

import type { Comment } from "./types";

const TARGET = new EventTarget();
const TYPE = "comment_added";

interface CommentAddedDetail {
  segment_id: string;
  comment: Comment;
}

export function dispatchCommentAdded(segmentId: string, comment: Comment): void {
  const detail: CommentAddedDetail = { segment_id: segmentId, comment };
  TARGET.dispatchEvent(new CustomEvent(TYPE, { detail }));
}

/**
 * Subscribe to live comment additions for a specific segment.
 * Returns an unsubscribe function (drop on unmount).
 */
export function subscribeToCommentsFor(
  segmentId: string,
  onComment: (c: Comment) => void,
): () => void {
  const handler = (ev: Event) => {
    const detail = (ev as CustomEvent<CommentAddedDetail>).detail;
    if (detail.segment_id === segmentId) onComment(detail.comment);
  };
  TARGET.addEventListener(TYPE, handler);
  return () => TARGET.removeEventListener(TYPE, handler);
}

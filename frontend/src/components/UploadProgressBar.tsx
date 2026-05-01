import { useEffect } from "react";
import { X } from "lucide-react";
import { setUploadStatus, useUploadStatus } from "../uploadStatusBus";

/**
 * Thin top-of-feed bar driven by uploadStatusBus. Mounted in Feed.tsx as a
 * sticky sibling immediately under <Masthead /> (Masthead is sticky top-0
 * h-[96px], this bar is sticky top-[96px]). Renders nothing on idle.
 *
 * - uploading: 3px-tall coral indeterminate shimmer (keyframe defined in
 *   index.css). Backend doesn't expose progress events on /clips, so an
 *   indeterminate animation is intentional.
 * - error: same height in red, with a static event-shaped message and a
 *   dismiss "X" (44×44 hit area per iOS HIG). Auto-dismisses after 6s.
 *
 * Anonymity (CLAUDE.md): the message string never carries a username, never
 * says "your upload" — only event-shaped phrases. Caller-supplied strings are
 * truncated server-side; here we trust the bus.
 */
export function UploadProgressBar() {
  const status = useUploadStatus();

  // Auto-dismiss errors after 6s. Cleared on unmount or status change so a
  // re-entry into "error" with a different message restarts the timer.
  useEffect(() => {
    if (status.kind !== "error") return;
    const t = window.setTimeout(() => {
      setUploadStatus({ kind: "idle" });
    }, 6000);
    return () => window.clearTimeout(t);
  }, [status]);

  if (status.kind === "idle") return null;

  // Sticky pin under the masthead (which is sticky top-0 z-30 h-[96px]).
  // Same z-30 keeps the bar above feed content while scrolling.
  const baseWrap =
    "sticky top-[96px] z-30 w-full bg-surface";

  if (status.kind === "uploading") {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={baseWrap}
      >
        <div className="relative h-[3px] w-full overflow-hidden bg-coral-light/25">
          <div
            className="absolute inset-y-0 -left-1/3 w-1/3 bg-coral"
            style={{
              animation: "upload-shimmer 1.4s linear infinite",
            }}
          />
        </div>
      </div>
    );
  }

  // error
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="false"
      className={baseWrap}
    >
      <div className="flex items-center justify-between gap-2 px-4 py-1.5 bg-accent-record/15 border-b border-accent-record/40">
        <span className="text-xs font-medium text-ink-primary truncate">
          {status.message}
        </span>
        <button
          type="button"
          onClick={() => setUploadStatus({ kind: "idle" })}
          aria-label="Dismiss upload status"
          className="p-2 -m-2 inline-flex items-center justify-center text-ink-secondary hover:text-ink-primary"
        >
          <X size={16} strokeWidth={2.25} />
        </button>
      </div>
    </div>
  );
}

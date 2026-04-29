import { useMediaQuery } from "../hooks/useMediaQuery";
import { CommentSheet } from "./CommentSheet";
import { CommentPopup } from "./CommentPopup";

/**
 * Viewport-switching wrapper: bottom-sheet on mobile, modal popup on desktop.
 * Renders only the chosen variant so neither variant runs effects when hidden.
 *
 * Breakpoint matches Tailwind's `md:` (≥768px).
 */
export function Comments({
  segmentId,
  videoUrls,
  open,
  onClose,
}: {
  segmentId: string;
  /** All angle URLs for the montage. Popup re-uses the feed card's
   *  multi-angle treatment (auto-advance + bars + tap-to-nav). */
  videoUrls: (string | null)[] | null;
  open: boolean;
  onClose: () => void;
}) {
  const isDesktop = useMediaQuery("(min-width: 768px)");
  if (isDesktop) {
    return (
      <CommentPopup
        segmentId={segmentId}
        videoUrls={videoUrls}
        open={open}
        onClose={onClose}
      />
    );
  }
  return <CommentSheet segmentId={segmentId} open={open} onClose={onClose} />;
}

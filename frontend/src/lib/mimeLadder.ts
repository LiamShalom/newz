/**
 * CAP-10 MIME ladder. Verbatim from PATTERNS.md / STACK.md §"Browser Camera Capture".
 * DO NOT REORDER. Safari is happier with NO mimeType than with a wrong one — that is why
 * pickMimeType returns `undefined` when nothing matches; callers MUST then omit the
 * `mimeType` option entirely from the MediaRecorder constructor.
 */
export const MIME_CANDIDATES = [
  "video/mp4;codecs=avc1,mp4a",
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
] as const;

export type MimeCandidate = (typeof MIME_CANDIDATES)[number];

export function pickMimeType(): MimeCandidate | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  for (const t of MIME_CANDIDATES) {
    try {
      if (MediaRecorder.isTypeSupported(t)) return t;
    } catch {
      // Some old Safaris throw on unknown strings — keep trying.
    }
  }
  return undefined;
}

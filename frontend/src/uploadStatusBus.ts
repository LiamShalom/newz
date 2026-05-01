// Shared upload status for the optimistic-navigate flow.
//
// The recorder + camera-upload-button now navigate to /feed in the same gesture
// frame they kick off the upload, so the upload itself runs as a detached
// promise outside any React tree. We need a tiny EventTarget bus to surface
// progress (indeterminate) + failure to the feed's <UploadProgressBar />.
// Mirrors muteBus.ts / commentsBus.ts so we don't introduce a state library
// (Context / Zustand / Jotai) for a single tagged-union value. Anonymity-by-
// default applies: error messages are event-shaped strings, never per-user.
//
// Module-level singleton — only one in-flight upload modeled at a time. If two
// uploads kick off back-to-back the second `uploading` write is idempotent and
// the bar continues; the success/error of the first can clobber the second
// (acceptable for the pilot, flagged in the SUMMARY).
//
// Setter is module-level (not React state) because callers live OUTSIDE the
// React tree (Recorder.submitClip detached promise, CameraUploadButton.onPick
// detached promise) — they need to fire after navigate has unmounted them.
// Hook is read-only.
//
// CLAUDE.md: no display names, no usernames, no per-user state. Bar message
// strings stay event-shaped.

import { useEffect, useState } from "react";

export type UploadStatus =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "error"; message: string };

const TARGET = new EventTarget();
const TYPE = "upload_status_changed";

let status: UploadStatus = { kind: "idle" };

export function getUploadStatus(): UploadStatus {
  return status;
}

export function setUploadStatus(next: UploadStatus): void {
  // Identity-equal short-circuit. Two `uploading` writes back-to-back should
  // not produce two re-renders, and dismissing while already idle is a no-op.
  if (status.kind === next.kind) {
    if (status.kind === "error" && next.kind === "error") {
      if (status.message === next.message) return;
    } else {
      return;
    }
  }
  status = next;
  TARGET.dispatchEvent(new CustomEvent(TYPE));
}

export function subscribeToUploadStatus(listener: () => void): () => void {
  TARGET.addEventListener(TYPE, listener);
  return () => TARGET.removeEventListener(TYPE, listener);
}

/**
 * React hook: returns the current upload status and re-renders when it
 * changes. Read-only by design — setter is the module-level setUploadStatus
 * since real callers live outside the React tree (detached upload promises).
 */
export function useUploadStatus(): UploadStatus {
  const [value, setValue] = useState<UploadStatus>(status);
  useEffect(() => subscribeToUploadStatus(() => setValue(status)), []);
  return value;
}

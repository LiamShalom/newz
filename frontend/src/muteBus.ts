// Shared mute state for feed-card and popup video playback.
//
// Reason: iOS Safari requires `muted` for unattended autoplay, so every video
// must start muted. But once the user opts into sound, that decision should
// persist across cards (TikTok pattern) and across the comment popup. A tiny
// EventTarget bus mirrors the commentsBus.ts approach already in use.

import { useEffect, useState } from "react";

const TARGET = new EventTarget();
const TYPE = "mute_changed";

let muted = true;

export function getMuted(): boolean {
  return muted;
}

export function setMuted(next: boolean): void {
  if (muted === next) return;
  muted = next;
  TARGET.dispatchEvent(new CustomEvent(TYPE));
}

export function subscribeToMute(listener: () => void): () => void {
  TARGET.addEventListener(TYPE, listener);
  return () => TARGET.removeEventListener(TYPE, listener);
}

/**
 * React hook: returns the current shared muted state and re-renders when it
 * changes. The setter is the module-level setMuted (stable identity).
 */
export function useMuted(): [boolean, (next: boolean) => void] {
  const [value, setValue] = useState<boolean>(muted);
  useEffect(() => subscribeToMute(() => setValue(muted)), []);
  return [value, setMuted];
}

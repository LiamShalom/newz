// Shared mute state for feed-card and popup video playback.
//
// Reason: iOS Safari refuses unmuted autoplay, so every video must mount
// muted. To still ship "audio on by default" UX, armAutoUnmute() arms a
// one-shot listener that flips the bus to unmuted on the very first user
// gesture (tap, touch, key) — TikTok pattern. After that, the bus persists
// across cards and the comment popup. The listener disarms on first fire,
// on any explicit setMuted call, or when the gesture targets an element
// marked [data-mute-control] (so the dedicated mute button doesn't race
// the auto-unmute and produce a no-op toggle).

import { useEffect, useState } from "react";

const TARGET = new EventTarget();
const TYPE = "mute_changed";

let muted = true;

const GESTURE_EVENTS = ["pointerdown", "touchstart", "keydown"] as const;
let autoUnmuteArmed = false;

function handleFirstGesture(e: Event): void {
  if (!autoUnmuteArmed) return;
  const target = e.target as Element | null;
  if (target && typeof target.closest === "function" && target.closest("[data-mute-control]")) {
    disarmAutoUnmute();
    return;
  }
  setMuted(false);
}

function disarmAutoUnmute(): void {
  if (!autoUnmuteArmed) return;
  autoUnmuteArmed = false;
  if (typeof window === "undefined") return;
  for (const evt of GESTURE_EVENTS) {
    window.removeEventListener(evt, handleFirstGesture, true);
  }
}

export function getMuted(): boolean {
  return muted;
}

export function setMuted(next: boolean): void {
  disarmAutoUnmute();
  if (muted === next) return;
  muted = next;
  TARGET.dispatchEvent(new CustomEvent(TYPE));
}

export function subscribeToMute(listener: () => void): () => void {
  TARGET.addEventListener(TYPE, listener);
  return () => TARGET.removeEventListener(TYPE, listener);
}

/**
 * Arm a one-shot listener that flips the global mute to false on the first
 * user gesture. Idempotent — safe to call multiple times. Call once at app
 * boot.
 */
export function armAutoUnmute(): void {
  if (typeof window === "undefined") return;
  if (autoUnmuteArmed) return;
  autoUnmuteArmed = true;
  for (const evt of GESTURE_EVENTS) {
    window.addEventListener(evt, handleFirstGesture, { capture: true, passive: true });
  }
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

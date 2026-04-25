import type { Clip } from "./types";

// Pre-Phase-4: no caption exists yet. Render a neutral, deterministic fallback.
// When Phase 4 ships clip.caption, callers prefer it over this.
export function fallbackHeadline(_clip: Clip): string {
  return "Anonymous footage";
}

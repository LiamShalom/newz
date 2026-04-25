---
status: partial
phase: 04-multi-agent-compile-real-time-feed
source: [04-VERIFICATION.md]
started: 2026-04-25T12:00:00Z
updated: 2026-04-25T12:00:00Z
---

## Current Test

[awaiting human testing — requires ANTHROPIC_API_KEY + real video clips + real iPhone]

## Tests

### 1. CMP-01/CMP-04 End-to-End Compile Pipeline
expected: With ANTHROPIC_API_KEY set and real video clips uploaded, a cluster reaching size >= 2 triggers compile automatically. The backend logs show compile_started then segment_published within 30s. Feed re-renders with the new segment showing a caption and "Compiled from N angles" badge.
result: [pending]

### 2. FED-02 TikTok Autoplay on Real iPhone
expected: Open the feed on a real iPhone Safari. Videos autoplay immediately without a tap gesture. Video fills the screen (max-h-[80vh]). playsInline prevents iOS from fullscreening. Muted is required for iOS autoplay to work.
result: [pending]

### 3. RTM-02 SSE Auto-Reconnect
expected: Open the feed in a browser. Observe one EventSource connection in DevTools Network tab. Disable WiFi for 10s then re-enable. The EventSource reconnects automatically (browser-native — no manual retry). No stale connection or duplicate.
result: [pending]

### 4. RTM-03 Feed Re-Renders Within 1s
expected: Upload a clip that pushes a cluster to size >= 2. Start a stopwatch on segment_published log. Feed should show the new segment at the top within 1 second.
result: [pending]

### 5. CMP-08 Caption Grounding
expected: Inspect AI-generated captions. They must reference ONLY: date, neighborhood, and clip count. They must NOT contain participant counts, motives, names, or speculation ("appears to", "reportedly"). Fallback caption format: "Multi-angle event captured by N contributors on Mon DD, YYYY."
result: [pending]

### 6. CMP-04 Parallel Subagent Execution
expected: Enable verbose logging or observe backend logs during compile. angle-selector and caption-writer should both appear in the log before editor begins. Total wall-clock should be under 30s (well under if parallel — ~10-15s).
result: [pending]

### 7. FED-03 Distance Overlay End-to-End
expected: With real GPS + real uploaded clips, the FeedTile shows a distance string ("3 blocks away", "0.4 mi away") rather than the location string fallback. Open feed at the same location as the clip — should show "right here" or "1 block away".
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0
blocked: 0

## Gaps

---
slug: captions-multi-angle-template
status: root_cause_found
trigger: |
  the captions are still being included as multi-angle event capture. we want it to be creating based on video, and location
created: 2026-04-25
updated: 2026-04-25
---

# Debug Session: captions-multi-angle-template

## Symptoms

- **Expected behavior:** Caption is generated based on video content + location data (place name, GPS-derived context).
- **Actual behavior:** Caption renders as a generic multi-angle / event-capture template instead of describing video + location.
- **Specific symptom selected:** "Generic multi-angle template" — captions look like 'Multi-angle coverage of [event]' regardless of actual video content.
- **Observed where:** Feed UI in browser (segment cards in the live feed).
- **Error messages:** None reported.
- **Timeline:** First-time regression — caption generation has never produced video+location-based output since being wired up. This is Phase 4 just landed; never had a working baseline.
- **Reproduction:** Trigger compile pipeline (upload clips → cluster forms → multi-agent compile → SSE → segment renders in feed). Caption shown on segment card is the generic multi-angle template instead of a content+location-driven sentence.

## Project Context

- **Active phase:** Phase 4 — Multi-Agent Compile + Real-Time Feed.
- **Caption generation lives in:** Claude Agent SDK 4-subagent pipeline (Angle Selector ‖ Caption Writer + Publisher). See `.planning/phases/04-multi-agent-compile-real-time-feed/`.
- **Stack reminder:** FastAPI backend, claude-agent-sdk==0.1.68, Sonnet for subagents, Haiku for Publisher, 30s wall-clock cap.
- **Hard constraint:** Caption must be informed by video (Marengo embedding context or Twelve Labs metadata) AND location (GPS / place-name lookup), NOT by cluster-size / multi-angle framing.

## Current Focus

```yaml
hypothesis: |
  CONFIRMED. Multiple "multi-angle event captured…" string literals exist in the
  pipeline. The vision-grounded Caption Writer (Track A) does run, but Track C
  (caption_pipeline.generate_caption) runs in parallel and its result
  unconditionally OVERWRITES Track A's good caption — including when Track C
  itself fell back to a generic "Multi-angle event captured by N contributor(s)"
  template. Additionally a seeded demo segment ships with the same template,
  and the synchronous fallback in compile.py uses it too.
test: |
  Read the compile pipeline source (Caption Writer subagent prompt + the input payload
  it receives) and verify what fields are passed in. Compare against expected inputs
  (video description / Marengo signal, location string, GPS).
expecting: |
  Either: (1) the prompt template is generic and doesn't include video+location fields,
  OR (2) the fields are passed but the prompt instructs the subagent to caption based on
  the multi-angle event framing instead of the actual video content.
next_action: |
  Apply the four-part fix described in the Resolution section. Highest-priority fix is
  the Track C overwrite logic in compile.py:409-420 — Track A's vision caption should
  win, with Track C used only as a fallback. Then remove the "multi-angle…" template
  strings from the two fallback paths and the seed.
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-25 — User report: captions on feed cards are generic multi-angle templates; have never been video+location grounded since Phase 4 landed.
- timestamp: 2026-04-25 — `backend/pipeline/compile.py:328` `_save_fallback_segment` writes literal `f"Multi-angle event captured by {len(clip_ids)} contributors on {when}."` — direct match for symptom.
- timestamp: 2026-04-25 — `backend/pipeline/caption_pipeline.py:171` `_fallback_caption` writes the same literal `f"Multi-angle event captured by {n} contributor(s) on {when}."` — fires when ANTHROPIC_API_KEY missing or any exception in Track C, including all-frames-failed.
- timestamp: 2026-04-25 — `backend/pipeline/compile.py:409-420` overwrites Track A's good Publisher-saved caption with `caption_result["caption"]` whenever `caption_result` is a dict, *including* the fallback dict above. There is no preference for Track A.
- timestamp: 2026-04-25 — `backend/seed/demo_segment.py:50-53` seeds initial DB row with caption "Staged demo: multi-angle event captured at Caltech campus, Pasadena, CA. Compiled from 3 angles." — currently the only segment in the live DB.
- timestamp: 2026-04-25 — Live DB query: 1 segment, caption is the seeded demo string. 6 clusters exist, 5 of them have no segment (compile failed silently or hasn't reached threshold).

## Eliminated

- The Caption Writer subagent prompt itself (compile.py:48-64 `CAPTION_WRITER_SYSTEM`) is correctly grounded in keyframes + cluster metadata. Not the bug.
- Angle Selector / Editor / Publisher prompts. Publisher does not rewrite captions.
- `extract_cluster_keyframes` and `extract_frames` look correct; they degrade gracefully (return [] / log warning), they don't generate the bad template themselves.

## Resolution

### Root cause (one sentence)

Track C (`generate_caption`) runs in parallel with Track A (vision Caption Writer) and unconditionally overwrites Track A's output in `compile.py:409-420`, AND Track C's own fallback path emits the literal "Multi-angle event captured by N contributor(s)" string the user is complaining about — combined with a seeded demo row that ships with the same template.

### Fix (four parts)

1. **`backend/pipeline/compile.py:401-420` — stop overwriting Track A's caption with Track C's fallback.**
   Track Track C returning a real (non-fallback) caption explicitly. Only overwrite if Track C succeeded *and* did not fall back. Suggested approach: have `generate_caption` return `{"caption": ..., "location": ..., "source": "vision"|"fallback"}` and only apply when `source == "vision"`. Alternative if you prefer minimal surface change: have `_fallback_caption` return `None` instead of a dict, and the call site treats `None` as "use Track A's caption".

2. **`backend/pipeline/caption_pipeline.py:163-172` — replace the "Multi-angle event captured…" template** with either (a) `None` (preferred — see fix 1) so Track A's caption is preserved, or (b) a place-only sentence like `f"Footage from {location} on {when}."` if it must be a string.

3. **`backend/pipeline/compile.py:317-336` `_save_fallback_segment` — replace the "Multi-angle event captured…" template** with a place + date sentence that names location, e.g. `f"{when} — Pasadena, CA. Submitted footage from contributors."` This path only runs on hard failure of Track A, but it must not emit the forbidden template either.

4. **`backend/seed/demo_segment.py:50-53` — replace the seeded demo caption.** It's currently the *only* segment row in the live DB and likely what the user is actually looking at. Replace with something concrete like `"Pedestrians crossing Pasadena Boulevard at midday — Pasadena, CA."` Or skip the seed entirely on first paint (return EmptyState until a real upload lands).

### Optional follow-up

The empty `caption_result` branch in compile.py also needs to handle the case where Track A wrote *nothing* and Track C fell back — currently you'd write `seg.get("caption", "")` which is empty. Preserve Track A's caption by reading the segment row before the overwrite (already done at line 410), and only call `insert_segment` if you actually have something better to write than the row already has.


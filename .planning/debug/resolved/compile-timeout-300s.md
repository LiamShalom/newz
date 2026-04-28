---
slug: compile-timeout-300s
status: resolved
fix_applied: 2026-04-27
files_changed:
  - backend/pipeline/caption_pipeline.py
  - backend/pipeline/compile.py
trigger: |
  DATA_START
  Sometimes when attempting to create segments the backend will timeout, this is the error we get in railway:
  2026-04-27 20:12:29,422 WARNING backend.pipeline.compile compile TIMEOUT cluster_id=9b7e3649092f450c833c7a26e65e6c03 after 300s — using fallback
  DATA_END
created: 2026-04-27
updated: 2026-04-27
---

# Debug Session: compile-timeout-300s

## Symptoms

- **Expected:** Compile pipeline produces a stitched segment for a cluster within the 300s budget; cluster transitions out of pending state with a real (non-fallback) compile output.
- **Actual:** `backend.pipeline.compile` logs `compile TIMEOUT cluster_id=... after 300s — using fallback`. Pipeline gives up, fallback path serves cached/placeholder output instead of real multi-agent compile.
- **Error message (verbatim):** `2026-04-27 20:12:29,422 WARNING backend.pipeline.compile compile TIMEOUT cluster_id=9b7e3649092f450c833c7a26e65e6c03 after 300s — using fallback`
- **Timeline:** Intermittent. User notes: "It doesn't always happen, just sometimes, usually after longer clips are uploaded."
- **Frequency:** Rare (<10% of compiles).
- **Mode:** Live external API path (Claude Agent SDK + Gemini), not OFFLINE_DEMO.
- **Environment:** Railway production deploy.

## Current Focus

```yaml
hypothesis: Caption pipeline composite balloons to span the full duration of a long parent clip because _build_stitch_refs merges multiple selected children from the same parent into [min_start, max_end]. Gemini generate_content latency on the long composite (with no inner timeout) consumes most of the 300s budget; the parallel orchestrator chain pushes total wall-clock past 300s.
test: Trace the caption pipeline's stitch-input construction for clusters whose parents are long (>60s). Verify that _select_caption_children + _build_stitch_refs can produce a composite that spans the full parent duration. Verify there is no per-call timeout on Gemini upload, polling-after-30s ceiling, or generate_content. Verify the orchestrator-chain branch has no inner timeout either.
expecting: Code path confirms unbounded composite duration when same-parent children are selected; no inner timeouts on Gemini SDK or claude-agent-sdk query(); user signal "longer clips → timeout" matches caption-branch scaling, not orchestrator-branch scaling.
next_action: Converge — root cause found.
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Initial Suspicion Surface (orchestrator notes — debugger should validate, not assume)

Based on the project guide and user-supplied symptoms, candidate threads to probe:

1. **Per-call vs aggregate timeout.** The 300s budget covers the entire compile (multi-agent SDK + Gemini captions + ffmpeg stitch). If any single upstream call lacks an inner timeout/retry cap, one slow LLM call can starve the rest.
2. **Long-clip Gemini latency.** User explicitly correlates with "longer clips uploaded." Gemini 2.5 Flash native video input scales with clip duration; if a cluster references long parent uploads, the captioning step alone can blow the budget.
3. **Multi-agent SDK retries / throttle.** `claude-agent-sdk==0.1.68` may retry under throttling, multiplying wall-clock. Subagent fan-out (Sonnet) in serial vs parallel matters.
4. **ffmpeg stitch on long inputs.** Even with `libx264 ultrafast` + `-c copy` parallelization, very long source clips can stretch the encode tail. Worth checking whether stitch stage runs inside or outside the 300s budget.
5. **Cluster size growth.** If "longer clips" are also clips that landed in larger clusters, more parents → more LLM work → linear blow-up.
6. **Cold-start adjacent issues.** Marengo pre-warm covers embedding, not compile path. First compile after deploy could be slower.

These are hypotheses to test, not conclusions. Debugger agent should read the pipeline code, find the actual timeout wrapper, instrument or reason from logs, and converge by elimination.

## Evidence

### E1 — The single 300s timeout is on the parallel `asyncio.gather` of two LLM branches

`backend/pipeline/compile.py:386-395`:

```python
results = await asyncio.wait_for(
    asyncio.gather(
        _run_orchestrator_chain(cluster_id),
        _branch_caption(cluster_id),
        return_exceptions=True,
    ),
    timeout=300.0,
)
```

Whichever branch is the long pole controls whether we hit 300s. There is no inner cap on either branch.

### E2 — `_branch_caption` has NO inner timeouts on any Gemini SDK call

`backend/pipeline/caption_pipeline.py:386-426`:

- `client.files.upload(file=stitched)` — no timeout.
- Polling loop has a 30s ceiling (`for _ in range(30): await asyncio.sleep(1)`), but only on the polling, not on the upload itself.
- `client.models.generate_content(model=..., contents=[uploaded, user_prompt], config=...)` — **no timeout**, runs in default executor.

Default `google-genai` HTTP client timeout for video `generate_content` is generous (600s+ per Google's reference). A slow Gemini 2.5 Flash call on long-duration video can run 60–200s+ on its own under load.

### E3 — Caption-pipeline composite duration is unbounded by clip length (root cause path)

The composite mp4 fed to Gemini is built from 3 children selected by `_select_caption_children(centroid, n=3)`:

`backend/pipeline/caption_pipeline.py:256-270`:

```python
def _select_caption_children(children, centroid, n=3):
    scored = [(float(np.dot(vec, centroid)), child) for child in children if child.get("vec") is not None]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:n]]
```

No parent-diversity constraint (unlike the angle-selector subagent in `compile.py`). All 3 picks can come from the same parent.

Then `_build_stitch_refs` (caption_pipeline.py:273-306) **dedupes by `parent_path` and merges into `[min(start), max(end)]`**:

```python
if parent_path in by_path:
    existing = by_path[parent_path]
    existing["start_offset_sec"] = min(existing["start_offset_sec"], start)
    existing["end_offset_sec"] = max(existing["end_offset_sec"], end)
```

Children are 3-second slices spanning the FULL parent clip duration (Marengo `VideoSegmentation_Fixed(duration_sec=3)` in `embed.py:80-82`). If the centroid-closest 3 children for a 90-second parent are at offsets `[0–3, 45–48, 87–90]`, the merged window becomes `[0, 90]` — **the entire parent gets re-encoded and shipped to Gemini**.

`stitch_clips` (`stitch.py:30-87`) is a libx264 ultrafast re-encode (NOT `-c copy`), so a 90s composite means 90s of encoded video bytes, then 90s of native-video reasoning by Gemini.

### E4 — `_run_orchestrator_chain` does NOT scale with clip duration

The orchestrator chain (`compile.py:127-163`) runs Claude Agent SDK with subagents that operate on **metadata only** via `get_cluster_runs` and `get_clip_metadata` (compile_tools.py). Inputs are run dataclass fields (id, parent_id, start/end offsets, duration, lat/lng/ts) — never video bytes. Subagent latency scales with cluster cardinality, not clip duration.

This eliminates the orchestrator branch as the primary driver of the user's "longer clips → timeout" correlation. The SDK call has no inner timeout (potential secondary contributor under throttle), but a slow orchestrator chain alone wouldn't correlate with clip length.

### E5 — Phase 2 ffmpeg stitch is OUTSIDE the 300s budget

`compile.py:419-432` runs `_stitch_segment_runs` under a separate 30s `asyncio.wait_for`, and uses `-c copy` stream-copy (`stitch._sync_trim`). Even on long inputs this is fast (~50–100ms per run). Eliminates ffmpeg as a contributor to the 300s timeout.

### E6 — User signal alignment

User: "It doesn't always happen, just sometimes, usually after longer clips are uploaded."

- **Caption branch:** scales linearly with selected-children span × 2 (encode + Gemini reasoning). Long parent clips → long composite → long Gemini latency. **Matches signal.**
- **Orchestrator branch:** flat in clip duration. Does not match signal.
- **Frequency <10%:** consistent with the conditional probability that `_select_caption_children` happens to pick 2+ children from the same long parent AND Gemini latency lands in the slow tail. Most clusters either have short parents (no balloon) or have parent-diverse top-3 (composite stays short).

## Eliminated Hypotheses

- **(Initial 4) ffmpeg stitch tail on long inputs.** Eliminated by E5 — Phase 2 stitch is outside the 300s budget and uses `-c copy`. Caption-pipeline stitch is in budget but its CPU cost is dwarfed by the subsequent Gemini call.
- **(Initial 5) Cluster size growth.** Eliminated as primary — orchestrator chain reads metadata only, doesn't scale meaningfully with cluster size at the cardinalities seen in prod (a few parents per cluster). May be a small constant contributor.
- **(Initial 6) Cold-start.** Pre-warm covers Marengo only. Claude SDK / Gemini paths could have first-call setup cost, but this is a fixed per-process overhead, not correlated with clip duration. Eliminated as primary.

## Resolution

### Root Cause

The 300s `asyncio.wait_for` covers two LLM branches in parallel, but **neither branch has an inner timeout**. The caption branch (`_branch_caption` → `caption_pipeline.generate_caption`) builds a Gemini-input composite mp4 whose duration is **unbounded by parent clip length**:

- `_select_caption_children` picks top-3 children by cosine to centroid with no parent-diversity constraint.
- `_build_stitch_refs` then dedupes by `parent_path` and merges multiple same-parent children into a single `[min(start), max(end)]` window.
- Marengo emits children as 3-second fixed slices spanning the full parent duration.
- A long parent (e.g., 90s+) whose centroid-closest 3 children straddle its timeline produces a composite covering the **entire parent**.

That composite is libx264-re-encoded then shipped to `gemini-2.5-flash` `generate_content` with native video reasoning. Gemini's latency scales with input duration and is bursty under load. With **no per-call timeout** on `client.files.upload(...)`, no timeout on `generate_content(...)`, and a Google-genai SDK default that exceeds 300s, a single slow Gemini call can consume the entire parent budget. Combined with orchestrator-chain variance running in parallel, total wall-clock crosses 300s and the outer `wait_for` raises `TimeoutError`, triggering the fallback.

This matches the user's "longer clips → intermittent" signal precisely: the failure surface activates only when (a) cluster has a long parent AND (b) `_select_caption_children` picks ≥2 children from that long parent AND (c) Gemini lands in the latency tail. All three conditions occur together <10% of the time.

### specialist_hint

`python` — issue is an asyncio/timeout-budget pattern in Python with external SDK calls (Gemini + claude-agent-sdk).

### Suggested Fix Direction

Two changes, both in `caption_pipeline.py`, ordered by impact:

1. **Bound the caption-input composite duration.** Cap the merged window per parent in `_build_stitch_refs` to a small fixed budget (e.g., 9s — three 3s children worth of content). When same-parent children would merge into a longer span, keep only the children adjacent to the centroid-closest one, not the full envelope. Concretely: replace the `min(start)/max(end)` merge with "keep the first child only, OR pick contiguous children only," AND/OR enforce a `MAX_CAPTION_INPUT_SEC = 12` clamp on the resulting window.
2. **Add per-call timeouts inside `_branch_caption`.** Wrap `client.files.upload(...)` in `asyncio.wait_for(..., timeout=30)`, and `client.models.generate_content(...)` in `asyncio.wait_for(..., timeout=120)`. On inner timeout, return `None` so the compile pipeline uses the fallback caption while the orchestrator chain still finishes and saves a real segment row.

Optional belt-and-suspenders:
- Cap per-call on `_run_orchestrator_chain` (e.g., `asyncio.wait_for(query_loop, timeout=180)`) so the orchestrator can't independently consume the full budget under SDK throttle/retry.
- Log composite duration before the Gemini call to make this regression visible going forward.

The fix preserves anonymity, OFFLINE_DEMO, iOS Safari behavior, and the 300s outer budget. It changes only how the caption branch handles long parents and adds inner timeouts that fail fast to the existing fallback path instead of starving the orchestrator chain.

## Specialist Review

**Skill:** python-expert-best-practices-code-review (mapped from `specialist_hint: python`)
**Verdict:** SUGGEST_CHANGE — fix direction is correct but two refinements improve correctness and surgical scope.

### Refinement 1 — Add SDK-level HTTP timeout, not just `asyncio.wait_for`

`asyncio.wait_for` around a `loop.run_in_executor(None, sync_call)` future will mark the asyncio future cancelled, but **the underlying thread keeps running** until the sync HTTP call returns. The thread eventually drains, but in a single-process FastAPI on Railway this can pile up under bursty load.

Set the timeout at the SDK transport layer in addition to the asyncio wrapper:

```python
from google.genai import types as genai_types
client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=genai_types.HttpOptions(timeout=120_000),  # ms
)
```

This makes the underlying HTTP request actually abort. Combine with `asyncio.wait_for(..., timeout=125)` as belt-and-suspenders.

### Refinement 2 — Don't merge same-parent windows at all; emit one ref per child

The existing comment in `_build_stitch_refs` claims merging is required to avoid `multiple outgoing edges with same upstream label None`. That collision happens **only** when the same `ffmpeg.input(path)` Python object is fed into multiple filter chains. The current code calls `ffmpeg.input(path, ss=..., to=...)` per ref (one per dict in `clip_refs`), so ffmpeg sees them as **independent input nodes** even when paths match — no collision.

Concrete change: drop the `by_path` dedupe entirely. Emit one ref per selected child with `[start, start+3]`. With `n=3` children, composite is **always exactly 9s** regardless of parent length.

```python
def _build_stitch_refs(selected: list[dict]) -> list[dict]:
    refs: list[dict] = []
    for child in selected:
        parent_path = child.get("parent_path")
        if not parent_path:
            continue
        start = float(child.get("start_offset_sec") or 0.0)
        end = child.get("end_offset_sec")
        end = float(end) if end is not None else start + 3.0
        refs.append({
            "path": parent_path,
            "start_offset_sec": start,
            "end_offset_sec": end,
        })
    return refs
```

This is smaller, simpler, and removes the unbounded-duration bug at the source. The asyncio inner timeouts then become a defense-in-depth layer for Gemini-side latency (network slowness, rate limits) rather than the only bound on duration.

### Verdict summary

Both Refinements integrate cleanly with the original Suggested Fix Direction. Apply Refinement 2 first (it eliminates the root cause directly) plus Refinement 1's HTTP timeout (cheap, prevents future regressions), and skip the optional `MAX_CAPTION_INPUT_SEC` clamp from the original fix — Refinement 2 makes it redundant. Optional orchestrator-chain inner timeout from the original is still worthwhile for SDK-throttle resilience.

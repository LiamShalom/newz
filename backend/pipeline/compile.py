"""
backend/pipeline/compile.py — vision-enabled compile pipeline (Phase 4).

Public API:
    compile_segment(cluster_id: str) -> None
        Fire-and-forget coroutine. Called via asyncio.create_task from run.py.
        Hard 60s wall-clock cap (CMP-06). Fallback on timeout or error.

Pipeline:
    1. caption-writer (direct vision query, midpoint keyframe per clip)
    2. orchestrator chain: angle-selector → editor → publisher (subagents)

Caption-writer is a top-level query() with image content blocks rather than a
subagent — claude-agent-sdk 0.1.68 does not propagate image content from MCP
tool returns into a subagent's vision context, so we pre-extract keyframes in
Python and inline them into the user message.

MCP tools (subagents only): get_cluster_clips, get_clip_metadata, save_segment.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
)

from .. import config, db, events
from .compile_tools import newz_tools_server
from .stitch import stitch_clips, trim_window
from .caption_pipeline import generate_caption
from .runs import compute_runs_for_cluster

log = logging.getLogger(__name__)


ORCHESTRATOR_PROMPT_TEMPLATE = """Compile cluster {cluster_id} into a published news segment.

The title and caption will be filled in later by another worker. Pass empty
strings ("") for both when calling save_segment. The orchestrator will
overwrite them.

Steps — use the named subagents in this order:
1. Run angle-selector to pick the best 2-4 RUNS and order them.
2. Run publisher with angle-selector's run_ids. Pass title="" and caption="".

Pass angle-selector's JSON output verbatim into publisher's prompt.
The cluster_id is: {cluster_id}
"""

_MCP = ["newz_tools"]

AGENTS = {
    "angle-selector": AgentDefinition(
        description=(
            "Picks 2-4 best RUNS from a cluster and orders them chronologically. "
            "A run = one continuous camera angle within a single parent clip. "
            "Run FIRST."
        ),
        prompt="""You are the Angle Selector for the Newz news compile pipeline.

You select the best 2-4 RUNS from a cluster. A run = one continuous camera
angle (a contiguous span of similar 3-second slices from the same source
clip). Different runs from different parent clips give you different
viewpoints of the same event.

HARD CONSTRAINT — PARENT DIVERSITY:
  When the cluster contains 2 or more distinct parent clips, your selection
  MUST include at least one run from each of at least 2 distinct parents.
  A segment showing only one viewpoint is unacceptable. If you find yourself
  picking 2+ runs from the same parent_id while another parent has runs you
  haven't picked, drop one of the same-parent runs and pick a run from the
  other parent instead.

Selection criteria — within the parent-diversity constraint, rank by:
1. TEMPORAL SPREAD: prefer runs from early, middle, and late in the event
   timeline (spread across the timestamp range).
2. SPATIAL DIVERSITY: prefer runs whose parent clips were recorded from
   different GPS coordinates (different physical viewpoints).
3. DURATION: prefer runs whose duration_sec >= 3.0; discard runs shorter
   than 2.0 seconds.
4. NO REDUNDANCY: exclude runs whose parent was filmed within 5 seconds AND
   within 10 meters of an already-selected run's parent.

Order the selected runs chronologically (earliest parent ts first).

Use mcp__newz_tools__get_cluster_runs to list candidates, then
mcp__newz_tools__get_clip_metadata for any parent-clip details.
Return ONLY a single JSON object: {"run_ids": ["...", "..."], "rationale": "..."}.
Do not include any text outside the JSON.""",
        tools=["mcp__newz_tools__get_cluster_runs", "mcp__newz_tools__get_clip_metadata"],
        mcpServers=_MCP,
        model="sonnet",
    ),
    "publisher": AgentDefinition(
        description=(
            "Persists the finished segment via save_segment. Run AFTER angle-selector. "
            "Only calls the save_segment tool — does not rewrite captions."
        ),
        prompt="""You are the Publisher for the Newz news compile pipeline.

Take the Angle Selector's run_ids and persist the segment. Title and caption
are filled in later by another worker — pass empty strings for both here.

Call mcp__newz_tools__save_segment EXACTLY ONCE with:
  - cluster_id: provided by the orchestrator
  - ordered_run_ids: from angle-selector's run_ids list
  - title: ""
  - caption: ""
  - location: "Pasadena, CA"
  - source_count: number of distinct parent_ids in ordered_run_ids

Return ONLY the segment id string from the tool result.""",
        tools=["mcp__newz_tools__save_segment"],
        mcpServers=_MCP,
        model="haiku",
    ),
}


async def _run_orchestrator_chain(cluster_id: str) -> str:
    """Run angle-selector → editor → publisher. Caption/title are filled later
    by Branch B's overwrite — publisher saves placeholder empty strings.
    """
    options = ClaudeAgentOptions(
        allowed_tools=[
            "Agent",
            "mcp__newz_tools__get_cluster_runs",
            "mcp__newz_tools__get_clip_metadata",
            "mcp__newz_tools__save_segment",
        ],
        agents=AGENTS,
        mcp_servers={"newz_tools": newz_tools_server},
        max_turns=20,
        model="sonnet",
    )
    prompt = ORCHESTRATOR_PROMPT_TEMPLATE.format(cluster_id=cluster_id)
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                log.error(
                    "compile orchestrator error cluster_id=%s turns=%s errors=%s result=%s",
                    cluster_id, msg.num_turns, msg.errors, msg.result,
                )
                raise RuntimeError(f"orchestrator returned is_error=True: {msg.errors}")
            log.info(
                "compile orchestrator done cluster_id=%s turns=%s duration_ms=%s",
                cluster_id, msg.num_turns, msg.duration_ms,
            )
            break
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        raise RuntimeError(
            f"compile finished but no segment row for cluster {cluster_id} — "
            "Publisher may have failed to call save_segment"
        )
    return seg["id"]


async def _get_children_with_vecs(cluster_id: str) -> list[dict]:
    """Load child clips for cluster with their embedding vectors attached."""
    rows = await db.fetch_cluster_clips_with_children(cluster_id)
    children = []
    for r in rows:
        vec = await db.get_embedding(r["id"])
        children.append({**r, "vec": vec})
    return children


async def _branch_caption(cluster_id: str) -> dict | None:
    """Branch B: describe centroid-closest children, synth title+caption.

    Wraps the existing caption_pipeline.generate_caption. Returns whatever
    that pipeline emits — currently {caption, location, source} (M5 will
    extend with title). compile_segment uses .get("title") defensively so
    pre-M5 calls gracefully leave title empty.
    """
    from .cluster import CLUSTERS  # local import: avoid module-load cycle
    cluster_cache = CLUSTERS.get(cluster_id)
    if cluster_cache is None:
        return None
    children = await _get_children_with_vecs(cluster_id)
    if not children:
        return None
    return await generate_caption(cluster_id, cluster_cache.centroid, children)


async def _resolve_run_ids_to_stitch_refs(
    cluster_id: str, ordered_run_ids: list[str]
) -> list[dict]:
    """Re-derive runs from cluster, then look up each ordered_run_id.

    Childless-parent runs (member_child_ids == []) emit end_offset_sec=None
    so ffmpeg ingests the full parent file. Otherwise we use the run's
    [start, end] window. Unknown run_ids are dropped with a warning.
    """
    runs = await compute_runs_for_cluster(cluster_id)
    by_id = {r.id: r for r in runs}
    refs: list[dict] = []
    for rid in ordered_run_ids:
        r = by_id.get(rid)
        if r is None:
            log.warning("resolve: unknown run_id=%s cluster_id=%s", rid, cluster_id)
            continue
        end = None if not r.member_child_ids else r.end_offset_sec
        refs.append({
            "path": r.parent_path,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": end,
        })
    return refs


async def _save_fallback_segment(cluster_id: str, video_url: str | None = None) -> str:
    """CMP-06: idempotent fallback. Chronological order, generic AP-wire caption."""
    existing = await db.get_segment_for_cluster(cluster_id)
    if existing:
        return existing["id"]
    clips = await db.fetch_cluster_clips(cluster_id)
    clip_ids = [c["id"] for c in clips]
    if clips:
        when = datetime.fromtimestamp(clips[0]["ts"], tz=timezone.utc).strftime("%b %-d, %Y")
    else:
        when = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")
    location_str = "Pasadena, CA"  # default; cluster centroid reverse-geocode is a Phase 5 follow-up
    caption = f"{when} — {location_str}. Submitted footage from {len(clip_ids)} contributor(s)."
    return await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=clip_ids,
        title="",
        caption=caption,
        location=location_str,
        source_count=len(clip_ids),
        video_url=video_url,
    )


def _parent_id_of_run(run_id: str) -> str:
    """Run IDs are deterministic `{parent_id}_run_{idx}`."""
    return run_id.rsplit("_run_", 1)[0]


async def _enforce_parent_diversity(cluster_id: str, min_parents: int = 2) -> None:
    """Deterministic guard: if angle-selector picked runs from < min_parents
    distinct parents while the cluster has 2+ parents available, augment with
    the earliest run from each missing parent.

    Patches the segment row in place so Phase 2 stitch sees the augmented
    run_ids when it reads the row.
    """
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        return
    raw = seg.get("ordered_clip_ids")
    picked = json.loads(raw) if isinstance(raw, str) else (raw or [])
    if not picked:
        return

    runs = await compute_runs_for_cluster(cluster_id)
    if not runs:
        return

    by_parent: dict[str, list] = {}
    for r in runs:
        by_parent.setdefault(r.parent_id, []).append(r)

    cluster_parents = list(by_parent.keys())
    target = min(min_parents, len(cluster_parents))
    picked_parents = list(dict.fromkeys(_parent_id_of_run(rid) for rid in picked))

    if len(picked_parents) >= target:
        return  # already diverse enough

    additions: list[str] = []
    needed = target - len(picked_parents)
    for parent_id in cluster_parents:
        if parent_id in picked_parents:
            continue
        first_run = sorted(by_parent[parent_id], key=lambda r: r.start_offset_sec)[0]
        if first_run.id not in picked:
            additions.append(first_run.id)
        if len(additions) >= needed:
            break

    if not additions:
        return

    new_picked = picked + additions
    distinct_parents = len({_parent_id_of_run(rid) for rid in new_picked})
    log.warning(
        "parent diversity guard: angle-selector picked %d distinct parent(s) "
        "(cluster has %d). Augmenting with %d run(s): %s",
        len(picked_parents), len(cluster_parents), len(additions), additions,
    )
    await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=new_picked,
        title=seg.get("title") or "",
        caption=seg.get("caption") or "",
        location=seg.get("location") or "Pasadena, CA",
        source_count=distinct_parents,
        video_url=seg.get("video_url"),
    )


async def _stitch_segment_runs(cluster_id: str) -> list[str]:
    """Stitch EACH chosen run into its own .mp4. Returns ordered list of /media URLs.

    Per-run stitching (not cluster-wide concatenation) so the frontend can
    navigate between angles while still applying ffmpeg normalization within
    a run (start_offset → end_offset window from one parent file).

    Output: data/clips/{run_id}.mp4 per run, in the same order as run_ids.
    Runs OUTSIDE the LLM wall-clock budget — must not be cancelled by the
    orchestrator-chain timeout.
    """
    seg = await db.get_segment_for_cluster(cluster_id)
    if seg is None:
        return []
    raw = seg.get("ordered_clip_ids")
    run_ids = (
        json.loads(raw) if isinstance(raw, str)
        else (raw or [])
    )
    if not run_ids:
        log.warning("stitch: no run_ids saved for cluster_id=%s", cluster_id)
        return []
    refs = await _resolve_run_ids_to_stitch_refs(cluster_id, run_ids)
    if not refs:
        return []

    # Trim each run's window in PARALLEL via -c copy stream-copy (no re-encode).
    # Runs are always contiguous within ONE parent file, so this is a fast
    # ffmpeg trim, not a real concat. asyncio.gather lets ffmpeg processes
    # share CPU instead of awaiting one-at-a-time.
    async def _trim_one(run_id: str, ref: dict) -> tuple[str, str | None]:
        output_path = str(config.DATA_DIR / "clips" / f"{run_id}.mp4")
        t0 = time.monotonic()
        result = await trim_window(ref, output_path)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if result and Path(result).exists() and result == output_path:
            log.info("trim ok run_id=%s elapsed_ms=%d", run_id, elapsed_ms)
            return run_id, f"/media/{run_id}.mp4"
        log.warning(
            "trim failed run_id=%s cluster_id=%s elapsed_ms=%d",
            run_id, cluster_id, elapsed_ms,
        )
        return run_id, None

    results = await asyncio.gather(
        *[_trim_one(rid, ref) for rid, ref in zip(run_ids, refs)],
    )
    return [url for _rid, url in results if url is not None]


async def compile_segment(cluster_id: str) -> None:
    """Top-level entry. LLM work in parallel under 300s cap, then stitch sequentially.

    Phase 1 (LLM, 300s budget): orchestrator chain ‖ caption pipeline.
        Orchestrator chain saves segment row with run_ids + empty title/caption.
        Caption pipeline returns {caption, location, [title]} or None.
        Budget set to 300s to swallow long LLM latency variance and
        retry/throttle bursts without falling back to parent-id segments.
    Phase 2 (deterministic, 30s budget): stitch chosen runs into compiled.mp4.
        Pulled out of the LLM gather because stitch is fast and must not be
        cancelled by orchestrator-chain timeouts.
    Phase 3: single insert_segment combines both phases atomically.
    """
    started_at = time.time()
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
    })

    segment_id: str = ""
    video_url: str | None = None
    caption_result: dict | None = None

    try:
        # Phase 1: LLM work in parallel.
        results = await asyncio.wait_for(
            asyncio.gather(
                _run_orchestrator_chain(cluster_id),
                _branch_caption(cluster_id),
                return_exceptions=True,
            ),
            timeout=300.0,
        )
        a_result, b_result = results

        if isinstance(a_result, Exception):
            log.error("orchestrator chain failed: %s — using fallback", a_result)
            segment_id = await _save_fallback_segment(cluster_id, None)
        else:
            segment_id = a_result

        if isinstance(b_result, dict) and b_result.get("source") == "vision":
            caption_result = b_result
        elif isinstance(b_result, Exception):
            log.warning("caption pipeline failed: %s — using fallback caption", b_result)

        # Phase 1.5: deterministic parent-diversity guard. Patches the segment
        # row if angle-selector picked from < 2 distinct parents while the
        # cluster has 2+ available. Belt-and-suspenders alongside the prompt
        # constraint — LLM constraint compliance isn't guaranteed.
        if not isinstance(a_result, Exception):
            try:
                await _enforce_parent_diversity(cluster_id, min_parents=2)
            except Exception as exc:
                log.warning("parent diversity guard failed cluster_id=%s: %s", cluster_id, exc)

        # Phase 2: stitch each chosen run separately (only if orchestrator succeeded).
        # Separate 30s budget so a slow ffmpeg encode doesn't bleed into LLM
        # phase failures. Returns ordered list of /media URLs (one per run).
        run_video_urls: list[str] = []
        if not isinstance(a_result, Exception):
            try:
                run_video_urls = await asyncio.wait_for(
                    _stitch_segment_runs(cluster_id),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                log.warning("stitch TIMEOUT cluster_id=%s after 30s", cluster_id)
            except Exception as exc:
                log.warning("stitch failed cluster_id=%s: %s", cluster_id, exc)
        # First run's video doubles as the segment's headline video_url for
        # frontends that don't iterate video_urls.
        video_url = run_video_urls[0] if run_video_urls else None

        # Phase 3: re-insert with all updates landed.
        seg = await db.get_segment_for_cluster(cluster_id)
        if seg is not None:
            run_ids = (
                json.loads(seg["ordered_clip_ids"])
                if isinstance(seg.get("ordered_clip_ids"), str)
                else seg.get("ordered_clip_ids", [])
            )
            distinct_parents = len({rid.rsplit("_run_", 1)[0] for rid in run_ids})
            await db.insert_segment(
                cluster_id=cluster_id,
                ordered_clip_ids=run_ids,
                title=(caption_result.get("title", "") if caption_result else seg.get("title") or ""),
                caption=(caption_result["caption"] if caption_result else seg.get("caption") or ""),
                location=(caption_result["location"] if caption_result else seg.get("location") or "Pasadena, CA"),
                source_count=distinct_parents or seg.get("source_count", 1),
                video_url=video_url or seg.get("video_url"),
            )

        elapsed_ms = int((time.time() - started_at) * 1000)
        log.info(
            "compile success cluster_id=%s segment_id=%s elapsed_ms=%d video_url=%s",
            cluster_id, segment_id, elapsed_ms, video_url,
        )

    except asyncio.TimeoutError:
        log.warning("compile TIMEOUT cluster_id=%s after 300s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    except Exception:
        log.exception("compile FAILED cluster_id=%s — using fallback", cluster_id)
        segment_id = await _save_fallback_segment(cluster_id, video_url)
    finally:
        await db.set_compile_in_flight(cluster_id, False)

    await events.broadcast({
        "type": "segment_published",
        "cluster_id": cluster_id,
        "segment_id": segment_id,
    })

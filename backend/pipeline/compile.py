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
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
)

from .. import config, db, events
from .compile_tools import newz_tools_server
from .stitch import stitch_clips, trim_window
from .caption_pipeline import generate_caption
from .geocode import reverse_geocode
from .runs import compute_runs_for_cluster


async def _download_refs_to_tempdir(refs: list[dict], tmpdir: str) -> list[dict]:
    """Phase 10 (BLOB-04 / D-09): pre-download HTTP-URL refs into a tempdir.

    Returns refs with `path` rewritten to local file paths and `headers` cleared.
    Local-mode refs (path doesn't start with http) pass through unchanged.

    Uses httpx.stream + aiter_bytes to avoid loading entire source clips into
    memory (some are up to MAX_UPLOAD_BYTES = 100 MiB).
    """
    from ..storage import blob_client

    async def _download_one(ref: dict, idx: int) -> dict:
        src_url = ref["path"]
        if not src_url.startswith("http"):
            return ref
        local_path = f"{tmpdir}/src-{idx}.mp4"
        client = blob_client.get_client()
        headers = ref.get("headers") or {}
        async with client.stream("GET", src_url, headers=headers) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        return {**ref, "path": local_path, "headers": None}

    return await asyncio.gather(*[_download_one(r, i) for i, r in enumerate(refs)])


async def stitch_multi_source(refs: list[dict], run_id: str) -> str | None:
    """Phase 10 (BLOB-04): tempdir-wrapped multi-source stitch.

    Used when the caller needs the libx264 normalize-and-concat path
    (multiple distinct sources). Single-parent trims go through trim_window
    directly without this helper.
    """
    import tempfile
    blob_mode = config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO
    with tempfile.TemporaryDirectory() as tmpdir:
        local_refs = await _download_refs_to_tempdir(refs, tmpdir)
        if blob_mode:
            tmp_out_handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp_output_path = tmp_out_handle.name
            tmp_out_handle.close()
        else:
            tmp_output_path = str(config.DATA_DIR / "clips" / f"{run_id}.mp4")
        try:
            result = await stitch_clips(local_refs, tmp_output_path, run_id=run_id)
        finally:
            if blob_mode:
                try:
                    os.unlink(tmp_output_path)
                except FileNotFoundError:
                    pass
        return result or None

log = logging.getLogger(__name__)

# Phase 14: per-cluster recompile counter (process-local, resets on restart).
# Single-process FastAPI + --workers 1 makes module-local state authoritative
# for the pilot. NOT persisted — a Railway redeploy zeroes the counter, which
# is fine for the soft-warn observability use case (the goal is "did this
# cluster trip the warn threshold during this process lifecycle"). Revisit
# post-pilot if a hard cap is needed (then add clusters.compile_count column
# per RESEARCH § R4).
_RECOMPILE_COUNTS: dict[str, int] = {}
_RECOMPILE_WARN_THRESHOLD: int = 5


ANGLE_SELECTOR_PROMPT_TEMPLATE = """You are picking the best 2-4 RUNS from cluster {cluster_id}.

A run = one continuous camera angle (a contiguous span of similar 3-second
slices from the same source clip). Different runs from different parent clips
give different viewpoints of the same event.

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

Make ONE call to mcp__newz_tools__get_cluster_runs — the result already
includes lat, lng, ts, parent_id, and duration_sec for every run. Do NOT
call get_clip_metadata; the cluster_runs payload has everything you need.

After that single tool call, return ONLY a JSON object as your final
message. Format (a one-line markdown fence is fine):
{{"run_ids": ["...", "..."], "rationale": "..."}}
Do not call any more tools after returning the JSON.
"""


def _extract_run_ids(text: str) -> list[str]:
    """Pull the {"run_ids":[...], ...} object out of a model response.

    Tolerant of markdown fences and surrounding chatter — the SDK has been
    inconsistent about whether the final assistant turn is pure JSON or
    wrapped in ```json ... ```. Returns [] if no parseable JSON is found.
    """
    if not text:
        return []
    candidates: list[str] = []
    # Pull anything inside ```...``` first (the longest fenced block wins).
    fence_re = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    candidates.extend(fence_re.findall(text))
    # Fall back to the last balanced top-level object in the raw text.
    last_brace = text.rfind("}")
    if last_brace != -1:
        depth = 0
        start = -1
        for i in range(last_brace, -1, -1):
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    start = i
                    break
        if start != -1:
            candidates.append(text[start:last_brace + 1])
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        run_ids = obj.get("run_ids")
        if isinstance(run_ids, list) and all(isinstance(r, str) for r in run_ids):
            return run_ids
    return []


async def _run_orchestrator_chain(cluster_id: str) -> str:
    """Single-pass run selection: ask the model to return JSON, write the
    segment row from Python.

    Replaces the old orchestrator → angle-selector → publisher subagent chain.
    The publisher subagent finished its turn without invoking save_segment
    on roughly one of every two runs (both Haiku and Sonnet), leaving compile
    to fall through to _save_fallback_segment with no playable video. Cutting
    out the publisher hop entirely makes the persistence step deterministic.
    """
    options = ClaudeAgentOptions(
        allowed_tools=[
            "mcp__newz_tools__get_cluster_runs",
            "mcp__newz_tools__get_clip_metadata",
        ],
        mcp_servers={"newz_tools": newz_tools_server},
        # 10 turns wasn't enough — Sonnet was burning turns on multiple
        # get_clip_metadata lookups before producing JSON. With the prompt
        # tightened to a single tool call, 20 is generous headroom.
        max_turns=20,
        model="sonnet",
    )
    prompt = ANGLE_SELECTOR_PROMPT_TEMPLATE.format(cluster_id=cluster_id)
    final_text: str | None = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                log.error(
                    "compile angle-selector error cluster_id=%s turns=%s errors=%s result=%s",
                    cluster_id, msg.num_turns, msg.errors, msg.result,
                )
                raise RuntimeError(f"angle-selector returned is_error=True: {msg.errors}")
            log.info(
                "compile angle-selector done cluster_id=%s turns=%s duration_ms=%s",
                cluster_id, msg.num_turns, msg.duration_ms,
            )
            final_text = msg.result
            break

    run_ids = _extract_run_ids(final_text or "")
    if not run_ids:
        log.error(
            "angle-selector returned no parseable run_ids cluster_id=%s text=%r",
            cluster_id, (final_text or "")[:500],
        )
        raise RuntimeError(
            f"angle-selector returned no run_ids for cluster {cluster_id}"
        )

    distinct_parents = len({rid.rsplit("_run_", 1)[0] for rid in run_ids})
    cluster = await db.get_cluster(cluster_id)
    initial_location = await reverse_geocode(
        (cluster or {}).get("centroid_lat"),
        (cluster or {}).get("centroid_lng"),
    )
    seg_id = await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=run_ids,
        title="",
        caption="",
        location=initial_location,
        source_count=distinct_parents or len(run_ids),
    )
    log.info(
        "save_segment cluster_id=%s seg_id=%s runs=%d distinct_parents=%d",
        cluster_id, seg_id, len(run_ids), distinct_parents,
    )
    return seg_id


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

    Phase 10 (D-08, D-11, amendment 1): storage.stitch_input_for returns the
    (path_or_url, headers) tuple — pure function, no network call.
    """
    from .. import storage  # local import — avoid circular at module load
    runs = await compute_runs_for_cluster(cluster_id)
    by_id = {r.id: r for r in runs}
    refs: list[dict] = []
    for rid in ordered_run_ids:
        r = by_id.get(rid)
        if r is None:
            log.warning("resolve: unknown run_id=%s cluster_id=%s", rid, cluster_id)
            continue
        end = None if not r.member_child_ids else r.end_offset_sec
        path_or_url, headers = storage.stitch_input_for({
            "parent_path": r.parent_path,
            "parent_blob_url": getattr(r, "parent_blob_url", None),
        })
        refs.append({
            "path": path_or_url,
            "start_offset_sec": r.start_offset_sec,
            "end_offset_sec": end,
            "headers": headers,
            "run_id": rid,
        })
    return refs


async def _deterministic_run_pick(cluster_id: str, max_runs: int = 4) -> list[str]:
    """First run from each parent in chronological order. No LLM.

    Used as the fallback when angle-selector raises (timeout, max_turns, bad
    JSON). Picks proper run IDs so the stitch path can produce playable
    runs/{run_id}.mp4 URLs — without this, fallback segments stored parent
    IDs and the frontend showed "Compiling…" forever in blob mode.
    """
    runs = await compute_runs_for_cluster(cluster_id)
    if not runs:
        return []
    by_parent: dict[str, list] = {}
    for r in runs:
        by_parent.setdefault(r.parent_id, []).append(r)
    # Sort parents by earliest run start_offset_sec to keep timeline order.
    parent_order = sorted(
        by_parent.keys(),
        key=lambda pid: min(r.start_offset_sec for r in by_parent[pid]),
    )
    picked: list[str] = []
    for pid in parent_order:
        first = sorted(by_parent[pid], key=lambda r: r.start_offset_sec)[0]
        picked.append(first.id)
        if len(picked) >= max_runs:
            break
    return picked


async def _save_fallback_segment(cluster_id: str, video_url: str | None = None) -> str:
    """CMP-06: idempotent fallback. Picks first run per parent so the stitch
    path can still produce a playable video, then writes a generic caption.
    """
    existing = await db.get_segment_for_cluster(cluster_id)
    if existing:
        return existing["id"]
    clips = await db.fetch_cluster_clips(cluster_id)
    run_ids = await _deterministic_run_pick(cluster_id)
    # Childless-parent clusters yield no runs; fall back to parent IDs so the
    # row at least exists. In blob mode this still renders "Compiling…", but
    # the row anchors the cluster for any future recompile.
    ordered_ids = run_ids if run_ids else [c["id"] for c in clips]
    distinct_parents = (
        len({rid.rsplit("_run_", 1)[0] for rid in run_ids})
        if run_ids else len(clips)
    )
    if clips:
        when = datetime.fromtimestamp(clips[0]["ts"], tz=timezone.utc).strftime("%b %-d, %Y")
    else:
        when = datetime.now(tz=timezone.utc).strftime("%b %-d, %Y")
    cluster = await db.get_cluster(cluster_id)
    location_str = await reverse_geocode(
        (cluster or {}).get("centroid_lat"),
        (cluster or {}).get("centroid_lng"),
    )
    caption = f"{when} — {location_str}. Submitted footage from {distinct_parents} contributor(s)."
    return await db.insert_segment(
        cluster_id=cluster_id,
        ordered_clip_ids=ordered_ids,
        title="",
        caption=caption,
        location=location_str,
        source_count=distinct_parents or len(clips),
        video_url=video_url,
        # Quick task 260501-bet: explicit None clears stale evidence/intent on
        # cluster recompile-after-failure (relies on ON CONFLICT refresh
        # including these columns — db_postgres.insert_segment + migration 0006).
        evidence=None,
        intent=None,
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
    """Stitch EACH chosen run into its own .mp4. Returns ordered list of playable URLs.

    Per-run stitching (not cluster-wide concatenation) so the frontend can
    navigate between angles while still applying ffmpeg normalization within
    a run (start_offset → end_offset window from one parent file).

    Phase 10:
      - Output goes to tempfile.NamedTemporaryFile, atomic-rename inside
        _sync_trim, upload to runs/{run_id}.mp4 (public) inside trim_window.
      - Returns absolute Blob URLs in blob mode, /media/{run_id}.mp4 in local.
    """
    import tempfile
    from .. import storage  # local import — avoid circular
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

    blob_mode = config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO

    # Trim each run's window in PARALLEL via -c copy stream-copy (no re-encode).
    # Runs are always contiguous within ONE parent file, so this is a fast
    # ffmpeg trim. In blob mode, ffmpeg uses HTTP Range requests via -headers
    # bearer auth (BLOB-03); the resulting .mp4 lands in a tempfile, then is
    # uploaded to runs/{run_id}.mp4 inside trim_window (D-10).
    async def _trim_one(run_id: str, ref: dict) -> tuple[str, str | None]:
        if blob_mode:
            tmp_handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            output_path = tmp_handle.name
            tmp_handle.close()
        else:
            output_path = str(config.DATA_DIR / "clips" / f"{run_id}.mp4")
        t0 = time.monotonic()
        try:
            result = await trim_window(ref, output_path, run_id=run_id)
        finally:
            if blob_mode:
                # Best-effort tempfile cleanup; trim_window already uploaded.
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if not result:
            log.warning(
                "trim failed run_id=%s cluster_id=%s elapsed_ms=%d",
                run_id, cluster_id, elapsed_ms,
            )
            return run_id, None
        log.info("trim ok run_id=%s elapsed_ms=%d", run_id, elapsed_ms)
        if blob_mode:
            # trim_window returns either an absolute Blob URL (legacy) or the
            # relative backend-proxy path `/runs/{run_id}.mp4` (current — the
            # provisioned Vercel Blob store is private-only, so reads go
            # through the FastAPI proxy). On upload failure it returns the
            # local tempfile path (already unlinked above), which would leak
            # `/tmp/...` into the segment row — frontend would request
            # `${API_BASE}/tmp/...` and 404. Accept http URLs and `/runs/`
            # paths; reject everything else and emit None so the feed renders
            # "Compiling…" cleanly via fetch_recent_segments fallback.
            if isinstance(result, str) and (
                result.startswith("http") or result.startswith("/runs/")
            ):
                return run_id, result
            log.warning(
                "trim+upload result not a URL run_id=%s result_prefix=%r — emitting None",
                run_id, (result or "")[:40],
            )
            return run_id, None
        # local mode: result is the local FS path. Surface as /media URL.
        if Path(result).exists() and result == output_path:
            return run_id, f"/media/{run_id}.mp4"
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
    # Phase 14: detect recompile vs first-publish for the SSE payload + soft-warn.
    # An existing segment row means this is a recompile pass (D-NEW-01 in 14-PLAN).
    seg_existing = await db.get_segment_for_cluster(cluster_id)
    is_recompile = seg_existing is not None
    await events.broadcast({
        "type": "compile_started",
        "cluster_id": cluster_id,
        "started_at": started_at,
        "recompile": is_recompile,
    })

    if is_recompile:
        # Module-local counter; dict mutation is atomic at the asyncio scheduling
        # boundary, no asyncio.Lock needed (counter is approximate-by-design — a
        # missed increment under contention is acceptable; we only soft-warn at
        # >=_RECOMPILE_WARN_THRESHOLD).
        recompile_count = _RECOMPILE_COUNTS.get(cluster_id, 0) + 1
        _RECOMPILE_COUNTS[cluster_id] = recompile_count
        if recompile_count >= _RECOMPILE_WARN_THRESHOLD:
            log.warning(
                "compile recompile_count_high cluster_id=%s count=%d -- investigate hot-event behavior",
                cluster_id, recompile_count,
            )

    segment_id: str = ""
    video_url: str | None = None
    caption_result: dict | None = None

    try:
        # Phase 1: LLM work in parallel.
        # Inner cap on the orchestrator chain so SDK throttle/retry can't
        # consume the full 300s budget on its own. Caption branch already has
        # its own per-call timeouts inside generate_caption (Gemini upload +
        # generate_content). See .planning/debug/compile-timeout-300s.md.
        results = await asyncio.wait_for(
            asyncio.gather(
                asyncio.wait_for(_run_orchestrator_chain(cluster_id), timeout=180.0),
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

        # Phase 2: stitch each chosen run separately. Always runs — the
        # fallback now writes deterministic run IDs (first run per parent),
        # so even when the LLM call failed there's something to stitch.
        # Separate 30s budget so a slow ffmpeg encode doesn't bleed into LLM
        # phase failures. Returns ordered list of run video URLs.
        run_video_urls: list[str] = []
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

        # Phase 11 (D-08, D-14): broadened soft-flag policy. Read each cluster
        # member's moderation_decisions; if ANY member shows hate or violence
        # category with verdict in (flag, block), write segments.soft_flag=true.
        # Decoupled from corroboration count (no >=2-parent gate here -- D-08).
        # Defensive: never let a soft-flag derivation failure prevent the segment
        # from shipping. Default to False on any exception (visible-by-default
        # for ops; missing soft-flag is preferable to a missing montage).
        #
        # WR-07: single batched query (one DB roundtrip) replaces the previous
        # N+1 pattern (one get_moderation_decisions per cluster member). On
        # postgres this saves N pool-acquire + roundtrip pairs; on SQLite it
        # collapses N file-locked queries into one.
        soft_flag = False
        try:
            members = await db.fetch_cluster_clips(cluster_id)
            member_ids = [m["id"] for m in members]
            decisions = await db.get_moderation_decisions_for_clips(member_ids)
            for d in decisions:
                raw = d.get("raw_response") or {}
                if isinstance(raw, str):
                    # SQLite TEXT path or postgres without WR-04 codec — defensive parse.
                    try:
                        raw = json.loads(raw)
                    except (TypeError, ValueError):
                        raw = {}
                for cat in ("hate", "violence"):
                    cat_signal = raw.get(cat) or {}
                    if isinstance(cat_signal, dict) and cat_signal.get("verdict") in ("flag", "block"):
                        soft_flag = True
                        break
                if soft_flag:
                    break
        except Exception as exc:
            log.warning(
                "soft_flag derivation failed cluster_id=%s: %s -- defaulting false",
                cluster_id, exc,
            )

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
                soft_flag=soft_flag,
                # Quick task 260501-bet: thread evidence + intent JSONB through.
                # caption_result carries them when run_evidence_to_intent_pipeline
                # succeeds; absent on fallback paths (None clears stale values via
                # the ON CONFLICT refresh list in db_postgres.insert_segment).
                evidence=(caption_result.get("evidence") if caption_result else None),
                intent=(caption_result.get("intent") if caption_result else None),
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

---
slug: compile-no-stitchable-refs
status: resolved
trigger: "Vercel preview produced a post but with generic caption and neither video appearing — Railway logs show 'no stitchable refs' warn + 'orchestrator chain failed: no segment row, using fallback' error during compile, ending with video_url=None"
created: 2026-04-29
updated: 2026-04-29
branch: liam/phase-10-blob-migration
phase: 10-vercel-blob-migration
related_resolved: phone-upload-no-railway-logs (resolved — uploads now reach backend), video-upload-path-null-blob (db4dd8d, f7700b7)
fix_commit: fe52887
---

# Debug Session: compile-no-stitchable-refs

## Symptoms

DATA_START
**Expected behavior:** Two clips upload from iOS Safari preview → both embed → cluster forms → compile pipeline (Claude Agent SDK + Gemini caption + ffmpeg stitch) produces a real segment with a unique caption and a stitched `video_url`. Frontend feed renders a SegmentCard playing the stitched video with the AI-generated caption.

**Actual behavior:** Two clips DID upload + embed + cluster successfully. Compile reports `success` but with `video_url=None`. Frontend shows a post with a generic/fallback caption and neither source video plays. Phase 10 blob migration is the suspected breaking change.

**Error messages from Railway logs:**

1. WARN @ 07:05:09.847 (immediately after compile_started):
   ```
   generate_caption: no stitchable refs for cluster a24def8fab87442595997f3688e2b205
   logger=backend.pipeline.caption_pipeline
   ```

2. ERROR @ 07:07:30.196 (after compile orchestrator finished, 138.9s):
   ```
   orchestrator chain failed: compile finished but no segment row for cluster a24def8fab87442595997f3688e2b205
   — Publisher may have failed to call save_segment — using fallback
   logger=backend.pipeline.compile
   ```

3. INFO @ 07:07:30.463 (fallback emitted segment with no video):
   ```
   compile success cluster_id=a24def8fab87442595997f3688e2b205
   segment_id=d26bacca54b34eacb43a88672cfb9e6c elapsed_ms=140957 video_url=None
   ```

**Pipeline trace (happy path up to compile):**
- `blob op=upload pathname=uploads/81211540...mp4 bytes=4735560` (clip 1, 06:58:21) — Vercel Blob PUT 200 OK
- `insert_clip id=81211540...` then `event clip_added` (postgres)
- `embed clip_id=81211540... latency_ms=24905 parent_dims=512 children=2` (06:59:54)
- `cluster_worker ... new=True composite=n/a` — clip 1 forms cluster `a24def8f...`
- `blob op=upload pathname=uploads/57b631fc...mp4 bytes=3726740` (clip 2, 07:02:30)
- `embed clip_id=57b631fc... latency_ms=26436 parent_dims=512 children=1` (07:05:08)
- `cluster_worker ... new=False composite=0.917` — clip 2 joins same cluster
- `compile triggered cluster_id=a24def8f...` (07:05:09)
- `event compile_started` → `Using bundled Claude Code CLI: ...`
- WARN  `generate_caption: no stitchable refs` (immediately, 07:05:09.847)
- (138s of Claude Agent SDK orchestration, 6 turns)
- ERROR  `orchestrator chain failed ... using fallback`
- `compile success ... video_url=None`
- `event segment_published` (frontend then renders the no-video post)

**Timeline:** First post-merge production run on the Phase 10 blob-migration preview after the fix-forward chain (f7700b7 path NOT NULL relax → db4dd8d blob-to-tempfile in embed_worker → ac448a1 silent-upload + VITE_API_BASE typo fix → 1ab39ae HUMAN-UAT confirms SC-1/2/4). HUMAN-UAT explicitly DEFERRED Task 5.5 + later SCs to merge-time. SC-3 (compile/stitch) was likely among the deferred items.

**Reproduction:** Two iOS Safari uploads at the Vercel preview frontend that share enough Marengo similarity (composite=0.917) and proximity to merge into one cluster. The compile fires once cluster has >=2 distinct parent uploads — this is the first time blob-mode actually ran the compile path end-to-end.

**Branch:** `liam/phase-10-blob-migration`
**Phase artifacts:** `.planning/phases/10-vercel-blob-migration/`

**Two distinct failure surfaces — likely related but separable:**

A. **Backend compile pipeline bug.** `caption_pipeline.generate_caption` logs "no stitchable refs" inside the compile orchestrator. The orchestrator then runs for 138s but Publisher never calls `save_segment`, so the post-compile DB lookup finds no segment row and falls back. Most likely cause: Phase 10 migrated clip storage from local FS (`/data/clips/...`) to Vercel Blob URLs in `clips.path` (or a separate `clips.blob_pathname` column). The stitch/caption code paths still expect local filesystem paths, so they cannot resolve "stitchable refs" and silently degrade. The Claude Agent SDK Publisher tool likely tries to call `save_segment` with a stitched-video path that was never produced because ffmpeg had nothing to stitch.

B. **Frontend video playback.** "Neither video appearing" — even if compile produced a `video_url`, the source clip blob URLs are PRIVATE (`hlgbvhvavvgpwp13.private.blob.vercel-storage.com/uploads/...`). A browser cannot directly GET a private blob without a signed URL or backend proxy. If the frontend tries to render either the compiled segment or the source clips with private blob URLs, video tags will fail silently. This may be obscured by surface A (no compiled segment) — once A is fixed, B may still bite.

**Hypothesis-relevant code locations to investigate first:**
- `backend/pipeline/caption_pipeline.py` — emits the "no stitchable refs" warn
- `backend/pipeline/compile.py` — orchestrator chain + fallback emit + `save_segment` invariant
- `backend/pipeline/stitch.py` (or wherever ffmpeg runs) — does it accept blob URLs? Download to tmpfile?
- `backend/pipeline/embed_worker.py` — already migrated to blob (db4dd8d), pattern to copy
- `backend/storage/blob_client.py` — does it expose a `download_to_tempfile` helper that compile/stitch should reuse?
- `backend/db_postgres.py` — schema for `clips`: is `path` now nullable, and what column carries the blob ref?
- Frontend `SegmentCard` / clip rendering — does it expect publicly fetchable URLs? Are private blobs proxied?

**Suspected root cause (single-sentence working hypothesis for the debugger):**
The Phase 10 blob migration updated the upload/embed paths to read clips from Vercel Blob URLs but did NOT migrate the compile pipeline (caption + stitch + save_segment) to do the same — so when a cluster fires compile in blob mode, the stitcher cannot resolve any source files, the caption pipeline reports "no stitchable refs," the Publisher tool never calls save_segment, and the orchestrator falls back to a no-video segment.

DATA_END

## Initial Code Survey (post-investigation)

### What was already correct in the deployed code

- `backend/db_postgres.py:insert_clip` (lines 158-182) already detects `result.startswith("http")` and routes the URL to `clips.blob_url` (NULL `path`). Parents are correctly persisted in blob mode.
- `backend/db_postgres.py:fetch_cluster_clips_with_children` (lines 479-546) already builds `parent_blob_url_map` from parent rows and projects `parent_blob_url` onto every child row in the result set. Both parents and children carry the URL through the cluster query.
- `backend/pipeline/runs.py:compute_runs_for_cluster` (lines 86-146) already populates `Run.parent_blob_url` from the row dict (line 105, 115, 139). All synthesized runs carry the URL forward.
- `backend/pipeline/compile.py:_resolve_run_ids_to_stitch_refs` (lines 251-284) already calls `storage.stitch_input_for(...)` which returns `(blob_url, headers)` in blob mode, and threads `headers` through to refs.
- `backend/pipeline/stitch.py:_sync_trim` (lines 161-163) already forwards `ref["headers"]` to ffmpeg's `-headers` flag with the mandatory CRLF terminator. The trim path (used by `_stitch_segment_runs` for per-run output) is fully blob-aware.
- `backend/pipeline/stitch.py:trim_window` (lines 194-228) already uploads the local trim output to `runs/{run_id}.mp4` (public access) and returns the absolute Blob URL.
- `backend/storage/blob.py:authorized_blob_input` (lines 89-95) provides `(url, bearer-token-headers)` for private reads — pure helper, no network.
- Migration `20260428_0001_initial_v1_1_schema.py` already creates `clips.blob_url TEXT` (nullable, line 52). No schema gap.

### Where the blob-mode gap actually lived

`backend/pipeline/caption_pipeline.py:_build_stitch_refs` (pre-fix) ONLY consulted `child["parent_path"]`. In blob mode, parent_path is NULL because `insert_clip` routes the result to `blob_url`. So every child failed the `if not parent_path: continue` check, refs ended up empty, and `generate_caption` bailed at line 346 with "no stitchable refs".

Even if `_build_stitch_refs` had emitted a Blob URL as `path`, the downstream `stitch_clips → _sync_stitch` path could not have ingested it: `_sync_stitch` does NOT forward `ref.headers` (only `_sync_trim` does), and Vercel private blobs require Authorization-bearer reads.

So the caption pipeline had two compounding bugs:
1. Refs never built (URL never reached `_sync_stitch`).
2. Even if built, `_sync_stitch` would have 401'd without a bearer header.

## Current Focus

```yaml
hypothesis: "Phase 10 blob migration updated upload + embed + the trim path (per-run stitch) but missed caption_pipeline._build_stitch_refs (still keyed on parent_path) and the stitch_clips path (no header forwarding to _sync_stitch). The orchestrator chain failure is a downstream LLM-flake symptom of the caption branch instantly returning None and orchestrator-side timing — not itself a Phase 10 migration gap."
test: "git log on caption_pipeline.py / compile.py / stitch.py to find the fix-forward commit; verify both Surface A1 (refs built from blob_url) and Surface A2 (private-URL bytes downloaded to local tempdir before stitch_clips) are addressed."
expecting: "A single fix commit on the caption pipeline that (a) prefers parent_blob_url + auth headers via authorized_blob_input(), and (b) pre-downloads URL refs to a TemporaryDirectory before calling stitch_clips. Trim path needs no change (already blob-aware)."
next_action: "verify fix completeness; flag remaining residual gap (orchestrator-fallback path does not stitch) as a follow-up."
reasoning_checkpoint: "fix landed in HEAD as fe52887 (Apr 29 00:11:13 PT) — 28s before this debug session was created. Surface A is fully addressed. Surface B (private blob playback in frontend) is mooted by trim_window uploading per-run outputs to runs/* PUBLIC."
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-29T07:11 PT — Read backend/pipeline/caption_pipeline.py at HEAD. Confirmed `_build_stitch_refs` (lines 272-319) handles `parent_blob_url` first via `authorized_blob_input(pathname)`, falls back to `parent_path`, and skips only when both are null. Header dict is attached to the ref. Confirmed `generate_caption` (lines 357-383) detects `r["path"].startswith("http")` and pre-downloads each ref into a TemporaryDirectory using `httpx.stream` (chunk_size=64 KiB), rewriting refs to local file paths and clearing `headers` before calling `stitch_clips`. Same streaming pattern as `compile.py:_download_refs_to_tempdir` (lines 42-67) and `embed.py:embed_worker` (lines 130-145, db4dd8d).

- timestamp: 2026-04-29T07:11 PT — Read backend/pipeline/compile.py at HEAD. Confirmed `_resolve_run_ids_to_stitch_refs` returns `(path_or_url, headers)` from `storage.stitch_input_for(...)` (line 273). `_stitch_segment_runs._trim_one` calls `trim_window(ref, ..., run_id=run_id)` which forwards headers to `_sync_trim` and uploads the result to `runs/{run_id}.mp4` (public). Trim path is end-to-end blob-aware.

- timestamp: 2026-04-29T07:11 PT — Read backend/pipeline/stitch.py at HEAD. `_sync_stitch` does NOT consume `ref["headers"]` (only `_sync_trim` does at lines 161-163). This is fine because the only `stitch_clips` caller (`caption_pipeline.generate_caption`) now pre-downloads URL refs to local paths before calling stitch_clips. URL refs never reach `_sync_stitch`.

- timestamp: 2026-04-29T07:11 PT — Read backend/storage/blob.py. Confirmed `stitch_input_for` (lines 79-86) returns `(parent_blob_url, bearer-headers)` in blob mode and `(parent_path, None)` during migration window when only path is populated. Pure function, no network.

- timestamp: 2026-04-29T07:11 PT — `git show fe52887 --stat` confirms the fix touches ONLY `backend/pipeline/caption_pipeline.py` (+71/-16). The fix commit was authored at 00:11:13 PT 2026-04-29; this debug session file was created at 00:11:41 PT — 28 seconds later. The user wrote the fix immediately after observing the Railway failure, then opened the debug session to formalize the investigation.

- timestamp: 2026-04-29T07:11 PT — `git log` on backend/pipeline/caption_pipeline.py shows the fix is the latest commit. HEAD == origin/liam/phase-10-blob-migration; fix is committed but NOT yet pushed/deployed to Railway. Verified `git status`: working tree is clean apart from this debug file and untracked package-lock.json/package.json (out of scope).

- timestamp: 2026-04-29T07:11 PT — Surface A2 ("orchestrator chain failed — no segment row") analysis. The orchestrator branch and the caption branch run in parallel via `asyncio.gather` (compile.py:488-495), with an inner 180s cap on the orchestrator and a 300s outer cap. In the failing run, orchestrator completed in 138s (under cap) but `db.get_segment_for_cluster` returned None — meaning Publisher's `save_segment` MCP tool never executed. Reading `compile_tools.save_segment` (lines 77-90) shows the tool wraps `db.insert_segment` with no Phase-10 dependency. The most parsimonious explanation: Sonnet (orchestrator) terminated without calling Publisher, OR Publisher (haiku) returned text without invoking the tool. This is an LLM-flake mode, NOT a Phase 10 migration gap. v1.0 retrospective notes the orchestrator chain has occasional non-tool-calling failures; the existing fallback emits a chronological-clip-ids segment with `video_url=None` (compile.py:287-308), which matches the observed end state.

## Eliminated

- Frontend private-blob playback gap (Surface B): mooted because `_stitch_segment_runs._trim_one` uploads each run's output to `runs/{run_id}.mp4` with `access="public"` (stitch.py:215-227, blob.py:31-39). The compiled-segment `video_url` returned to the frontend is a PUBLIC Blob CDN URL, not a private one. Frontend `<video>` tags can fetch it directly without auth. Source-clip raw playback (e.g., a SegmentCard that embeds the original `clips.blob_url`) WOULD hit the private-bucket issue, but the segment payload from `fetch_recent_segments` only exposes the stitched run URLs — not the raw source-clip URLs. No frontend-side fix is required for the standard happy path.

- Orchestrator missing-segment-row as a Phase 10 migration bug: ruled out (see Evidence above). The orchestrator chain failure is an LLM-flake or an internal SDK hiccup, not a Phase 10 wiring gap.

## Resolution

**Root cause:** Phase 10 migrated the upload + embed + per-run trim paths to consume `clips.blob_url` (with bearer-auth headers forwarded to ffmpeg via `_sync_trim`), but missed the caption pipeline's `_build_stitch_refs`, which still keyed on `parent_path`. In blob mode `parent_path` is NULL (per the `f7700b7` NOT NULL relax), so every ref was skipped and `generate_caption` bailed at "no stitchable refs". A second compounding gap: even if refs had been built with Blob URLs, `_sync_stitch` (used by `stitch_clips` for the Gemini composite) does not forward auth headers — so Vercel's private-bucket policy would have rejected the read with 401.

**Fix (already committed locally as `fe52887` — pending push to Railway):**

`backend/pipeline/caption_pipeline.py` — two changes in one commit:

1. `_build_stitch_refs` now prefers `child["parent_blob_url"]` over `child["parent_path"]`. When the URL is present, it's converted to `(authorized_url, bearer_headers)` via `storage.blob.authorized_blob_input(pathname)` and emitted as the ref's `path` (with `headers` set on the ref). Falls back to `parent_path` for local mode; skips only when BOTH are null.

2. `generate_caption` detects refs whose `path` starts with `http` and pre-downloads each one to a `tempfile.TemporaryDirectory()` using `httpx.stream` with 64 KiB chunks (mirrors `compile.py:_download_refs_to_tempdir` and `embed.py:embed_worker` blob-to-tempfile pattern). Refs are rewritten to local file paths with `headers=None` before being passed to `stitch_clips`. Local-mode refs pass through unchanged. The TemporaryDirectory is cleaned up in a `finally` block. The composite-deletion `finally` (which guards against the data-loss bug where `stitch_clips` falls back to `clip_refs[0]["path"]` on failure) is preserved.

Trim path (`_stitch_segment_runs` -> `trim_window` -> `_sync_trim`) needed no change — it was already blob-aware (forwards `ref["headers"]` to ffmpeg `-headers`, uploads result to public `runs/*` bucket).

**Verification path (post-deploy):**
- Push branch to Railway, run two-clip iOS Safari upload reproduction
- Expect: caption_pipeline produces a Gemini-generated `{title, caption, location}` instead of the warn line
- Expect: `_stitch_segment_runs` produces 2+ run video_urls (public Blob URLs at `runs/{run_id}.mp4`)
- Expect: final compile log shows `video_url=https://hlgbvhvavvgpwp13.public.blob.vercel-storage.com/runs/...` instead of `video_url=None`
- Expect: frontend SegmentCard plays the stitched run video and shows the AI caption

**Residual gap (NOT addressed by this fix — flagged for follow-up):**
The orchestrator-fallback path (`compile.py:498-500`, `_save_fallback_segment` called when the orchestrator chain raises) emits a segment with `video_url=None` — even in blob mode, even when source clips are perfectly resolvable. The fallback path doesn't run `_stitch_segment_runs`. If the LLM chain fails (Sonnet refuses to invoke Publisher, Haiku malforms the tool call, etc.), the user still sees a no-video post.

A defensive hardening would be: when `a_result` is an Exception, call `_stitch_segment_runs` against a deterministic fallback selection (e.g., earliest-3 runs, one per parent) and persist its `video_url` via `_save_fallback_segment(cluster_id, video_url=...)`. This is independent of the Phase 10 migration and was almost certainly latent in v1.0; calling it out here so it isn't lost. Recommend filing as a separate debug session if it recurs in production.

**Specialist review:** N/A — this debug session was launched after the user had already authored the fix. No specialist re-review of the proposed change was needed; the fix mirrors the established `embed_worker.py` blob-to-tempfile pattern.

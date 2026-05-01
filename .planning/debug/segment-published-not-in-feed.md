---
slug: segment-published-not-in-feed
status: inconclusive-needs-prod-db-check
trigger: "even though the event is getting published its not appearing in the feed"
created: 2026-04-30
---

# segment_published fires but montage doesn't appear in feed

## Symptoms

User reports: backend Railway logs show `event segment_published` firing for a cluster, but the resulting montage does not appear in the feed UI.

### Key log evidence (deployment `e753db23-3592-407c-852c-e459acdb4b4f`)

- **Pipeline ran cleanly:**
  - Marengo embed succeeded (`embed clip_id=51bc7e0e5f0746c78c88b4ecfeda23ae latency_ms=...`)
  - Clustering: `cluster_id=f021db1cc22440fa9f7e9363dcc25c10 new=False composite=0.762`
  - Two parent runs re-trimmed and re-uploaded:
    - `f428a560c2a342b0a48a5435d1b9c06f_run_0.mp4`
    - `ca0f10ab9e3f4e7eacffb6d9a9ce6751_run_0.mp4` (also `c6301a4d88ac4cd6aac726aa2fe92298` and `634d8ffd397d43009bdb7fed687ae2df`)
  - Caption generated: "Man Reacts To Soccer Game"
  - `event segment_published` fired at `2026-05-01T03:19:56.316535Z`

- **Cluster was existing → Phase 14 recompile path** (`new=False`).

- **Earlier in the batch:** clip `9c07e82c53154e5480515b7209e38cd3` was hidden by moderation
  (`reason=classifier_unknown_error — clip hidden, queued for admin`). Unrelated.

- **SSE pipe is alive:** logs show `sse subscribe total=1` and `total=2`.

## Investigation findings

### Backend code path is correct

Walked the recompile path end-to-end:

- `backend/pipeline/run.py:189` — `_should_recompile` correctly fires `compile_segment` task.
- `backend/pipeline/compile.py:243` — `_run_orchestrator_chain` calls `db.insert_segment`.
- `backend/db_postgres.py:339` — `insert_segment` uses `ON CONFLICT(cluster_id) DO UPDATE`,
  preserving the segment id but refreshing `ordered_clip_ids`, `title`, `caption`,
  `location`, `source_count`, `video_url`, `soft_flag`. **`created_at` is intentionally
  NOT updated** (only in INSERT, not in UPDATE clause).
- `backend/pipeline/compile.py:683` — Phase 3 final insert writes correct caption + video_url.
- `backend/pipeline/compile.py:718` — `events.broadcast({type: "segment_published", ...})`.
- `backend/events.py:30` — `log.info("event %s", ...)` confirms broadcast() ran.

### Frontend SSE handler is correct (and unchanged for Phase 14)

- `frontend/src/views/Feed.tsx:60` — both `segment_published` and `cluster_assigned`
  trigger `void refetchFeed()`, which calls `fetchSegments()` → `GET /feed`.
- `fetch_recent_segments` (db_postgres.py:379) — no hidden filter; JOIN on clusters
  succeeds because the cluster row exists (created in cluster_worker upsert,
  `is_new_cluster=False` proves it's already there).

### Per Phase 14 design, recompile updates the card in place — does NOT bubble to top

`14-RESEARCH.md:224` documents the chosen design:

> When the recompile re-emits `segment_published` for an existing `cluster_id`, the
> `segments` table row is UPDATEd (not INSERTed), so the segment id is unchanged.
> The next `fetchSegments()` call returns a `Segment` with the same id but updated
> fields. React's `setSegments(next)` triggers a diff; `FeedShell` re-renders with
> the updated card.

This is intentional: `created_at` is preserved on `ON CONFLICT DO UPDATE` so the
segment stays at its original feed position. **The recompiled montage will NOT
appear at the top of the feed** — it stays where it was originally published.

## Most likely root cause

**This is most likely a UX/observability mismatch, not a code regression.**

The user expected the recompiled montage to surface as a fresh entry at the top of
the feed (the way a first-compile does). By Phase 14 design, recompile updates the
existing card in place — it stays at its original `created_at` position.

If many newer segments have been published since the original first-compile, the
recompiled card may be below the fold. The user is interpreting "no new card at
the top" as "not in the feed at all".

## Less likely (but possible) causes — need DB inspection to rule out

1. **Phase 1 orchestrator inserted with empty title/caption + `video_url=NULL`**, then
   something between Phase 1 and Phase 3 raised. The `except Exception` handler at
   `compile.py:712` calls `_save_fallback_segment` which **returns the existing seg
   id without updating the row** (compile.py:354-356). Phase 3 (line 683) is INSIDE
   the try block, so a Phase 2 exception would leave the row in the empty-title state
   from line 243. The card would render with empty title + `Compiling…` placeholder.
   But: an exception would log "compile FAILED" — the user's logs show no such line.

2. **Frontend tab was backgrounded** — Safari throttles background EventSource
   connections; events might queue and the broadcast() might log but the client never
   process. Reload of the feed on foreground would show the segment.

3. **Stitch silently failed** — `_stitch_segment_runs` exception is caught at
   compile.py:639 with `log.warning("stitch failed cluster_id=%s: %s", ...)`. The
   user's log snippet shows "Two parent runs re-trimmed and re-uploaded" so this
   probably did NOT fail, but verify.

## Verification next steps

To confirm root cause #1 (UX/sort-order) vs the alternatives, run on production DB:

```sql
SELECT id, cluster_id, title, caption, video_url,
       to_timestamp(created_at) AS created,
       length(ordered_clip_ids) AS ordered_len,
       source_count, soft_flag
FROM segments
WHERE cluster_id = 'f021db1cc22440fa9f7e9363dcc25c10';
```

Expected if H1 (UX issue): row exists, has the new caption "Man Reacts To Soccer
Game", `video_url` is non-null and looks like `/runs/{run_id}.mp4` or a Vercel Blob
URL, `created_at` is the ORIGINAL first-compile timestamp (well before
2026-05-01T03:19:56).

Then hit `GET /feed` directly:
```
curl https://<railway>/feed | jq '.segments[] | select(.cluster_id=="f021db1cc22440fa9f7e9363dcc25c10")'
```

If the row IS present in `/feed` response → confirmed H1 (UX/sort issue).
If the row is missing → escalate; investigate JOIN failure or filter regression.

## Recommended fixes

### If H1 confirmed (UX issue)

Two options for the user/product side:

**Option A (zero code):** Document that recompile updates in place. Build user mental
model: "your second clip merged into the existing montage and added a new angle".

**Option B (small backend change):** Bubble recompiled segments to the top by
updating `created_at` (or a separate `last_compiled_at`) on recompile. Adds the
`s.created_at = EXCLUDED.created_at` line to the ON CONFLICT clause in
`db.insert_segment` — but only on the recompile insert path. Needs care:

- Pure approach: add a new `last_compiled_at` column, sort by `GREATEST(created_at,
  last_compiled_at)` in `fetch_recent_segments`. Preserves "first published" data
  while letting recompiles bubble. This was originally proposed as Path B in
  14-CONTEXT.md ("`compiled_at` column") and rejected for pilot scope. May be worth
  reopening.

- Quick approach: just refresh `created_at` to `now()` on every insert (modify
  `db_postgres.py:339-374` to add `created_at = EXCLUDED.created_at`). Drawback: the
  "originally published" timestamp on the card is lost (relativeTime() in
  SegmentCard would always say "just now" after a recompile).

**Option C (frontend toast):** When `segment_published` SSE event arrives for a
cluster_id whose card is already in state, flash a small "✨ updated" badge on the
card. Path B-lite originally considered this but deferred. Low effort; preserves
"recompile in place" semantics without leaving the user thinking it didn't work.

### If H2/H3 (mid-recompile failure leaves stale row)

Tighten `_save_fallback_segment` to actually rewrite the segment row when called
from a recompile path (currently it short-circuits on `if existing: return existing
["id"]`). Or wrap Phase 1.5/Phase 2 in a single try block that always lands a Phase
3 update with `caption_result` and the new `video_url`.

## Status

**Inconclusive — need production DB query** to determine whether the segment row
exists in `/feed` for cluster `f021db1cc22440fa9f7e9363dcc25c10`. If yes → UX/sort
fix (Option B or C). If no → genuine regression; deeper investigation required.

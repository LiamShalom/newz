# Phase 01 — Handoff (mid-session restart)

**Branch:** `feature/comments-and-sharing` (12 commits ahead of `main`)
**Last commit:** `6e0bd03 phase 01 T2.8: iOS keyboard handling for comment sheet`
**Working tree:** clean (only `__pycache__/*.pyc` show as dirty — ignored).
**Date:** 2026-04-28

## Where I am in the plan (`01-PLAN.md`)

### Wave 1 — Backend skeleton ✅ COMPLETE
- [x] T1.1 — `comments` table on both backends (SQLite SCHEMA_SQL + Alembic `0002_comments`)
- [x] T1.2 — `POST /segments/{id}/comments` (note: route is `/segments/`, not `/montages/` — matches existing `/feed` nomenclature)
- [x] T1.3 — `GET /segments/{id}/comments` (returns `{comments: [...]}`, newest first, no `session_id` leakage)
- [x] T1.4 — SSE `comment_added` event broadcast on POST success
- [x] T1.5 — In-memory rate limiter: 5 per 5 min + 10 per hour per `X-Session-Id` → 429 + `Retry-After`
- [x] T1.6 — Content filter stub: profanity prefix + URL/spam regex + repetition

### Wave 2 — Comment UI ✅ COMPLETE
- [x] T2.1 — `frontend/src/api.ts` (`fetchComments`, `postComment`, `CommentPostError`) + `commentsBus.ts` pub-sub
- [x] T2.2 — `CommentSheet.tsx` (mobile bottom sheet, 70dvh portal)
- [x] T2.3 — `CommentPopup.tsx` (desktop modal, video left + comments right) with shared `CommentList` + `CommentComposer`
- [x] T2.4 — Viewport switcher: `Comments.tsx` wrapper + `useMediaQuery` hook (768px = Tailwind `md:`)
- [x] T2.5 — Comment button on `SegmentCard` with count badge (lazy fetch on mount + live SSE increment)
- [x] T2.6 — Empty state ("Be the first to comment.") in `CommentList`
- [x] T2.7 — Anonymous label rendering: `Ghost` icon + "anonymous · {relative time}" header per row
- [x] T2.8 — iOS keyboard handling: body-scroll-lock + VisualViewport offset + `70dvh`

### Wave 3 — Share + public montage route ⬜ NOT STARTED
- [ ] T3.1 — Backend route `/m/<segment_id>` with full Open Graph meta tags (server-side rendered HTML for iMessage/Twitter unfurlers)
- [ ] T3.2 — Frontend route `/m/:segmentId` rendering standalone montage view (video + caption + comments)
- [ ] T3.3 — Share button on each card: `navigator.share({title, text, url})`; hide entirely if `navigator.share` unavailable

### Wave 4 — Verification ⬜ NOT STARTED
- [ ] T4.1 — Real iPhone test: post, persist, share to Messages, verify OG preview
- [ ] T4.2 — Desktop test: popup post + Web Share API or graceful hide
- [ ] T4.3 — Identity-leak audit: inspect network + DOM for any `session_id` / IP / other identifier
- [ ] T4.4 — Spam test: rapid post → 429 + UI message
- [ ] T4.5 — Update ROADMAP.md status (Mando #5 → ✅ Shipped); write `01-SUMMARY.md`

## Critical context for the next session

### 1. Liam's Neon connection is in flight
Liam was actively connecting Neon when I left off. My code is already compatible:
- Migration `backend/migrations/versions/20260428_0002_comments.py` chains off Liam's `0001_initial_v1_1_schema`. When Liam's `railway_migrate.sh` runs `alembic upgrade head`, it picks up automatically.
- Comment CRUD lives in **both** `db_sqlite.py` and `db_postgres.py` with byte-identical signatures so the `db.py` dispatcher routes correctly per `METADATA_BACKEND` env var.
- Schema uses `DOUBLE PRECISION`/`REAL` for `created_at` (Unix seconds), matching v1.0 column conventions — keeps dispatcher signature parity. Phase 9 backbone tables (`moderation_decisions`, `reports`, `reported_csam`) use `TIMESTAMPTZ`, but comments doesn't because we want a SQLite parallel.

**Watch for migration head-collision:** if Liam pushes another `0002_*` migration on `main`, rebase mine to `0003_comments` and update `down_revision`.

### 2. SQLite retirement note already filed
Roan asked how quickly SQLite could be dropped after Neon. Answer: ~2 hours of focused work (the strategic question is what `OFFLINE_DEMO=true` becomes — in-memory stub vs retire the flag entirely). Note left in two places:
- `backend/db_sqlite.py` header docstring
- `STATE.md` "Backbone track pre-flight" todo (owner: Liam)

### 3. Rename in-progress for the merge — done
The session-id naming was inconsistent between my new code (`session_uuid` / `X-Session-UUID`) and the existing codebase (`session_id` / `X-Session-Id`). All flipped in commit `2c38d7e`. Frontend reuses `getOrCreateSessionId()` from `session.ts` directly.

### 4. What I couldn't test locally
- Backend: full ASGI bootstrap is blocked because Liam's Phase 8 added `structlog`/`sentry-sdk`/`prometheus-client`/`asyncpg`/`alembic` deps and there's no network for `pip install` in this environment. **CRUD functions, rate limiter, and content filter all unit-tested directly** — but I never ran the FastAPI app end-to-end.
- Frontend: `tsc --noEmit` clean, all 25 existing vitest tests pass. **Did not run `npm run dev`** — no live UI verification on a real iPhone or even a desktop browser yet.

### 5. Endpoint shape (final)
- `POST /segments/{segment_id}/comments` — body `{text}` (1-300 chars, trimmed), header `X-Session-Id` required.
  - 201 → `{id, segment_id, text, created_at}`
  - 400 → header missing / length / content filter
  - 404 → segment doesn't exist
  - 429 → rate limit; includes `Retry-After` header
- `GET /segments/{segment_id}/comments` — returns `{comments: [...]}` newest-first, max 200.
- SSE `comment_added` event: `{type, segment_id, comment}` over the existing `/events` channel.

### 6. Frontend wiring summary
- `Feed.tsx` already routes `comment_added` SSE events into `commentsBus.dispatchCommentAdded(...)`.
- `SegmentCard.tsx` adds a comment button under the caption, fetches initial count via `fetchComments(segment.id)`, subscribes to bus for live increments.
- Tap button → `<Comments segmentId videoUrl open onClose />` which renders `CommentSheet` (mobile, <768px) or `CommentPopup` (desktop) via `useMediaQuery`.

## What to do first when you resume

1. Read this file + `01-PLAN.md`.
2. Recommended next step: **Wave 3** (share button + public route + OG tags). T3.1 is the only one with a backend touch — single FastAPI route returning HTML with `og:title`/`og:description`/`og:video` referencing the segment's `video_url`.
3. **If Liam has shipped his Neon connection in the meantime**, double-check no migration head collision before Wave 3:
   ```bash
   git fetch origin
   git log origin/main -- backend/migrations/versions/
   ```
   If a new `0002_*` exists on main, rebase the comments migration to `0003_*`.
4. After Wave 3 ships, do Wave 4 verification on a real iPhone (T4.1) — that's the only thing that catches iOS keyboard / OG preview / Web Share API issues for real.

## Files added/modified this session

**Backend:**
- `backend/db_sqlite.py` — added `comments` table + 3 CRUD functions + retirement-note header
- `backend/db_postgres.py` — added 3 parallel CRUD functions
- `backend/migrations/versions/20260428_0002_comments.py` — new
- `backend/app.py` — POST/GET routes + `_segment_exists` helper
- `backend/models.py` — `CommentCreateRequest` pydantic model
- `backend/rate_limit.py` — new
- `backend/content_filter.py` — new

**Frontend:**
- `frontend/src/types.ts` — `Comment` interface + `comment_added` event variant
- `frontend/src/api.ts` — `fetchComments`, `postComment`, `CommentPostError`
- `frontend/src/commentsBus.ts` — new
- `frontend/src/hooks/useMediaQuery.ts` — new
- `frontend/src/components/CommentList.tsx` — new
- `frontend/src/components/CommentComposer.tsx` — new
- `frontend/src/components/CommentSheet.tsx` — new
- `frontend/src/components/CommentPopup.tsx` — new
- `frontend/src/components/Comments.tsx` — new
- `frontend/src/components/SegmentCard.tsx` — comment button + Comments overlay
- `frontend/src/views/Feed.tsx` — wire `comment_added` SSE → `commentsBus`

**Planning:**
- `.planning/PROJECT.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `CLAUDE.md` — merged backbone (Liam, phases 8-13) + feature track (Roan, per-feature) under one v1.1 narrative

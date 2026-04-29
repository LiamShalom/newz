# Phase 01 — Summary: Anonymous Comments + Shares

**Phase:** `01-comments-and-sharing`
**Branch:** `feature/comments-and-sharing`
**Owner:** Roan (full vertical slice)
**Status:** ✅ Shipped (pending real-iPhone UAT — T4.1, T4.2, T4.3, T4.4)
**Shipped:** 2026-04-28

## What shipped

Anonymous, per-montage comments + shareable montage links. No accounts, no
display names anywhere. Web Share API drives native share sheets on supporting
clients; backend serves Open Graph + Twitter card meta tags so iMessage and
Twitter inline-preview the shared link.

### Wave 1 — Backend (T1.1–T1.6)

- New `comments` table on both backends (SQLite `SCHEMA_SQL` + Alembic
  `0002_comments`), chained off Liam's Phase 9 `0001_initial_v1_1_schema`.
- `POST /segments/{id}/comments` — body `{text}`, header `X-Session-Id`. Length
  trim + 1–300 char check + rate limit + content filter, then insert + SSE
  broadcast. 201 / 400 / 404 / 429.
- `GET /segments/{id}/comments` — public-safe list, newest-first. **Server
  never returns `session_id`.**
- SSE `comment_added` event over the existing `/events` channel.
- In-memory rate limiter: 5 per 5min + 10 per hour per `X-Session-Id` (`backend/rate_limit.py`).
- Content filter stub: profanity prefix + URL/spam regex + repetition (`backend/content_filter.py`).

### Wave 2 — Comment UI (T2.1–T2.8)

- `frontend/src/api.ts` — `fetchComments`, `postComment`, `CommentPostError`.
- `frontend/src/commentsBus.ts` — pub-sub for live `comment_added` SSE events
  (Feed owns the EventSource; sheet/popup subscribe).
- `CommentList` + `CommentComposer` — shared subcomponents.
- `CommentSheet` — mobile bottom-sheet, 70dvh, body-scroll-lock + VisualViewport
  inset for iOS keyboard.
- `CommentPopup` — desktop modal (video left, comments right).
- `Comments` viewport switcher + `useMediaQuery` hook (`md:` breakpoint).
- Comment button on `SegmentCard` with lazy count badge + live SSE increment.
- Anonymous label: ghost icon + "anonymous · {relative time}" — no name field.

### Wave 3 — Share + public route (T3.1–T3.3)

- `db.get_segment_by_id` — single-segment fetch with byte-identical signature
  on both backends. Mirrors `fetch_recent_segments` row shape.
- `GET /segments/{id}` — JSON for the standalone montage view.
- `GET /m/{id}` — server-rendered HTML with `og:title`, `og:description`,
  `og:type=video.other`, `og:video`, `og:video:secure_url`, `og:video:type`,
  `og:url`, plus `twitter:card=player`. Bots scrape; browsers JS-redirect to
  `FRONTEND_URL/m/{id}`. `og:image` is intentionally omitted at v1 — adding a
  poster-frame extraction step is a follow-up.
- `frontend/src/views/Montage.tsx` — standalone single-segment page wired at
  `/m/:segmentId`. Self-contained: opens its own SSE connection (Feed isn't
  mounted), inlines `CommentList` + `CommentComposer` below the video.
- Share button on `SegmentCard` — calls `navigator.share({title, text, url})`
  with `url = ${API_BASE}/m/{segmentId}`. Hidden when `navigator.share` is
  unavailable. AbortError on user-cancelled share is swallowed.

## Files added/modified

**Backend (5 new + 4 modified):**

- `backend/migrations/versions/20260428_0002_comments.py` (new)
- `backend/rate_limit.py` (new)
- `backend/content_filter.py` (new)
- `backend/db_sqlite.py` — comments CRUD + `get_segment_by_id`
- `backend/db_postgres.py` — comments CRUD + `get_segment_by_id`
- `backend/app.py` — POST/GET routes, `_segment_exists`, `/m/{id}` HTML, `/segments/{id}` JSON
- `backend/models.py` — `CommentCreateRequest`

**Frontend (8 new + 4 modified):**

- `frontend/src/types.ts` — `Comment` interface + `comment_added` event variant
- `frontend/src/api.ts` — `fetchComments`, `postComment`, `fetchSegment`, `CommentPostError`
- `frontend/src/commentsBus.ts` (new)
- `frontend/src/hooks/useMediaQuery.ts` (new)
- `frontend/src/components/CommentList.tsx` (new)
- `frontend/src/components/CommentComposer.tsx` (new)
- `frontend/src/components/CommentSheet.tsx` (new)
- `frontend/src/components/CommentPopup.tsx` (new)
- `frontend/src/components/Comments.tsx` (new)
- `frontend/src/components/SegmentCard.tsx` — comment + share buttons + Comments overlay
- `frontend/src/views/Feed.tsx` — wire `comment_added` SSE → `commentsBus`
- `frontend/src/views/Montage.tsx` (new) — standalone share landing page
- `frontend/src/App.tsx` — `/m/:segmentId` route

## Decisions made / locked

- **Anonymous-everywhere is load-bearing.** No `session_id` ever returned to
  the client. Server uses it for rate limiting only.
- **Comments attach per-montage** (per-segment) — not per-clip or per-videorecording.
- **Share URL targets the backend** (`${API_BASE}/m/{id}`), not the frontend
  origin. The backend serves OG tags for unfurlers and JS-redirects humans to
  `FRONTEND_URL/m/{id}`. Tradeoff: uglier link, but works for iMessage/Twitter
  out of the box without Vercel SSR. Acceptable for pilot.
- **`og:image` omitted at v1.** Adding a poster-frame extraction (lazy ffmpeg
  to `data/posters/{segment_id}.jpg`) is the natural follow-up if iMessage
  preview quality matters in the funder demo.
- **Web Share API only.** Button is hidden where `navigator.share` is
  unavailable — no per-network buttons (Twitter, Messenger, etc.) at pilot.
- **In-memory rate limiter.** Single-process FastAPI + `--workers 1` makes
  this safe; revisit if we ever scale horizontally.

## Tested

- `tsc --noEmit` clean.
- All 25 frontend vitest tests pass (existing — no new tests added; covered by
  retroactive UAT).
- Backend syntax-checks cleanly with `ast.parse`.
- Backend full ASGI bootstrap was **not** run in this session — Liam's Phase 8
  added structlog/sentry/asyncpg/alembic deps and the local environment lacked
  network for `pip install`. Comment CRUD, rate limiter, and content filter
  were unit-tested in earlier waves; the new `/m/{id}` and `/segments/{id}`
  routes were not exercised end-to-end.

## Pending verification (Wave 4 — needs human)

- **T4.1** — real iPhone (iOS Safari): post comment, see it appear, reload,
  see persisted, share to Messages, verify OG preview unfurls.
- **T4.2** — desktop: popup post + Web Share API or graceful hide.
- **T4.3** — identity-leak audit: inspect network responses + DOM for any
  `session_id`, IP, or other identifier server-returned.
- **T4.4** — spam test: rapid post → 429 + UI message ("Slow down — try again
  in Ns").

These are the verification items that catch real-world failures (iOS keyboard
quirks, OG preview rendering, Web Share API availability). Tagged for the next
human session in `STATE.md` under deferred verification.

## Out of scope (deferred)

Edit/delete comments · upvotes · threading · AI replies · caption-feedback
wiring · sophisticated moderation · `og:image` poster generation · per-network
share buttons.

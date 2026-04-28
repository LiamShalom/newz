# Phase 01 — Plan: Anonymous Comments + Shares

**Phase:** 01-comments-and-sharing
**Branch:** `feature/comments-and-sharing`
**Owner:** Roan (entire feature — UI + backend)
**See:** `01-CONTEXT.md` for problem, decisions, scope.

## Approach

Roan ships the full vertical slice: FastAPI routes + SQLite migration + SSE event + frontend components + share button + public montage route + OG tags. Recommended sequence below builds backend skeleton first so the frontend can wire to a real API from the start, but starting with a `localStorage` mock is fine if it accelerates UI iteration — interface stays the same either way.

## Task Breakdown

### Wave 1 — Backend skeleton

- [ ] **T1.1** — DB migration: `comments` table — `id INTEGER PRIMARY KEY, montage_id TEXT NOT NULL, session_uuid TEXT NOT NULL, text TEXT NOT NULL CHECK(length(text) <= 300), created_at TEXT NOT NULL DEFAULT (datetime('now'))`. Index on `(montage_id, created_at DESC)`.
- [ ] **T1.2** — `POST /montages/<id>/comments` — body `{ text }`, header `X-Session-UUID`. Validates length, applies rate limit, runs basic content filter, inserts row, broadcasts SSE event.
- [ ] **T1.3** — `GET /montages/<id>/comments` — returns array of `{ id, text, created_at }` (NEVER `session_uuid` to clients). Pagination optional (montage-scope means small N).
- [ ] **T1.4** — SSE event: extend the existing feed SSE channel with a `comment_added` event type carrying `{ montage_id, comment }`.
- [ ] **T1.5** — Rate limiter: in-memory (single-process FastAPI is fine at pilot scale). 5 per 5 min + 10 per hour per `session_uuid`. 429 on exceed.
- [ ] **T1.6** — Content filter stub: profanity blocklist + URL/spam regex. Simple wins now; iterate later.

### Wave 2 — Comment UI

- [ ] **T2.1** — API client (`frontend/src/api/comments.ts`): `addComment`, `listComments(montageId)`, `subscribeToComments(montageId, cb)` over SSE. Optional: `mockComments.ts` shim with the same interface for offline iteration.
- [ ] **T2.2** — Comment bottom-sheet component (`frontend/src/components/CommentSheet.tsx`): slides up from bottom, full-width, ~70vh, video stays pinned above. Header: comment count + close button. Body: scrollable list (newest first). Footer: text input + send button + char counter (300 limit).
- [ ] **T2.3** — Comment popup component (`frontend/src/components/CommentPopup.tsx`): desktop-only, modal overlay. Two columns: video left (~60%), comments panel right (~40%). Same input/list internals as bottom-sheet — extract `CommentList` + `CommentComposer` shared subcomponents.
- [ ] **T2.4** — Viewport switcher: in `FeedTile` (or wherever montages render), conditionally render `<CommentSheet>` vs `<CommentPopup>` based on a Tailwind breakpoint hook. Verify no flash on resize.
- [ ] **T2.5** — Comment button on each montage card. Shows comment count badge. On tap → open sheet (mobile) or popup (desktop).
- [ ] **T2.6** — Empty state: when `comments.length === 0`, show subtle prompt ("Be the first to comment.").
- [ ] **T2.7** — Anonymous label rendering: every comment row shows the same ghost-icon + relative time ("2m ago"), no name field. Verify nothing leaks an identifier.
- [ ] **T2.8** — iOS keyboard handling: when input focused on iOS Safari, bottom-sheet must slide above the keyboard. Test on real iPhone.

### Wave 3 — Share + public montage route

- [ ] **T3.1** — Backend route `/m/<montage_id>` returning HTML with full Open Graph meta tags (`og:title`, `og:description`, `og:image` pointing at the montage poster frame, `og:video`). Server-side rendered, not a client-side route — iMessage/Twitter unfurlers don't run JS. Either FastAPI returns HTML directly or a small SSR shim wraps the existing montage fetch.
- [ ] **T3.2** — Frontend route `/m/:montageId` rendering the standalone montage view (video + caption + comments below) for users who land on the link in a browser.
- [ ] **T3.3** — Share button on each montage card. On click: `navigator.share({ title, text, url })` with `url = window.location.origin + '/m/' + montageId`. If `navigator.share` unavailable, hide the button entirely.

### Wave 4 — Verification

- [ ] **T4.1** — Test on real iPhone (iOS Safari): post comment, see it appear, reload, see persisted, share to Messages, verify OG preview.
- [ ] **T4.2** — Test on desktop: post via popup, verify Web Share API or graceful hide.
- [ ] **T4.3** — Confirm zero identity leaks: inspect network responses + DOM for any `session_uuid`, IP, or other identifier server-returned to client.
- [ ] **T4.4** — Spam test: post comments rapidly, verify rate limit kicks in (429 + UI message).
- [ ] **T4.5** — Update ROADMAP.md status (Mando #5 → ✅ Shipped). Write `01-SUMMARY.md`.

## Done When

- Mobile: viewer can tap a comment icon on any montage, see existing comments in a bottom-sheet, type and post a new one, see it appear without refresh.
- Desktop: same flow via popup.
- Mobile + desktop: viewer can tap a share button and trigger native share sheet (where supported), with the link rendering an OG preview in iMessage.
- Inspecting any comment payload reveals NO identity-leaking field client-side.
- Rate limit blocks comment storms gracefully (429 + UI message).
- ROADMAP.md Mando #5 marked shipped. `01-SUMMARY.md` written.

## Out of Plan (deferred)

Edit/delete comments · upvotes · threading · AI replies · caption-feedback wiring · sophisticated moderation. Each is a separate future phase if pursued.

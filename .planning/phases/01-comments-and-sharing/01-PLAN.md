# Phase 01 — Plan: Anonymous Comments + Shares

**Phase:** 01-comments-and-sharing
**Branch:** `feature/comments-and-sharing`
**Owner:** Roan (UI) — primary; Liam (backend) — handoff
**See:** `01-CONTEXT.md` for problem, decisions, scope.

## Approach

UI-first build against a mocked comments API. Roan ships the components, share button, and public-montage-route shell with `localStorage`-backed mock data. Liam picks up backend (DB migration, endpoints, SSE, OG tags, rate limit) once UI is reviewable. Merge backend in a follow-up commit, then end-to-end verification.

## Task Breakdown

### Wave 1 — UI shell & mock data (Roan, can start now)

- [ ] **T1.1** — Add `comments` mock store (`frontend/src/lib/mockComments.ts`): localStorage-backed `{ montageId, text, createdAt }[]`, with `addComment`, `listComments(montageId)`, `subscribeToComments(montageId, cb)` (mock SSE via interval polling).
- [ ] **T1.2** — Comment bottom-sheet component (`frontend/src/components/CommentSheet.tsx`): slides up from bottom, full-width, ~70vh, video stays pinned above. Header: comment count + close button. Body: scrollable list (newest first). Footer: text input + send button + char counter (300 limit).
- [ ] **T1.3** — Comment popup component (`frontend/src/components/CommentPopup.tsx`): desktop-only, modal overlay. Two columns: video left (~60%), comments panel right (~40%). Same input/list internals as bottom-sheet — extract `CommentList` + `CommentComposer` shared subcomponents.
- [ ] **T1.4** — Viewport switcher: in `FeedTile` (or wherever montages render), conditionally render `<CommentSheet>` vs `<CommentPopup>` based on a Tailwind breakpoint hook. Verify no flash on resize.
- [ ] **T1.5** — Comment button on each montage card. Shows comment count badge (mock-driven). On tap → open sheet (mobile) or popup (desktop).
- [ ] **T1.6** — Share button on each montage card. On click: `navigator.share({ title, text, url })` where `url = window.location.origin + '/m/' + montageId`. If `navigator.share` unavailable, hide the button entirely.
- [ ] **T1.7** — Empty state: when `comments.length === 0`, show subtle prompt ("Be the first to comment.").
- [ ] **T1.8** — Anonymous label rendering: every comment row shows the same ghost-icon + relative time ("2m ago"), no name field. Verify nothing leaks an identifier.
- [ ] **T1.9** — iOS keyboard handling: when input focused on iOS Safari, bottom-sheet must slide above the keyboard. Test on real iPhone.

### Wave 2 — Public montage route shell (Roan UI + minimal backend stub)

- [ ] **T2.1** — Frontend: route `/m/:montageId` rendering a single montage in standalone view (video + caption + comments below). Uses existing montage fetch.
- [ ] **T2.2** — Backend (Liam, minimal): server-side render OG tags for `/m/<montageId>` so iMessage/Twitter previews show poster image + montage caption. Coordinate with Liam — needs cooperation from the existing FastAPI route to render HTML with OG meta tags (or a small SSR shim). Could be punted to a later iteration if URL alone is enough for v1 — flag as decision point in PR.

### Wave 3 — Backend (Liam — handoff after Wave 1 lands)

- [ ] **T3.1** — DB migration: `comments` table — `id INTEGER PRIMARY KEY, montage_id TEXT NOT NULL, session_uuid TEXT NOT NULL, text TEXT NOT NULL CHECK(length(text) <= 300), created_at TEXT NOT NULL DEFAULT (datetime('now'))`. Index on `(montage_id, created_at DESC)`.
- [ ] **T3.2** — `POST /montages/<id>/comments` — body `{ text }`, header `X-Session-UUID`. Validates length, applies rate limit, runs basic content filter, inserts row, broadcasts SSE event.
- [ ] **T3.3** — `GET /montages/<id>/comments` — returns array of `{ id, text, created_at }` (NEVER `session_uuid` to clients). Pagination optional (montage-scope means small N).
- [ ] **T3.4** — SSE event: extend the existing feed SSE channel with a `comment_added` event type carrying `{ montage_id, comment }`.
- [ ] **T3.5** — Rate limiter: in-memory (since single-process FastAPI, OK for pilot scale). 5 per 5 min + 10 per hour per `session_uuid`. 429 on exceed.
- [ ] **T3.6** — Content filter stub: profanity blocklist + URL/spam regex. Simple wins now; iterate later.
- [ ] **T3.7** — Frontend: swap `mockComments.ts` import for real API client (`api/comments.ts`). Same interface so component code doesn't change.

### Wave 4 — Verification

- [ ] **T4.1** — Test on real iPhone (iOS Safari): post comment, see it appear, reload, see persisted, share to Messages, verify OG preview.
- [ ] **T4.2** — Test on desktop: post via popup, verify Web Share API or graceful hide.
- [ ] **T4.3** — Confirm zero identity leaks: inspect network responses + DOM for any `session_uuid`, IP, or other identifier.
- [ ] **T4.4** — Spam test: post 10 comments rapidly, verify rate limit kicks in.
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

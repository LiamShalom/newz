# Phase 01 — Anonymous Comments + Shares

**Milestone:** v1.1 Pilot MVP for funding
**Branch:** `feature/comments-and-sharing`
**Owner:** Roan (UI) + Liam (backend handoff)
**Backlog ref:** ROADMAP.md Mando #5
**Status:** Planning complete; ready to build (UI-first, backend stubbed)

## Problem

The pilot needs engagement primitives so a viewer of a montage can react and propagate the content. Without comments and shares, every montage is a dead-end — a funder will ask "OK, then what?" and we have no answer. Two of the most-frequently asked-about features in user feedback per the post-hackathon "Next Steps" doc.

These need to work **without breaking the anonymity premise** that carried the v1.0 pitch. No accounts. No display names. No identity surfaced anywhere.

## Decisions Made (locked)

1. **Comments attach per-montage, not per-clip and not per-videorecording.** A montage is the user-facing unit; clips and videorecordings are pipeline internals. (Nomenclature reminder: videorecording = raw upload; clip = Marengo embedding-space slice; montage = compiled multi-angle output.)
2. **Fully anonymous comments.** Stored as `text + montage_id + timestamp + (server-side only) anonymous session UUID for rate limiting`. UI renders every comment as "Anonymous" — no handle, no avatar, no color/icon hash that could leak identity.
3. **No edit, no delete.** Identity-less comments can't have grants. Once posted, immutable. (Server-side admin delete is fine; user-facing delete is not.)
4. **Comment UI — viewport-conditional:**
   - **Mobile (iOS Safari, narrow viewport):** Bottom-sheet overlay that slides up from the bottom (Instagram/TikTok pattern). Persists the montage video at the top, comments scroll below.
   - **Desktop (wider viewport):** Modal popup with video on the left, comments panel on the right (Instagram desktop pattern).
5. **Share = Web Share API only** (no copy-link fallback in v1, per user call). On platforms without `navigator.share`, the share button is hidden — accept the gap. Re-evaluate after pilot if support gaps cause real problems.
6. **Each share needs a public per-montage URL with Open Graph tags** so previews render in iMessage/Twitter/etc. Backend work.
7. **Comments are display-only in v1 — they do NOT feed the caption agent.** Caption-curation-from-comments is deferred (would require re-running compile pipeline on new comments; meaningful backend scope crossing into Liam's territory).
8. **Threading: flat list.** No nested replies in v1. AI Comment Replies (non-mando #6) can revisit threading if/when it ships.
9. **Ordering: newest first.** Standard chronological reverse.
10. **Length cap: 300 characters** per comment. Server-side enforced; client-side counter.
11. **Rate limiting:** server-side, keyed off the anonymous session UUID. Specifics (X comments per Y minutes) are a Liam call when he picks up the backend work — placeholder: 5 comments per 5 minutes, 10 per hour.
12. **New comments propagate via SSE** — same channel pattern as the feed auto-refresh in v1.0.

## Scope

**In:**
- Comment data model (DB migration: `comments` table)
- POST/GET comment endpoints (REST)
- SSE event for new comments on a montage
- Comment bottom-sheet (mobile) / popup (desktop) UI components
- Share button on each montage card → `navigator.share()` invocation
- Public per-montage URL route (e.g. `/m/<montage_id>`) with OG tags rendered server-side
- Server-side rate limiting + length validation
- Server-side basic content filter (profanity / link-spam stub — improve iteratively)

**Out (in this phase):**
- Edit / delete comments (no identity model)
- Likes / upvotes on comments (custom signal is non-mando #3 — separate phase)
- Threading / replies (deferred until AI Comment Replies)
- Caption-feedback-from-comments wiring (separate follow-up phase)
- AI-generated replies (non-mando #6)
- Sophisticated content moderation (stub only; full moderation is mando #6)
- Per-clip or per-videorecording comments
- Email/push notifications (no identity to notify)

## Open Questions (non-blocking — resolve during build)

- **Comment count badge** on the montage card — show the count, or hide entirely? Lean: show, reinforces engagement signal in the feed without breaking anonymity.
- **What "Anonymous" actually renders as** — literal "Anonymous" label, no label at all, or a single shared icon? Lean: small ghost-icon + nothing else; consistent.
- **Spam mitigations beyond rate limit** — IP-based throttling, captcha, content classifier. Lean: rate limit + length cap + profanity filter for v1; iterate.
- **Web Share API behavior on iOS Safari PWA installed via A2HS** — Liam's a2hs hint branch is in flight. May need testing once both ship.
- **Empty state copy** — "Be the first to comment." vs. silence. Lean: small prompt.
- **Comment input affordance on iOS keyboard** — bottom-sheet needs to slide above the on-screen keyboard. Known iOS Safari pain point.

## Constraints from PROJECT.md

- Anonymity is load-bearing — applies fully to comments and shares.
- iOS Safari is the primary surface — bottom-sheet UX must work with iOS keyboard.
- Reliability over polish — ship working comments before polishing animations.
- Roan = UI, Liam = backend — UI build proceeds against mocked backend; Liam handoff required to ship.

## Dependencies / Sequence

- UI build CAN proceed independently against a mocked comments API.
- Public per-montage URL + OG tags requires backend route work → blocks share button being demo-able end-to-end.
- Real backend (DB schema, endpoints, SSE event, rate limiter) is a Liam pickup. Flag in PR.
- Liam's `demo/home-screen-app-hint` branch (PWA Add-to-Home-Screen) is independent; testing it does not interfere with this phase.

---
*Drafted: 2026-04-27 from "Next Steps" PDF + four design Q&A with Roan*

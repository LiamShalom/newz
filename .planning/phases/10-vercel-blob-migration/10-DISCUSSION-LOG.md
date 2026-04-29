# Phase 10: Vercel Blob Migration — Discussion Log

**Date:** 2026-04-29
**Mode:** discuss (default)
**Phase boundary:** Replace Railway local-FS clip storage with server-mediated Vercel Blob; ffmpeg reads from Blob (signed-URL byte-range trim, tempdir-download stitch); compiled run-segments land in Blob CDN; `/media` StaticFiles mount retired; `STORAGE_BACKEND` flag for rollback.

This file is a human-reference audit trail. Downstream agents (researcher, planner, executor) read `10-CONTEXT.md` directly.

---

## Areas Selected for Discussion

User selected all four offered gray areas (multiSelect):
- Blob URL access policy
- v1.0 demo clip migration
- ffmpeg + Blob integration flow
- Vercel Blob SDK pick

---

## Area 1 — Vercel Blob SDK pick (discussed first; foundational)

**Question presented:** Which Vercel Blob client approach for the FastAPI backend?

**Options:**
- (Recommended) Raw httpx async wrapper — ~150 LOC typed httpx client over Blob REST API (PUT upload, signed-URL mint, DELETE cleanup, HEAD). Async-native, no SDK version-pin risk, matches Phase 9 asyncpg style. Resolves STATE.md "AsyncBlobClient bleeding-edge" concern by avoiding the SDK entirely.
- `vercel_blob` Python SDK (AsyncBlobClient @0.5.8) — bleeding-edge async SDK; less code, more dependency surface; spike still owed before planning per STATE.md todo.
- Mixed: SDK for upload, httpx for signed URLs.

**User selection:** Raw httpx async wrapper (recommended).

**Resulting decisions in CONTEXT.md:** D-01, D-02, D-03, D-04, D-25.

**Rationale captured:** SDK churn pre-1.0 is the load-bearing concern. Blob REST surface area we touch is small (4 ops). Async-native fit with Phase 9's asyncpg/structlog stack. Avoids version-pin risk explicitly flagged in STATE.md pending todos.

---

## Area 2 — Blob URL access policy

**Context surfaced before question:** Vercel Blob's two access modes (public vs private+signed). Trade-offs in BLOB-03 (ffmpeg trim auth), BLOB-08 (cleanup leak window), frontend caching, anonymity (none — Sentry already scrubs `blob_url`).

**Question presented:** Vercel Blob access mode for `uploads/` and `runs/` prefixes?

**Options:**
- (Recommended) Split: private `uploads/`, public `runs/` — raw user clips need signed URLs (leak window bounded by TTL); compiled segments are public (CDN-cacheable, frontend renders directly, no signed-URL refresh logic).
- All public — simplest code; one-line `ffmpeg.input(url)`; trade: leaked `uploads/` URLs valid until cleanup hook fires.
- All private + signed URLs everywhere — strongest leak-decay; adds frontend signed-URL refresh + per-trim mint; highest complexity.

**User selection:** Split: private `uploads/`, public `runs/` (recommended).

**Resulting decisions in CONTEXT.md:** D-05, D-06, D-07.

**Rationale captured:** Split policy separates "intermediate" surface (raw clips, leak-decay matters) from "publish" surface (compiled segments, CDN cache + frontend simplicity matter). Best fit for BLOB-08 cleanup semantics.

---

## Area 3 — ffmpeg + Blob integration flow

**Context surfaced before question:** Two ffmpeg paths have very different access patterns. BLOB-03 trim does HTTP Range over signed URL (ffmpeg-python supports URL inputs natively, query-param-token works without `-headers`). BLOB-04 stitch needs pre-download into `tempfile.TemporaryDirectory()` (re-encode streams poorly). Recommendations bundled: 15-min signed-URL TTL minted fresh per call; tempdir-per-stitch with `asyncio.gather`-parallel downloads; sequential trim → upload → return URL for run-segments.

**Question presented:** ffmpeg + Blob integration trade-offs — accept the three recommendations, or pick a different stance?

**Options:**
- (Recommended) Accept all three recommendations — 15-min TTL minted fresh per call; tempdir-per-stitch with parallel downloads; sequential trim → upload → return URL.
- Tighter TTL (5 min) + per-call URL caching — shorter leak window; adds in-process URL cache.
- Looser TTL (1 hour) + cluster-level tempdir reuse — faster recompiles; adds tempdir lifecycle complexity.
- Stream trim output directly to Blob (no local temp) — skips local disk; breaks atomic-rename pattern in `_sync_trim`.

**User selection:** Accept all three recommendations.

**Resulting decisions in CONTEXT.md:** D-08, D-09, D-10, D-11.

**Rationale captured:** 15-min TTL provides headroom for retries and ffmpeg cold-start; the real leak defense is the BLOB-08 cleanup hook, not TTL tightness. Tempdir-per-stitch keeps `montage-not-updating` (v1.0-retro deferred bug) blast radius contained — adding cache coherence to mutation-fragile cluster code is a poor mid-migration call. Sequential upload preserves the atomic-rename + failure-fallback pattern the v1.0 stitch already validated.

---

## Area 4 — v1.0 demo clip migration (cutover handling)

**Context surfaced before question:** Inspected `backend/seed/demo/*.mp4` (checked-in fixture corpus: clip-1..4, realworld-1..3, adversarial set). No production user data — anonymous-by-design. CLAUDE.md confirms `POST /admin/reset` already wipes clips between demo runs. v1.0 SQLite rows preserved by Phase 9's dump-and-load have NULL `blob_url`, so they'd render broken post-cutover.

**Question presented:** How should v1.0 clip rows be handled at the Phase 10 cutover?

**Options:**
- (Recommended) Fresh-start + feed filter + seed-replay script — feed query adds `WHERE blob_url IS NOT NULL`; new `seed_demo_to_blob.py` POSTs each fixture file to `/clips` to re-materialize the demo via the live pipeline.
- One-shot backfill (mirrors Phase 9 D-01) — `local_to_blob.py` reads `/data/clips/*` from Railway volume, uploads to Blob, ALTERs each row to set `blob_url`. Heavier but symmetric with Phase 9.
- Both — feed filter ships in Phase 10; backfill exists ad-hoc for live-demo continuity.

**User selection (custom freetext):** "you can delete and ignore these demo clips."

**Resulting decisions in CONTEXT.md:** D-15.

**Rationale captured:** User's freetext simplifies past all three offered options. No backfill, no feed filter, no read-fallback. At Phase 10 deploy: call existing `POST /admin/reset` to truncate the legacy clips/embeddings/clusters/segments rows. Demo dataset re-uploaded fresh via UI (or a thin seed-replay script). Zero migration code; zero dead `WHERE blob_url IS NOT NULL` predicate carrying forward. Justification holds: Newz has no production user data; demo corpus is checked-in fixtures we control.

---

## Scope Creep Redirected

None this discussion. All user input stayed within the BLOB-01..08 boundary.

---

## Deferred Ideas Captured

See `10-CONTEXT.md` `<deferred>` block. Notable:
- Cluster-level tempdir reuse / source-clip cache → v1.2+
- Stream trim output directly to Blob (no local temp) → considered & rejected
- Cluster-aware Blob region pinning → v1.2+
- Blob CDN metrics in `/metrics` → v1.2+
- `backend/storage/local.py` deletion → v1.2+ (mirrors Phase 9 D-09)
- Multipart upload for >100 MiB clips → out of scope
- Direct browser → Blob upload → permanently rejected
- Cloudflare R2 → v1.2+ if egress material
- Pre-warm Blob on startup → rejected (no Marengo-style cold-start analog)
- Background sweeper for orphan blob cleanup → out of scope

---

## Claude's Discretion (locked-in defaults the planner can act on)

- D-23: env var names (`STORAGE_BACKEND`, `BLOB_READ_WRITE_TOKEN`) and `.env.example` documentation
- D-24: `tenacity` retry posture (3 attempts, exponential backoff, transient 5xx only)
- D-25: httpx wrapper module location (`backend/storage/blob_client.py`)
- D-26: `Content-Type` policy for upload (mp4/webm matches inbound; runs/ always video/mp4)
- D-27: no Blob warm-up on startup
- D-28: structured logging shape for storage operations
- Test fixture extension to `STORAGE_BACKEND` parametrize (D-21)
- Wave-0 smoke deploy posture (D-22)

---

## Verifications Owed (forwarded to research / planning)

- D-17: confirm `frontend/src/api.ts:29-31` does not double-prefix absolute URLs (likely-OK; one-line guard if not)
- D-22: wave-0 manual deploy with `STORAGE_BACKEND=blob` + test upload before integration tests are in their final shape
- Confirm `httpx` is in `backend/requirements.txt` (transitive via FastAPI? — verify and pin if not)
- Confirm `frontend/src/types.ts` doc-string update is the only frontend doc churn beyond api.ts audit

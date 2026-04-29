# Roadmap: Newz

## Milestones

- ✅ **v1.0 Hackathon MVP** — Phases 1-4 (shipped 2026-04-26, won HackTech 2026)
- 🚧 **v1.1 Pilot MVP for funding (Public-Launch-Ready Backbone)** — two tracks, in progress

## v1.1 Pilot MVP — Active

**Goal:** Get Newz in front of funders (TwelveLabs feature/credits, Buerk Center @ UW, CoMotion @ UW) with something that works for real users — not just a demo. Reliability + missing core UX features. Two parallel tracks under one milestone.

**Phase numbering note:** Backbone uses sequenced numbering (8-13, continuing from v1.0's 4); feature track restarted at `01-` due to a parallel re-frame on 2026-04-27. Reconcile in a later cleanup; no behavioral impact.

### Track A: Backbone (Liam, sequenced phases 8–13)

Hardens the v1.0 monolith for public launch without disturbing load-bearing decisions (single-process asyncio, no ORM, no Redis, anonymity-by-default, `--workers 1`, in-memory CLUSTERS cache). Build order is dependency-first: observability first so all migration work is debuggable; Postgres next as keystone; then Blob; then moderation; then reporting; then deepening.

| # | Phase | Status | Phase Dir |
|---|-------|--------|-----------|
| 8 | Observability scaffolding (structlog + Sentry + Logfire + Prometheus + PII scrubbers) | ✅ Shipped | `phases/08-observability-scaffolding/` |
| 9 | Postgres migration to Neon (asyncpg + Alembic, METADATA_BACKEND dispatcher) | ✅ Shipped | `phases/09-postgres-migration-neon-asyncpg-alembic/` |
| 10 | Vercel Blob migration for clip media (server-mediated; signed URLs; `STORAGE_BACKEND` flag) | 🟡 Planning next | TBD |
| 11 | Moderation gate (Gemini Flash-Lite + Cloudflare CSAM hash, parallel-with-Marengo, tiered fail policy) | ⬜ Open | TBD |
| 12 | Reactive reporting + admin queue (anonymous reports; UNIQUE(segment, ip_hash) brigading defense) | ⬜ Open | TBD |
| 13 | Observability deepening + OFFLINE_DEMO audit (Logfire spans across pipeline; anonymity regression test; firewalled CI smoke test) | ⬜ Open | TBD |

**Execution order:** 8 → 9 → 10 → (11 ∥ 12) → 13. Phase 11 and 12 share schema but operate on disjoint columns — can parallelize after Phase 10 ships.

### Track B: Feature track (Roan, per-feature phases)

Per-feature GSD: each backlog item becomes its own phase under `phases/<NN>-<slug>/` when work begins. No fixed sequence — pick by priority + dependency. Mando = blocking for funder demos. Non-mando = nice-to-have if time.

#### Mando

| # | Feature | Type | Owner | Status | Phase Dir |
|---|---------|------|-------|--------|-----------|
| 1 | Upload timeout / reliability | Bug | Liam | ✅ Shipped (PR #1, `bccd5d5`) | — |
| 2 | Clip selection logic fix | Bug | Liam | 🟡 Open — montage doesn't seem to pick clips; may need redesign | — |
| 3 | Location bug ("UW shows Pasadena") | Bug | Liam | ✅ Shipped (PR #2, `beda750`) | — |
| 4 | Safari location services bug + permissions gate decision | Bug + Decision | Roan | 🟡 Open — see strategic Q in PROJECT.md | — |
| 5 | **Anonymous comments + shares** | Feature | Roan | ✅ Shipped (pending real-iPhone verification) | `phases/01-comments-and-sharing/` |
| 6 | Video censoring (UI side; pairs with Phase 11 backbone) | Feature | Roan | 🟡 Open — depends on backbone Phase 11 | — |
| 7 | Permissions gate (mic + cam + location flow) | Feature | Roan | 🟡 Open — depends on #4 | — |
| 8 | Adding videorecordings to existing montages | Bug | Liam | 🟡 Open — feature exists but doesn't work | — |
| 9 | Real test suite | Infra | Either | 🟡 Open | — |

#### Non-mando

| # | Feature | Type | Owner | Status | Phase Dir |
|---|---------|------|-------|--------|-----------|
| 1 | Reduce Claude token usage | Optimization | TBD | 🟡 Open | — |
| 2 | Domain / new name | Branding | TBD | 🟡 Open | — |
| 3 | Custom engagement signal (replaces likes) | Feature | TBD | 🟡 Open — design decision pending | — |
| 4 | Audio embedding | Feature | Liam | 🟡 Open — verify Marengo coverage first | — |
| 5 | Multiple feed tabs (Recent / Popular / Today) | Feature | Roan | 🟡 Open | — |
| 6 | AI comment replies | Feature | TBD | 🟡 Open — depends on Mando #5 shipping | — |

#### Considered, then dropped

- **Conventional likes** — content isn't human-authored; human-style "like" carries low signal. Replacement is non-mando #3 (custom signal).
- **"NO DIH PIX" filter as standalone** — folded into video censoring (mando #6).

## Phase Index

### v1.1 Pilot MVP (active)

- [x] Phase 8: Observability scaffolding — shipped · Liam
- [x] Phase 9: Postgres migration (Neon + asyncpg + Alembic) — shipped · Liam
- [ ] Phase 10: Vercel Blob migration — planning · Liam
- [ ] Phase 11: Moderation gate — open · Liam
- [ ] Phase 12: Reactive reporting + admin queue — open · Liam
- [ ] Phase 13: Observability deepening + OFFLINE_DEMO audit — open · Liam
- [x] Phase 01: Anonymous comments + shares — shipped (pending real-iPhone verification) · Roan

### v1.0 Hackathon MVP (shipped)

<details>
<summary>✅ v1.0 Hackathon MVP (Phases 1-4) — SHIPPED 2026-04-26</summary>

- [x] Phase 1: Foundation, Capture & Ingest (5/5 plans) — completed 2026-04-25
- [x] Phase 2: Marengo Embedding (2/2 plans) — completed 2026-04-25
- [x] Phase 3: Clustering + Debug Overlay (2/2 plans) — completed 2026-04-25
- [x] Phase 4: Multi-Agent Compile + Real-Time Feed (3/3 plans + parent-cluster pivot) — completed 2026-04-26

Full archive: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)

</details>

## Backbone Phase Details

### Phase 8: Observability Scaffolding ✅
**Goal**: Every subsequent phase ships with structured logs, error tracking, traces, and PII scrubbers already in place — eliminate Railway log spelunking during the rest of the migration.
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04, PRIV-01, PRIV-02
**Plans**: 3 plans (all shipped)
- [x] 08-01-PLAN.md — observability module skeleton (anonymity, logging_config, sentry, middleware, metrics) + config + deps + scrubber/logging unit tests
- [x] 08-02-PLAN.md — wire observability into backend/app.py (first-import, middleware order, /metrics route) + XFF/contextvars/auth integration tests
- [x] 08-03-PLAN.md — pipeline stage timing (ingest/embed/cluster) + Sentry OFFLINE_DEMO smoke + before_send round-trip + stage label enum guard

### Phase 9: Postgres Migration (Neon + asyncpg + Alembic) ✅
**Goal**: Retire SQLite-on-volume; metadata lives in managed Postgres with the full v1.1 schema (moderation columns, blob_url, is_hidden, reports, moderation_decisions, reported_csam) baked into the initial migration.
**Depends on**: Phase 8
**Requirements**: DB-01 through DB-07, MOD-09, DEMO-03
**Plans**: 9 plans (all shipped)
- [x] 09-01 through 09-09 — see `phases/09-postgres-migration-neon-asyncpg-alembic/`

### Phase 10: Vercel Blob Migration
**Goal**: Retire Railway `/data/clips/` for clip media; uploads land in Vercel Blob via server-mediated path; ffmpeg reads from Blob with two strategies (signed-URL byte-range trim, tempdir-download stitch); compiled segments served from Blob CDN.
**Depends on**: Phase 9
**Requirements**: BLOB-01 through BLOB-08
**Success Criteria** (what must be TRUE):
  1. Backend redeploys to Railway and existing clip media still plays from the feed (Blob URLs absolute; `/media` StaticFiles mount removed).
  2. A new clip recorded in the iOS Safari PWA uploads via `POST /clips` and lands in Vercel Blob under `uploads/{clip_id}.{ext}` — verifiable via Blob console.
  3. Compiled run segments appear in Vercel Blob under `runs/{run_id}.mp4` and the frontend feed renders them from absolute Blob URLs.
  4. A direct browser PUT to Vercel Blob is rejected (verified by attempting one and observing 401/403).
  5. After a clip's moderation decision flips to `blocked`, its Blob object is hard-deleted within the cleanup window (verifiable via Blob console + DB join).
  6. Setting `STORAGE_BACKEND=local` env var rolls the backend back to the v1.0 local-FS path without code changes.
**Plans**: 1 plan

Plans:
- [x] 10-01-PLAN.md — Vercel Blob migration: storage package, lifespan integration, ffmpeg + private Blob auth headers, tempdir-stitch, frontend absolute-URL guard, BLOB-08 cleanup hook
**UI hint**: yes

### Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash)
**Goal**: Every uploaded clip passes through a moderation gate before entering cluster/compile; gate runs parallel-with-Marengo so common-case latency does not regress; tiered failure policy (timeout fail-CLOSED, 5xx outage fail-OPEN to admin queue, CSAM fail-CLOSED); newsworthy corroboration via ≥2-parent + violence-signal soft-flag.
**Depends on**: Phase 9, Phase 10
**Requirements**: MOD-01 through MOD-08, MOD-10, PRIV-03
**Success Criteria**: Disallowed content never reaches public feed; common-case latency within 10% of v1.0 baseline; fail-CLOSED on timeout; OFFLINE_DEMO produces `passed` with no external call; ≥2-parent violence soft-flag → tap-to-view; outbound payload contains video bytes only.
**Plans**: TBD
**UI hint**: yes (pairs with feature-track censoring)

### Phase 12: Reactive Reporting + Admin Queue
**Goal**: Anonymous post-publish report flow + token-guarded admin queue with embedded clip playback; reports table never carries session_uuid; brigading-defense via UNIQUE(segment, ip_hash); admin actions hide segments and optionally block underlying clips.
**Depends on**: Phase 9
**Requirements**: REPORT-01 through REPORT-10, PRIV-04
**Success Criteria**: Tapping Report submits without session_uuid in body; admin endpoint token-guarded; hide-segment removes from feed within one SSE refresh; UNIQUE constraint prevents brigading; GPS only at city-level in admin UI; no auto-takedown by report count alone.
**Plans**: TBD
**UI hint**: yes

### Phase 13: Observability Deepening + OFFLINE_DEMO Audit
**Goal**: Wrap the final v1.1 pipeline shape in Logfire spans (instrument_anthropic, OTel context across asyncio.create_task); lock anonymity invariants behind a regression test; lock OFFLINE_DEMO end-to-end behind a firewalled-startup CI smoke test; bounded metric labels enforced.
**Depends on**: Phase 11, Phase 12
**Requirements**: OBS-05 through OBS-09, DEMO-01, DEMO-02
**Success Criteria**: Single Logfire trace covers ingest → embed → moderate → cluster → compile → stitch → SSE; per-subagent token counts via `instrument_anthropic`; firewalled CI smoke test asserts OFFLINE_DEMO startup; PII regression test green on every PR; whitelisted span attributes only; Sentry `traces_sample_rate=0`, Logfire owns spans.
**Plans**: TBD

## Progress Summary

| Phase | Track | Plans Complete | Status | Completed |
|-------|-------|----------------|--------|-----------|
| 1. Foundation, Capture & Ingest | v1.0 | 5/5 | Complete | 2026-04-25 |
| 2. Marengo Embedding | v1.0 | 2/2 | Complete | 2026-04-25 |
| 3. Clustering + Debug Overlay | v1.0 | 2/2 | Complete | 2026-04-25 |
| 4. Multi-Agent Compile + Real-Time Feed | v1.0 | 3/3 | Complete | 2026-04-26 |
| 8. Observability Scaffolding | v1.1 backbone | 3/3 | Complete | 2026-04-28 |
| 9. Postgres Migration | v1.1 backbone | 9/9 | Complete | 2026-04-28 |
| 10. Vercel Blob Migration | v1.1 backbone | 1/1 | Complete | 2026-04-29 |
| 11. Moderation Gate | v1.1 backbone | 0/TBD | Not started | — |
| 12. Reactive Reporting + Admin Queue | v1.1 backbone | 0/TBD | Not started | — |
| 13. Observability Deepening + OFFLINE_DEMO Audit | v1.1 backbone | 0/TBD | Not started | — |
| 01. Anonymous comments + shares | v1.1 feature | 1/1 | Shipped (pending iPhone UAT) | 2026-04-28 |

---

*v1.1 sequencing: backbone runs as a dependency chain (Liam, phases 8-13). Feature track is opportunistic per-feature (Roan). Promote a feature backlog item to a phase by creating `.planning/phases/<NN>-<slug>/` with `<NN>-CONTEXT.md` and `<NN>-PLAN.md`.*

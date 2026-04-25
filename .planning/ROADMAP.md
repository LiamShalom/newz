# Roadmap: Newz

**Created:** 2026-04-24
**Granularity:** coarse (5 phases)
**Build window:** 24-48 hour hackathon (HackTech, Caltech, April 24-26 2026)
**Coverage:** 61/61 v1 requirements mapped

## Core Value

Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent segment. If clustering fails, the entire product premise fails.

## Phase Strategy

Build-order discipline: every phase ships a demoable artifact. If we stop at any phase, we have something to show. Phases are hour-sized, not week-sized.

| Phase | Goal | Time Estimate | Demoable Artifact |
|-------|------|---------------|-------------------|
| 1 | Foundation + Capture + Ingest | 5-7hr | Record on iPhone Safari, see clip play back from feed |
| 2 | Marengo Embedding | 3-4hr | Each clip gets a 512-d multimodal vector visible in debug |
| 3 | Clustering + Debug Overlay | 4-5hr | Staged clips fuse into one cluster with visible score breakdown — THE PITCH |
| 4 | Multi-Agent Compile + Real-Time Feed | 5-7hr | Four agents collaborate, segment renders live via SSE |
| 5 | Demo Hardening | remaining | `make demo` works offline, screencast as Tier 5 fallback |

## Phases

- [ ] **Phase 1: Foundation, Capture & Ingest** - Skeleton + iOS Safari camera verified + clips upload, persist, and play back from raw feed
- [ ] **Phase 2: Marengo Embedding** - 512-d multimodal vectors generated per clip, stored in SQLite, visible in debug
- [ ] **Phase 3: Clustering + Debug Overlay** - Composite-score clustering with calibration notebook proves staged clips fuse correctly; debug overlay shows the math
- [ ] **Phase 4: Multi-Agent Compile + Real-Time Feed** - Four-subagent Claude Agent SDK pipeline produces segments; SSE streams pipeline events; feed renders compiled segments live
- [ ] **Phase 5: Demo Hardening** - OFFLINE_DEMO mode, staged dataset replay button, single `make demo` command, 90s screencast committed

## Phase Details

### Phase 1: Foundation, Capture & Ingest
**Goal**: A user can open the app on a real iPhone, record a clip with GPS attached, and watch it play back from the feed — end-to-end with no AI yet.
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, CAP-01, CAP-02, CAP-03, CAP-04, CAP-05, CAP-06, CAP-07, CAP-08, CAP-09, CAP-10, ING-01, ING-02, ING-03, ING-04, ING-05, ING-06
**Success Criteria** (what must be TRUE):
  1. Judge can open the deployed Vercel URL on a real iPhone, see a feed without signing in, and tap a single FAB to enter the camera
  2. Judge can record a clip on iPhone Safari (with MIME-type fallback ladder working) and see it play back inline from the feed within seconds
  3. Submit returns 202 in under 100ms with a clip ID; the UI never blocks on the pipeline; failed uploads queue in localStorage and retry on reconnect
  4. Every uploaded clip has GPS lat/lng + timestamp + anonymous session UUID persisted (clip on `/data` volume, metadata in SQLite) and the pipeline is kicked off via `asyncio.create_task`
  5. iOS Safari hardware verification gate has been passed on a real iPhone (not emulator, not Chrome devtools) — recording, playback, and HTTPS camera/GPS permissions all confirmed
**Plans**: 5 plans
- [x] 01-01-repo-bootstrap-PLAN.md — FastAPI + Vite/React/TS/Tailwind 4 scaffold + /health + Makefile + .gitignore
- [x] 01-02-backend-ingest-PLAN.md — POST /clips (202 + asyncio.create_task), SQLite WAL schema, /clips static mount, GET /feed
- [x] 01-03-frontend-feed-shell-PLAN.md — Feed view + RecordFAB + EmptyState + FeedTile + session UUID + uploadQueue
- [x] 01-04-camera-mime-gps-PLAN.md — Recorder state machine: priming modal + MediaRecorder + CAP-10 MIME ladder + 30s ring + GPS-blocking submit
- [ ] 01-05-deploy-iphone-gate-PLAN.md — Vercel + Railway deploy config + real-iPhone hardware verification gate (FND-03)
**UI hint**: yes

### Phase 2: Marengo Embedding
**Goal**: Every ingested clip gets a real 512-d multimodal Marengo 3.0 embedding stored alongside its metadata, with mock-mode and pre-warm in place so demo-day cold-starts and offline dev are non-issues.
**Depends on**: Phase 1
**Requirements**: EMB-01, EMB-02, EMB-03, EMB-04, EMB-05
**Success Criteria** (what must be TRUE):
  1. After a clip is submitted, a `marengo3.0` embedding is generated and stored as a 512-d BLOB on the clip row in SQLite
  2. Setting `USE_MOCK_EMBEDDINGS=true` returns deterministic fake vectors so the rest of the pipeline can be developed and demoed without any Twelve Labs API call
  3. Embed worker logs end-to-end latency for every call; the value surfaces in the debug overlay so judges see real numbers
  4. Backend startup pre-warms Marengo with a throwaway call so the first real demo embed is never paying cold-start cost
**Plans**: 2 plans
Plans:
- [ ] 02-01-PLAN.md — DB schema + pipeline/embed.py (SDK v2 two-step, mock mode, run_in_executor, tenacity retry)
- [ ] 02-02-PLAN.md — config.py PRE_WARM_CLIP_PATH + lifespan pre-warm + wire embed_worker into run_pipeline

### Phase 3: Clustering + Debug Overlay
**Goal**: Staged demo clips fuse into a single cluster with visible Marengo / GPS / timestamp score breakdown, calibrated empirically against the actual demo dataset. This is the pitch — even if Phases 4-5 fail, this phase alone is demoable and proves the thesis.
**Depends on**: Phase 2
**Requirements**: CLU-01, CLU-02, CLU-03, CLU-04, CLU-05, CLU-06, CLU-07, CLU-08, CLU-09, CLU-10, RTM-04
**Success Criteria** (what must be TRUE):
  1. Three to four staged clips of the same event from different angles cluster together into one cluster, validated by the calibration notebook checked into the repo
  2. Two unrelated clips at the same time and same place do NOT cluster together (adversarial test in the notebook passes)
  3. Judge can open the debug overlay and see live score breakdown per cluster: Marengo cosine, GPS distance in meters, timestamp delta in seconds — and these numbers update as each clip embeds and clusters
  4. Threshold (default 0.55) is exposed as an env var and can be hot-swapped without redeploy; GPS weight collapses to 0 when geolocation is unavailable so Marengo carries the cluster
  5. Active clusters survive a backend restart — they rebuild from SQLite on startup with no Redis or external broker
**Plans**: 2 plans
Plans:
- [ ] 03-01-PLAN.md — pipeline/cluster.py + db helpers + run.py wiring + lifespan rebuild + cluster_assigned SSE
- [ ] 03-02-PLAN.md — staged demo clips + seed_demo.py + GET /debug/clusters route + calibration notebook (CLU-07/CLU-08)
**UI hint**: yes

### Phase 4: Multi-Agent Compile + Real-Time Feed
**Goal**: When a cluster reaches size >= 2, a four-subagent Claude Agent SDK pipeline (Angle Selector, Editor, Caption Writer, Publisher) produces a published segment within a 30s wall-clock cap; the feed re-renders live via SSE; judges see the AP-wire caption + multi-angle clip count overlay.
**Depends on**: Phase 3
**Requirements**: CMP-01, CMP-02, CMP-03, CMP-04, CMP-05, CMP-06, CMP-07, CMP-08, CMP-09, FED-01, FED-02, FED-03, FED-04, FED-05, RTM-01, RTM-02, RTM-03
**Success Criteria** (what must be TRUE):
  1. When the staged cluster reaches size 2, the compile pipeline kicks off automatically; Angle Selector and Caption Writer run in parallel; total wall-clock to published segment is under 30 seconds (with fallback if exceeded)
  2. Judge sees a vertical full-screen feed (TikTok-style autoplay) with each segment showing AI-written AP-wire-style caption, distance overlay ("2 blocks away"), age overlay ("4 min ago"), and source count badge ("Compiled from 4 angles")
  3. Judge can tap the FAB on any feed view to pivot to the camera and submit a new clip; the new clip flows through the pipeline and the feed re-renders the new segment at the top within 1 second of `segment_published`
  4. Captions are grounded — they reference only what is in the clips' metadata (date, neighborhood, source count); no hallucinated participant counts or motives
  5. SSE EventSource auto-reconnects on disconnect; an empty feed shows the pre-seeded staged demo segment so the first impression is never blank
**Plans**: TBD
**UI hint**: yes

### Phase 5: Demo Hardening
**Goal**: The full demo runs reliably under hostile conditions — venue WiFi dies, judge's iPhone won't grant permissions, Marengo or Anthropic rate-limits — without any scrambling on stage. `make demo` boots everything; OFFLINE_DEMO serves cached responses; the screencast is the Tier-5 fallback baked into the pitch deck.
**Depends on**: Phase 4
**Requirements**: DEM-01, DEM-02, DEM-03, DEM-04, DEM-05, DEM-06, DEM-07
**Success Criteria** (what must be TRUE):
  1. With network fully disabled, the staged event still clusters and compiles end-to-end because `OFFLINE_DEMO=true` serves cached embeddings + cached compile output (zero external API calls)
  2. A "Replay Staged Event" button on the feed re-injects the 3-4 pre-recorded staged clips through the pipeline as a one-tap fallback when live capture fails
  3. The `?demo_location=lat,lon` query param overrides browser geolocation so staged clips cluster correctly indoors at Caltech regardless of GPS accuracy
  4. A single `make demo` (or equivalent) command boots the full stack with the staged dataset already seeded — no multi-step setup at the demo table
  5. A 90-second pre-recorded screencast of the full demo flow is committed to the repo and embedded in pitch-deck slide 2 as the Tier-5 fallback
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation, Capture & Ingest | 5/5 | Complete | 2026-04-25 |
| 2. Marengo Embedding | 2/2 | Complete | 2026-04-25 |
| 3. Clustering + Debug Overlay | 0/2 | Planned | - |
| 4. Multi-Agent Compile + Real-Time Feed | 0/0 | Not started | - |
| 5. Demo Hardening | 0/0 | Not started | - |

## Phase-to-Pitfall Mapping

Pitfalls from research/PITFALLS.md, mapped to the phase that closes them:

| Pitfall | Severity | Closed in Phase |
|---------|----------|-----------------|
| 3. iOS Safari MediaRecorder broken | KILL-DEMO | Phase 1 (hardware gate) |
| 7. Marengo file format rejection | SLOW-BUILD | Phase 1 (CAP-05 30s cap, CAP-10 MIME ladder) |
| 8. Session continuity broken | SLOW-BUILD | Phase 1 (ING-06 anonymous UUID) |
| 9. Embed queue backup | SLOW-BUILD | Phase 1 (ING-02 fire-and-forget pattern) |
| 13. Mic permission blocks video | MINOR | Phase 1 (CAP-04 robust MediaRecorder) |
| 1. Marengo embed latency | KILL-DEMO | Phase 2 (EMB-03 mock + EMB-05 pre-warm) |
| 2. Clustering thresholds untuned | KILL-DEMO | Phase 3 (CLU-07 calibration notebook) |
| 4. GPS indoors broken | KILL-DEMO | Phase 3 (CLU-06 fallback) + Phase 5 (DEM-05 override) |
| 11. Adversarial cluster collision | MINOR | Phase 3 (CLU-08 adversarial test) |
| 5. Compile pipeline too slow | KILL-DEMO | Phase 4 (CMP-04 parallel + CMP-06 30s cap) |
| 12. Caption hallucination | MINOR | Phase 4 (CMP-08 grounded) |
| 10. Spinner-and-pray loading | SLOW-BUILD | Phase 4 (CMP-07 status events + RTM-03 SSE) |
| 6. Hackathon WiFi dies | KILL-DEMO | Phase 5 (DEM-04 OFFLINE_DEMO + DEM-06 screencast) |

## Out-of-Scope Reminders

Documented in PROJECT.md / REQUIREMENTS.md, repeated here so they don't sneak into a phase:

- No live streaming (WebRTC out of scope)
- No content moderation pipeline (acknowledged in pitch as Day 2)
- No user accounts / login / profiles (anonymity is load-bearing)
- No native iOS app (PWA sufficient)
- No likes / comments / engagement features
- No user-authored captions (AI is the editor)
- No vector DB (NumPy in-memory cosine over <1000 vectors)
- No Redis / Celery / message queue (asyncio.create_task only)
- No wow-factor snap animation, streaming caption tokens, or pipeline status banner (deferred to v2 — locked decision)

## Evolution

- **After each phase transition** (`/gsd-transition`): update PROJECT.md (Validated/Active/Out of Scope), update STATE.md current position, mark phase checkbox.
- **After milestone completion** (`/gsd-complete-milestone`): full review of phases vs. core value; audit out-of-scope reasons; archive.

---
*Last updated: 2026-04-24 after Phase 2 planning*

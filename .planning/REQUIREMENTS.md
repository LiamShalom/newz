# Requirements: Newz

**Defined:** 2026-04-24
**Core Value:** Multi-angle event clustering must work — show the same event captured by different people, automatically grouped and compiled into one coherent segment.

## v1 Requirements

Hackathon MVP scope. Each maps to a roadmap phase. v1 lock: live-first demo with staged-clip fallback, core flow only (no wow-factor animations beyond what's needed for the pipeline to be visible).

### Foundation

- [ ] **FND-01**: FastAPI backend boots locally with `/health` endpoint returning 200
- [ ] **FND-02**: React + Vite frontend boots locally with feed and record routes
- [ ] **FND-03**: iOS Safari MediaRecorder verified on real iPhone hardware (not emulator)
- [ ] **FND-04**: Backend deployed to Railway with persistent volume mounted at `/data`
- [ ] **FND-05**: Frontend deployed to Vercel with HTTPS (required for camera/GPS permissions)

### Capture

- [ ] **CAP-01**: User can open the app and see a feed without signing in (no account, no login)
- [ ] **CAP-02**: User can tap a single FAB on the feed to enter the camera
- [ ] **CAP-03**: User sees pre-permission priming modal explaining camera + GPS access before browser prompts
- [ ] **CAP-04**: User can record video via in-app camera using MediaRecorder API
- [ ] **CAP-05**: Recording has visible duration counter and hard 30-second cap
- [ ] **CAP-06**: User sees submit-or-retake preview screen after recording stops
- [ ] **CAP-07**: Browser geolocation captures GPS lat/lng at submit time (5s timeout, never blocks)
- [ ] **CAP-08**: Submit attaches GPS + timestamp to the clip and uploads via multipart POST
- [ ] **CAP-09**: Failed uploads queue in localStorage and retry on reconnect
- [ ] **CAP-10**: MIME type fallback ladder works on iOS Safari (mp4;avc1 → webm;vp9 → webm → no mimeType)

### Ingest

- [ ] **ING-01**: `POST /clips` accepts multipart upload (video file + lat + lng + timestamp)
- [ ] **ING-02**: Endpoint returns 202 within 100ms with a clip ID, never blocks on the pipeline
- [ ] **ING-03**: Clip file persisted to local FS at `/data/clips/{clip_id}.{ext}`
- [ ] **ING-04**: Clip metadata persisted to SQLite (clip_id, path, lat, lng, timestamp, status)
- [ ] **ING-05**: Pipeline kicked off via `asyncio.create_task` — embed → cluster → (maybe) compile
- [ ] **ING-06**: Anonymous session UUID stored in localStorage, attached to clips for "this is mine" UX (never sent to server as identity)

### Embedding

- [ ] **EMB-01**: Twelve Labs `marengo3.0` (lowercase) embedding generated for each ingested clip
- [ ] **EMB-02**: 512-dimension embedding vector stored in SQLite as BLOB on the clip row
- [ ] **EMB-03**: `USE_MOCK_EMBEDDINGS=true` flag returns deterministic fake vectors for offline dev
- [ ] **EMB-04**: Embed worker logs latency for every call (visible in debug overlay)
- [ ] **EMB-05**: Pipeline pre-warms Marengo with throwaway call on backend startup

### Clustering

- [ ] **CLU-01**: Online single-pass clustering algorithm assigns each new clip to a cluster or creates a new one
- [ ] **CLU-02**: Composite score = 0.55 × Marengo cosine + 0.30 × GPS proximity + 0.15 × timestamp proximity
- [ ] **CLU-03**: GPS proximity normalized over 200m radius (1.0 at 0m, 0 at >=200m)
- [ ] **CLU-04**: Timestamp proximity normalized over 600s window (1.0 at 0s, 0 at >=600s)
- [ ] **CLU-05**: Threshold 0.55 (starting value) for join-vs-create — exposed as env var for hot-swap
- [ ] **CLU-06**: GPS weight collapses to 0 when geolocation unavailable (Marengo-only fallback)
- [ ] **CLU-07**: Calibration notebook in repo proves staged demo clips cluster correctly with chosen threshold
- [ ] **CLU-08**: Adversarial test: two unrelated clips at same time + same place do NOT cluster together
- [ ] **CLU-09**: Debug overlay shows score breakdown per cluster (Marengo cosine, GPS distance in m, timestamp delta in s)
- [ ] **CLU-10**: Active clusters cached in memory, rebuilt from SQLite on startup (no Redis)

### Compile (Multi-Agent Pipeline)

- [ ] **CMP-01**: Compile triggered when cluster size >= 2 AND no compile in flight
- [ ] **CMP-02**: Claude Agent SDK orchestrator with 4 sub-agents: Angle Selector, Editor, Caption Writer, Publisher
- [ ] **CMP-03**: Each sub-agent has a constrained tool set (Angle Selector reads scores, Publisher is the only one that writes the segment)
- [ ] **CMP-04**: Angle Selector and Caption Writer run in parallel where independent; Editor → Publisher is sequential
- [ ] **CMP-05**: Pipeline produces a segment record: ordered clip IDs, AP-wire-style caption with date + location, source clip count
- [ ] **CMP-06**: Hard 30-second wall-clock cap; on timeout, fallback to default ordering + generic caption
- [ ] **CMP-07**: Pipeline status (current agent, elapsed time) emitted as events for SSE
- [ ] **CMP-08**: Caption is grounded — references only what is in the clips' metadata (no hallucinated details)
- [ ] **CMP-09**: Re-compiles when new clip joins existing cluster (debounced 30s)

### Feed (Consume)

- [ ] **FED-01**: `GET /feed?lat&lng` returns published segments sorted by proximity to viewer + recency
- [ ] **FED-02**: Vertical full-screen feed with autoplay-on-scroll (TikTok-style)
- [ ] **FED-03**: Each segment card shows: video, AI caption, distance overlay ("2 blocks away"), age overlay ("4 min ago"), source count badge ("Compiled from 4 angles")
- [ ] **FED-04**: One-tap pivot from feed to camera (FAB visible on every feed view)
- [ ] **FED-05**: Empty state shows pre-seeded staged demo segment so feed is never blank

### Real-Time Updates

- [ ] **RTM-01**: `GET /events` SSE endpoint streams pipeline events (clip_added, cluster_updated, segment_published)
- [ ] **RTM-02**: Frontend EventSource auto-reconnects on disconnect
- [ ] **RTM-03**: Feed re-renders new segment at top within 1 second of `segment_published` event
- [ ] **RTM-04**: Debug overlay updates similarity scores live as clips are embedded and clustered

### Demo Hardening

- [ ] **DEM-01**: Pre-recorded staged dataset (3-4 clips of one event from different angles) committed to repo
- [ ] **DEM-02**: Embeddings + compiled segment for staged dataset pre-computed and cached on disk
- [ ] **DEM-03**: "Replay Staged Event" button on feed runs the staged dataset through the pipeline as a one-tap fallback
- [ ] **DEM-04**: `OFFLINE_DEMO=true` env flag serves cached embeddings + cached compile output, requires zero external API calls
- [ ] **DEM-05**: `?demo_location=lat,lon` query param overrides browser geolocation for staged clips at the venue
- [ ] **DEM-06**: 90-second pre-recorded screencast of the full demo committed to repo for pitch-deck Tier 5 fallback
- [ ] **DEM-07**: Single `make demo` (or equivalent) command boots full stack with staged data ready

## v2 Requirements

Deferred. Acknowledged but not in the hackathon roadmap.

### Wow-Factor Visuals

- **WOW-01**: Live "snap" animation as clips visually merge into a cluster crossing threshold
- **WOW-02**: Streaming caption tokens (caption types itself during compile)
- **WOW-03**: Multi-agent pipeline status banner ("Angle Selector: done · Editor: working...")
- **WOW-04**: Visible similarity scores as a permanent feed overlay (currently in debug only)

### Trust & Moderation

- **MOD-01**: Report-clip flow
- **MOD-02**: Automated NSFW detection on embed
- **MOD-03**: Admin dashboard for cluster review

### Engagement

- **ENG-01**: Per-segment likes / reactions
- **ENG-02**: Push notifications for events near user
- **ENG-03**: Map view of recent events

### Platform

- **PLT-01**: Native iOS app (PWA → native)
- **PLT-02**: Live streaming (WebRTC)
- **PLT-03**: National / regional feed escalation

## Out of Scope

Explicitly excluded for the hackathon. Documented to prevent scope creep mid-build.

| Feature | Reason |
|---------|--------|
| User accounts / login / profiles | Anonymity by default is the load-bearing differentiator — adding accounts contradicts the value prop |
| User-authored captions | Defeats anonymity AND the AI editorial moat — pipeline IS the editor |
| Live streaming | Days of WebRTC work; out of scope per PROJECT.md |
| Likes / comments / reactions | Adds moderation surface; requires identity model; not in core flow |
| National / regional feed | Hyperlocal IS the differentiator — broadening dilutes the pitch |
| Content moderation pipeline | Multi-week build; acknowledged in pitch as Day 2 work |
| Native iOS app | Multi-day effort; PWA sufficient for demo |
| In-app clip editing | Defeats "tap and submit" — zero-friction is the promise |
| Map view of events | Significant UI work; feed shows distance overlay; defer |
| Wow-factor snap animation | Liam's call: defer to post-hackathon, demo proves clustering with real-time recording instead |
| Streaming caption / status banner | Deferred — focus on shipping core flow cleanly |
| Pinecone / Qdrant / vector DB | NumPy in-memory cosine is faster + zero infra at <1000 vectors |
| Redis / Celery / message queue | One process + asyncio.create_task is sufficient at hackathon scale |
| Server-side video transcoding | Browser-recorded clips play back as-is on the same browser; no transcode needed |

## Traceability

Populated during roadmap creation by gsd-roadmapper.

| Requirement | Phase | Status |
|-------------|-------|--------|
| (filled by roadmapper) | | |

**Coverage:**
- v1 requirements: 50 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 50 ⚠️ (will be 0 after roadmap)

---
*Requirements defined: 2026-04-24*
*Last updated: 2026-04-24 after initial definition*

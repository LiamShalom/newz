# Project Research Summary

**Project:** Newz — AI-native hyperlocal news from anonymous crowd video
**Domain:** Crowdsourced multimodal video clustering + agentic editorial compile
**Researched:** 2026-04-24
**Confidence:** HIGH (stack, architecture, features); MEDIUM (clustering thresholds, demo hardening specifics)

---

## TL;DR — Load-Bearing Decisions

1. **Single FastAPI monolith, no microservices.** One `uvicorn` process runs embed + cluster + compile as asyncio coroutines. Redis/Celery/BullMQ are explicitly ruled out. Any added service is a demo failure mode.
2. **Marengo 3.0 sync embed is the core magic, but it takes 5–30s.** Never block the UI on it. Fire-and-forget on POST /clips, poll status via SSE. Pre-embed all staged demo clips before the pitch starts.
3. **Clustering is the product thesis — must be calibrated empirically before the demo.** Weights: Visual 55%, GPS 30%, Time 15%, threshold 0.55. These are starting points; run the actual demo clips through a notebook to validate by hour 12.
4. **The four-agent compile pipeline (Angle Selector → Editor → Caption Writer → Publisher) is the "Best Use of AI" narrative.** Non-negotiable. Must stream status to UI. Parallelize where independent. Hard-cap at 30s wall-clock.
5. **Pre-recorded staged demo dataset is load-bearing, not optional polish.** Live capture will fail under demo conditions (indoor GPS, hackathon WiFi, iOS camera permissions). All 6 WOULD-KILL-DEMO pitfalls require pre-computed fallbacks to survive.

---

## Stack (Locked)

| Layer | Choice | Version | Notes |
|-------|--------|---------|-------|
| Frontend | React + Vite + TypeScript | React 18.3, Vite 5 | Not Next.js — no SSR needed; Vite cold-start <1s |
| Styling | Tailwind CSS | 4.x | Zero design overhead |
| Routing | React Router | 6.x | Two routes: `/` (feed) + `/record` (camera) |
| Backend | FastAPI + Uvicorn | 0.115 / 0.30 | Native async, Pydantic v2, first-class SDK support |
| Runtime | Python | 3.11 | 3.10+ required by Agent SDK; avoid 3.13 (patchy wheels) |
| Video AI | `twelvelabs` SDK → Marengo 3.0 | 1.2.3 | **`marengo3.0`** (lowercase, no hyphen). 2.7 sunset 2026-03-30. |
| Multi-agent | `claude-agent-sdk` | 0.1.68 | Bundles CLI binary — no Node.js needed on Railway. Pin this version. |
| Vector search | NumPy in-memory cosine | 2.x | Single matmul over ≤1000 vectors. No vector DB. |
| Metadata DB | SQLite via aiosqlite | WAL mode | Zero-config; sufficient at hackathon scale |
| Video storage | Local FS + FastAPI StaticFiles | — | No S3. One line, never fails. |
| FE hosting | Vercel | — | Push-to-deploy; CDN/HTTPS automatic |
| BE hosting | Railway | — | Auto-detects FastAPI; persistent volume for `/data` |

**Do-Not-Use List:**
- `Marengo-retrieval-2.7` — dead since 2026-03-30
- FastAPI on Vercel — 10s function timeout kills the pipeline
- Pinecone / Qdrant / ChromaDB — unnecessary at <1000 vectors, adds external failure modes
- Redis / Celery / BullMQ — overkill for single-process demo
- `MediaRecorder` with hardcoded `mimeType: "video/webm"` — silently fails on iOS Safari
- User auth / accounts / login — contradicts the load-bearing anonymity differentiator

**SDK version pinning matters:**
- `claude-agent-sdk 0.1.68` is the stable Sonnet/Haiku line. To use Opus 4.7, pin `>=0.2.111` — the two SDK lines have incompatible APIs for Opus model tokens.
- `twelvelabs 1.2.3` — verify on day 1 with `pip show twelvelabs` and a 30-second REPL check of `dir(client.embed)`.

---

## Architecture

### System Shape

Single-process FastAPI monolith. Pipeline stages are asyncio coroutines chained via `asyncio.create_task` — no separate workers, no message brokers.

```
Browser (React)
  Recorder.tsx  →  POST /clips (multipart: file, lat, lng, ts)
  Feed.tsx       →  GET /feed?lat&lng
                    GET /events (SSE)
  Debug.tsx      →  GET /clusters/:id

FastAPI Monolith (one uvicorn process)
  POST /clips → 202 immediately → asyncio.create_task(run_pipeline)
  Background: embed_worker → cluster_worker → compile_worker
  SSE event bus: asyncio.Queue per connected client

Storage
  /data/clips/{id}.webm   — served via StaticFiles
  newz.db (SQLite)        — clips, embeddings, clusters, segments
  In-memory: active_clusters list (rebuilt from SQLite at startup)

External APIs
  Twelve Labs → Marengo 3.0 embed (512-d vectors, sync path for <10min clips)
  Anthropic   → Claude Agent SDK compile pipeline
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `Recorder.tsx` | MediaRecorder + Geolocation + multipart POST |
| `Feed.tsx` | SSE listener + segment grid (vertical, full-screen autoplay) |
| `Debug.tsx` | Cluster score overlay — load-bearing for judge demo |
| `pipeline/embed.py` | Twelve Labs Marengo 3.0 wrapper; store 512-d vectors as SQLite BLOB |
| `pipeline/cluster.py` | Online single-pass clustering with composite score; in-memory centroid cache |
| `pipeline/compile.py` | Claude Agent SDK 4-subagent pipeline; writes segment to SQLite |
| `events.py` | SSE bus — `asyncio.Queue` per client, broadcast on each pipeline transition |
| `seed/` | Pre-recorded demo clips + replay script — runs on startup to pre-populate DB |

### Clustering Algorithm (Concrete)

```python
W_VISUAL = 0.55   # Marengo multimodal is the dominant signal
W_GPS    = 0.30   # Hyperlocal GPS prevents cross-location false merges
W_TIME   = 0.15   # Prevents same-corner morning/evening merge
THRESHOLD = 0.55  # Empirically validate against staged demo dataset — do not ship untuned
```

Each score normalized to [0,1]: cosine similarity, GPS proximity within 200m radius, timestamp within 10-minute window. Composite = weighted sum. New clip joins best-scoring cluster if composite >= threshold, else creates a new cluster. Online/streaming — no batch reclustering needed at hackathon scale.

### Compile Trigger

Compile when: cluster size >= 2 AND no compile in-flight AND (size just hit 3 OR 30s elapsed since last new arrival).

### Data Flow (Hot Path)

```
User taps Stop → Blob + GPS + ts
→ POST /clips → 202 in <100ms
→ background: Marengo embed (~5-30s) → cluster assign → (if threshold) compile (~10-30s)
→ SSE broadcasts: clip_added → cluster_updated → segment_published
→ Feed re-renders with new segment tile at top
```

### Build-Order Checkpoints

| Checkpoint | Deliverable | Est. Time | Gate Condition |
|-----------|-------------|-----------|----------------|
| 0 | Skeleton (FastAPI /health + React shell with router) | 1-2hr | Both servers start |
| 1 | Capture + Playback — record on phone, see in feed | 3-4hr | **First demo-capable slice. iOS Safari verified on real hardware.** |
| 2 | Marengo embedding — 512-d vector per clip | 3-4hr | Vectors stored in SQLite, visible in debug |
| 3 | Clustering + Debug Overlay — staged clips fuse correctly | 4-5hr | **The pitch. Score breakdown visible. Calibration notebook done.** |
| 4 | Multi-agent compile — 4-agent pipeline produces segment | 4-5hr | Headline + caption + ordered clips in feed, wall-clock <30s |
| 5 | SSE real-time feed — replace 3s polling | 2-3hr | Feed updates live without refresh |
| 6 | Polish + offline mode | remaining | Single `make demo` command works with network disabled |

**Critical gate:** Do NOT advance past Checkpoint 1 until iOS Safari camera + playback is verified on a real phone. Emulators lie.

---

## Features by Category

### Table Stakes (Ship Broken = Demo Dead)

- One-tap record from feed (single FAB, no multi-step)
- Pre-permission priming modal before browser camera/GPS dialogs (NN/g: +28-81% grant rate)
- Visible recording indicator + duration counter + hard 30s cap
- Submit-or-retake preview screen
- Vertical TikTok-style feed with full-screen autoplay, swipe-up navigation
- Proximity + recency sort (hyperlocal IS the product)
- "2 blocks away · 4 min ago" distance + age overlay per segment
- Loading state during compile showing phase names ("clustering → selecting angles → writing caption")
- Graceful empty state + pre-seeded demo dataset as fallback
- Network retry with local persist on submit (hackathon WiFi will fail)
- Source clip count badge: "Compiled from 4 angles"

### Differentiators (Newz vs. Citizen / TikTok / Watch Duty)

- **Multi-angle compiled segment** — Citizen shows one stream, TikTok shows N independent clips, Newz fuses them. This is the entire product premise.
- **Marengo-driven multimodal clustering** — no human moderator; automated; show the math in debug view
- **Anonymous-by-default** — no sign-in screen, by design; load-bearing for sensitive footage value prop
- **AI-written AP-wire-style captions** — neutral, factual, with location + timestamp; no user input
- **Recorder-viewer same loop** — everyone is a journalist; no creator/consumer split
- **Cluster confirmation count as trust signal** — "Confirmed by 4 independent angles" replaces account credibility
- **Hyperlocal-only forever** — Citizen and Watch Duty both went national and lost neighborhood feel

### Demo Wow Factor (Priority Order)

1. **Live clustering visualization** — clips "snap" into cluster in real time as Marengo similarity crosses threshold. THE money shot.
2. **Visible similarity scores** — Marengo 0.87, GPS 12m, delta-t 38s. Numbers = "real, not vibes."
3. **Multi-agent pipeline status stream** — "Angle Selector: done · Editor: done · Caption Writer: working..." Four agents, visible.
4. **Streaming AP-wire caption** — tokens type themselves during compile. Cinematic, cheap to build.
5. **One-tap full demo loop** — scroll → record → capture → cluster forms → segment appears. <60s end-to-end.

### Anti-Features (Not Building)

| Feature | Why Not |
|---------|---------|
| Live streaming | Days of WebRTC work; out of scope per PROJECT.md |
| Likes / comments | Adds moderation surface, requires identity model |
| User-authored captions | Defeats anonymity; AI caption is the editorial moat |
| Accounts / profiles | Defeats the entire value prop |
| Content moderation | Multi-week build; acknowledge in pitch as Day 2 |
| National feed | Citizen/Watch Duty went national and lost neighborhood feel |
| Map view | Significant UI work; feed shows distance; defer to v1.x |
| Native iOS app | Multi-day build; PWA sufficient for demo |
| In-app editing | Defeats "tap and submit" promise; pipeline IS the editor |

---

## Top 6 Pitfalls (All WOULD-KILL-DEMO)

### 1. Marengo embed latency blocks "submit → cluster forms" moment
**Risk:** 20–60s blank screen between submission and cluster visualization kills demo momentum.
**Prevention:** Fire-and-forget architecture from day 1. Return 202 immediately. Multi-stage SSE progress. Pre-embed all staged clips before pitch. Pre-warm with throwaway API call 60s before demo. `USE_MOCK_EMBEDDINGS=true` flag for development.
**Address in:** Checkpoint 1 — pattern established from day 1, not hour 30.

### 2. Clustering thresholds untuned — clips don't group OR everything merges
**Risk:** Staged clips fail to cluster (threshold too high) or every submission collapses into one cluster (too low). Either breaks the product thesis.
**Prevention:** Calibrate with real demo dataset by hour 12. Compute pairwise cosine scores in a notebook, set threshold based on actual distribution. Add adversarial test: 2 unrelated clips, same time + place, must NOT cluster. Expose threshold as env var for hot-swap without redeploy.
**Address in:** Checkpoint 3 — calibration notebook is a phase deliverable, not optional.

### 3. iOS Safari MediaRecorder produces broken/unplayable video
**Risk:** Demo on iPhone → Safari → silent MediaRecorder failure → black screen → Marengo rejection.
**Prevention:** Test on real iPhone from Checkpoint 1. MIME type detection ladder: mp4;avc1 → webm;vp9 → webm → no mimeType. Always `<video playsinline muted autoplay>`. HTTPS only.
**Address in:** Checkpoint 0/1 — first thing built must be "iOS Safari records and plays back."

### 4. Indoor GPS at Caltech returns wrong building or POSITION_UNAVAILABLE
**Risk:** Three clips from same room read as 200m apart. GPS clustering collapses the "same event same place" story.
**Prevention:** GPS is a weighted signal (30%), not a hard filter. Weight = 0 if unavailable, Marengo carries the cluster. Ship `?demo_location=lat,lon` query param override for staged clips. Set GPS timeout 5s, never block submit.
**Address in:** Checkpoint 0 (browser) + Checkpoint 3 (weighted signal) + demo prep.

### 5. Compile pipeline takes 90+ seconds — judges lose interest
**Risk:** 4 sequential subagents x 10-20s each = 40-80s wall-clock. Judges read a sentence between submit and segment ready.
**Prevention:** Parallelize Angle Selector and Caption Writer (independent). Only Editor → Publisher must be sequential. Hard-cap at 30s; fallback to default ordering + generic caption if exceeded. Pre-compile staged demo segment and cache it. Stream status tokens to UI.
**Address in:** Checkpoint 4 — parallel design from the start, not as a fix.

### 6. Hackathon venue WiFi dies mid-demo
**Risk:** Marengo or Anthropic API timeouts cascade. Frontend can't reach backend. Demo dies.
**Prevention:** Multi-tier offline strategy: (1) personal hotspot, (2) `OFFLINE_DEMO=true` env flag serves everything from local SQLite + disk, (3) 90s pre-recorded screencast in pitch deck slide 2. Test Tier 1, 2, 4 before demo day. Test Tier 3 night-before at venue.
**Address in:** Checkpoint 6 — offline mode is an engineering deliverable.

---

## Implied Phase Ordering

### Phase 0: Foundation + iOS Camera Verification (1-2hr)
**Rationale:** Unblocks everything. iOS Safari must work before any other code has demo value.
**Delivers:** FastAPI /health, React shell, MediaRecorder verified on real iPhone, GPS permission flow.
**Pitfall closed:** Pitfall 3 (iOS Safari). Verify on real hardware before writing a line of backend logic.
**Research flag:** Standard patterns — fully documented in STACK.md/ARCHITECTURE.md.

### Phase 1: Clip Ingest + Raw Feed (3-4hr)
**Rationale:** First demoable slice — establishes full upload → storage → render loop. Fire-and-forget async pattern locked in here, not later.
**Delivers:** POST /clips (202 + background pipeline kick), GET /feed returns raw clips, video plays. Network retry + local persist. Marengo file format validation. Anonymous session UUID in localStorage.
**Pitfalls closed:** Pitfall 1 (async pattern), Pitfall 7 (file rejection), Pitfall 8 (session continuity), Pitfall 9 (concurrent embed queue).
**Research flag:** Standard patterns.

### Phase 2: Marengo Embedding (3-4hr)
**Rationale:** Clustering is impossible without real embeddings. Build against fake vectors first = rewrite later.
**Delivers:** 512-d multimodal vectors per clip in SQLite. Embedding status in debug view. Pre-warm on startup. `USE_MOCK_EMBEDDINGS` flag.
**Pitfall closed:** Pitfall 1 (latency — async pattern already in place from Phase 1).
**Research flag:** Verify `dir(client.embed)` in a 30-second REPL on day 1 before writing embed.py.

### Phase 3: Clustering + Debug Overlay (4-5hr)
**Rationale:** This is the pitch. Working clustering + visible debug overlay = the demo is demoable even if Phases 4-6 fail.
**Delivers:** Online composite clustering (V55/G30/T15 / threshold 0.55). Debug overlay with score breakdown. Seed script. Calibration notebook checked into repo. Adversarial test passing.
**Pitfalls closed:** Pitfall 2 (untuned thresholds — notebook is a deliverable), Pitfall 4 (GPS — demo_location override), Pitfall 11 (adversarial cluster collision).
**Research flag:** Threshold calibration requires empirical work — cannot be skipped.

### Phase 4: Multi-Agent Compile Pipeline (4-5hr)
**Rationale:** "Best Use of AI" narrative. Must come after clustering is verified — broken clusters produce gibberish segments.
**Delivers:** 4-subagent pipeline with parallelized independent agents. Segment in SQLite. Status stream to UI. 30s hard timeout + fallback. Pre-compiled cached segment for staged dataset.
**Pitfalls closed:** Pitfall 5 (compile too slow — parallel from start), Pitfall 12 (caption hallucination — grounded prompt).
**Research flag:** Verify Agent SDK parallel subagent execution syntax in 0.1.68 docs before writing compile.py.

### Phase 5: SSE Real-Time Feed (2-3hr)
**Rationale:** Replaces 3s polling. Required for live clustering visualization (the wow moment). Low risk, high demo impact.
**Delivers:** EventSource connection, live feed updates on each pipeline transition, cluster animation on `cluster_updated`.
**Wow factors enabled:** Live clustering visualization, multi-agent pipeline status stream.
**Research flag:** Standard patterns — fully specified in ARCHITECTURE.md.

### Phase 6: Demo Polish + Offline Mode (remaining time)
**Rationale:** Judge-facing polish + demo survival mechanisms. Offline mode is an engineering deliverable, not a scramble.
**Delivers:** Proximity + recency feed sort, loading state copy, "Replay Staged Event" button, `OFFLINE_DEMO=true`, pre-recorded 90s screencast, single `make demo` entry point.
**Pitfall closed:** Pitfall 6 (WiFi dies).
**Research flag:** No research needed — execution only.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI, official docs, GitHub releases 2026-04-24. REPL-check SDK surfaces on day 1. |
| Features | HIGH | Competitor analysis thorough (Citizen, Watch Duty, Nextdoor, TikTok, BeReal). Wow-factor ordering validated against hackathon judging criteria. |
| Architecture | HIGH | Component shape, data flow, AsyncIO patterns well-documented. Agent SDK subagent parallelization is MEDIUM — verify before writing compile.py. |
| Pitfalls | MEDIUM-HIGH | iOS Safari and Marengo latency have documented root causes. Clustering thresholds are empirically unverified starting points. |

**Overall confidence:** HIGH for build decisions. MEDIUM for threshold calibration.

### Gaps Requiring Empirical Validation During Build

1. **Clustering threshold 0.55** — starting point; must be calibrated against actual staged demo clips by hour 12. Non-negotiable Phase 3 deliverable.
2. **Marengo same-event cosine similarity range** — research estimates 0.5–0.8 for different-angle same-event clips. Actual distribution on your staged clips determines whether W_VISUAL=0.55 holds.
3. **Compile pipeline wall-clock with parallel subagents** — must be measured with real API latency. If >30s, cached segment becomes primary demo path.
4. **Indoor GPS accuracy at Caltech** — likely worse than the 35-100m desktop estimate. Test night-before at venue. `?demo_location` override covers worst case.
5. **Agent SDK parallel subagent syntax in 0.1.68** — ARCHITECTURE.md shows sequential pattern; verify parallel execution approach in SDK docs before writing compile.py.

---

## Sources

### Primary (HIGH confidence)
- TwelveLabs Marengo 3.0 docs + release notes — 2.7 sunset, 3.0 GA, 512-d vectors, sync path
- TwelveLabs Python SDK 1.2.3 (PyPI) — current API surface, file format requirements (4s min, 360x360 min)
- Claude Agent SDK docs (code.claude.com) — AgentDefinition, Agent tool requirement, context isolation
- claude-agent-sdk-python 0.1.68 (GitHub) — bundled CLI binary, no Node.js dep
- FastAPI background task docs — asyncio.create_task vs BackgroundTasks distinction
- MDN MediaRecorder + WebKit blog — iOS Safari codec support, MIME fallback pattern
- Railway FastAPI deploy guide — persistent volume, auto-detect

### Secondary (MEDIUM confidence)
- Online clustering algorithm patterns — single-pass composite score well-established; weights are domain-specific
- NN/g permission priming research — 28-81% grant rate lift with contextual priming
- iOS MediaRecorder duration bug — community-confirmed, Apple Developer Forums
- Hackathon WiFi failure patterns — broad field evidence; offline mode strategy is industry-standard

---

*Research completed: 2026-04-24*
*Ready for roadmap: yes*
*Next step: roadmapper agent creates phases from Implied Phase Ordering above*

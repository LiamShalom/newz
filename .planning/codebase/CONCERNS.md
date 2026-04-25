# Codebase Concerns

**Analysis Date:** 2026-04-24

> **Note:** No source code has been written yet — the project is at Phase 0 (planning complete, implementation pending). All concerns are architectural and design-level, surfaced from `.planning/research/PITFALLS.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/STACK.md`, and `.planning/REQUIREMENTS.md`. These are not bugs but known risks that must be designed around as implementation begins.

---

## Tech Debt

**Hardcoded clustering threshold (CLU-05):**
- Issue: The starting composite score threshold of 0.55 and weights (W_VISUAL=0.55, W_GPS=0.30, W_TIME=0.15) in `backend/pipeline/cluster.py` are empirically unverified starting points. Shipping without calibration against the real demo dataset is the single highest-probability demo failure.
- Files: `backend/pipeline/cluster.py` (to be created), `.planning/research/ARCHITECTURE.md` (weight rationale)
- Impact: Staged clips fail to cluster (threshold too high) OR every clip collapses into one mega-cluster (threshold too low). Either breaks the product thesis entirely.
- Fix approach: Calibration notebook (`backend/notebooks/calibrate_thresholds.ipynb`) is a mandatory Phase 3 deliverable — run staged demo clips through it, plot pairwise similarity distribution, set threshold based on actual gap between same-event and different-event scores. Expose all weights and threshold as env vars (`CLUSTER_W_VISUAL`, `CLUSTER_W_GPS`, `CLUSTER_W_TIME`, `CLUSTER_THRESHOLD`) for hot-swap without redeploy.

**Single-pass online clustering is order-dependent:**
- Issue: The planned online assignment algorithm (`assign_or_create` in `backend/pipeline/cluster.py`) is order-dependent — a clip arriving "early" may seed a cluster that should have merged into a later one.
- Files: `backend/pipeline/cluster.py` (to be created), `.planning/research/ARCHITECTURE.md` (Pattern 2)
- Impact: In controlled demo conditions (staged clips, known arrival order), this is acceptable. Under random judge submissions, clips may fork into separate clusters that should be one.
- Fix approach: Acceptable for hackathon scope. Document in pitch as "online streaming clustering — some edge cases at scale." For production, add periodic batch recluster job.

**In-process asyncio pipeline — no durability:**
- Issue: The entire embed → cluster → compile pipeline runs as `asyncio.create_task` coroutines inside the single FastAPI process. A process crash mid-pipeline drops all in-flight work silently.
- Files: `backend/app.py` (to be created), `.planning/research/ARCHITECTURE.md` (Pattern 1)
- Impact: If the Railway container restarts mid-demo, any clips currently embedding or compiling are lost. The pipeline must be re-fired manually.
- Fix approach: Acceptable for hackathon. Mitigate with idempotent pipeline stages (`if already_done: skip` on every stage), persistent `embedding_status` column in SQLite (`pending | done | failed`), and a startup recluster from SQLite (`CLU-10`). If process restarts, `seed.py` re-fires the staged dataset automatically.

**No retry logic scaffolded for Marengo failures:**
- Issue: Every Marengo API call in `backend/pipeline/embed.py` is a single-attempt request. A transient 503 or rate-limit response drops the clip permanently (no retry queue).
- Files: `backend/pipeline/embed.py` (to be created), `.planning/research/PITFALLS.md` (Tech Debt table)
- Impact: Under demo load (3-5 concurrent uploads), a single Marengo 429 silently loses a judge's clip. The clip shows as "embedded: failed" with no recovery path.
- Fix approach: Wrap every Marengo call in `tenacity` retry decorator: 3 attempts, exponential backoff (2s, 4s, 8s). Log attempt count. Fall back to `USE_MOCK_EMBEDDINGS` if all retries exhausted and the flag is set.

**Compile pipeline subagent parallelization unverified:**
- Issue: `ARCHITECTURE.md` shows a sequential orchestrator pattern. The requirement for Angle Selector and Caption Writer to run in parallel (`CMP-04`) depends on Claude Agent SDK 0.1.68 parallel subagent execution syntax that has not been verified against the actual SDK.
- Files: `backend/pipeline/compile.py` (to be created), `.planning/research/SUMMARY.md` (Gap 5)
- Impact: If parallel execution syntax is wrong, all four agents run sequentially: 4 × 10-20s = 40-80s wall-clock. This exceeds the 30s hard cap, meaning the demo ALWAYS falls back to the cached segment — reducing the live AI narrative.
- Fix approach: Verify with a 5-minute REPL check of `claude-agent-sdk==0.1.68` parallel agent invocation docs on day 1 BEFORE writing `compile.py`. Confirm with `?demo_location` and a one-clip test cluster.

**SQLite WAL mode + in-memory cluster index dual-write drift:**
- Issue: The design maintains both an `active_clusters` in-memory list (for fast assignment loop) AND SQLite rows (for durability). If a write to one succeeds and the other fails, they drift out of sync.
- Files: `backend/pipeline/cluster.py` (to be created), `backend/db.py` (to be created)
- Impact: Feed shows different cluster state than what the in-memory algorithm is working from. Manifests as "clip joined a cluster that the feed doesn't show" or "score breakdown in debug shows different members than the feed."
- Fix approach: Always write SQLite first, then update in-memory. On startup, always rebuild in-memory from SQLite (never from a cache file). Keep the mutation surface small: only `assign_or_create` should mutate both.

---

## Known Bugs (Pre-Implementation Risks)

**iOS Safari MediaRecorder silent failure on wrong MIME type:**
- Symptoms: Recording appears to work (no JS error thrown), but the resulting Blob is empty or produces a zero-duration file. Marengo rejects the upload with a 4xx. The feed never updates.
- Files: `frontend/src/views/Recorder.tsx` (to be created), `.planning/research/PITFALLS.md` (Pitfall 3)
- Trigger: Passing `mimeType: "video/webm"` or `"video/webm;codecs=vp9"` to `MediaRecorder` constructor on iOS Safari.
- Workaround: MIME type detection ladder must be the first code written in `Recorder.tsx`. Pattern: probe `MediaRecorder.isTypeSupported()` in order: `video/mp4;codecs=avc1,mp4a` → `video/mp4` → `video/webm;codecs=vp9,opus` → `video/webm` → omit entirely. If no mimeType is supported, pass no mimeType option at all (Safari historically more stable with no option than a wrong one).

**MediaRecorder duration metadata missing (Safari):**
- Symptoms: Recorded file has `duration: NaN` or `0` in metadata. Backend `ffprobe` check rejects clip. Marengo minimum 4s duration requirement fails even on a 10s recording.
- Files: `frontend/src/views/Recorder.tsx` (to be created), `backend/app.py` (to be created), `.planning/research/PITFALLS.md` (Pitfall 3)
- Trigger: Safari MediaRecorder does not write duration metadata into the MP4 container when recording stops.
- Workaround: Do not rely on duration metadata from the Blob. Either (a) record in fixed 5s chunks and stitch on backend, or (b) track recording duration in JS (`Date.now()` delta) and pass it as a separate form field alongside the upload. Backend uses the JS-reported duration for Marengo validation.

**GPS `POSITION_UNAVAILABLE` silently drops the clustering GPS signal:**
- Symptoms: Clip uploads successfully but is assigned `lat=null, lng=null`. Cluster assignment runs with `W_GPS=0`, producing a Marengo-only cluster. If Marengo cosine is borderline (0.5-0.6), clips that should cluster may miss the 0.55 threshold.
- Files: `frontend/src/views/Recorder.tsx` (to be created), `backend/pipeline/cluster.py` (to be created), `.planning/research/PITFALLS.md` (Pitfall 4)
- Trigger: Indoor GPS at Caltech. `enableHighAccuracy: true` worsens this — slow fix, frequent timeout.
- Workaround: `CLU-06` (GPS weight collapses to 0 when unavailable) covers the algorithm side. For demo day, `?demo_location=lat,lon` query param (`DEM-05`) overrides browser geolocation for staged clips. Set `enableHighAccuracy: false, timeout: 5000, maximumAge: 30000` in all geolocation calls.

**Compile pipeline 30s timeout produces generic caption — indistinguishable from error:**
- Symptoms: Pipeline fires, wall-clock hits 30s, fallback segment is written with default angle ordering and generic caption "Event compiled from N clips." Judges see a segment but with no AI-written headline. Hard to explain on stage.
- Files: `backend/pipeline/compile.py` (to be created), `.planning/research/PITFALLS.md` (Pitfall 5)
- Trigger: Anthropic API latency at demo (hackathon WiFi + first cold call). Sequential subagent execution if parallel syntax is wrong.
- Workaround: Pre-compile the staged demo cluster and cache the result to `backend/seed/segment.json` before the pitch. `OFFLINE_DEMO=true` serves this cache. During "live" demo, the fallback should be the pre-compiled cached segment for the staged dataset, not a generic caption.

---

## Security Considerations

**API keys exposed if frontend build misconfigured:**
- Risk: If `TWELVELABS_API_KEY` or `ANTHROPIC_API_KEY` are added to frontend `.env.local` (as `VITE_*` vars), Vite will bundle them into the static JS. Anyone can extract them from the deployed Vercel app.
- Files: `frontend/.env.local` (to be created), `backend/.env` (to be created), `.planning/research/PITFALLS.md` (Security table)
- Current mitigation: Not yet implemented (pre-code). Architecture decision in `ARCHITECTURE.md` is correct: all Marengo and Anthropic calls are server-side only. Frontend never sees these keys.
- Recommendations: Enforce this at the backend router level — no Twelve Labs or Anthropic SDK import anywhere under `frontend/`. Add a CI check or `grep -r "TWELVELABS\|ANTHROPIC" frontend/src/` pre-commit hook.

**IP address logging could de-anonymize users:**
- Risk: Default FastAPI/Uvicorn access logs include the client IP address on every request. A clip submitted from `POST /clips` would log the submitter's IP alongside the clip_id, allowing correlation.
- Files: `backend/app.py` (to be created), `.planning/research/PITFALLS.md` (Security table)
- Current mitigation: Not yet implemented. Anonymity is a load-bearing differentiator per `PROJECT.md`.
- Recommendations: Add a middleware that strips `X-Forwarded-For` and `client.host` before logging at ingest. Never store IP in the `clips` table. Log only `{clip_id, embedding_status, cluster_id}` — no IP or session_id to the clip record server-side.

**Session UUID in localStorage is not anonymous to the device owner:**
- Risk: The anonymous session UUID (`ING-06`) is stored in localStorage and attached to clips for "this is mine" UX. On a shared device, a second user opening the same browser sees the first user's submitted clips highlighted.
- Files: `frontend/src/views/Feed.tsx` (to be created), `.planning/research/PITFALLS.md` (Pitfall 8)
- Current mitigation: Acceptable for hackathon. Session UUID is never sent to the server as identity — it's only used client-side for local highlighting.
- Recommendations: Document in pitch as known limitation. For production: use sessionStorage (tab-scoped, clears on close) instead of localStorage.

**No upload size limit — DoS vector:**
- Risk: `POST /clips` without a size limit allows arbitrarily large uploads, exhausting Railway volume or triggering Railway memory limits.
- Files: `backend/app.py` (to be created), `.planning/research/PITFALLS.md` (Security table)
- Current mitigation: Not implemented. Planned: 100MB per clip enforced in FastAPI; client-side warning at 60s recording.
- Recommendations: Add FastAPI `File(..., max_size=100 * 1024 * 1024)` constraint in `POST /clips` handler on day 1. Also cap `MediaRecorder` at 30s recording (`CAP-05`) which keeps uploads under ~50MB for 720p H.264.

**Unsigned clip uploads — no spam protection:**
- Risk: Anyone who discovers the `POST /clips` endpoint can flood the ingest with junk clips, exhausting Marengo API credits and Railway disk volume.
- Files: `backend/app.py` (to be created), `.planning/research/PITFALLS.md` (Security table)
- Current mitigation: None. Explicitly deferred per `PROJECT.md`.
- Recommendations: Rate-limit per IP in FastAPI middleware (e.g., `slowapi` library, 10 uploads/min/IP). Mention as Day 2 work in pitch. For demo hardening: Marengo API is credited; Anthropic is credited. Monitor both during live demo.

---

## Performance Bottlenecks

**Pairwise similarity recomputed on every new clip (quadratic scaling):**
- Problem: The planned `assign_or_create` function in `backend/pipeline/cluster.py` computes composite similarity between the new clip and every existing cluster on each ingest. At hackathon scale (< 100 clips), this is `O(N)` and fine. Above ~50 active clusters the loop adds noticeable per-clip latency.
- Files: `backend/pipeline/cluster.py` (to be created), `.planning/research/PITFALLS.md` (Performance Traps)
- Cause: In-memory linear scan over `active_clusters`. Each iteration: cosine sim (512-d matmul), haversine call, weighted sum.
- Improvement path: Acceptable at demo scale. For production, bucket clusters by spatial-temporal grid (geohash + 10-min time bucket) and only compare new clips within the same bucket.

**Marengo polling at constant interval blocks the embed worker:**
- Problem: `task.wait_for_done(sleep_interval=2)` polls every 2 seconds with a synchronous wait. If Marengo latency spikes to 30s, the coroutine is blocked for 30s, delaying cluster assignment for that clip.
- Files: `backend/pipeline/embed.py` (to be created), `.planning/research/PITFALLS.md` (Performance Traps)
- Cause: `wait_for_done` in the `twelvelabs` SDK is a synchronous polling loop. Under asyncio, this blocks the event loop if not wrapped in `asyncio.to_thread`.
- Improvement path: Wrap `task.wait_for_done()` in `await asyncio.to_thread(task.wait_for_done, sleep_interval=2)` to prevent blocking the event loop. For production, use Marengo webhook callbacks instead of polling.

**Feed query joins N segments + clusters on every GET /feed:**
- Problem: `GET /feed?lat&lng` is planned as a SQLite `SELECT segments JOIN clusters` with an in-process haversine computation over all returned segments. At ~50 segments this adds visible latency to the feed load.
- Files: `backend/feed.py` (to be created), `.planning/research/PITFALLS.md` (Performance Traps)
- Cause: No index on `(centroid_lat, centroid_lng)` in the clusters table. Haversine computed in Python, not pushed into SQL.
- Improvement path: Paginate feed (20 segments at a time, `LIMIT 20 OFFSET ?`). Pre-sort by `created_at DESC` in SQL (index on `segments.created_at`). Compute haversine only on the 20 returned rows, not the whole table. At demo scale this is cosmetic; at production scale needs PostGIS.

---

## Fragile Areas

**SSE subscriber list under concurrent connect/disconnect:**
- Files: `backend/events.py` (to be created), `.planning/research/ARCHITECTURE.md` (Pattern 4)
- Why fragile: The planned `_subscribers: list[asyncio.Queue]` is mutated by both the SSE generator (on disconnect, removes from list) and `broadcast()` (iterates the list). A disconnect during a broadcast can cause `list.remove()` to race with `list iteration`, raising `ValueError`.
- Safe modification: Use `_subscribers: set[asyncio.Queue]` (set operations are atomic in CPython). Or copy the list before iterating in `broadcast()`: `for q in list(_subscribers):`. Always use `try/finally` in the generator to guarantee removal on disconnect.
- Test coverage: No tests planned yet for SSE teardown under load.

**Cluster compile trigger has a race condition:**
- Files: `backend/pipeline/cluster.py` (to be created), `backend/db.py` (to be created)
- Why fragile: `should_compile()` checks `c.compile_in_flight` and `c.segment_id` to prevent double-firing. But the check and the `compile_in_flight=True` write are not atomic — two clips arriving within the same asyncio tick could both pass the check before either sets the flag.
- Safe modification: Use `asyncio.Lock` per cluster_id, or perform the check+set as a single SQLite `UPDATE clusters SET compile_in_flight=1 WHERE id=? AND compile_in_flight=0` and check `rowcount == 1` before proceeding.
- Test coverage: Requires concurrent test case (two clips arriving simultaneously targeting the same cluster).

**OFFLINE_DEMO flag must be checked before every external API call:**
- Files: `backend/pipeline/embed.py`, `backend/pipeline/compile.py`, `backend/config.py` (all to be created)
- Why fragile: `DEM-04` requires that `OFFLINE_DEMO=true` bypasses ALL external API calls and serves from cache. If any call site in `embed.py` or `compile.py` checks the flag inconsistently (or a new call is added without checking), the offline demo silently makes a live API call and fails when network is down.
- Safe modification: Centralize the flag check in `backend/config.py` as a module-level constant. Add a function `def assert_online()` that raises if `OFFLINE_DEMO` is set, called at the top of any function that touches an external API. This makes omission a runtime error, not a silent failure.
- Test coverage: Integration test that sets `OFFLINE_DEMO=true` and asserts zero external HTTP requests are made.

**Staged demo clips file path dependencies:**
- Files: `backend/seed/seed.py` (to be created), `backend/seed/demo_clips/` (to be created)
- Why fragile: `seed.py` replays staged clips by posting them to `POST /clips`. This hardcodes the clip filenames and expects them to exist at `backend/seed/demo_clips/`. If anyone renames the files, moves the directory, or runs the seed from the wrong working directory, the demo replay silently fails.
- Safe modification: Use `pathlib.Path(__file__).parent / "demo_clips"` for resolution. Validate all expected files exist at startup and log a clear error if missing. Include file checksums in `seed.py` so staged clip content drift is detectable.

---

## Scaling Limits

**Local filesystem clip storage:**
- Current capacity: Railway persistent volume, typically 1-10GB free tier.
- Limit: At 30s 720p H.264, each clip is ~30-50MB. The Railway volume fills at ~200-300 clips. On a laptop demo, runs out faster.
- Scaling path: Move `clips/` to S3/R2 after hackathon. Serving clips via `FastAPI StaticFiles` stops working for multi-instance deploy. Migration is ~30 lines of code.

**In-memory cluster index:**
- Current capacity: Holds all active clusters in a Python list in the single FastAPI process. Effectively unlimited for demo scale (< 100 clusters).
- Limit: Above ~5,000 active clusters (each holding a 512-d centroid vector + member list), memory usage grows and the linear scan assignment loop adds per-clip latency.
- Scaling path: Add a sliding "active window" (clusters with `last_addition_ts` in the last 24hr). Archive older clusters to SQLite-only. At 50K+ vectors, add FAISS or Qdrant.

**SQLite WAL mode under concurrent writes:**
- Current capacity: Single writer + multiple readers. Sufficient for one asyncio process with background tasks.
- Limit: WAL mode allows one concurrent writer. If two pipeline stages try to write simultaneously (e.g., `embed_worker` and `cluster_worker` both complete at the same moment), one blocks. At hackathon scale this adds <1ms. At production scale (10+ concurrent uploads), this creates a write bottleneck.
- Scaling path: Switch to Postgres + pgvector when moving to multi-instance deploy. `aiosqlite` → `asyncpg` is a low-effort migration.

**Claude Agent SDK subagent context growth:**
- Current capacity: Compile pipeline orchestrator passes full cluster metadata + each prior subagent's JSON output to the next agent. At 4 clips per cluster, this is ~2-4KB total context.
- Limit: If cluster grows to 20+ clips, or if clip metadata includes transcript text, context per compile run can exceed 10KB. Each subagent pays for this in latency and cost.
- Scaling path: Trim context to essentials: pass only `clip_id + GPS + timestamp + cosine_score` to agents, not full metadata. Cap cluster context at `MAX_CONTEXT_CLIPS=6` before compile trigger.

---

## Dependencies at Risk

**`claude-agent-sdk==0.1.68` — SDK version split:**
- Risk: The 0.1.x line supports Sonnet/Haiku but NOT Opus 4.7. If the pitch narrative benefits from Opus ("we used the most powerful model"), the team must upgrade to `>=0.2.111` — but that SDK line has a different API surface for model tokens that is not yet verified against the current code plan.
- Impact: Wrong SDK version = `thinking.type.enabled` API errors at demo time.
- Migration plan: Pin `0.1.68` and use Sonnet. Only upgrade to `>=0.2.111` for Opus if there is verified time before the demo to test the new API surface.

**`twelvelabs==1.2.3` — sync vs async embed path ambiguity:**
- Risk: `.planning/research/STACK.md` and `.planning/research/ARCHITECTURE.md` give conflicting signals: STACK.md describes a synchronous `client.embed.create()` call; ARCHITECTURE.md describes `client.embed.task.create()` + `task.wait_for_done()` async polling. The correct path for `twelvelabs==1.2.3` is unconfirmed until a 30-second REPL check on day 1.
- Impact: Using the wrong API surface produces either a `AttributeError` (if the method doesn't exist) or a 10-30s blocking call in the async path (if sync is used without `asyncio.to_thread`).
- Migration plan: REPL-check `dir(client.embed)` on day 1 before writing a single line of `embed.py`. This is an explicit tracked open todo in `STATE.md`.

**`numpy>=2.x` + potential `faiss-cpu` incompatibility:**
- Risk: If `faiss-cpu` is added later (for scaling beyond ~10K vectors), it requires NumPy <2. Pinning `numpy==2.1.3` now would require a version downgrade to add FAISS.
- Impact: Minor — FAISS is not in scope for hackathon. Risk only materializes at Day-2 scaling work.
- Migration plan: If FAISS becomes needed, pin `numpy<2` in `requirements.txt` and re-test the cosine similarity code (numpy 1.x → 2.x dtype semantics differ slightly).

---

## Missing Critical Features

**No content moderation of any kind:**
- Problem: Any user can upload any video. With no moderation pipeline and anonymous capture enabled, NSFW or harmful content can reach the feed immediately.
- Blocks: Not blocking for the hackathon demo (controlled environment, staged dataset). Would block any public launch.
- Priority: Explicitly deferred per `PROJECT.md`. Must be addressed before any public-facing deployment beyond the hackathon.

**No OFFLINE_DEMO implementation (DEM-04):**
- Problem: As of Phase 0, `OFFLINE_DEMO=true` flag does not exist. It is a Phase 5 deliverable. If Phase 5 is not reached in the 48-hour build window, the demo has no network-failure fallback.
- Blocks: Demo survival under hackathon WiFi failure (Pitfall 6, severity: WOULD-KILL-DEMO).
- Priority: HIGH — should be built partially in Phase 2 (cache Marengo results to disk) and fully in Phase 5. Do not leave it entirely to Phase 5.

**No calibration notebook for clustering thresholds:**
- Problem: `CLU-07` (calibration notebook) is a Phase 3 deliverable and has not been created. Until it exists and the staged clips are run through it, the threshold of 0.55 is an unverified assumption.
- Blocks: Demo accuracy. If threshold is wrong, the clustering demo fails — the entire product thesis fails.
- Priority: CRITICAL — must be done by hour 12 of the hackathon. Cannot be deferred.

**No iOS Safari hardware gate completed (FND-03):**
- Problem: `FND-03` (iOS Safari MediaRecorder verified on real iPhone) is Phase 1 success criterion and has not been completed. All subsequent camera-related code is speculative until this gate passes.
- Blocks: Everything. The demo target is iOS Safari on a real iPhone. Emulators lie about MIME type support.
- Priority: CRITICAL — first thing to verify in Phase 1, before writing any backend logic.

---

## Test Coverage Gaps

**No tests for MIME type fallback ladder:**
- What's not tested: The `MediaRecorder.isTypeSupported()` probe sequence in `Recorder.tsx`. If the ladder is wrong (wrong order, wrong MIME strings), iOS Safari silently fails to record.
- Files: `frontend/src/views/Recorder.tsx` (to be created)
- Risk: The highest-probability single-point demo failure. Silent — produces an empty Blob with no JS error.
- Priority: High — verify manually on a real iPhone in Phase 1 before writing any other frontend code. Add automated test with a Safari WebDriver if time permits.

**No tests for SSE reconnect behavior:**
- What's not tested: `RTM-02` (EventSource auto-reconnects on disconnect). The `events.py` subscriber list teardown on disconnect, the browser EventSource retry, and the feed state on reconnect (does it re-fetch? does it miss events?).
- Files: `backend/events.py` (to be created), `frontend/src/sse.ts` (to be created)
- Risk: SSE disconnect during demo (network blip) leaves the feed in a stale state with no visible indication. Judges submit clips that "disappear."
- Priority: Medium — verify with a manual network disable/restore test during Phase 4. Implement event replay on reconnect (send last N events on new SSE connect) if time permits.

**No adversarial clustering test for false-positive merges:**
- What's not tested: `CLU-08` — two unrelated clips at the same time and same physical place do NOT cluster together. This is the primary adversarial case for GPS+time overweighting.
- Files: `backend/notebooks/calibrate_thresholds.ipynb` (to be created), `backend/pipeline/cluster.py` (to be created)
- Risk: Demo has two unrelated judge submissions at the same venue (same GPS, same time) that false-positive cluster together. The debug overlay shows the merge — judges see the system fail in front of them.
- Priority: High — required as part of the Phase 3 calibration notebook deliverable. No Phase 3 completion without this test passing.

**No integration test for OFFLINE_DEMO mode:**
- What's not tested: That `OFFLINE_DEMO=true` truly makes zero external API calls. A single missed API call site (e.g., a pre-warm call that runs on startup regardless of the flag) causes demo failure when network is disabled.
- Files: `backend/pipeline/embed.py`, `backend/pipeline/compile.py`, `backend/app.py` (all to be created)
- Risk: WiFi dies during demo. `OFFLINE_DEMO=true` is set. A startup pre-warm call to Marengo silently hangs for 30s. FastAPI startup stalls. Demo machine appears dead.
- Priority: High — test by literally disabling WiFi and running `make demo` as part of Phase 5 completion criteria.

---

*Concerns audit: 2026-04-24*

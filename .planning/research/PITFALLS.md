# Pitfalls Research

**Domain:** AI-native hyperlocal news platform (hackathon MVP) — browser camera + multimodal video embeddings + multi-agent compile pipeline
**Researched:** 2026-04-24
**Confidence:** MEDIUM-HIGH (Twelve Labs/Claude Agent SDK docs verified; clustering thresholds and demo-day specifics are LOW-confidence empirical guesses requiring early calibration)

---

## Critical Pitfalls (Would-Kill-Demo)

### Pitfall 1: Marengo embeddings do not return synchronously fast enough for "tap submit and watch the cluster form"

**What goes wrong:**
You wire submit → upload → Marengo embed → cluster → render. On stage, judges see a 30–60 second blank screen between submit and "your clip joined this cluster." Magic dies.

**Why it happens:**
- Marengo 3.0 processes ~10s for a ≤60s video on the **fast** path. That's the model latency, not end-to-end. Add upload, async polling, queueing, and you're easily 20–60s for the first clip.
- Marengo's recommended path is `StartAsyncInvoke` (Bedrock) / async embedding endpoint — synchronous endpoint exists for videos <10 min but is not "interactive UI" fast.
- New rate-limit system (effective Jan 2026) is multi-dimensional per modality. Free/dev tier likely throttles aggressively under demo load.
- Cold-start: first request after idle period stalls.

**How to avoid:**
- **Pre-embed the demo dataset.** All 3–4 staged clips embedded and stored in Postgres/Pinecone before pitch starts. The "submit → cluster" demo is a **playback** of pre-computed state, not live compute, with a **convincing live-feel UI** (progress bar, "embedding...", "computing similarity scores...").
- For the one "live" clip judges might request: pre-warm Marengo with a throwaway request 60s before the demo so cold-start is paid.
- Architecture: backend writes `clip.status = "embedding"` immediately, returns 202, frontend polls every 1s. Even if embedding takes 20s, UX is "we're working" not "frozen."
- Build a **mock Marengo** flag (`USE_MOCK_EMBEDDINGS=true`) that returns pre-computed vectors keyed by filename. Develop against this 90% of the time.

**Warning signs:**
- Roundtrip from upload to embedding ready exceeds 15s in dev — at the demo it'll be 2–3x worse.
- Rate limit headers show <20% remaining in dev.
- First request after a 5-minute idle takes 2x longer than warm requests.

**Phase to address:** Phase 1 (ingest plumbing) — build the async-with-polling pattern from day one, not as a fix at hour 30.

**Severity:** WOULD-KILL-DEMO

---

### Pitfall 2: Clustering thresholds untuned — clips don't group OR everything groups into one mega-cluster

**What goes wrong:**
You ship with arbitrary thresholds (cosine ≥ 0.8, GPS < 100m, Δt < 5min). On stage, your 4 staged clips either fail to cluster (one is on a different angle, similarity 0.79) or every clip in the database collapses into one cluster because thresholds are too loose.

**Why it happens:**
- Marengo similarity scores between "same event different angle" clips are not 0.95 like text — they can be in the 0.5–0.8 range depending on overlap of visual/motion/audio signals.
- 512-dim multimodal embeddings encode visual+motion+audio+speech. Two clips of the same event with different audio (one clip has a passing car) can score lower than expected.
- Three-signal weighted clustering has 4 free parameters (3 weights + 1 final threshold). Untuned, you get nonsense.
- Cold start: first clip in a new cluster has no neighbors to compare against — needs a "singleton cluster" rule or it gets dropped.

**How to avoid:**
- **Calibrate empirically with the real demo dataset by hour 12.** Record the 4 staged clips early (or have a backup set), embed them, compute pairwise scores in a notebook, **plot the distribution**. Set thresholds based on what you actually see, not a priori.
- Use a **scoring formula** rather than 3 independent thresholds:
  ```
  score = 0.5 * marengo_sim + 0.3 * gps_proximity + 0.2 * time_proximity
  cluster_if_score > 0.65  # tune this
  ```
  Single tunable threshold = fewer ways to break.
- Add **adversarial test cases** in the dataset: 2 unrelated clips at the same time same place (e.g., two random Caltech indoor shots within 5min). Verify they DON'T cluster. If they do, your weights overweight GPS+time.
- Singleton handling: a new clip with no neighbors above threshold creates its own cluster. Never drop clips.
- Use cosine similarity (not Euclidean) for Marengo embeddings — they're trained for cosine.
- **Show scores in the debug view** (already in plan) — judges seeing 0.74 / 50m / 2min and an explanation beats a black-box.

**Warning signs:**
- Pairwise similarity matrix on demo dataset shows scores all bunched in 0.6–0.7 range (no separation between same-event and different-event).
- Adversarial test passes only when threshold is so high that real same-event clips also get rejected.
- A clip "joins" a cluster that's geographically distant because Marengo similarity is high (e.g., two protest clips at different campuses).

**Phase to address:** Phase 2 (clustering) — must include a calibration notebook in deliverables, not just code.

**Severity:** WOULD-KILL-DEMO

---

### Pitfall 3: iOS Safari MediaRecorder produces broken/unplayable video files

**What goes wrong:**
You build on Chrome desktop. At demo, judge takes out their iPhone, Safari fails silently — either MediaRecorder isn't fully supported, the resulting blob has a corrupt header, or playback shows a black frame.

**Why it happens:**
- Safari supports MediaRecorder but with codec/MIME quirks. `video/webm` (Chrome default) is not supported on Safari — must use `video/mp4` with H.264+AAC.
- Common bug: MediaRecorder on Safari produces files where duration metadata is missing or 0 — playback works in Safari but fails on backend transcode/upload validators (Marengo will reject).
- Removing the MIME type entirely actually works in some Safari versions (browser picks default) — but defaults vary by iOS version.
- Safari requires `playsinline`, `muted`, `autoplay` on `<video>` for inline preview — without them you get black screen on iOS.
- Safari re-prompts for camera permission per session even if previously granted. Users who tap "Block" once are stuck.
- HTTPS-only — `localhost` works for dev but any LAN IP demo (e.g., `192.168.x.x`) will be silently denied without HTTPS.

**How to avoid:**
- **Test on actual iOS Safari from Phase 1.** Don't trust Chrome-on-Mac-with-DevTools-iOS-emulation — it lies about codec support.
- MIME type detection ladder:
  ```js
  const mimeTypes = ['video/mp4;codecs=avc1.42E01E', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm'];
  const mimeType = mimeTypes.find(t => MediaRecorder.isTypeSupported(t));
  ```
- Fix MediaRecorder duration bug: use `webcodecs` polyfill OR re-mux on backend with ffmpeg before sending to Marengo. Cheaper alternative: record in 5-second fixed chunks and stitch on backend.
- Always set `<video playsinline muted autoplay>` for previews.
- HTTPS for demo: deploy backend behind ngrok/Vercel, not raw IP. Tunnels degrade gracefully, IP setups fail catastrophically.
- Camera permission UX: explicit "Tap to record" button (NOT auto-prompt on page load — Safari will quiet-block).

**Warning signs:**
- Recording works but resulting file shows `duration: NaN` or 0 in metadata.
- Backend ffprobe rejects the upload.
- Black `<video>` element on iOS even though stream is recording.
- Safari shows "no camera access" with no prompt visible (silent block).

**Phase to address:** Phase 0 (camera prototype) — the FIRST thing built must be "open Safari on a real iPhone, record a clip, play it back." Defer everything else until that works.

**Severity:** WOULD-KILL-DEMO

---

### Pitfall 4: GPS indoors at Caltech reads as wrong building (or doesn't read at all)

**What goes wrong:**
Demo is indoors at Caltech. Three judges' clips submitted from the same room read as 3 different GPS coordinates 200m apart, OR `POSITION_UNAVAILABLE` errors. Clustering by GPS proximity falls apart — the demo's whole "same event same place" story collapses.

**Why it happens:**
- GPS hardware fails indoors — satellites blocked. Browser falls back to WiFi triangulation, which at a hackathon venue (everyone on the same APs) returns the AP's geocoded location, not yours. Multi-floor buildings = unpredictable.
- `enableHighAccuracy: true` makes this worse indoors — slower fix, sometimes times out and returns nothing.
- iOS Safari's permission UI is slower than Chrome's — first request can take 10–30s.
- Some users will tap "Don't Allow" out of habit.

**How to avoid:**
- **Don't rely on GPS as a hard filter** — use it as one of three weighted signals. If GPS unavailable, fall back to weight=0 for that signal and lean on Marengo+time.
- For demo: **inject a fixed "demo location" override** controlled by a query param or env flag. `?demo_location=caltech_quad` sets all clips to a fixed coordinate with small random jitter (5–10m). Ship with this **hardcoded for the demo dataset** so GPS doesn't matter for the staged clips.
- For "live" capture: accept whatever GPS returns, even if it's IP-geocoded city-level. Show the user the location, let them confirm.
- Set `timeout: 5000, maximumAge: 30000` on `getCurrentPosition` — don't block submit on slow GPS.
- Permission UX: ask for GPS only after first tap on "Submit," not on page load. Show explicit "Enable location to share where this happened" CTA.
- Test indoors at the actual venue night-before. Don't be surprised on demo morning.

**Warning signs:**
- Same physical location returns different coordinates >50m apart on consecutive requests.
- `getCurrentPosition` times out indoors during dev testing.
- Coordinates plot as the venue's WiFi router location, not the user's actual position.

**Phase to address:** Phase 0 (capture) for browser-side handling; Phase 2 (clustering) for the weighted signal approach; Phase 4 (demo prep) for the fixed-location override.

**Severity:** WOULD-KILL-DEMO (if hard filter); WOULD-SLOW-BUILD (if weighted signal handled correctly)

---

### Pitfall 5: Claude Agent SDK compile pipeline takes 90+ seconds — judges lose interest

**What goes wrong:**
Multi-agent pipeline (Angle Selector → Editor → Caption Writer → Publisher) runs sequentially with full context passed between agents. Each agent does a 10–20s LLM call. By the time the segment renders, judges have moved on.

**Why it happens:**
- Subagents run sequentially when there's no explicit parallelization — the "split-and-merge" pattern requires deliberate orchestrator design.
- Each subagent's context can balloon: orchestrator passes full clip metadata + previous agent output. Token costs compound non-linearly across cycles.
- Agent SDK's default tool use is verbose — every tool call adds tokens to the next message.
- Cold model: first Claude call after idle takes longer (provider-side warmup).

**How to avoid:**
- **Parallelize where independent.** Angle Selector and Caption Writer don't depend on each other — run concurrently. Only Editor and Publisher need sequential ordering. Use the SDK's parallel subagent execution.
- **Token budget per subagent.** Hard caps in the agent harness (e.g., `max_tokens=800` per agent). Define consistent output schemas (JSON, not prose).
- **Pre-compile demo segments.** The 3–4 staged clips' final compiled segment is generated *before* the pitch and cached. The "live" compile demo is a re-run with a visible-but-fake progress bar; result is ready in <3s because it's cached.
- **Stream the orchestrator's status messages** to UI so judges see "Angle Selector: done, Caption Writer: working..." — perceived progress beats actual speed.
- Use Claude Haiku or Sonnet (not Opus) for the sub-agents — 3x faster, sufficient for structured tasks.
- Implement a `MAX_PIPELINE_DURATION_S = 30` hard timeout. If exceeded, render a fallback segment with default angle ordering and a generic caption.

**Warning signs:**
- Local end-to-end pipeline run >45s.
- Subagent context shows >5000 tokens per agent.
- Tokens-used metric grows >20% per cycle in iterative compile loops.
- Watching the demo, you can read a sentence between "submit" and "segment ready."

**Phase to address:** Phase 3 (compile pipeline) — must include parallel subagent design from the start, not as a hour-30 optimization.

**Severity:** WOULD-KILL-DEMO

---

### Pitfall 6: Hackathon venue WiFi dies during demo

**What goes wrong:**
Mid-pitch, WiFi at Caltech drops or saturates. Marengo API call times out. Anthropic API times out. Frontend can't reach backend. Demo is dead in front of judges.

**Why it happens:**
- Caltech Hackathon WiFi is shared across hundreds of people simultaneously deploying, pulling models, and doing live demos. Saturation is normal during peak demo hours.
- Demo machine pulled DHCP at 9am, by noon WiFi is congested, request timeouts cascade.
- Cellular hotspot fallback often forgotten until the moment of failure.

**How to avoid:**
- **Personal hotspot from a teammate's phone.** Tether the demo laptop to a different cell carrier than the Caltech network. Test it works the night before.
- **Offline-capable demo mode.** All staged-clip embeddings, cluster results, and compiled segments are stored locally (SQLite + local file system). A `OFFLINE_DEMO=true` env flag bypasses all API calls and serves cached responses. The demo functions identically with no network.
- **Pre-recorded screencast as ultimate fallback.** 90-second video of the full flow on a working machine, ready to play if everything fails. Embedded in the pitch deck on slide 2.
- Have a **wired ethernet** option if any hackathon-provided demo table has it.
- Test the demo at the venue at 11pm the night before — venue WiFi load patterns will reveal themselves.

**Warning signs:**
- API roundtrip latency at venue >2x what you saw in dev.
- Request timeouts during the morning/afternoon practice runs.
- DNS lookups taking >500ms at venue.

**Phase to address:** Phase 4 (demo prep) — offline mode is a deliberate engineering deliverable, not a fallback you scramble to build.

**Severity:** WOULD-KILL-DEMO

---

## Moderate Pitfalls (Would-Slow-Build)

### Pitfall 7: Marengo file format / duration rejection blocks ingest

**What goes wrong:**
Clips recorded by browser are 3 seconds (under the 4s minimum), or resolution is 240p (under 360x360 minimum), or aspect ratio is non-standard. Marengo returns 4xx, ingest pipeline silently fails.

**Why it happens:**
- Marengo requires: duration 4s–2h, resolution ≥360x360, aspect ratio in {1:1, 4:3, 4:5, 5:4, 16:9, 9:16, 17:9}.
- Browser MediaRecorder defaults vary by device — iPhone 8 vs iPhone 15 produce different resolutions.
- Users tap-and-release quickly producing 1–2s clips.

**How to avoid:**
- Enforce minimum recording duration in UI: button must be held ≥5s OR uses fixed 6-second auto-stop.
- Validate dimensions client-side before upload, reject and re-encode with `MediaRecorder` constraints `{video: {width: {ideal: 720}, height: {ideal: 1280}}}` (force 9:16 portrait).
- Backend validation step before sending to Marengo — return clear error to client, not a silent 500.
- Add ffprobe check on backend, rebail clips to 720p MP4 H.264 if needed.

**Warning signs:** Marengo 4xx errors in logs; clips disappearing from feed without explanation.

**Phase to address:** Phase 1 (ingest)

**Severity:** WOULD-SLOW-BUILD

---

### Pitfall 8: Anonymous capture breaks "this is my clip" session continuity

**What goes wrong:**
User submits a clip, app says "thanks!" but never references *their* clip again. Or — worse — user submits, then opens a new tab, can't find their clip, loses trust the system worked.

**Why it happens:**
- Anonymity is interpreted as "no session at all" — but session ≠ identity. Cookie/localStorage-based session id is anonymous.
- No feedback loop: submit → black hole.

**How to avoid:**
- Generate an **anonymous session id** (UUID in localStorage on first visit). Tag clips with this id server-side but never display/expose.
- After submit: show "Your clip is being analyzed... it joined the [Caltech protest] cluster" — pinpoints user's clip in the feed with a subtle highlight.
- "Your clips" tab (filtered by session id) — anonymous to others, visible to user.
- Never tie session id to PII, never log it externally — anonymity preserved at server level.

**Warning signs:** User feedback "did my submission go through?"; no way to recover from refresh.

**Phase to address:** Phase 1 (ingest UX) and Phase 4 (feed UX)

**Severity:** WOULD-SLOW-BUILD (build-time fix is small; UX impact at demo is large)

---

### Pitfall 9: Embedding queue backs up under judge clicks

**What goes wrong:**
Judges each submit a clip during the demo (3–5 simultaneous uploads). Backend processes them serially, takes 60s before the 5th clip embeds. Queue visibility is zero.

**Why it happens:**
- FastAPI default async worker = 1; embedding requests serialize.
- Marengo's async job is per-request — concurrent calls work but require separate task tracking.
- No queue UI — user has no idea where they are in line.

**How to avoke:**
- Background task queue: FastAPI `BackgroundTasks` for fire-and-forget OR `arq`/`rq` (lightweight, Redis-not-required if using `arq` with in-memory for hackathon scope) — but per project memory, **avoid Redis**. Use FastAPI BackgroundTasks + asyncio.Queue for in-process concurrency.
- Process up to N=5 embeddings in parallel (asyncio.gather) — Marengo's rate limit allows this on dev tier per docs.
- Show queue position in UI: "You're #3 in line. Embedding starts in ~15s."
- Pre-warm Marengo before demo with a throwaway request.

**Warning signs:** Latency increases linearly with concurrent uploads; users see "submitting..." for >30s under load.

**Phase to address:** Phase 1 (ingest)

**Severity:** WOULD-SLOW-BUILD

---

### Pitfall 10: Loading states are "spinner and pray"

**What goes wrong:**
Submit button → infinite spinner → eventually a clip appears in the feed. No feedback during the 20s in between. Users assume it's broken, refresh, submit twice.

**Why it happens:**
- Async pipelines are slow; absence of progress UI = perceived broken.
- Devs build happy path first; loading states get rushed at hour 36.

**How to avoid:**
- Multi-stage progress UI tied to backend status: `uploading → embedding → clustering → compiled`. Server-Sent Events or WebSocket for status push (or polling every 2s if simpler).
- Optimistic UI: clip appears in "your submissions" instantly with a "processing" badge.
- Each stage shows actual signal: "Marengo similarity score computed: 0.78."
- Skeleton loaders for the feed.

**Warning signs:** Demo dry-run, anyone says "is it loading?"; users refresh during processing.

**Phase to address:** Phase 4 (UX polish) — must be in the original plan, not a polish pass.

**Severity:** WOULD-SLOW-BUILD

---

## Minor Pitfalls

### Pitfall 11: Two unrelated events at the same time and place adversarially cluster

**What goes wrong:** Two unrelated clips taken in the same building at the same time get clustered because GPS+time score high. Marengo similarity should reject, but if weights overweight GPS+time, they leak through.

**Prevention:** Adversarial test suite (see Pitfall 2). Use Marengo as the dominant signal (weight 0.5+), GPS+time as tie-breakers (weight 0.3 + 0.2).

**Phase to address:** Phase 2

**Severity:** MINOR (caught by Pitfall 2's calibration if done right)

---

### Pitfall 12: Caption Writer hallucinates — invents a protest that didn't happen

**What goes wrong:** Claude generates "Hundreds gather at Caltech to protest tuition hikes" when clips show 4 people in a hallway. Demo embarrassment.

**Prevention:** Caption Writer prompt explicitly grounded in clip metadata (number of clips, GPS, time, transcribed audio if available). System prompt: "Only describe what is verifiable from the metadata. Do not invent participant counts, motives, or context not present in the input."

**Phase to address:** Phase 3 (compile pipeline)

**Severity:** MINOR for demo (with curated dataset); HIGH for any future production. Mention in pitch as known issue.

---

### Pitfall 13: Browser microphone permission blocks video recording

**What goes wrong:** User taps "Don't Allow" on microphone but the MediaRecorder request includes `audio: true`. Entire stream fails because both mic + camera are requested together.

**Prevention:** Request `{video: true, audio: true}` initially; if `NotAllowedError` for audio, retry with `{video: true, audio: false}`. Marengo can still embed video-only clips (it has multimodal but doesn't require all signals).

**Phase to address:** Phase 0 (capture)

**Severity:** MINOR

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | Acceptable for Hackathon? |
|----------|-------------------|----------------|---------------------------|
| In-memory clip store (no DB persistence beyond hackathon) | No DB setup time | All data lost on restart | YES — but persist embeddings to disk JSON for demo recovery |
| Hardcoded thresholds (no admin UI) | 30 min saved | Re-deploy to tune | YES — but expose via env var so re-tuning is fast |
| No content moderation | Saves a day | Brand/legal risk | YES (in pitch as Day 2) — never in real production |
| Single Marengo API key, no rotation | No key mgmt code | Rate limit = single point of failure | YES with budget alerts; have backup key as fallback |
| Synchronous compile pipeline (no parallel subagents) | Simpler code | 3x slower demo | NO — this kills the demo, parallelize from start |
| No retry logic on Marengo failures | Saves 1 hour | Single 503 = lost clip | NO — wrap every Marengo call in `tenacity` retry (3x, exponential backoff) |
| Pre-baked demo dataset masquerading as "live" | Reliable demo | "Did they actually build it?" credibility risk | YES — but real "live" capture works too as a backup proof |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Twelve Labs Marengo 3.0 | Using sync endpoint for >10min videos; expecting <5s response | Use async endpoint always; poll for completion; pre-embed demo data |
| Twelve Labs Marengo 3.0 | Sending video in unsupported codec/resolution | Validate + transcode client- or server-side before upload |
| Claude Agent SDK | Sequential subagents with full context pass-through | Parallelize independent agents; trim context; use JSON output schemas |
| Claude Agent SDK | Unbounded token budgets | Hard caps per subagent; total pipeline budget enforced |
| Browser Geolocation | `enableHighAccuracy: true` + no timeout indoors | `enableHighAccuracy: false, timeout: 5000`; treat GPS as soft signal |
| Browser MediaRecorder | Hardcoding `video/webm` | Use `MediaRecorder.isTypeSupported` ladder, prefer `video/mp4` for iOS |
| Browser MediaRecorder | `<video>` without playsinline/muted/autoplay on iOS | Always include all three; HTTPS required |
| FastAPI | Blocking I/O in route handlers (e.g., requests.post to Marengo) | Use `httpx.AsyncClient` + `await`; offload long work to BackgroundTasks |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Recompute pairwise similarity on every new clip | Linear → quadratic latency | Store similarities in DB; only compute new clip vs existing | At ~50 clips |
| Linear scan over all clusters for "where does this clip go" | Slow ingest | Index clusters by spatial-temporal bucket; only compare within bucket | At ~100 clusters |
| Loading entire feed on app open | Long initial load | Paginate feed (20 segments at a time); virtual scroll | At ~50 segments |
| Re-embedding video on every retry | Burns rate limit | Cache embeddings by content hash | First retry storm |
| Sequential agent pipeline | 60+ second compile | Parallel subagents (see Pitfall 5) | Always — fix from day one |
| Polling Marengo status every 100ms | Rate-limit ban | Poll every 2s with exponential backoff | First 5 concurrent uploads |

---

## Security & Trust Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing IP address with anonymous clip | Breaks anonymity promise | Never log IP alongside clip id; use middleware that strips IP |
| Embedding session id in shareable clip URLs | De-anonymization via URL | Use opaque clip ids unrelated to session |
| Allowing arbitrary clip downloads (deepfake source material risk) | Abuse vector | For demo, ignore. For production, watermark + DRM |
| Marengo API key in frontend bundle | Key theft | All Marengo calls server-side; key in env var |
| No upload size limit | DoS via giant uploads | Max 100MB per clip enforced in FastAPI; client-side warning at 60s |
| Unsigned clip uploads | Anyone can post anything | For hackathon: rate limit per IP; explicitly deferred moderation noted in pitch |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Camera permission prompt on page load | Silent block on iOS Safari, confused users | Prompt only after explicit "Record" tap |
| GPS permission prompt on page load | Same as above | Prompt only on first submit attempt |
| No clip preview before submit | User submits accidental black-screen clip | Always show 2s preview with "Re-record" + "Submit" buttons |
| Submit blocks on full embedding | User waits 30s on a frozen UI | Optimistic submit → show in "yours" instantly → progress over time |
| No indication clip joined a cluster | "Did my submission do anything?" | Toast: "Your clip joined [event] — see it in the feed" |
| Auto-play video in feed with sound | Mobile data + privacy | Muted autoplay, tap to unmute, lazy-load |
| All-text loading states | "Is it broken?" | Animated similarity-score bars, fake-but-honest "Computing matches..." copy |

---

## "Looks Done But Isn't" Checklist

- [ ] **Camera capture:** Works on Chrome desktop — verified on iOS Safari iPhone (not emulator)?
- [ ] **Camera capture:** Recorded blob has valid duration metadata (test with `ffprobe`)?
- [ ] **GPS:** Indoor test at venue completed — fallback to fixed-location override works?
- [ ] **Embedding:** Pre-embedded demo dataset cached, falls back if Marengo down?
- [ ] **Clustering:** Calibration notebook checked into repo with score distributions?
- [ ] **Clustering:** Adversarial test (2 unrelated clips same time/place) verified to NOT cluster?
- [ ] **Compile pipeline:** Sub-agents run in parallel where independent — measured wall-time <30s?
- [ ] **Compile pipeline:** Hard timeout + fallback compile path exists?
- [ ] **Demo flow:** End-to-end works with WiFi disabled (offline mode)?
- [ ] **Demo flow:** Pre-recorded screencast exists as last-resort fallback?
- [ ] **Anonymity:** No IP, fingerprint, or PII in any logged clip record?
- [ ] **Loading states:** Every async action shows visible progress, not just spinners?
- [ ] **Debug view:** Marengo similarity scores + GPS distance + time delta visible to judges?
- [ ] **Rate limits:** Marengo and Anthropic API current usage <50% of limit during dry run?
- [ ] **Mobile responsiveness:** Feed and recorder usable on a phone in portrait?

---

## Demo-Day Fallback Strategy (Graceful Degradation)

**Tier 0: Everything works** — Live capture, real embeddings, real clustering, real compile pipeline. Best case.

**Tier 1: Marengo rate-limited or down** — Switch to `USE_MOCK_EMBEDDINGS=true`. Demo dataset has pre-computed vectors keyed by clip filename. Cluster + compile still runs live; only embedding is faked. Indistinguishable to judges.

**Tier 2: Anthropic / Claude Agent SDK rate-limited or down** — Pre-baked compiled segments for the demo dataset are loaded from disk. Pipeline UI shows fake but plausible "Angle Selector running... done. Editor running... done." over 5–10s. Final segment renders from cache.

**Tier 3: WiFi unreliable** — Switch demo laptop to phone hotspot (tested night before). All API calls work normally.

**Tier 4: All network gone** — `OFFLINE_DEMO=true`. Backend serves cached responses for the staged dataset entirely from local SQLite + disk. Demo runs identically; nothing crosses network.

**Tier 5: Catastrophic failure (laptop dies, etc.)** — Pre-recorded 90-second screencast embedded in pitch deck. "Here's the system in action" — judges still see the magic, presentation continues.

**Hard rule:** Test Tier 1, 2, and 4 before demo day. Test Tier 3 night-before at the venue. Tier 5 is always ready.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Marengo cold-start at demo | LOW | Pre-warm with throwaway request 60s before demo |
| Marengo rate limit hit | MEDIUM | Switch to MOCK_EMBEDDINGS flag; cached vectors |
| Clustering thresholds wrong | MEDIUM | Hot-swap via env var, no redeploy needed |
| Compile pipeline timeout | LOW | Fallback compile path with default angle order + generic caption |
| Browser permission denied | LOW | Show clear instructions; provide "demo mode" with pre-recorded clip browse |
| GPS unavailable | LOW | Fixed-location override per demo dataset |
| WiFi dies | LOW | Phone hotspot |
| Demo machine bricked | LOW | Backup laptop with full repo cloned, screencast on phone |

---

## Pitfall-to-Phase Mapping

| Pitfall | Severity | Prevention Phase | Verification |
|---------|----------|------------------|--------------|
| 1. Marengo sync latency | KILL-DEMO | Phase 1 | End-to-end submit→embed visible <20s in dry run |
| 2. Clustering thresholds untuned | KILL-DEMO | Phase 2 | Calibration notebook in repo; adversarial test passes |
| 3. iOS Safari MediaRecorder broken | KILL-DEMO | Phase 0 | Real iPhone Safari recording + playback verified |
| 4. GPS indoors broken | KILL-DEMO | Phase 0 + 2 + 4 | Demo-location override functional; indoor test done |
| 5. Compile pipeline too slow | KILL-DEMO | Phase 3 | Wall-clock <30s measured; parallel subagents in code |
| 6. Hackathon WiFi dies | KILL-DEMO | Phase 4 | Offline mode works with network disabled |
| 7. Marengo file format rejection | SLOW-BUILD | Phase 1 | All test clips pass Marengo upload validation |
| 8. Session continuity broken | SLOW-BUILD | Phase 1 + 4 | "Your clips" view shows submitted clips |
| 9. Embedding queue backup | SLOW-BUILD | Phase 1 | 5 concurrent uploads complete in <30s |
| 10. Spinner-and-pray loading | SLOW-BUILD | Phase 4 | Multi-stage progress UI for every async action |
| 11. Adversarial cluster collision | MINOR | Phase 2 | Adversarial test in calibration notebook |
| 12. Caption hallucination | MINOR | Phase 3 | Grounded prompt; manual review of demo segment captions |
| 13. Mic-blocks-video permission | MINOR | Phase 0 | Audio-fallback retry logic in MediaRecorder code |

---

## Sources

- [Twelve Labs Marengo 3.0 release blog](https://www.twelvelabs.io/blog/marengo-3-00) — embedding dimensions (512), latency (~10s for ≤60s video), composite performance benchmarks
- [Twelve Labs Create Embeddings docs](https://docs.twelvelabs.io/docs/guides/create-embeddings/video) — file format, duration limits (4s–2h), resolution requirements (≥360x360), aspect ratios
- [Twelve Labs Release Notes](https://docs.twelvelabs.io/docs/get-started/release-notes) — multi-dimensional rate limits effective Jan 2026, modality-based limits
- [TwelveLabs Marengo on AWS Bedrock](https://www.twelvelabs.io/blog/marengo-pegasus-on-amazon-bedrock) — async StartAsyncInvoke best practice for video
- [Claude Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview) — official SDK documentation
- [Claude Code Sub-Agents: Parallel vs Sequential Patterns](https://claudefa.st/blog/guide/agents/sub-agent-best-practices) — orchestration patterns
- [AI Agent Token Budget Management (MindStudio)](https://www.mindstudio.ai/blog/ai-agent-token-budget-management-claude-code) — token blowup in multi-agent systems, hard caps
- [Building agents with the Claude Agent SDK (Anthropic)](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) — context isolation, parallel patterns
- [WebKit MediaRecorder API blog](https://webkit.org/blog/11353/mediarecorder-api/) — Safari MediaRecorder support details
- [MDN MediaRecorder mimeType](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/mimeType) — codec/MIME type compatibility
- [Remotion: Fixing MediaRecorder video](https://www.remotion.dev/docs/webcodecs/fix-mediarecorder-video) — duration metadata bugs in Safari
- [MDN Geolocation API](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API) — getCurrentPosition options, timeout/accuracy tradeoffs
- [LogRocket: Geolocation API gotchas](https://blog.logrocket.com/what-you-need-know-while-using-geolocation-api/) — indoor accuracy, permission UX, fallback patterns
- [HDBSCAN cluster tool (GitHub)](https://github.com/yigitkonur/hdbscan-cluster-tool) — density-based clustering for embeddings, parameter tuning
- [Hack Upstate: Hackathon demo tips](https://medium.com/upstate-interactive/8-tips-to-a-successful-hackathon-demo-and-presentation-4d1ae83415ad) — running locally, screencast fallbacks
- Project memory: Season beta infrastructure feedback — no Redis preference applied to queue choice (FastAPI BackgroundTasks + asyncio over Redis-based queue)

---
*Pitfalls research for: AI-native hyperlocal news platform (Newz)*
*Researched: 2026-04-24*

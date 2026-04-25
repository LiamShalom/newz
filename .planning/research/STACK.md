# Stack Research

**Domain:** Hyperlocal AI-native news app (anonymous video capture → multimodal clustering → multi-agent compile → local feed)
**Researched:** 2026-04-24
**Confidence:** HIGH on all locked-in core pieces (verified against official docs April 2026); MEDIUM on hosting/storage choices (verified-current but could be substituted without breaking the demo)
**Build window:** 24–48 hours, demo must run live

---

## TL;DR Recommended Stack

| Layer | Choice | Rationale (one line) |
|------|--------|----------------------|
| Frontend | React 18 + Vite + TypeScript | Vite cold-start under 1s; TS catches integration bugs at compile time |
| FE styling | Tailwind CSS 4 | Zero design overhead; ship a credible UI in hours |
| Camera/GPS | Native browser APIs (getUserMedia + MediaRecorder + Geolocation) | No SDKs needed; works on iOS Safari with one mime-type workaround |
| Backend | FastAPI + Uvicorn (Python 3.11) | First-class Twelve Labs + Anthropic SDKs; async out of the box |
| Video AI | `twelvelabs` SDK 1.2.x → Marengo 3.0, sync embed for clips ≤10min | 512-dim multimodal embeddings; sync endpoint avoids polling complexity |
| Multi-agent | `claude-agent-sdk` 0.1.6x (Python), Opus 4.7 + Sonnet subagents | CLI binary bundled — no Node.js needed; AgentDefinition pattern |
| Vector search | NumPy in-memory cosine on normalized vectors | 1000-clip scale; no DB, no extension, no setup |
| Metadata DB | SQLite (file-backed) via SQLAlchemy or raw `sqlite3` | Zero-config, file-portable, sufficient for hackathon scale |
| Video storage | Local filesystem in container, served via FastAPI `StaticFiles` | One container = one truth; no S3 keys to manage in 24hrs |
| FE hosting | Vercel (FE only) | Push-to-deploy from Git in seconds |
| BE hosting | Railway (FastAPI in single container) | Auto-detects Dockerfile / framework; ~1 minute deploy from GitHub |

---

## Recommended Stack — Detailed

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| React | 18.3.x | UI framework | Locked-in. Use 18 not 19 — less library churn for hackathon timeframe. |
| Vite | 5.x | FE bundler / dev server | Sub-second HMR, zero-config TS, builds to static assets Vercel serves directly. |
| TypeScript | 5.5+ | FE type safety | Catches camera/upload contract drift before you waste demo time debugging. |
| Tailwind CSS | 4.x | Styling | Ship pixel-credible UI in hours; no design system decisions. |
| FastAPI | 0.115+ | Python web framework | Native async, auto OpenAPI, Pydantic v2, first-class for Twelve Labs + Anthropic SDKs. |
| Uvicorn | 0.30+ | ASGI server | Standard FastAPI runner; `--reload` in dev. |
| Python | 3.11 | Runtime | 3.11 is sweet spot for Claude Agent SDK (requires 3.10+) and twelvelabs (3.8+). Avoid 3.13 — wheel availability still patchy for some deps as of 2026-04. |
| `twelvelabs` | 1.2.3 (Apr 20 2026) | Twelve Labs Python SDK | Official SDK; the **only** ergonomic way to call Marengo 3.0 from Python. Verified-current on PyPI. |
| `claude-agent-sdk` | 0.1.68 (Apr 25 2026) | Multi-agent runtime | Bundles Claude Code CLI binary inside wheel — no Node.js install needed on backend. Verified against GitHub release. |

### Supporting Libraries (Backend)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `python-multipart` | latest | Form/file upload parsing | **Required** by FastAPI to receive video uploads. Don't forget it — cryptic 400 if missing. |
| `numpy` | 2.x | Vector math | Cosine similarity over Marengo embeddings. Pre-normalize once at insert; then top-k = single matmul. |
| `anthropic` | 0.39+ | Direct Claude API | If you need a quick Claude call **outside** the agent SDK (e.g., one-shot caption). Optional — Agent SDK covers most cases. |
| `pydantic` | 2.x | Data validation | Comes with FastAPI; use models for GPS, cluster, segment payloads. |
| `python-dotenv` | latest | Local env management | Standard. Don't commit `.env`. |
| `httpx` | 0.27+ | Async HTTP client | If you need to call any extra service (e.g., reverse-geocode) inside a request handler. |
| `pillow` | 11.x | Image generation | Only if you want to extract a thumbnail frame for the feed; otherwise skip. |

### Supporting Libraries (Frontend)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| React Router | 6.x | Client routing | Two routes: `/` (feed) + `/record` (camera). Don't add a third unless required. |
| Zustand | 4.x | State management | Lightweight; avoids Redux ceremony. Holds GPS, recording state, feed list. Use only if `useState` becomes painful. |
| `swr` or `@tanstack/react-query` | latest | Data fetching | Optional. For 24hr build, raw `fetch` + `useEffect` is fine. Adopt only if you have time. |
| `date-fns` | 3.x | Time formatting | "2 minutes ago" in the feed. Tree-shakable. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` or `pip` + `requirements.txt` | Python deps | `uv` is faster, but plain pip is fine — don't burn time on tooling. |
| Vite dev server | FE dev | `vite` on `:5173`, FastAPI on `:8000`. Set `VITE_API_BASE` env var. |
| Vercel CLI | FE deploy | `vercel --prod` from `frontend/` after `pnpm build`. |
| Railway CLI | BE deploy | `railway up` from `backend/`. Or just connect GitHub repo and push. |
| ngrok or Cloudflare Tunnel | Live demo failsafe | Backup if Railway misbehaves at demo time — point laptop at a tunnel. |

---

## Marengo 3.0 — Critical Implementation Details

**Confidence: HIGH** (verified against `docs.twelvelabs.io` April 2026, PyPI 1.2.3 release notes, and the official Marengo 3.0 launch blog).

### Key facts

- Embedding dimensions: **512** (down from 1024 in 2.7 — much cheaper to store and compute over)
- Marengo 2.7 was **sunset on 2026-03-30 19:00 PT**. Anything you find online referencing `Marengo-retrieval-2.7` as the model_name is dead. Starting in mid-March 2026 TwelveLabs auto-reindexes existing videos to 3.0; embeddings between 2.7 and 3.0 are **not compatible**.
- Model name string for the SDK: **`"marengo3.0"`** (lowercase, no hyphen). Older docs/examples show `"Marengo-retrieval-2.7"` style — do not use that for 3.0.
- Two embedding scopes: **`clip`** (segment-level, multiple per video) vs **`asset`** (one embedding for the whole file — recommended for 10–30s submissions, which is exactly our case).
- Three modalities to enable per request: **`visual`**, **`audio`** (non-speech sounds), **`transcription`** (transcribed speech). For news clustering, **enable all three**.
- For our use case (clips well under 10 min), there is a **synchronous embed path** that returns vectors immediately without polling. Use it. Async `/embed-v2/tasks` exists for ≥10min content and retains results for 7 days; we don't need that.
- 4-second minimum clip length. Enforce this at the camera UI (record button must be held ≥4s before submit is enabled) — Marengo will reject shorter clips.

### Reference call shape (sync, for short clips)

```python
from twelvelabs import TwelveLabs

client = TwelveLabs(api_key=os.environ["TWELVELABS_API_KEY"])

# Sync embed for short videos (≤10 min)
result = client.embed.create(
    model_name="marengo3.0",
    video_file=open("/path/to/clip.mp4", "rb"),  # or video_url=...
    video_embedding_scope=["asset"],             # one vector per clip
    embedding_option=["visual", "audio", "transcription"],
)

# result.video_embedding.segments[0].embeddings_float -> list[float] of length 512
```

If the SDK surface differs slightly (the API moved between minor versions through 2026), the canonical reference is `client.embed.task.create(...)` for async + `client.embed.task.retrieve(task.id)` after `task.wait_for_done()`. **Verify the exact method name against `pip show twelvelabs` + `dir(client.embed)` on day 1** — do not trust any code snippet (including this one) without a 30-second REPL check.

### Latency expectations

Marengo 3.0 is faster than competitors and faster than 2.7. For a 10–30s clip, expect **a few seconds of embed time** end-to-end on the sync path — well within an HTTP request budget. Plan UI: show "uploading…" then "analyzing…" then "added to feed". Do NOT block the user on the embed call return — fire-and-forget from FE perspective; FE polls the feed or uses optimistic UI.

---

## Claude Agent SDK — Critical Implementation Details

**Confidence: HIGH** (verified against `code.claude.com/docs/en/agent-sdk/*` and the GitHub Python SDK April 2026).

### Key facts

- Package: **`claude-agent-sdk`** (Python). Installed via `pip install claude-agent-sdk`. Requires Python 3.10+.
- Version as of 2026-04-25: **0.1.68**. Version-pin to avoid mid-hack breakage: `claude-agent-sdk==0.1.68`.
- The Python SDK **bundles the Claude Code CLI binary inside the wheel** — you do **not** need to install Node.js or Claude Code separately on the FastAPI server. This is critical for Railway/Fly deploy: the container just needs Python + this package.
- Auth: `ANTHROPIC_API_KEY` env var. (Bedrock/Vertex flags also exist — irrelevant here.)
- Opus 4.7 (`claude-opus-4-7`) requires SDK ≥ 0.2.111 — **but the latest stable 0.1.x line works with Sonnet/Haiku**. If you want Opus 4.7 specifically, pin `claude-agent-sdk>=0.2.111`. **Recommended for hackathon: use Sonnet for subagents (faster, cheaper, plenty smart for caption/edit work) and reserve Opus for the orchestrator if at all.**
- Subagent pattern: define agents via `AgentDefinition` in `ClaudeAgentOptions(agents={...})`. **Must include `"Agent"` in `allowed_tools`** for the orchestrator to be able to delegate. Subagents cannot spawn their own subagents (good — prevents recursion).
- Each subagent gets a fresh context window. Parent passes a string prompt; subagent returns a final string. Pass file paths and decisions explicitly in the prompt.

### Reference shape for the compile pipeline

```python
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

async def compile_segment(cluster):
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash", "Agent"],
        agents={
            "angle-selector": AgentDefinition(
                description="Picks the best 2-3 angles from a cluster of multi-angle clips.",
                prompt="Given clip metadata + Marengo similarity scores, select the angles...",
                tools=["Read"],
                model="sonnet",
            ),
            "editor": AgentDefinition(
                description="Orders selected clips into a coherent segment timeline.",
                prompt="Order clips chronologically, then by angle diversity...",
                tools=["Read"],
                model="sonnet",
            ),
            "caption-writer": AgentDefinition(
                description="Writes a short news-style caption with date and location.",
                prompt="Write a 1-sentence caption: what happened, when, where...",
                tools=["Read"],
                model="sonnet",
            ),
        },
    )
    async for msg in query(prompt=f"Compile a segment from cluster {cluster.id}...", options=options):
        ...
```

### Headless / server pattern

The SDK works fine in a FastAPI handler. You'll typically: enqueue a compile job (BackgroundTasks), inside the job spin up the agent with `query()`, collect the final result, write it to SQLite, then expose `/segment/{cluster_id}` to the FE. Don't run the agent inside the request-response cycle — the wall-clock will exceed Vercel/Railway request timeouts.

---

## Vector Store — Pick Numpy In-Memory

**Confidence: HIGH** for the recommendation; the alternatives are real but unjustified for hackathon scale.

For hackathon scale (a few demo clips + maybe ≤1000 if you stress-test), **don't introduce a vector DB**. The Marengo embeddings are 512-dim — top-k search over 1000 normalized vectors is **<1ms** with a single numpy `@` matmul. Anything more complex burns build time on infrastructure that doesn't appear in the demo.

```python
import numpy as np

# at insert: normalize once
vec = np.asarray(embedding, dtype=np.float32)
vec /= np.linalg.norm(vec) + 1e-12
# store in SQLite as bytes (vec.tobytes()) alongside clip metadata

# at query: load all vectors as a (N, 512) matrix; matmul against query vec
sims = matrix @ query_vec      # cosine similarity, since all are unit-normalized
top_k = np.argsort(-sims)[:k]
```

Persist via SQLite blob column. Reload into memory on FastAPI startup. That's the whole vector store.

### Why not the alternatives

| Option | Why not |
|--------|---------|
| **pgvector** | Postgres setup, extension install, IVF/HNSW index tuning — 30+ min you don't have. Use only if your hosting forces Postgres on you. |
| **sqlite-vss / sqlite-vec** | Native extension load is finicky; `sqlite-vss` is ~unmaintained and `sqlite-vec` is newer but adds setup risk for zero benefit at our scale. |
| **FAISS** | Library install with no persistence layer; you'd reimplement save/load yourself. Fine — but no faster than numpy at <10K vectors and you eat install/build complexity. |
| **Pinecone / Qdrant Cloud** | API key + network round-trip + free-tier limits; adds an external dependency that can fail on demo day. Avoid. |
| **ChromaDB** | More moving parts than numpy; no real benefit at 1000-vector scale. |

Decision rule: **upgrade to FAISS or pgvector only if you cross ~50K vectors or need ANN approximation. Hackathon never reaches that.**

---

## Video Storage — Local Filesystem

**Confidence: MEDIUM–HIGH** — works for demo, would not work at production scale, but that's correct hackathon scope.

- Store uploaded clips on the FastAPI server's local filesystem under e.g. `/data/clips/{clip_id}.mp4`.
- Serve back via FastAPI `StaticFiles` mount at `/clips/`. The feed UI uses `<video src="https://api.your-app.com/clips/{id}.mp4" />`.
- This works on Railway because Railway gives each service a persistent volume (mount it at `/data`). On Fly.io, attach a Fly Volume.
- **Do NOT use S3** unless you have prior experience. S3 setup time (bucket, IAM, presigned URLs, CORS) is at least 30 min, more if you hit a snag. You can always migrate post-hackathon.
- **Do NOT** embed the video as base64 in JSON responses. Set up the static file serve on day 1.
- For demo-day reliability: **keep the pre-recorded staged clips in `frontend/public/demo/`** so the worst-case-no-server demo still has a video to show. (See PROJECT.md — pre-recorded demo dataset is already in scope.)

### Mime type at upload

Browser sends `video/webm` (Chrome/Firefox) or `video/mp4` (Safari). Save the file with the right extension based on the actual mime type, not a hardcoded `.mp4`. Simple lookup table in the upload handler.

---

## Browser Camera Capture — MediaRecorder Quirks

**Confidence: HIGH** (verified across MDN, WebKit blog, and field reports April 2026).

The single most demo-killing iOS issue: **passing a `mimeType` option to `MediaRecorder` that Safari doesn't accept causes the MediaRecorder to silently fail to record**.

### The robust pattern

```ts
async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment" },  // back camera
    audio: true,
  });

  // Pick a mime type Safari can actually use; fall back to default
  const candidates = [
    "video/mp4;codecs=avc1,mp4a",   // Safari prefers this
    "video/webm;codecs=vp9,opus",   // Chrome/Firefox
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ];
  const mimeType = candidates.find(t => MediaRecorder.isTypeSupported(t));

  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
  // If no mimeType is supported, omit the option entirely. Safari has historically
  // been happier with NO mimeType than with a wrong one.

  const chunks: Blob[] = [];
  recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    const blob = new Blob(chunks, { type: recorder.mimeType || "video/mp4" });
    upload(blob);  // POST as multipart/form-data
  };
  recorder.start();
  return recorder;
}
```

### Other gotchas

- **iOS Safari long-clip bug**: clips ≥60s can cause iOS to reload the page. Cap recording to 30s in the UI — also right for the product (short clips → easier clustering).
- **getUserMedia requires HTTPS**. Vercel + Railway both give HTTPS by default. Localhost works without it. Don't try to demo from `http://...`.
- **iOS permission prompt**: only fires on user gesture. The "Record" button must call `getUserMedia` directly inside the click handler — don't wrap in `setTimeout` or async chains before the prompt.
- **Camera orientation**: portrait videos report `videoWidth=720, videoHeight=1280` on iOS. Use CSS `aspect-ratio` not fixed dimensions.

---

## Browser Geolocation — Caveats and Fallback

**Confidence: HIGH**.

- `navigator.geolocation.getCurrentPosition()` is fine for demo. Wrap in a Promise; pass `{ enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 }`.
- **Mobile w/ GPS**: 5–15m accuracy. **Desktop w/ Wi-Fi**: 35–100m. **Indoor**: significantly worse, can be 100m+ off, can take a full minute for a fix.
- For a hackathon ballroom (likely indoor, multi-team Wi-Fi) the indoor accuracy hit can break the GPS-proximity signal. **Demo workaround:** allow the recorder UI to accept a manually-entered "spoofed location" as a query param `?loc=lat,lon` so the team can pin clips to the staged scenario regardless of actual room location. Do **not** make this a user-visible feature; it's a demo escape hatch.
- **Permission denied / timeout fallback**: don't block submission. Submit clip with `gps=null`. Cluster scoring should weight Marengo similarity higher and GPS lower when GPS is missing.
- IP geolocation as fallback: city-level only (50–80% accurate at city), useless for hyperlocal clustering. Skip — better to mark GPS missing and let Marengo carry the cluster.

---

## Hosting — Split FE/BE, Vercel + Railway

**Confidence: MEDIUM-HIGH**. The split itself is solid; the specific platforms are interchangeable with Render or Fly.io.

### Frontend → Vercel

- `vercel --prod` from the `frontend/` directory after `pnpm build`. Connect repo to auto-deploy on push.
- Environment variable: `VITE_API_BASE=https://your-backend.up.railway.app` (or wherever).
- Vercel handles HTTPS, CDN, caching automatically. Zero config.

### Backend → Railway (recommended) or Fly.io

**Railway** wins for hackathon speed:
- Auto-detects Python / Dockerfile, deploys from GitHub in ~1 minute
- Persistent volume for `/data/clips/`
- Free tier sufficient for demo traffic
- One-line redeploys via `railway up`

**Fly.io** is the close runner-up — 35+ regions, sub-minute deploys, but slightly more config (`fly.toml`). Pick Fly only if you're already familiar.

**Render** works fine but requires more configuration than Railway.

### Why NOT deploy FastAPI to Vercel

Vercel runs FastAPI as serverless functions. **Demo-killing problems for this app:**
- Free-tier 10s function timeout — Marengo embed + Claude Agent SDK pipeline will exceed this
- No persistent disk — can't store uploaded clips
- Cold starts on stale endpoints (2–3s on first hit) — judge demo will hit cold
- Background tasks need external orchestration (Inngest etc.) — extra dependency

Use Vercel for the React static build only. Backend goes on Railway/Fly/Render.

### CORS

In `main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["FRONTEND_URL"], "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Set `FRONTEND_URL` in Railway env vars after the first Vercel deploy gives you the URL. Forgetting this is the #1 "why doesn't my demo work" cause for FE/BE-split projects.

---

## Installation

### Backend (`backend/requirements.txt`)

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
twelvelabs==1.2.3
claude-agent-sdk==0.1.68
anthropic==0.39.0
numpy==2.1.3
httpx==0.27.2
```

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
pnpm create vite frontend --template react-ts
cd frontend
pnpm add react-router-dom zustand date-fns
pnpm add -D tailwindcss@4 @tailwindcss/vite
pnpm dev
```

### Environment variables

Backend `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
TWELVELABS_API_KEY=tlk_...
FRONTEND_URL=https://newz-fe.vercel.app
DATA_DIR=/data
```

Frontend `.env.local`:
```
VITE_API_BASE=https://newz-api.up.railway.app
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Vite + React | Next.js 15 | If you wanted SSR-rendered shareable feed pages — but Vercel can deploy Next.js + Python in one project. For a 24hr demo, Vite is faster to set up and we don't need SSR. |
| numpy in-memory | pgvector on Supabase | If you already have Supabase wired and want auth/realtime later. Today, overkill. |
| numpy in-memory | FAISS (`faiss-cpu`) | If you cross ~50K vectors or want IVF. Won't happen in 48hrs. |
| SQLite | Postgres | If you need concurrent writes from multiple workers, or want pgvector to live next to relational data. For 1 worker + 1 demo, SQLite wins. |
| Local FS | S3 + presigned URLs | If you need multi-instance backend or care about clip retention. Day-2 work. |
| Railway | Fly.io | If you want global edge or already know Fly's `fly.toml`. Equivalent for this build. |
| Railway | Modal | Modal is genuinely good for GPU/long jobs but adds a cognitive layer; doesn't fit a 24hr generic FastAPI deploy. |
| Sonnet for subagents | Opus 4.7 for orchestrator | If your "Best Use of AI" pitch needs the latest model on stage. Worth it; pin SDK ≥0.2.111. |
| Browser MediaRecorder | RecordRTC library | If MediaRecorder iOS pain becomes acute. Adds 80kb to the bundle. Don't reach for it unless you've burned an hour on native APIs. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `Marengo-retrieval-2.7` model_name | **Sunset 2026-03-30**. API will return errors. Old code samples online still reference it. | `marengo3.0` |
| Marengo async embed task for short clips | Adds polling complexity, 7-day retention window, and latency for a 10–30s clip that the sync endpoint handles instantly. | Sync embed (the SDK auto-routes for short clips). |
| FastAPI on Vercel for this app | 10s function timeout, no persistent disk, no long-running background tasks. The Marengo embed call alone risks the timeout. | Railway / Fly.io / Render. |
| Pinecone/Qdrant cloud at hackathon scale | Adds API key, network hop, free-tier limits, and a single point of demo failure for ~10 vectors. | numpy in-memory cosine. |
| `MediaRecorder` with hardcoded `mimeType: "video/webm"` | Safari rejects it silently, recorder produces empty output, demo dies on iPhone. | Probe with `MediaRecorder.isTypeSupported()`, fall back to no mimeType. |
| Recording clips ≥60s on iOS | Page reloads mid-recording (documented Safari/iOS issue). | Cap at 30s in UI; matches product anyway. |
| User accounts / auth in v0 | PROJECT.md explicitly says anonymous-by-default. Adding auth eats build time and contradicts the value prop. | No auth. Anonymity is the feature. |
| Redis / Celery / BullMQ | Long-running compile jobs can be FastAPI `BackgroundTasks` writing to SQLite. Brokers add deploy and ops overhead unjustified at 1-worker scale. | `BackgroundTasks` + status column in SQLite. |
| Live camera streaming (WebRTC, HLS) | Out of scope per PROJECT.md and adds days of work. | Record-then-upload only. |
| `claude-agent-sdk` < 0.1.6x | Older versions have different API surface; subagent pattern stabilized in late-2025 / early-2026 releases. | Pin `0.1.68` or latest stable. |
| Running Claude Agent SDK inside the request-response cycle | Wall-clock per pipeline run is multi-second; will exceed common timeouts and block the FE. | `BackgroundTasks` + FE polls a `/segment/{cluster_id}` endpoint. |
| Embedding the API key in the FE bundle | Anyone with the deployed app can extract it; Anthropic + Twelve Labs keys are paid. | Backend-only. FE never sees keys. |

---

## Stack Patterns by Variant

**If you want maximum "Best Use of AI" stage-presence:**
- Pin `claude-agent-sdk>=0.2.111` and use `model="opus"` (Opus 4.7) for the orchestrator agent.
- Use Sonnet for the three subagents (angle-selector, editor, caption-writer) to keep latency reasonable.
- Show subagent invocations live in the debug panel — judges see "Angle Selector → Editor → Caption Writer" cascade.

**If clustering accuracy is faltering on demo data:**
- Crank `embedding_option` to all three modalities (`visual`, `audio`, `transcription`) — single-modality similarity is brittle on multi-angle footage where audio cues are the strongest cross-angle signal.
- Tune the cluster score weights live (sliders in debug panel) — judges love seeing the math.

**If you run out of time before deploy:**
- Skip Vercel. Run the FE on Railway as static files served by FastAPI's `StaticFiles`. One container, one URL. Trade-off: no CDN, but the demo is in one room.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `claude-agent-sdk` 0.1.68 | Python 3.10+ | CLI binary bundled; macOS/Linux/Windows wheels available |
| `claude-agent-sdk` ≥ 0.2.111 | Python 3.10+ | **Required** for Opus 4.7 (`claude-opus-4-7`). Do NOT mix Opus 4.7 with 0.1.x — you'll get `thinking.type.enabled` API errors. |
| `twelvelabs` 1.2.3 | Python 3.8 – 3.12 | Marengo 2.7 sunset 2026-03-30; only `marengo3.0` and pegasus models accepted |
| `fastapi` 0.115 | `pydantic` 2.x, `python-multipart` ≥ 0.0.7 | python-multipart REQUIRED for video uploads — easy to forget |
| `numpy` 2.x | Python 3.10+ | `faiss-cpu` if added later requires NumPy <2 — pin separately if FAISS is introduced |
| Vite 5 | Node ≥ 18 | Vite 6 also fine; 5 is more stable as of April 2026 |

---

## Sources

- [TwelveLabs Marengo 3.0 launch blog](https://www.twelvelabs.io/blog/marengo-3-0) — model capabilities, dimensions, latency claims (HIGH)
- [TwelveLabs Marengo concepts page](https://docs.twelvelabs.io/docs/concepts/models/marengo) — official model reference (HIGH)
- [TwelveLabs release notes](https://docs.twelvelabs.io/docs/get-started/release-notes) — 2.7 sunset date, 3.0 GA, breaking SDK changes April 2026 (HIGH)
- [TwelveLabs Python SDK on PyPI](https://pypi.org/project/twelvelabs/) — version 1.2.3, install command (HIGH)
- [TwelveLabs Python SDK GitHub](https://github.com/twelvelabs-io/twelvelabs-python) — current API surface (HIGH)
- [TwelveLabs Embed API Beta announcement](https://www.twelvelabs.io/blog/introducing-twelve-labs-embed-api-open-beta) — embed task pattern reference (MEDIUM, older but pattern stable)
- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) — package name, install, basic pattern, Opus 4.7 version requirement (HIGH)
- [Claude Agent SDK subagents docs](https://code.claude.com/docs/en/agent-sdk/subagents) — `AgentDefinition` pattern, `Agent` tool requirement, isolation rules (HIGH)
- [claude-agent-sdk-python GitHub](https://github.com/anthropics/claude-agent-sdk-python) — 0.1.68 release, bundled CLI binary, no Node.js dep (HIGH)
- [MDN MediaRecorder.mimeType](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/mimeType) — mime type probing (HIGH)
- [WebKit MediaRecorder blog](https://webkit.org/blog/11353/mediarecorder-api/) — Safari-specific behavior (HIGH)
- [api.video MediaRecorder tutorial](https://api.video/blog/tutorials/building-record-a-video-the-mediarecorder-api/) — cross-browser pattern (MEDIUM, third-party but accurate)
- [iOS MediaRecorder reload bug — Apple Developer Forums](https://developer.apple.com/forums/thread/694867) — 60s+ clip iOS reload (MEDIUM, community-confirmed)
- [MDN Geolocation API](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API/Using_the_Geolocation_API) — accuracy guarantees (HIGH)
- [Vercel Function timeout docs](https://vercel.com/kb/guide/what-can-i-do-about-vercel-serverless-functions-timing-out) — 10s free tier limit (HIGH)
- [Northflank: Vercel backend limitations](https://northflank.com/blog/vercel-backend-limitations) — why FastAPI on Vercel is wrong for this app (MEDIUM)
- [Railway FastAPI guide](https://docs.railway.com/guides/fastapi) — official deploy path (HIGH)
- [Fly.io FastAPI docs](https://fly.io/docs/python/frameworks/fastapi/) — alternative deploy (HIGH)

---
*Stack research for: Newz — AI-native hyperlocal news app, hackathon MVP build*
*Researched: 2026-04-24*
*Verify on day 1: `pip show twelvelabs claude-agent-sdk` to confirm versions, then a 30-second REPL check of `client.embed.*` method names before writing the embed call.*

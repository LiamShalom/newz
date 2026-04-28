# Phase 1: Foundation, Capture & Ingest — Pattern Map

**Mapped:** 2026-04-24
**Greenfield:** YES — repo contains only `.planning/` and `CLAUDE.md`. No in-repo analogs exist.
**Pattern source:** `.planning/research/ARCHITECTURE.md`, `.planning/research/STACK.md`, `.planning/research/SUMMARY.md`. All excerpts below are research-derived canonical patterns, not in-repo analogs. Planner should treat these as the authoritative starting templates for Phase 1.

## File Classification

Files inferred from CONTEXT.md (D-01..D-08), UI-SPEC.md (Component Inventory), REQUIREMENTS.md (FND-01..05, CAP-01..10, ING-01..06), and ARCHITECTURE.md "Recommended Project Structure". Components named per UI-SPEC; backend modules per ARCHITECTURE.

| File (to create) | Role | Data Flow | Closest Reference Pattern | Match Quality |
|------------------|------|-----------|---------------------------|---------------|
| **Backend** | | | | |
| `backend/app.py` | route entry / lifespan | request-response | ARCHITECTURE Pattern 1 (`POST /clips` 202 + `asyncio.create_task`) | research-canonical |
| `backend/config.py` | config | static | STACK §"Environment variables" | research-canonical |
| `backend/db.py` | data access | CRUD | ARCHITECTURE §"Storage" SQLite schema + `aiosqlite` | research-canonical |
| `backend/models.py` | model (Pydantic) | static | ARCHITECTURE Component table (`Clip`, `ScoreBreakdown`) | research-canonical |
| `backend/events.py` | event bus stub | pub-sub | ARCHITECTURE Pattern 4 (SSE) — Phase 1 stub only, full SSE lands Phase 4 | research-canonical |
| `backend/pipeline/__init__.py` | package | n/a | ARCHITECTURE §"Recommended Project Structure" | research-canonical |
| `backend/pipeline/run.py` *(or `pipeline.py`)* | orchestrator stub | event-driven | ARCHITECTURE Pattern 1 `run_pipeline()` — Phase 1 is a no-op stub | research-canonical |
| `backend/requirements.txt` | config | static | STACK §"Backend (`backend/requirements.txt`)" | research-canonical |
| `backend/.env.example` | config | static | STACK §"Environment variables" | research-canonical |
| `backend/Procfile` *or* `backend/railway.toml` | deploy config | static | STACK §"Backend → Railway" | research-canonical |
| **Frontend (Vite scaffold)** | | | | |
| `frontend/index.html` | entry | static | Vite default scaffold | research-canonical |
| `frontend/vite.config.ts` | config | static | STACK §"Frontend" + ARCHITECTURE proxy hint (`proxy /api → :8000`) | research-canonical |
| `frontend/tailwind.config.ts` | config | static | STACK §"Frontend" (Tailwind 4 via `@tailwindcss/vite`) | research-canonical |
| `frontend/package.json` | config | static | STACK §"Frontend" install commands | research-canonical |
| `frontend/tsconfig.json` | config | static | Vite default scaffold | research-canonical |
| `frontend/src/main.tsx` | entry | static | Vite default scaffold + React Router 6 mount | research-canonical |
| `frontend/src/App.tsx` | router | static | ARCHITECTURE §"Project Structure" (two routes: `/` feed, `/record` camera) | research-canonical |
| `frontend/src/index.css` | styles | static | Tailwind 4 directives | research-canonical |
| **Frontend libs** | | | | |
| `frontend/src/api.ts` | utility (fetch wrapper) | request-response | ARCHITECTURE §"Project Structure" (`api.ts` fetch wrappers) | research-canonical |
| `frontend/src/session.ts` | utility | static | ING-06 (anonymous session UUID in localStorage) | research-canonical |
| `frontend/src/uploadQueue.ts` | utility | event-driven (retry) | CAP-09 (localStorage queue + exponential backoff) | research-derived |
| `frontend/src/timeFormat.ts` | utility | static | UI-SPEC "relative timestamps" (`Intl.RelativeTimeFormat`) | research-derived |
| **Frontend views** | | | | |
| `frontend/src/views/Feed.tsx` | view | request-response | ARCHITECTURE §"Component Responsibilities" `Feed.tsx` (Phase 1: poll `/feed`, no SSE yet) | research-canonical |
| `frontend/src/views/Recorder.tsx` | view | streaming (MediaRecorder) | ARCHITECTURE §"Component Responsibilities" `Recorder.tsx` + STACK §"Browser Camera Capture" | research-canonical |
| **Frontend components (per UI-SPEC inventory)** | | | | |
| `frontend/src/components/RecordFAB.tsx` | component | request-response | UI-SPEC component inventory + Tailwind 4 utility classes | research-derived |
| `frontend/src/components/PrimingModal.tsx` | component | event-driven | UI-SPEC + CAP-03 (gating modal, sessionStorage flag) | research-derived |
| `frontend/src/components/CameraView.tsx` | component | streaming | STACK §"Browser Camera Capture" `getUserMedia` constraint pattern | research-canonical |
| `frontend/src/components/CameraFlipButton.tsx` | component | event-driven | UI-SPEC D-06 (`getUserMedia` constraint swap) | research-derived |
| `frontend/src/components/RecordButton.tsx` | component | streaming | UI-SPEC D-03 (ring-fill, 30s cap) + STACK MIME ladder | research-canonical |
| `frontend/src/components/RetakeScreen.tsx` | component | request-response | UI-SPEC D-05 (X dismiss + Submit) | research-derived |
| `frontend/src/components/SubmitButton.tsx` | component | request-response | UI-SPEC inventory; multipart POST submit | research-derived |
| `frontend/src/components/FeedShell.tsx` | component | static | UI-SPEC D-08 (throwaway scrollable list) | research-derived |
| `frontend/src/components/FeedTile.tsx` | component | static | UI-SPEC inventory (`<video controls playsinline>` + relative ts) | research-derived |
| `frontend/src/components/EmptyState.tsx` | component | static | UI-SPEC copywriting contract | research-derived |
| `frontend/src/components/PermissionErrorScreen.tsx` | component | static | UI-SPEC error states (camera-blocked / location-blocked / location-unavailable) | research-derived |
| **Repo root** | | | | |
| `.gitignore` | config | static | Standard (must exclude `clips/`, `newz.db`, `node_modules/`, `.env`, `.venv/`) | research-canonical |
| `README.md` | doc | static | Standard hackathon README (boot commands) | research-derived |

**Total:** ~36 new files (+ Vite-generated boilerplate that ships with `pnpm create vite`).

---

## Pattern Assignments

### `backend/app.py` (route entry, request-response)

**Reference:** `.planning/research/ARCHITECTURE.md` Pattern 1 (lines 134-161) + STACK.md §"CORS" (lines 318-328).

**FastAPI app skeleton + lifespan + CORS:**
```python
# backend/app.py
import os, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, events
from .pipeline.run import run_pipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()              # creates schema, WAL mode
    yield
    # no teardown for Phase 1

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "*"), "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory=os.environ["DATA_DIR"] + "/clips"), name="clips")

@app.get("/health")
async def health():
    return {"ok": True}
```

**Fire-and-forget POST /clips pattern (ING-01..06):**
```python
@app.post("/clips", status_code=202)
async def ingest_clip(
    file: UploadFile,
    lat: float = Form(...),
    lng: float = Form(...),
    ts: float = Form(...),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    clip_id = await db.insert_clip(file, lat, lng, ts, session_id=x_session_id)
    await events.broadcast({"type": "clip_added", "clip_id": clip_id})
    asyncio.create_task(run_pipeline(clip_id))   # fire-and-forget — Phase 1 stub
    return {"clip_id": clip_id, "status": "processing"}

@app.get("/feed")
async def feed():
    # Phase 1: raw clips ordered newest-first, no AI
    rows = await db.fetch_recent_clips(limit=50)
    return {"clips": rows}
```

**Why ING-02 (202 in <100ms):** All slow work (embed/cluster/compile in later phases) goes through `asyncio.create_task`. Phase 1's `run_pipeline` is a no-op stub but **the pattern must be in place from day 1** per CONTEXT.md `<code_context>` ("Establish the fire-and-forget pattern from day 1, not retrofit it later").

---

### `backend/db.py` (data access, CRUD)

**Reference:** `.planning/research/ARCHITECTURE.md` §"Storage" (lines 528-585) + STACK.md aiosqlite mention.

**Phase 1 needs only `clips` table populated** (CONTEXT.md `<code_context>`). Other tables (`clip_embeddings`, `clusters`, `segments`) can be created at init for forward-compat or deferred to phase 2/3 — planner's call.

**Schema (Phase 1 core; full schema for forward-compat):**
```sql
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  ts REAL NOT NULL,
  duration_sec REAL,
  embedding_status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
  cluster_id TEXT,
  session_id TEXT,                                    -- ING-06; never used as identity
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_created_at ON clips(created_at);
```

**Init pattern (WAL mode):**
```python
# backend/db.py
import aiosqlite, os, uuid, time
from pathlib import Path

DB_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "newz.db"

async def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DB_PATH.parent / "clips").mkdir(exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

async def insert_clip(file, lat: float, lng: float, ts: float, session_id: str | None) -> str:
    clip_id = uuid.uuid4().hex
    ext = _ext_from_mime(file.content_type)            # 'mp4' or 'webm'
    path = DB_PATH.parent / "clips" / f"{clip_id}.{ext}"
    with open(path, "wb") as f:
        f.write(await file.read())
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO clips (id, path, lat, lng, ts, session_id, created_at) VALUES (?,?,?,?,?,?,?)",
            (clip_id, str(path), lat, lng, ts, session_id, time.time()),
        )
        await conn.commit()
    return clip_id
```

**MIME → extension mapping (CAP-10):**
```python
_MIME_EXT = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    # browsers send the codec param appended; strip it
}
def _ext_from_mime(mime: str | None) -> str:
    if not mime: return "webm"
    base = mime.split(";")[0].strip()
    return _MIME_EXT.get(base, "webm")
```

---

### `backend/events.py` (event bus stub, pub-sub)

**Reference:** `.planning/research/ARCHITECTURE.md` Pattern 4 (lines 290-313).

**Phase 1 deliverable:** the `broadcast()` API exists and is callable from `app.py`. The actual SSE endpoint and subscriber loop can be a TODO comment in Phase 1 — it lands in Phase 4 (RTM-01..03). Per CONTEXT.md: *"SSE event-bus stub (`events.broadcast(...)`) should exist in Phase 1 even though the only event fired is `clip_added`."*

**Stub pattern:**
```python
# backend/events.py
import asyncio
from typing import Any

_subscribers: list[asyncio.Queue] = []

async def broadcast(event: dict[str, Any]) -> None:
    """Phase 1: no-op (no subscribers connected). Phase 4 wires SSE endpoint."""
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
```

---

### `backend/pipeline/run.py` (orchestrator stub, event-driven)

**Reference:** ARCHITECTURE.md Pattern 1 (lines 150-161). Phase 1 is **stub only**.

**Phase 1 stub:**
```python
# backend/pipeline/run.py
import logging
log = logging.getLogger(__name__)

async def run_pipeline(clip_id: str) -> None:
    """Phase 1 stub. Real pipeline lands in Phase 2 (embed) → Phase 3 (cluster) → Phase 4 (compile)."""
    log.info("pipeline kicked off for clip_id=%s (Phase 1: no-op)", clip_id)
    # TODO Phase 2: await embed.generate(clip_id)
    # TODO Phase 3: await cluster.assign_or_create(...)
    # TODO Phase 4: if cluster.should_compile: await compile.run(...)
```

---

### `backend/requirements.txt`

**Reference:** STACK.md §"Backend" (lines 339-349). **Pin exact versions** — STACK is explicit that 1.2.3 / 0.1.68 are verified-current and re-pinning matters.

**Phase 1 minimum (heavier deps deferred until they're needed):**
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.18
pydantic==2.10.3
python-dotenv==1.0.1
aiosqlite==0.20.0
```

**Defer to Phase 2:** `twelvelabs==1.2.3`, `numpy==2.1.3`.
**Defer to Phase 4:** `claude-agent-sdk==0.1.68`, `anthropic==0.39.0`, `sse-starlette`.

Planner may include all upfront for one `pip install` cycle — defensible either way.

---

### `frontend/src/views/Recorder.tsx` (view, streaming)

**Reference:** STACK.md §"Browser Camera Capture — MediaRecorder Quirks" (lines 230-258) — the load-bearing pattern. CAP-10 MIME ladder is encoded directly here.

**MIME-ladder pattern (CAP-10) — DO NOT DEVIATE:**
```typescript
// MIME ladder per CAP-10 + STACK.md "the single most demo-killing iOS issue"
const MIME_CANDIDATES = [
  "video/mp4;codecs=avc1,mp4a",   // Safari prefers
  "video/webm;codecs=vp9,opus",   // Chrome/Firefox
  "video/webm;codecs=vp8,opus",
  "video/webm",
];
const pickedMime = MIME_CANDIDATES.find(t => MediaRecorder.isTypeSupported(t));
// CRITICAL: if none supported, omit the option entirely. Safari is happier
// with NO mimeType than a wrong one.
const recorder = new MediaRecorder(stream, pickedMime ? { mimeType: pickedMime } : {});
```

**getUserMedia + permission gesture (CAP-04, CAP-03 priming gate):**
```typescript
async function startRecording(facingMode: "environment" | "user" = "environment") {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode },
    audio: true,                                    // D-04: audio ON
  });
  // ... build recorder per MIME ladder above
  // Note: getUserMedia MUST be called inside the click handler, not after a setTimeout.
  // STACK.md: "iOS permission prompt only fires on user gesture."
}
```

**30s hard cap (CAP-05) + ring-fill (D-03):**
```typescript
recorder.start();
const startedAt = performance.now();
const tick = setInterval(() => {
  const elapsed = (performance.now() - startedAt) / 1000;
  setRingProgress(Math.min(elapsed / 30, 1));     // 0..1 → stroke-dashoffset
  if (elapsed >= 30) {
    recorder.stop();
    clearInterval(tick);
  }
}, 100);
```

**Submit (CAP-08, ING-01) + GPS attach (CAP-07 / D-07):**
```typescript
recorder.onstop = async () => {
  const blob = new Blob(chunks, { type: recorder.mimeType || "video/mp4" });
  const pos = await getPositionWithTimeout(5000);  // D-07: blocks if denied/timeout
  if (!pos) { showLocationErrorScreen(); return; }
  const fd = new FormData();
  fd.append("file", blob, `clip.${blob.type.includes("mp4") ? "mp4" : "webm"}`);
  fd.append("lat", String(pos.coords.latitude));
  fd.append("lng", String(pos.coords.longitude));
  fd.append("ts", String(Date.now() / 1000));
  try {
    await fetch(`${API_BASE}/clips`, {
      method: "POST",
      body: fd,
      headers: { "X-Session-Id": getOrCreateSessionId() },  // ING-06
    });
  } catch (err) {
    queueForRetry({ blob, lat: pos.coords.latitude, lng: pos.coords.longitude, ts: Date.now()/1000 });  // CAP-09
  }
};
```

**Load-bearing iOS attributes (UI-SPEC interaction contract item 8):**
- `<video autoplay muted playsinline>` — `playsinline` is mandatory; without it iOS fullscreens.

---

### `frontend/src/views/Feed.tsx` (view, request-response)

**Reference:** ARCHITECTURE.md §"Component Responsibilities" `Feed.tsx` + Checkpoint 1 (line 600: "polls `/feed` every 3 seconds"). Phase 1 explicitly **does NOT** use SSE per CONTEXT.md D-08 (SSE lands Phase 4 / RTM).

**Phase 1 fetch pattern — manual + on-mount, NO polling timer:**

CONTEXT.md D-08: *"Feed refresh: navigate-back-from-camera triggers a refetch + a manual pull-to-refresh. No background polling timer (and no SSE — that's Phase 4 RTM-01..03)."*

```typescript
// frontend/src/views/Feed.tsx
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchFeed } from "../api";
import { flushUploadQueue } from "../uploadQueue";

export function Feed() {
  const [clips, setClips] = useState<Clip[]>([]);
  const location = useLocation();

  const refetch = async () => {
    setClips(await fetchFeed());
  };

  useEffect(() => {
    flushUploadQueue();   // CAP-09: retry failed uploads on each visit
    refetch();
  }, [location.key]);     // re-runs on navigate-back-from-camera

  return clips.length === 0 ? <EmptyState /> : <FeedShell clips={clips} />;
}
```

---

### `frontend/src/api.ts` (utility)

**Reference:** ARCHITECTURE.md §"Project Structure" line 103.

```typescript
// frontend/src/api.ts
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchFeed(): Promise<Clip[]> {
  const res = await fetch(`${API_BASE}/feed`);
  if (!res.ok) throw new Error(`feed ${res.status}`);
  return (await res.json()).clips;
}

export async function postClip(fd: FormData, sessionId: string): Promise<{ clip_id: string }> {
  const res = await fetch(`${API_BASE}/clips`, {
    method: "POST",
    body: fd,
    headers: { "X-Session-Id": sessionId },
  });
  if (!res.ok) throw new Error(`clips ${res.status}`);
  return res.json();
}
```

---

### `frontend/src/session.ts` (utility)

**Reference:** ING-06 + CONTEXT.md `<decisions>` (anonymous session UUID timing).

```typescript
// frontend/src/session.ts
const KEY = "session_id";

export function getOrCreateSessionId(): string {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(KEY, id);
  }
  return id;
}
// ING-06 invariant: server stores this on the clip row but NEVER uses it for identity.
```

---

### `frontend/src/uploadQueue.ts` (utility, event-driven retry)

**Reference:** CAP-09 + CONTEXT.md `<decisions>` (localStorage queue + exponential backoff, retried on next feed visit).

```typescript
// frontend/src/uploadQueue.ts
type QueuedUpload = {
  id: string;
  blobBase64: string;          // Blob is not JSON-serializable; base64 it
  mimeType: string;
  lat: number; lng: number; ts: number;
  attempts: number;
  nextRetryAt: number;
};

const KEY = "upload_queue";

export function enqueue(item: Omit<QueuedUpload, "id" | "attempts" | "nextRetryAt">) { /* ... */ }

export async function flushUploadQueue(): Promise<void> {
  const queue: QueuedUpload[] = JSON.parse(localStorage.getItem(KEY) ?? "[]");
  const now = Date.now();
  for (const item of queue) {
    if (item.nextRetryAt > now) continue;
    try {
      // POST → on success, remove from queue
    } catch {
      item.attempts += 1;
      item.nextRetryAt = now + Math.min(60_000, 2 ** item.attempts * 1000);  // exp backoff, cap 60s
    }
  }
  localStorage.setItem(KEY, JSON.stringify(queue));
}
```

---

### `frontend/src/components/CameraView.tsx` (component, streaming)

**Reference:** STACK.md §"Browser Camera Capture" — mounts the `<video>`, owns the `MediaStream` lifecycle.

**Critical attributes (UI-SPEC interaction contract):**
```tsx
<video
  ref={videoRef}
  autoPlay
  muted
  playsInline                       // load-bearing on iOS
  className="w-full h-[100dvh] object-cover bg-[#0A0A0A]"
/>
```

**Constraint swap for camera-flip (D-06):**
```typescript
async function flipCamera(current: "environment" | "user") {
  // stop current tracks
  videoRef.current?.srcObject instanceof MediaStream &&
    videoRef.current.srcObject.getTracks().forEach(t => t.stop());
  // re-acquire with flipped facingMode
  const next = current === "environment" ? "user" : "environment";
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: next },
    audio: true,
  });
  if (videoRef.current) videoRef.current.srcObject = stream;
}
```

---

### `frontend/src/components/PrimingModal.tsx` (component, event-driven)

**Reference:** UI-SPEC §"Component Inventory" + CAP-03 + D-02 (gating, once per session).

**Once-per-session gate via sessionStorage:**
```tsx
const SHOWN_KEY = "priming_shown";

export function PrimingModal({ onContinue, onClose }: Props) {
  const [open, setOpen] = useState(() => sessionStorage.getItem(SHOWN_KEY) !== "1");
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#1A1A1A] rounded-2xl p-6 max-w-sm border border-[#262626]">
        <h2 className="text-2xl font-semibold text-[#FAFAFA]">Allow camera and location</h2>
        <p className="text-base text-[#FAFAFA] mt-4">
          Newz needs your camera to record and your location to group clips by event.
          Nothing is tied to you — there's no account.
        </p>
        <button
          autoFocus
          onClick={() => { sessionStorage.setItem(SHOWN_KEY, "1"); setOpen(false); onContinue(); }}
          className="mt-6 w-full h-14 rounded-full bg-[#EF4444] text-white font-semibold"
        >
          Allow and continue
        </button>
      </div>
    </div>
  );
}
```

**No backdrop dismiss, no Escape (UI-SPEC interaction contract item 5):** modal is gating per D-02.

---

### `frontend/src/components/RecordButton.tsx` (component, streaming)

**Reference:** UI-SPEC D-03 (ring-fill) + spacing scale (72px inner, 80px outer, 6px stroke).

**SVG ring + CSS stroke-dashoffset transition:**
```tsx
const CIRCUMFERENCE = 2 * Math.PI * 37;  // r=37 for 80px outer with 6px stroke

export function RecordButton({ recording, progress, onTap }: Props) {
  return (
    <button
      onClick={onTap}
      className="absolute bottom-[calc(16px+env(safe-area-inset-bottom))] left-1/2 -translate-x-1/2"
      aria-label={recording ? "Stop recording" : "Start recording"}
    >
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r="37" fill="none" stroke="#262626" strokeWidth="6" />
        {recording && (
          <circle
            cx="40" cy="40" r="37" fill="none"
            stroke="#EF4444" strokeWidth="6" strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={CIRCUMFERENCE * (1 - progress)}
            transform="rotate(-90 40 40)"
            style={{ transition: "stroke-dashoffset 100ms linear" }}
          />
        )}
        {/* inner red dot when idle, square stop glyph when recording */}
        {recording
          ? <rect x="32" y="32" width="16" height="16" rx="2" fill="#EF4444" />
          : <circle cx="40" cy="40" r="28" fill="#EF4444" />}
      </svg>
    </button>
  );
}
```

---

### `frontend/src/components/RetakeScreen.tsx` (component)

**Reference:** UI-SPEC D-05 (X top-left, Submit bottom, autoplay-loop preview).

```tsx
export function RetakeScreen({ blob, onRetake, onSubmit, submitting }: Props) {
  const url = useMemo(() => URL.createObjectURL(blob), [blob]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  return (
    <div className="fixed inset-0 bg-[#0A0A0A]" style={{ height: "100dvh" }}>
      <video src={url} autoPlay loop muted playsInline className="w-full h-full object-contain" />
      <button
        onClick={onRetake}
        aria-label="Retake"
        className="absolute top-[calc(16px+env(safe-area-inset-top))] left-4 w-11 h-11 flex items-center justify-center text-white"
      >
        <X size={24} />
      </button>
      <button
        onClick={onSubmit}
        disabled={submitting}
        className={`absolute bottom-[calc(16px+env(safe-area-inset-bottom))] left-6 right-6 h-14 rounded-full bg-[#EF4444] text-white font-semibold ${submitting ? "opacity-60" : ""}`}
      >
        Post clip
      </button>
    </div>
  );
}
```

---

### `frontend/src/components/PermissionErrorScreen.tsx` (component)

**Reference:** UI-SPEC copywriting contract (3 error states) + D-07 (block on camera AND GPS).

**Three states:** `camera-blocked`, `location-blocked`, `location-unavailable`. Copy is verbatim from UI-SPEC §"Copywriting Contract".

```tsx
const COPY = {
  "camera-blocked": {
    heading: "Camera blocked",
    body: "Open Settings → Safari → Camera and allow access for this site, then return and tap the red button again.",
    action: "Open Settings",
    actionHref: "prefs:root=Safari",  // best-effort iOS deep-link; inert on most setups
  },
  "location-blocked": { /* ... */ },
  "location-unavailable": {
    heading: "Couldn't get your location",
    body: "Step outside or near a window and try again. Indoor GPS is unreliable.",
    action: "Try again",
    actionHref: null,                   // wired to retry callback
  },
};
```

---

### `frontend/vite.config.ts` (config)

**Reference:** ARCHITECTURE.md project structure (line 105: `proxy /api → FastAPI :8000`) + STACK.md Tailwind 4 plugin.

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://localhost:8000" },   // dev only; prod uses VITE_API_BASE
  },
});
```

---

## Shared Patterns (Cross-Cutting)

### S1. Anonymity Invariant (load-bearing per CLAUDE.md)
**Apply to:** all backend routes, all frontend components.
- Backend reads `X-Session-Id` header, stores it on `clips.session_id`, **never logs it as identity, never returns it in responses, never indexes it**.
- Frontend writes `localStorage.session_id` only; never displays it; never sends it to a third party.
- ING-06 invariant: `session_id` is for "this is mine" UX in later phases (Phase 4 FED), not authentication.

### S2. Fire-and-Forget Pipeline Kickoff
**Apply to:** `app.py` POST `/clips` only.
- `asyncio.create_task(run_pipeline(clip_id))` — never `await`, never `BackgroundTasks` (per ARCHITECTURE.md "Why not BackgroundTasks").
- Phase 1 `run_pipeline` is a stub but the `create_task` call **must be in place from day 1**.

### S3. iOS Safari `<video>` Attributes (load-bearing)
**Apply to:** `CameraView.tsx`, `RetakeScreen.tsx`, `FeedTile.tsx`.
- Always: `autoPlay muted playsInline`. Missing `playsInline` causes iOS to fullscreen the player and break the UX (UI-SPEC interaction contract item 8).

### S4. Safe-Area Insets (iOS Safari toolbar)
**Apply to:** `RecordFAB.tsx`, `RecordButton.tsx`, `RetakeScreen.tsx` (X dismiss).
- Bottom: `bottom: calc(16px + env(safe-area-inset-bottom))`.
- Top: `top: calc(16px + env(safe-area-inset-top))`.
- Viewport-locked screens: `100dvh` not `100vh`.

### S5. MIME-Type Fallback Ladder (CAP-10) — DO NOT DEVIATE
**Apply to:** `Recorder.tsx` exclusively. Pattern fully specified in STACK.md §"Browser Camera Capture". Hardcoded `mimeType: "video/webm"` causes silent iOS failure.

### S6. CORS Allowlist
**Apply to:** `app.py` middleware setup.
- `allow_origins=[FRONTEND_URL, "http://localhost:5173"]`. STACK.md §"CORS" notes this is the #1 cause of broken FE/BE-split demos when forgotten after Vercel deploy.

### S7. Dark-First Theme Tokens (UI-SPEC §"Color")
**Apply to:** every Tailwind class authored in Phase 1.
- Background `#0A0A0A`, surface `#1A1A1A`, accent `#EF4444`, fg `#FAFAFA`, fg-muted `#A3A3A3`, border `#262626`.
- Accent (`#EF4444`) reserved for the 5 explicit usages in UI-SPEC; never for body links / focus rings / non-record icons.

### S8. Error-State Copywriting Contract
**Apply to:** `PermissionErrorScreen.tsx`. Copy is verbatim from UI-SPEC and **must not be paraphrased** — voice is "direct, lowercase-friendly, plain English, no exclamation marks, no emoji, never address user as if they have an account."

---

## No Analog Found

**ALL Phase 1 files** have no in-repo analog (greenfield). Planner should:
1. Treat ARCHITECTURE.md and STACK.md as the canonical source for backend patterns (FastAPI, asyncio, SQLite, MIME ladder, CORS).
2. Treat UI-SPEC.md as the canonical source for frontend visual/interaction patterns (component inventory, copy, color, spacing, aria-labels).
3. Not search elsewhere — the research docs were specifically commissioned to provide these patterns.

| File | Why no analog | Pattern source |
|------|---------------|----------------|
| every Phase 1 file | greenfield repo | research docs (ARCHITECTURE / STACK / UI-SPEC) |

---

## Open Conflicts to Carry into Plan

Inherited from CONTEXT.md `<open_conflicts>`. Planner must resolve before/during execution:

1. **CAP-07 vs. D-07** — CAP-07 says "5s timeout, never blocks"; D-07 says "block on GPS denied/unavailable/timeout." Patterns above (in `Recorder.tsx` and `PermissionErrorScreen.tsx`) implement D-07. Planner should either (a) explicitly amend CAP-07 in REQUIREMENTS.md, or (b) flip the pattern to soft-fail.
2. **Pitfall #4 indoor GPS** — risk accepted by Liam; no `?demo_location=` override in Phase 1. Planner should NOT add this code in Phase 1; it lands in Phase 5 (DEM-05).
3. **CLU-06** — structurally moot for Phase 1 (no null-GPS clips accepted). Re-evaluate when Phase 3 is planned.

---

## Metadata

**Pattern source files (read in full):**
- `.planning/phases/01-foundation-capture-ingest/01-CONTEXT.md` (129 lines)
- `.planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md` (209 lines)
- `.planning/PROJECT.md` (96 lines)
- `.planning/REQUIREMENTS.md` (236 lines)
- `.planning/ROADMAP.md` (148 lines)
- `.planning/research/SUMMARY.md` (306 lines)
- `.planning/research/ARCHITECTURE.md` (776 lines)
- `.planning/research/STACK.md` (474 lines)
- `./CLAUDE.md` (already in system context)

**Files scanned in repo:** 0 source files (greenfield — no `src/`, no `package.json`, no `backend/`, no `frontend/`).
**Analog search scope:** repo root only (confirmed greenfield via `ls -la /Users/liamshalom/Hacktech`).
**Pattern extraction date:** 2026-04-24.

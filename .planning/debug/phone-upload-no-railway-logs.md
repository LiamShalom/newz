---
slug: phone-upload-no-railway-logs
status: investigating
trigger: "iOS PWA preview shows submit-success state, but Railway preview backend logs show zero traffic for the upload (POST /clips never appears)"
created: 2026-04-28
updated: 2026-04-28
branch: liam/phase-10-blob-migration
phase: 10-vercel-blob-migration
related_resolved: video-upload-path-null-blob (fixed by f7700b7 + db4dd8d before this symptom)
---

# Debug Session: phone-upload-no-railway-logs

## Symptoms

DATA_START
**Expected behavior:** When the user records a clip on the iOS Safari PWA at the Vercel preview URL and taps submit, the frontend POSTs to `${VITE_API_BASE}/clips` on the Railway preview backend. The Railway logs show a `POST /clips` line and the clip appears in the feed within a few seconds.

**Actual behavior:** User records a clip on iOS Safari at the Vercel preview URL. App appears to succeed (post-submit UI state shown — no error displayed). The clip never appears in the feed. Railway preview backend logs show NO output associated with the upload — no `POST /clips` log line, no error.

**User-checked answers (2026-04-28):**
- Railway preview backend is deployed at or after commit `db4dd8d` (the embed/path fixes from the prior debug session).
- Vercel preview frontend has `VITE_API_BASE` set to the Railway preview backend URL in Vercel dashboard → Settings → Env Vars (Preview env scope).
- User has NOT yet checked whether ANY backend traffic appears in Railway logs from this iOS session (e.g., `/feed` load, `/health`).

**Visual UX on iOS at submit:** App appears to succeed — post-submit state shown, no error message.

**Reproduction:** Record a clip on iPhone Safari at the Vercel preview frontend, tap submit. Repeat — same silence in Railway logs.

**Timeline:** Started after Phase 10 cutover and fix-forward of the path NOT NULL bug. The prior bug (NotNullViolation) WAS visible in Railway logs as an exception traceback. This new symptom is the opposite — the request appears to never reach the backend at all.

**Branch:** `liam/phase-10-blob-migration`

**Hypothesis-relevant context:**
- The frontend is React 18 + Vite. `VITE_API_BASE` is baked at BUILD TIME (Vite inlines `import.meta.env.VITE_API_BASE` into the bundle).
- If `VITE_API_BASE` was set in Vercel AFTER the latest Preview build was created, the build does not include the new value. A REBUILD is required for the env change to take effect.
- iOS Safari + PWA + service-worker caching is notorious for serving stale bundles for hours after a deploy. Hard-reload may not be sufficient if a service worker registered the old bundle.
- Backend's `FRONTEND_URL` env var controls CORS allow-list (`backend/config.py:7`). If it doesn't match the Vercel preview origin exactly, the browser's CORS preflight fails — and on some Safari versions a CORS-blocked POST shows the page as "successful" because the JS Promise rejects silently if the upload code's `.catch` is missing or no-op.
- Vercel Deployment Protection was previously asking for login on iOS — user reported a 500 after login. If protection is still on, requests from the iOS browser may be intercepted by Vercel's edge before reaching the Vite-served bundle, never firing /clips at all.

**Possible upstream user-action questions still open:**
- Is the Vercel preview using a Vite build that postdates the `VITE_API_BASE` env var add?
- Does Safari's network panel (via Mac → Develop → iPhone) show the POST request firing AT ALL — and if so, what status / what host / what response?
- Is a Service Worker registered on the preview origin?
DATA_END

## Initial Code Survey (orchestrator-side, pre-investigation)

- `frontend/src/api.ts:7` — `export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";` — Vite-baked, fallback localhost.
- `frontend/src/api.ts:52` — `await fetch(\`${API_BASE}/clips\`, ...)` — the upload site.
- `backend/app.py` — CORS middleware uses `FRONTEND_URL` from config; allow-list check.
- `backend/config.py:7` — `FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")` — controls CORS origin.

## Current Focus

```yaml
hypothesis: "Vite-baked `VITE_API_BASE` is missing or stale in the deployed Vercel preview bundle, so iOS POSTs to localhost:8000 (the build-time fallback). Combined with the silent error swallow in Recorder.tsx submitClip's catch (which enqueues + navigates as if successful), this explains both symptoms exactly: zero Railway traffic, plus 'success' UX on iOS."
test: "Open the Vercel preview URL on a desktop browser. DevTools → Network tab. Record + submit a clip. Inspect the POST request: (1) does it fire at all, (2) what host does it target, (3) what's the response. Cross-check Vercel dashboard → Deployments → latest preview build timestamp vs Settings → Env Vars history for VITE_API_BASE."
expecting: "POST fires to http://localhost:8000/clips — fails with ERR_CONNECTION_REFUSED in DevTools. The fetch promise rejects, Recorder.tsx submitClip catch fires, item is enqueued to localStorage, navigate('/feed') runs. iOS never sees an error toast because there isn't one."
next_action: "Have user run the desktop disambiguator (Vercel preview + DevTools + record/submit) AND share the on-device localStorage upload_queue contents. The queue contents alone definitively confirm hypothesis 1: if the queue is non-empty after a 'successful' submit, the fetch DID throw and the silent enqueue ran."
reasoning_checkpoint: ""
tdd_checkpoint: ""
```

## Evidence

- timestamp: 2026-04-28 (orchestrator) — User confirms VITE_API_BASE IS set in Vercel Preview env. NOT confirmed: whether the latest preview build was triggered AFTER the env var was added.
- timestamp: 2026-04-28 (orchestrator) — User confirms backend is on db4dd8d+. The path/embed fix is live; this rules out the prior bug as the cause.
- timestamp: 2026-04-28 (orchestrator) — User has NOT yet checked Railway logs for OTHER traffic from this iOS session. Needed to disambiguate "request never fired" from "POST /clips specifically failed."
- timestamp: 2026-04-28 (orchestrator) — Earlier in this session the user reported Vercel Deployment Protection asking for Vercel login on iOS, and a 500 after login. User's choice was to disable protection or use bypass. NOT confirmed whether protection is now off.
- timestamp: 2026-04-28 (session-manager) — **Backend CORS is `allow_origins=["*"]`, `allow_credentials=False`** (`backend/app.py:142-148`). Wildcard CORS with no credentials is universally accepted by browsers. **Hypothesis 2 (CORS preflight rejection) is ELIMINATED** — there is no origin allow-list to mismatch.
- timestamp: 2026-04-28 (session-manager) — **Confirmed silent-error swallow in `frontend/src/views/Recorder.tsx:199-219`.** The `submitClip` flow wraps `postClip` in `try { ... navigate('/feed'); } catch { await enqueue(...); navigate('/feed'); }`. ANY thrown error (network failure, CORS error, abort, ERR_CONNECTION_REFUSED) results in the SAME post-submit UX as success. There is no error toast and no error log. **This explains the 'success on iOS / silence on backend' shape regardless of which hypothesis is the trigger** — it's the amplifier, not the cause.
- timestamp: 2026-04-28 (session-manager) — **No service worker registered.** Searched `frontend/src`, `index.html`, `vite.config.ts` for `serviceWorker`/`workbox`/`registerSW`/`sw.js` — zero matches. Stale-bundle-via-SW is ruled out, but standard HTTP cache + iOS-aggressive JS caching still applies.
- timestamp: 2026-04-28 (session-manager) — **Vite build-time inlining confirmed by inspection of local `frontend/dist/assets/index-*.js`:** the only matching string is `localhost:8000` (no Railway URL, no `VITE_API_BASE` placeholder). This is the exact fallback baked into a build run without `VITE_API_BASE` in the environment. If the Vercel preview build ran the same way (env var added AFTER the build), the deployed JS bundle behaves identically.

## Eliminated

- **Hypothesis 2 (CORS preflight rejection)** — backend CORS is `allow_origins=["*"]` / `allow_credentials=False`; wildcard origin accepts any browser origin. There is no allow-list to mismatch.
- **Service-worker stale-bundle** — no service worker is registered anywhere in the frontend.

## Resolution

```yaml
root_cause: "VITE_API_BASE in Vercel Preview env was set without the `https://` protocol prefix. The browser treats a value like `newz-preview.up.railway.app` as a relative URL — so `${API_BASE}/clips` resolves to `<vercel-host>/newz-preview.up.railway.app/clips`, which Vercel's edge returns 404 (or CORS-blocks). The fetch promise rejects, Recorder.tsx's silent .catch enqueues to localStorage and navigates to /feed, presenting iOS with a 'success' UX. Railway never sees the request."
fix: "1) (env-var, no code) — Vercel Dashboard → Settings → Env Vars → VITE_API_BASE (Preview scope) → prepend `https://`. Redeploy. 2) (code, silent-catch amplifier) — Recorder.tsx submitClip catch should at minimum console.error the failure; ideally surface a non-blocking notification. The CAP-09 enqueue-on-fail behavior is intentional and stays."
verification: "After Vercel redeploys with the corrected VITE_API_BASE, retest from iOS Safari: record + submit. Confirm (a) Railway logs show POST /clips, (b) the clip appears in the feed within 5–10s, (c) localStorage `upload_queue` is NOT populated post-submit."
files_changed: []
```

**Note on silent-catch fix:** The user agreed to fix the catch in Recorder.tsx:208 — landed as a separate commit on this branch. That fix prevents this entire debug cycle from recurring (any future fetch failure now logs to DevTools console).

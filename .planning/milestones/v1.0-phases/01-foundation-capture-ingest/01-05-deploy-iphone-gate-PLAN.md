---
phase: 01-foundation-capture-ingest
plan: 05
type: execute
wave: 4
depends_on: ["01-01", "01-02", "01-03", "01-04"]
files_modified:
  - vercel.json
  - frontend/.env.production.example
  - backend/Dockerfile
  - backend/.dockerignore
  - backend/railway.toml
  - backend/Procfile
  - README.md
  - docs/IPHONE-GATE.md
autonomous: false
requirements:
  - FND-03
  - FND-04
  - FND-05
user_setup:
  - service: vercel
    why: "Frontend hosting (FND-05). Required for HTTPS — iOS Safari rejects camera/GPS over plain HTTP."
    env_vars:
      - name: VITE_API_BASE
        source: "Set in Vercel Project -> Settings -> Environment Variables. Value is the Railway backend URL (e.g. https://newz-api.up.railway.app)."
    dashboard_config:
      - task: "Connect repo to Vercel; Root directory = frontend; Framework preset = Vite; Build = pnpm build; Output = dist"
        location: "https://vercel.com/new"
  - service: railway
    why: "Backend hosting + persistent volume at /data (FND-04). Free tier sufficient for hackathon."
    env_vars:
      - name: FRONTEND_URL
        source: "Set in Railway service -> Variables. Value is the Vercel deploy URL (e.g. https://newz.vercel.app)."
      - name: DATA_DIR
        source: "Set to /data in Railway -> Variables; Railway mounts the persistent volume there."
      - name: OFFLINE_DEMO
        source: "Set to false in prod. Phase 5 (DEM-04) wires the actual offline behavior."
    dashboard_config:
      - task: "Create new project; deploy from GitHub repo; root = backend; attach Volume mounted at /data"
        location: "https://railway.app/new"

must_haves:
  truths:
    - "Frontend deploys to Vercel from /frontend directory with HTTPS (FND-05)"
    - "Backend deploys to Railway from /backend directory with persistent volume mounted at /data (FND-04)"
    - "After deploy, Railway URL serves /health 200 over HTTPS and /media/{file} static mount serves uploaded clips"
    - "After deploy, Vercel URL boots the SPA, the FAB on / navigates to /record, and POST /clips reaches Railway backend"
    - "A real iPhone (not emulator, not Chrome devtools) on Safari can: open the Vercel URL, tap the red FAB, see the priming modal, allow permissions, record a clip, see retake, post it, and watch it play back from the feed (FND-03)"
    - "docs/IPHONE-GATE.md documents the iPhone test protocol and PASS criteria; README links to it"
    - "The iPhone gate is recorded as PASSED (or explicitly FAILED with the failure mode listed) before this plan can complete"
  artifacts:
    - path: "vercel.json"
      provides: "Vercel routing for SPA (rewrites all routes to /index.html)"
      contains: "rewrites"
    - path: "backend/Dockerfile"
      provides: "Python 3.11 base, installs requirements.txt, runs uvicorn with $PORT"
      contains: "python:3.11"
    - path: "backend/railway.toml"
      provides: "Railway service config — pinning health check + port"
      contains: "[deploy]"
    - path: "backend/.dockerignore"
      provides: "Keeps clip data and venvs out of the image"
      contains: ".venv"
    - path: "frontend/.env.production.example"
      provides: "Documented prod env vars for Vercel"
      contains: "VITE_API_BASE"
    - path: "docs/IPHONE-GATE.md"
      provides: "Hardware verification protocol with PASS/FAIL checklist"
      contains: "PASS"
  key_links:
    - from: "Vercel deploy"
      to: "Railway backend"
      via: "VITE_API_BASE env var"
      pattern: "VITE_API_BASE"
    - from: "Railway deploy"
      to: "Vercel origin"
      via: "FRONTEND_URL env var feeding CORS allowlist in backend/app.py"
      pattern: "FRONTEND_URL"
    - from: "Railway service"
      to: "/data volume"
      via: "DATA_DIR env var feeding backend/config.py"
      pattern: "DATA_DIR"
---

<objective>
Ship the Phase 1 build to a public, HTTPS-served URL that a judge can hit from a real iPhone. Two halves: (1) deploy config (Dockerfile + railway.toml + vercel.json + env scaffolding) so `vercel deploy` and `railway up` work; (2) the iOS Safari hardware verification gate — the explicit walk-through on a real iPhone (not emulator) that closes Pitfall #3 (KILL-DEMO).

Purpose: FND-03 is a gate, not a checkbox. Every Phase 1 piece could be perfect in code and still die at the demo because Safari has a quirk we did not test for. This plan forces that test before we move to Phase 2.

Output: Vercel + Railway URLs are live and the iPhone-gate document records a PASS (or explicit FAIL with bug filed). Phase 2 cannot start until this gate clears.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phases/01-foundation-capture-ingest/01-CONTEXT.md
@.planning/phases/01-foundation-capture-ingest/01-UI-SPEC.md
@.planning/research/STACK.md
@.planning/research/PITFALLS.md
@CLAUDE.md
@README.md
@backend/app.py
@backend/config.py
@frontend/package.json
@frontend/vite.config.ts

<interfaces>
<!-- From Plans 01-04: backend boots on uvicorn :PORT, frontend builds to frontend/dist with VITE_API_BASE baked at build time. -->

Backend boot command (Railway / Docker): `uvicorn backend.app:app --host 0.0.0.0 --port $PORT --app-dir .`
Frontend build command (Vercel): `cd frontend && pnpm install && pnpm build` -> output in `frontend/dist`

Required prod env vars:
- Vercel: `VITE_API_BASE` -> Railway origin (e.g. `https://newz-api.up.railway.app`)
- Railway: `FRONTEND_URL` -> Vercel origin (e.g. `https://newz.vercel.app`); `DATA_DIR=/data`; `OFFLINE_DEMO=false`

PITFALLS.md #3 verification list (the gate items):
- Recorded blob has valid duration metadata (else playback breaks).
- iOS shows the camera permission prompt (not silent block).
- Inline `<video>` plays on iOS without going fullscreen.
- HTTPS is required — `localhost` fine in dev, IP demos die.
- After Safari "block once" the user can recover.

Caltech indoor GPS risk: per CONTEXT.md `<open_conflicts>` item 2, accepted by Liam. The iPhone gate notes this as known but does NOT add the `?demo_location=` query param (DEM-05 lands in Phase 5). If indoor GPS at the test site fails repeatedly during the gate, the planner-owner records the failure and falls back to outdoor test for the gate verdict.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Deploy config (Dockerfile, railway.toml, vercel.json, env scaffolding, README updates)</name>
  <files>
    backend/Dockerfile
    backend/.dockerignore
    backend/railway.toml
    backend/Procfile
    vercel.json
    frontend/.env.production.example
    README.md
  </files>
  <read_first>
    .planning/research/STACK.md (lines 282-330 — Hosting / Vercel / Railway / CORS)
    backend/requirements.txt
    backend/config.py
    backend/app.py
    frontend/package.json
    frontend/vite.config.ts
    README.md (current state from Plan 01)
  </read_first>
  <action>
Create deploy config for both halves and update the README with the deploy walkthrough.

**`backend/Dockerfile`** — slim Python 3.11 + pinned deps. Railway auto-detects Dockerfile; this is the canonical path.
```
FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . /app/backend

# Railway provides $PORT at runtime; bind 0.0.0.0 so the container is reachable.
# --app-dir /app so `backend.app:app` resolves; the COPY above places the package
# at /app/backend.
WORKDIR /app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir ."]
```

**`backend/.dockerignore`** — keep the image clean.
```
.venv/
data/
*.db
*.db-wal
*.db-shm
__pycache__/
*.pyc
.env
.git/
.pytest_cache/
```

**`backend/railway.toml`** — pin health check and Dockerfile path. Railway also reads this to know which port to expose.
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

**`backend/Procfile`** — fallback for non-Docker deploys (if Railway misbehaves with the Dockerfile, this is the one-line alternative the user can switch to via Railway dashboard):
```
web: uvicorn backend.app:app --host 0.0.0.0 --port $PORT --app-dir ..
```

**`vercel.json`** at repo root — SPA fallback so React Router routes survive page refresh on `/record`. Tell Vercel the root is `frontend/`.
```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "buildCommand": "cd frontend && pnpm install --frozen-lockfile && pnpm build",
  "outputDirectory": "frontend/dist",
  "installCommand": "echo 'install handled by buildCommand'",
  "framework": null,
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

(The `framework: null` is intentional — Vercel's auto-Vite preset assumes the project root is the Vite root, which is not true for this monorepo. We override.)

**`frontend/.env.production.example`** — committed reference for the user setting up Vercel.
```
# Set in Vercel Project Settings -> Environment Variables.
# Value is the Railway backend URL (no trailing slash).
VITE_API_BASE=https://YOUR-BACKEND.up.railway.app
```

**Update `README.md`** — fill in the "Deploy" section that Plan 01 stubbed.

Append (replacing any "see Plan 05" stub) a Deploy section with:
1. Vercel deploy steps:
   - `vercel link` (or "New Project" -> connect repo)
   - Set project root: repo root (vercel.json declares `cd frontend` in build)
   - Add env var `VITE_API_BASE` after step 2 below provides a URL
   - `vercel --prod`
2. Railway deploy steps:
   - `railway init` -> connect to GitHub
   - Set Service Root Directory = `backend/`
   - Attach a Volume; mount path `/data`
   - Add env vars: `DATA_DIR=/data`, `FRONTEND_URL=<vercel url from step 1>`, `OFFLINE_DEMO=false`
   - Deploy
3. CORS gotcha (STACK.md "the #1 cause of broken FE/BE-split demos"):
   - After both URLs exist, redeploy backend so CORS picks up FRONTEND_URL.
   - Verify with: `curl -I -H "Origin: $FRONTEND_URL" $BACKEND_URL/health` -> response includes `access-control-allow-origin: $FRONTEND_URL`.
4. Link to `docs/IPHONE-GATE.md` for the hardware verification step.

**Why both railway.toml AND Procfile:** belt + suspenders. Railway reads railway.toml first; if the Dockerfile build fails for any reason (it shouldn't), the Procfile gives the user a one-line buildpack escape hatch from the dashboard.

**Why no FastAPI on Vercel:** STACK.md lines 304-312 — Vercel's serverless function timeout is 10s; Marengo embed in Phase 2 will exceed it. Backend MUST be on Railway/Fly/Render. This plan locks Railway.

**Why a Volume at `/data`:** Phase 1 writes clips to `${DATA_DIR}/clips/`. Without a volume, Railway redeploys wipe the disk and clips disappear. The Volume costs $0 on the free tier and is the documented Railway-FastAPI path (STACK.md line 293).
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech &amp;&amp; ls vercel.json backend/Dockerfile backend/railway.toml backend/Procfile backend/.dockerignore frontend/.env.production.example &amp;&amp; grep -q "rewrites" vercel.json &amp;&amp; grep -q "python:3.11" backend/Dockerfile &amp;&amp; grep -q "healthcheckPath" backend/railway.toml &amp;&amp; grep -q "VITE_API_BASE" frontend/.env.production.example &amp;&amp; echo OK</automated>
  </verify>
  <acceptance_criteria>
    - `grep -q "FROM python:3.11" backend/Dockerfile` succeeds
    - `grep -q "uvicorn backend.app:app" backend/Dockerfile` succeeds
    - `grep -q "host 0.0.0.0" backend/Dockerfile` succeeds
    - `grep -q '\${PORT' backend/Dockerfile` succeeds (Railway $PORT honored)
    - `grep -q ".venv" backend/.dockerignore` succeeds
    - `grep -q "data/" backend/.dockerignore` succeeds (clip data not baked into image)
    - `grep -q "healthcheckPath = \"/health\"" backend/railway.toml` succeeds
    - `grep -q "DOCKERFILE" backend/railway.toml` succeeds
    - `grep -q "uvicorn backend.app:app" backend/Procfile` succeeds
    - `grep -q "/index.html" vercel.json` succeeds (SPA fallback)
    - `grep -q "frontend/dist" vercel.json` succeeds (output dir set)
    - `grep -q "cd frontend" vercel.json` succeeds (monorepo build root)
    - `grep -q "VITE_API_BASE" frontend/.env.production.example` succeeds
    - `grep -q "Deploy" README.md` succeeds (deploy section now exists)
    - `grep -q "Railway" README.md && grep -q "Vercel" README.md` succeeds
    - `grep -q "IPHONE-GATE" README.md` succeeds (link to gate doc)
    - `grep -q "/data" README.md` succeeds (volume mount called out)
    - `grep -q "FRONTEND_URL" README.md` succeeds (CORS gotcha called out)
  </acceptance_criteria>
  <done>Deploy config files exist for both Vercel (frontend) and Railway (backend with /data volume). README documents the deploy steps. CORS allowlist gotcha called out. SPA rewrite handles /record refresh.</done>
</task>

<task type="checkpoint:human-action" gate="blocking">
  <name>Task 2: Deploy to Vercel + Railway (human-action: requires user accounts and dashboard config)</name>
  <files>
    docs/IPHONE-GATE.md
  </files>
  <read_first>
    README.md (Deploy section just authored in Task 1)
    backend/Dockerfile
    backend/railway.toml
    vercel.json
    .planning/research/STACK.md (lines 282-330)
    .planning/research/PITFALLS.md (Pitfall #6 — venue WiFi hostility; not blocking for this gate but informs the test)
  </read_first>
  <what-built>
- Plan 04 finished: full FE camera flow + BE ingest + raw feed working locally.
- Task 1 of this plan: deploy config (Dockerfile, railway.toml, vercel.json, env scaffolding, README deploy walkthrough).
  </what-built>
  <how-to-verify>
**This task requires a human (Liam) to perform actions Claude cannot perform via CLI/API:**

1. **Vercel account auth + first deploy** (~5 min):
   - From the repo root, run `pnpm dlx vercel link` (or `vercel link` if installed globally). Pick the team/scope. Project name: `newz`.
   - Run `pnpm dlx vercel --prod`. Wait for the deploy URL. Copy it (e.g. `https://newz-xyz.vercel.app`). DO NOT add the env var yet.

2. **Railway account auth + first deploy** (~5 min):
   - At https://railway.app/new, "Deploy from GitHub repo" -> pick this repo. Service root directory: `backend/`.
   - Add Volume: name `data`, mount path `/data`.
   - Add environment variables:
     - `DATA_DIR=/data`
     - `FRONTEND_URL=<vercel url from step 1>` (paste the URL from step 1)
     - `OFFLINE_DEMO=false`
   - Wait for first deploy to succeed (Dockerfile path; railway.toml health check at /health).
   - Copy the Railway public URL (e.g. `https://newz-api.up.railway.app`).

3. **Set Vercel env var + re-deploy** (~2 min):
   - Vercel dashboard -> Project Settings -> Environment Variables -> add `VITE_API_BASE=<railway url from step 2>` for Production.
   - Trigger a redeploy: `pnpm dlx vercel --prod` (or via dashboard).
   - Wait for the second deploy to finish.

4. **Smoke-test deployed services from a desktop browser**:
   - `curl -fsS https://<railway-url>/health` -> expect `{"ok":true}`. **PASTE the actual command + output below**.
   - Open `https://<vercel-url>/` in Chrome desktop -> see the empty-state feed + FAB.
   - Open DevTools Network tab. Tap the FAB. Observe the route changes to `/record`. Refresh `/record` directly — the SPA rewrite should serve the app, not 404.
   - With Chrome's Sensors -> Geolocation: 34.14, -118.13. Click through the priming modal. Allow camera + GPS. Record a 3-second clip. Tap "Post clip." Verify the POST to `/clips` returns 202. Verify the new clip appears on the feed.

5. **CORS verification**:
   - `curl -I -H "Origin: https://<vercel-url>" https://<railway-url>/health | grep -i access-control`
   - Expect `access-control-allow-origin: https://<vercel-url>` in the response. If absent, the redeploy in step 2c after setting FRONTEND_URL did not fire — kick the backend redeploy.

6. **Now create `docs/IPHONE-GATE.md`** with the iPhone test protocol. Use this template; fill in the URLs after deploy:

```markdown
# iPhone Hardware Gate (FND-03)

**Pitfall closed:** PITFALLS.md #3 (iOS Safari MediaRecorder) — KILL-DEMO severity.

**This document MUST be filled in with PASS or explicit FAIL before Phase 2 starts.**

## URLs

- Frontend: `<vercel-url>`
- Backend: `<railway-url>`

## Pre-flight

- [ ] Real iPhone with iOS 16+ (matches Liam's device). NOT a Chrome-DevTools iOS emulator.
- [ ] iPhone on a different Wi-Fi (or cellular) than the dev laptop — proves prod CORS, not localhost.
- [ ] iPhone Safari (NOT Chrome on iPhone — Chrome on iOS is a Safari WebView; behaves the same as Safari for MediaRecorder, but use Safari directly for the gate).

## Test sequence

| # | Action | Expected | PASS / FAIL | Notes |
|---|--------|----------|-------------|-------|
| 1 | Open `<vercel-url>` in iPhone Safari | Page loads on dark background; "No clips yet" / "Tap the red button to record one." visible; FAB visible at bottom-center, NOT under iOS toolbar | | |
| 2 | Tap FAB | Navigates to `/record`. Priming modal appears with verbatim copy "Allow camera and location" / "Allow and continue" | | |
| 3 | Tap "Allow and continue" | iOS prompts for camera permission. Allow. Then prompts for mic. Allow. Then later (on submit) prompts for location | | |
| 4 | Camera viewport renders | Live rear camera preview, full-bleed, no fullscreen takeover, no black screen | | |
| 5 | Tap camera-flip (top-right RefreshCcw icon) | Front camera shows; tap again, back to rear | | |
| 6 | Tap red record button | Ring fills around the button over time; no numeric counter | | |
| 7 | Tap stop within 5 seconds | Retake screen appears with autoplay-loop preview of the clip | | |
| 8 | Tap X (top-left) | Returns to camera viewport (fresh stream) | | |
| 9 | Record again, tap "Post clip" | iOS prompts for location. Allow. Submit fires. After 1-2s, navigates back to feed. Just-uploaded clip appears at top of feed and plays inline (NOT fullscreen) | | |
| 10 | Hold record for 30+ seconds | Auto-stops at exactly 30s; transitions to retake screen with no error | | |
| 11 | Deny camera (do this after revoking in Settings -> Safari -> Camera, then return) | "Camera blocked" screen with "Open Settings" button visible | | |
| 12 | Deny location | "Location blocked" screen renders (or "Couldn't get your location" if indoor GPS times out) | | |
| 13 | After successful post, refresh feed | Clip persists across refresh (SQLite + /data volume working) | | |

## Caltech indoor GPS test (informational, not blocking)

- [ ] Try the gate from inside a Caltech building. If GPS times out repeatedly -> document "indoor GPS unreliable, accepted risk" and re-run the gate from outdoors.
- This is the risk Liam accepted in CONTEXT.md `<open_conflicts>` item 2. Plan 5 (DEM-05) ships the `?demo_location=` override.

## Verdict

- [ ] **PASS** — every row above marked PASS. Phase 2 unblocked.
- [ ] **FAIL** — one or more rows FAIL. List the failure modes below; create a follow-up plan or revise an existing plan.

### Failure log

(empty if PASS)

### Sign-off

- Tested by: <name>
- Device: iPhone <model>, iOS <version>, Safari <version>
- Date / time: <YYYY-MM-DD HH:MM>
- Verdict: PASS / FAIL
```

7. **Run the iPhone gate sequence.** Record the verdict in `docs/IPHONE-GATE.md`. If anything FAILS:
   - Capture screenshots / video.
   - Note the row that failed and the exact failure mode.
   - Decide: hotfix in this plan (Task 3 below acts as the placeholder) OR file a revision request via `/gsd-plan-phase 1 --reviews`.

8. **Resume signal:** type one of:
   - `gate passed` — all 13 rows PASS, Phase 2 unblocked.
   - `gate failed: <one-line failure summary>` — orchestrator triggers a revision plan.
  </how-to-verify>
  <resume-signal>Type `gate passed` (all 13 rows + sign-off filled in) or `gate failed: <reason>`. Liam: paste the docs/IPHONE-GATE.md verdict + sign-off block here as proof.</resume-signal>
  <acceptance_criteria>
    - `docs/IPHONE-GATE.md` exists at the documented path
    - `grep -q "PASS" docs/IPHONE-GATE.md` succeeds (verdict checkbox + at least one row marked PASS)
    - `grep -q "Tested by:" docs/IPHONE-GATE.md` succeeds (sign-off block filled in)
    - `grep -q "iPhone" docs/IPHONE-GATE.md` succeeds (device recorded)
    - Vercel URL serves the SPA over HTTPS (proven by `curl -fsS -I https://<vercel-url>/ | head -3` showing 200)
    - Railway URL serves /health 200 over HTTPS (proven by `curl -fsS https://<railway-url>/health` returning `{"ok":true}`)
    - CORS allowlist includes the Vercel origin (proven by curl with Origin header in step 5)
    - User has provided a `gate passed` resume signal OR an explicit `gate failed: ...` with the failure cataloged in IPHONE-GATE.md
  </acceptance_criteria>
  <done>Both services live and HTTPS. iPhone gate documented and verdict recorded. If PASS: Phase 2 unblocked. If FAIL: failure modes captured for revision.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| internet -> Vercel CDN | Public, anonymous read of FE bundle. No secrets in bundle (VITE_API_BASE is the only baked env var; it is a URL, not a credential). |
| internet -> Railway BE | Public, anonymous POST/GET. Auth model = none by design (anonymous-by-default product). |
| Vercel CDN -> Railway BE | Cross-origin requests gated by CORS allowlist. |
| iPhone Safari -> Vercel HTTPS | Camera/GPS APIs require HTTPS — Vercel provides it. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-05-01 | I (Information disclosure) | API key in FE bundle | mitigate | No API keys are baked into the FE. `VITE_API_BASE` is a URL only. Phase 2's TWELVELABS_API_KEY and Phase 4's ANTHROPIC_API_KEY live ONLY on Railway env (per STACK.md line 416). Verified by inspection: `frontend/.env.production.example` lists only VITE_API_BASE. |
| T-05-02 | I (Information disclosure) | CORS misconfiguration after deploy | mitigate | `backend/app.py` CORS allow_origins explicitly references `config.FRONTEND_URL`. Acceptance criterion forces a curl smoke test that proves the header is present in deployed traffic. README's Deploy section calls this out as "the #1 cause of broken FE/BE-split demos." |
| T-05-03 | T (Tampering) | Persistent volume corruption | mitigate | Railway Volume backed by their managed storage; Phase 1 has no encryption-at-rest requirement (anonymous public clips). SQLite WAL mode survives crash-during-write. No mitigation beyond the platform's defaults. |
| T-05-04 | D (Denial of service) | Public POST /clips endpoint flooded | accept | Phase 1 deliberately has no rate limiting. Railway free tier provides infra-level abuse protection. PITFALLS.md #9 frames queue backup as a SLOW-BUILD UX issue, not a security threat. Production rate limiting deferred. |
| T-05-05 | E (Elevation of privilege) | iPhone gate bypassed | mitigate | The gate is a checkpoint task with explicit acceptance criteria (sign-off in docs/IPHONE-GATE.md). Plan completion is gated on the verdict. The orchestrator cannot mark this plan complete without the resume signal. |
| T-05-06 | I (Information disclosure) | Vercel/Railway logs contain GPS or session_id | mitigate | Backend log format pinned in Plan 02 (`lat=%.2f` rounded; session_id never logged). Vercel only logs static asset reqs (no user data on FE). |
</threat_model>

<verification>
- `pnpm dlx vercel inspect <vercel-url>` shows production deploy.
- `railway logs` shows uvicorn startup line + `/health` 200 responses.
- `curl -fsS https://<railway-url>/health` returns `{"ok":true}`.
- `curl -I -H "Origin: https://<vercel-url>" https://<railway-url>/health | grep -i access-control-allow-origin` returns the Vercel origin.
- `curl -fsS https://<vercel-url>/record` returns the SPA HTML (SPA rewrite working).
- iPhone gate document recorded as PASS or explicit FAIL.
</verification>

<success_criteria>
- FND-03: real iPhone Safari records, previews, posts a clip, and watches it play back from the feed — every row in IPHONE-GATE.md PASSES.
- FND-04: Railway deploy with `/data` volume mounted; `DATA_DIR=/data` env set; persistent across redeploys.
- FND-05: Vercel deploy on HTTPS with `VITE_API_BASE` env wired to Railway.
- CORS allowlist includes the prod Vercel origin (verified by curl).
- Phase 2 cannot start until this plan completes (autonomous: false; gate task is checkpoint:human-action).
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-capture-ingest/01-05-SUMMARY.md` with:
- Vercel + Railway URLs
- Curl smoke-test outputs (health, CORS, /feed, /media/{id} static fetch)
- The complete `docs/IPHONE-GATE.md` verdict block (PASS/FAIL + sign-off)
- Any deviations or hotfixes applied during the gate
- Phase 1 final status: complete + ready for `/gsd-transition` to Phase 2 (Marengo Embedding)
</output>

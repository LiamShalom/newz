---
phase: 10
plan: 01
type: execute
wave: 1
depends_on: [9]
files_modified:
  - backend/config.py
  - backend/.env.example
  - backend/requirements.txt
  - backend/storage/__init__.py
  - backend/storage/local.py
  - backend/storage/blob.py
  - backend/storage/blob_client.py
  - backend/storage/_url.py
  - backend/db_sqlite.py
  - backend/db_postgres.py
  - backend/app.py
  - backend/pipeline/stitch.py
  - backend/pipeline/compile.py
  - backend/tests/conftest.py
  - backend/tests/test_storage_dispatcher.py
  - backend/tests/test_blob_client.py
  - backend/tests/test_offline_demo_firewall.py
  - backend/scripts/seed_demo_to_blob.py
  - frontend/src/api.ts
  - frontend/src/types.ts
  - frontend/src/components/SegmentCard.test.tsx
  - frontend/src/api.test.ts
autonomous: false
requirements: [BLOB-01, BLOB-02, BLOB-03, BLOB-04, BLOB-05, BLOB-06, BLOB-07, BLOB-08]
user_setup:
  - service: vercel-blob
    why: "Object storage for clip media (uploads/) and compiled run segments (runs/)."
    env_vars:
      - name: BLOB_READ_WRITE_TOKEN
        source: "Vercel Dashboard, Storage, (Blob store), Tokens, Create Read/Write Token"
    dashboard_config:
      - task: "Create a Vercel Blob store (any region; default is fine for v1.1)."
        location: "Vercel Dashboard, Storage, Create, Blob"
      - task: "Confirm plan tier with user (Hobby = 20 simple ops/sec; Pro = 120). v1.1 demo bursts fit Hobby."
        location: "Vercel Dashboard, Storage, (Blob store), Settings"
      - task: "Set BLOB_READ_WRITE_TOKEN and STORAGE_BACKEND=blob on the Railway service."
        location: "Railway, newz-backend, Variables"

must_haves:
  truths:
    - "A new clip uploaded via POST /clips lands in Vercel Blob at uploads/{clip_id}.{ext}, NOT in /data/clips/."
    - "A compiled run segment lands in Vercel Blob at runs/{run_id}.mp4 and the frontend feed plays it."
    - "After Railway redeploy, existing Blob-backed clips and segments still play (no /data dependency)."
    - "ffmpeg _sync_trim ingests source clips directly from Blob URLs (Authorization Bearer header) using -c copy byte-range — no full-file pre-download."
    - "ffmpeg _sync_stitch downloads sources into a tempfile.TemporaryDirectory() before invoking the libx264 normalize-and-concat filter graph; the tempdir is auto-cleaned on context exit."
    - "Direct browser PUT to Vercel Blob is rejected (BLOB_READ_WRITE_TOKEN never reaches the browser)."
    - "Setting STORAGE_BACKEND=local rolls the backend back to v1.0 local-FS without code changes; /media StaticFiles mount re-registers."
    - "OFFLINE_DEMO=true produces zero outbound HTTP traffic to *.vercel-storage.com or vercel.com/api/blob at startup."
    - "cleanup_blocked_clip(clip_id) DELETEs the Blob object via the wrapper and is idempotent (no raise on already-deleted)."
  artifacts:
    - path: "backend/storage/__init__.py"
      provides: "STORAGE_BACKEND dispatcher (D-13). Module-import-time three-arm selection mirroring backend/db.py."
      contains: "from .blob import *"
    - path: "backend/storage/local.py"
      provides: "v1.0 local-FS lift-and-shift. save_clip_bytes / delete_clip / get_playable_url / cleanup_blocked_clip / stitch_input_for / authorized_blob_input."
      exports: ["save_clip_bytes", "delete_clip", "get_playable_url", "cleanup_blocked_clip", "stitch_input_for", "authorized_blob_input"]
    - path: "backend/storage/blob.py"
      provides: "Blob storage interface. Identical signatures to local.py (D-12 parity)."
      exports: ["save_clip_bytes", "delete_clip", "get_playable_url", "cleanup_blocked_clip", "stitch_input_for", "authorized_blob_input"]
    - path: "backend/storage/blob_client.py"
      provides: "Raw httpx async wrapper over the Vercel Blob REST API (D-01, D-25). Module-level singleton init in lifespan."
      exports: ["init_client", "close_client", "get_client", "upload", "delete", "head"]
      min_lines: 150
    - path: "backend/storage/_url.py"
      provides: "URL helpers — pathname_of_blob_url(url), is_absolute_url(s). Pure functions, no HTTP."
    - path: "backend/scripts/seed_demo_to_blob.py"
      provides: "Re-seed demo corpus through POST /clips after /admin/reset (amendment 7)."
    - path: "backend/config.py"
      provides: "STORAGE_BACKEND + BLOB_READ_WRITE_TOKEN env vars (D-23) added under a Phase 10 comment block matching Phase 9 style."
      contains: "STORAGE_BACKEND"
    - path: "backend/migrations/versions/20260428_0001_initial_v1_1_schema.py"
      provides: "READ-ONLY confirmation that clips.blob_url + clips.is_hidden already exist (L-04, L-05). NO new migration."
  key_links:
    - from: "backend/app.py lifespan"
      to: "backend/storage/blob_client.init_client"
      via: "if config.STORAGE_BACKEND == 'blob' and not config.OFFLINE_DEMO"
      pattern: "await blob_client.init_client\\(\\)"
    - from: "backend/db_sqlite.py insert_clip / backend/db_postgres.py insert_clip"
      to: "backend/storage.save_clip_bytes"
      via: "await storage.save_clip_bytes(clip_id, ext, contents) replaces path.write_bytes(contents)"
      pattern: "await storage\\.save_clip_bytes"
    - from: "backend/pipeline/compile.py _resolve_run_ids_to_stitch_refs"
      to: "backend/storage.stitch_input_for"
      via: "(path_or_url, headers) = storage.stitch_input_for(...) — pure URL builder, no network call (amendment 1)"
      pattern: "storage\\.stitch_input_for"
    - from: "backend/pipeline/stitch.py _sync_trim"
      to: "ffmpeg.input(url, headers=...)"
      via: "input_kwargs['headers'] uses CRLF terminator (amendment 4 / Pitfall 2)"
      pattern: "input_kwargs\\[\"headers\"\\]"
    - from: "backend/app.py line 151 region"
      to: "/media StaticFiles mount"
      via: "if config.STORAGE_BACKEND == 'local' or config.OFFLINE_DEMO: app.mount(...)"
      pattern: "STORAGE_BACKEND == \"local\""
    - from: "frontend/src/api.ts lines 27-33"
      to: "Segment.video_url rendering"
      via: "_abs(u) helper guards startsWith('http') before applying API_BASE"
      pattern: "startsWith\\(\"http\"\\)"
---

## Decision Amendments

These supersede CONTEXT.md decisions D-03, D-05, D-06, D-08 and add policy items 5 through 8. The executor MUST follow these amendments where they conflict with the underlying decision text.

1. **D-03 superseded — no `mint_signed_url` op.** Vercel Blob has no signed-URL feature (verified via docs, GitHub issue #544, vercel-py source — RESEARCH section 13 Pitfall 1). `backend/storage/blob_client.py` exposes:
   - `async upload(*, pathname, body, content_type, access)` — unchanged
   - `async delete(*, pathname)` — unchanged
   - `async head(*, pathname)` — unchanged
   - DROP `async mint_signed_url(...)`
   - The "build a stitch input" need is satisfied by a pure helper at the storage interface layer: `def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str]]` returns `(canonical_private_url, {"Authorization": "Bearer <token>"})`. Pure function. No network.

2. **D-05 partially superseded — split-access intent stands; mechanism changes.** `uploads/` PUT uses `access: "private"`. `runs/` PUT uses `access: "public"`. Reads of private blobs pass `Authorization: Bearer` header (no time-limited URL). Reads of public blobs use the URL directly with no auth.

3. **D-06 superseded — no 900s TTL.** "Mint fresh per call site" becomes "build (url, headers) tuple per call site." Cost is zero (no network round-trip). Leak-decay relies entirely on BLOB-08 cleanup (D-07's spirit holds).

4. **D-08 superseded — ffmpeg `-headers` flag, CRLF terminator mandatory.** `_sync_trim` uses `ffmpeg.input(url, headers="Authorization: Bearer <token>\r\n")`. ffmpeg-python forwards `headers=` verbatim to ffmpeg's `-headers` flag. CRLF (`\r\n`) line termination is required per ffmpeg HTTP protocol docs (RESEARCH section 13 Pitfall 2). Range requests confirmed working on Vercel Blob URLs.

5. **Recompile CDN cache lag accepted (RESEARCH section 13 Pitfall 7).** User chose to accept ~60s stale-serve lag for `runs/{run_id}.mp4` recompiles. Keep deterministic pathname. NO `addRandomSuffix=true`. NO counter-in-pathname. Upload uses `x-allow-overwrite: 1`.

6. **Vercel Blob plan tier: Hobby (20 ops/sec).** v1.1 traffic shape fits headroom. `blob_client.py` adds tenacity exponential backoff on 429 with max 3 attempts, alongside the existing D-24 5xx retry. Defense-in-depth.

7. **Ship `backend/scripts/seed_demo_to_blob.py` in this phase.** ~30 LOC. POSTs each `backend/seed/demo/*.mp4` through `/clips`. Documented usage: "Run after `POST /admin/reset` to refresh the demo corpus."

8. **Pin `httpx==0.28.1` and `tenacity==9.1.4` explicitly in `requirements.txt`** (currently transitive via `twelvelabs==1.2.3` — RESEARCH section 13 Pitfall 4). Defends against twelvelabs version-bumps dropping `httpx` as a dep.

---

<objective>
Retire Railway local-FS clip storage. Server-mediated upload to Vercel Blob (uploads/ private, runs/ public). ffmpeg trims private blobs via Authorization-bearer header (no signed URLs); ffmpeg stitches via tempdir-download. The /media StaticFiles mount registers only when STORAGE_BACKEND=local or OFFLINE_DEMO=true. STORAGE_BACKEND flag mirrors Phase 9's METADATA_BACKEND pattern for migration-window rollback. cleanup_blocked_clip(clip_id) hook ships in Phase 10 for Phase 11 to call.

Purpose: Decouple clip media from Railway redeploy; serve compiled segments from Vercel CDN; keep OFFLINE_DEMO firewalled.

Output: Six new files (backend/storage/__init__.py, local.py, blob.py, blob_client.py, _url.py, scripts/seed_demo_to_blob.py), refactors to db_sqlite.py / db_postgres.py / app.py / pipeline/stitch.py / pipeline/compile.py, three new tests, and a one-line frontend guard.
</objective>

<execution_context>
@/Users/liamshalom/Desktop/newz/.claude/get-shit-done/workflows/execute-plan.md
@/Users/liamshalom/Desktop/newz/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/10-vercel-blob-migration/10-CONTEXT.md
@.planning/phases/10-vercel-blob-migration/10-RESEARCH.md
@.planning/phases/10-vercel-blob-migration/10-PATTERNS.md
@.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md
@./CLAUDE.md

# Code touch points (read each ONCE before editing — extract patterns, then stop)
@backend/app.py
@backend/db.py
@backend/db_sqlite.py
@backend/db_postgres.py
@backend/config.py
@backend/.env.example
@backend/requirements.txt
@backend/pipeline/stitch.py
@backend/pipeline/compile.py
@backend/tests/conftest.py
@backend/migrations/versions/20260428_0001_initial_v1_1_schema.py
@frontend/src/api.ts
@frontend/src/types.ts
@frontend/src/components/SegmentCard.test.tsx

<interfaces>
# Phase 10 storage interface — both local.py and blob.py implement THIS surface byte-for-byte (D-12 parity).
# backend/storage/__init__.py re-exports the active backend's surface.

async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    """Persist clip bytes. Returns the value to store in the DB row.
       local: returns str(absolute_filesystem_path) -> goes into clips.path.
       blob:  returns absolute Blob URL (https://...vercel-storage.com/uploads/{clip_id}.{ext}) -> goes into clips.blob_url.
    """

async def delete_clip(path_or_url: str) -> None:
    """Best-effort delete. Idempotent (no raise on missing).
       local: tries Path(path_or_url).unlink().
       blob:  parses pathname from URL, calls blob_client.delete(pathname=...). 404 silenced.
    """

def get_playable_url(row: dict) -> str | None:
    """Frontend-renderable URL for a clip row.
       Prefer row['blob_url'] when populated (absolute https URL).
       Fall back to f'/media/{Path(row["path"]).name}' for legacy / local-mode rows.
       Return None if neither is populated.
    """

async def cleanup_blocked_clip(clip_id: str) -> None:
    """BLOB-08 hook (D-20). Phase 11 calls this after writing moderation_status='blocked'.
       Looks up the row, calls delete_clip on whichever of (path, blob_url) is populated.
       Idempotent. No-op if row missing or both columns NULL.
    """

def stitch_input_for(run_row: dict) -> tuple[str, dict[str, str] | None]:
    """Build the (path_or_url, headers) tuple that compile._resolve_run_ids_to_stitch_refs
       passes into ffmpeg via stitch.py:_sync_trim.
       local: (run_row['parent_path'], None)
       blob:  (run_row['parent_blob_url'], {'Authorization': f'Bearer {token}'}).
       Pure function — no network call (amendment 1).
    """

def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str]]:
    """Pure helper — replaces D-03 mint_signed_url. Returns
         (f'https://{store_id}.private.blob.vercel-storage.com/{pathname}',
          {'Authorization': f'Bearer {BLOB_READ_WRITE_TOKEN}'}).
       local mode: returns (f'/media/{Path(pathname).name}', None) for symmetry — never used in trim path.
       Caller is stitch_input_for (which already has the row, so this is the lower-level building block).
    """

# backend/storage/blob_client.py surface (D-03 corrected per amendment 1):

async def init_client() -> None:    # raises RuntimeError if BLOB_READ_WRITE_TOKEN empty (D-19)
async def close_client() -> None:
def get_client() -> httpx.AsyncClient:  # raises RuntimeError if not initialized

class BlobObject(TypedDict):
    url: str
    pathname: str
    contentType: str
    contentDisposition: str
    downloadUrl: str

async def upload(*, pathname: str, body: bytes, content_type: str,
                 access: Literal["public", "private"]) -> BlobObject
async def delete(*, pathname: str) -> None             # 404 silenced
async def head(*, pathname: str) -> BlobObject | None  # None on 404
</interfaces>

<phase_history_digest>
- Phase 8 D-12: middleware order XFFStrip, RequestID, Metrics, CORS, routes. Phase 10 changes nothing.
- Phase 8 D-14: Sentry before_send already redacts blob_url. Phase 10 logs pathname only — never the absolute URL or Bearer token.
- Phase 8 PRIV-02 (D-08): structlog contextvars whitelist = clip_id, request_id, session_hash. Phase 10 logs Blob URLs/pathnames/latencies as kwargs only.
- Phase 9 D-07/D-08: module-import-time dispatcher pattern. Phase 10 D-13 mirrors verbatim.
- Phase 9 D-10: conftest fixture parametrize. Phase 10 D-21 extends.
- Phase 9 D-11: OFFLINE_DEMO hard-override. Phase 10 D-18 mirrors.
- Phase 9 D-14: wave-0 smoke deploy. Phase 10 D-22 mirrors (Wave 0 below).
- Phase 9 D-16: lifespan-managed asyncpg pool. Phase 10 D-02 mirrors for httpx client.
- Phase 9 L-04: clips.blob_url + clips.is_hidden already exist in initial Alembic migration. Phase 10 does NO schema work for postgres (sqlite gets a defensive ALTER per Task 2.1).
</phase_history_digest>
</context>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser to FastAPI /clips | Untrusted multipart upload (existing — MIME prefix gate + 100 MiB cap at app.py:159-160). |
| FastAPI to Vercel Blob REST | Bearer-token-authed; outbound only; never round-trips browser-supplied bytes without server-side gating (L-02). |
| FastAPI to ffmpeg subprocess | ffmpeg fetches private Blob via -headers "Authorization: Bearer ..." flag forwarded by ffmpeg-python. |
| Browser to public runs/ Blob URL | Browser-direct; CDN-fronted; URL is unguessable enough (run_id is uuid-derived) but NOT a security boundary — anonymity is the actual privacy guarantee. |
| Phase 11 moderation decision to cleanup_blocked_clip | Internal call only; no token / no header crosses this boundary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-10-01 | Information Disclosure | log lines / Sentry breadcrumbs | high | mitigate | structlog kwargs only (Phase 8 PRIV-02). Log op, pathname, latency_ms, bytes — never the bearer header, never Authorization strings, never the absolute URL of a private blob. Sentry before_send already scrubs blob_url (Phase 8 D-14); verify httpx integration scrubs Authorization request headers in breadcrumbs (sentry-sdk default does — verify in Wave 4 test). |
| T-10-02 | Spoofing | direct browser PUT bypassing moderation gate | high | mitigate | BLOB_READ_WRITE_TOKEN server-only — never exposed to browser; never sent in any response body or header. Wrapper does NOT have a mint_client_upload_token op. Existing /clips ingest gate (MIME + size + lat/lng validation) is the only ingress (L-02 reinforced). Verification step in Wave 5: confirm a direct PUT https://teststore.private.blob.vercel-storage.com/uploads/x.mp4 from a browser context returns 401/403. |
| T-10-03 | Information Disclosure | leaked private blob URL replayed by attacker | medium | mitigate | No TTL on private URLs (Vercel Blob has no signed-URL feature). Defense: BLOB-08 cleanup_blocked_clip DELETEs blocked clips synchronously on moderation decision (D-20). Leak window equals time-to-block. Bearer token is process-singleton — separately compromised means full breach, not URL-leak escalation. |
| T-10-04 | Denial of Service / Tampering | fail-open on missing BLOB_READ_WRITE_TOKEN | high | mitigate | D-19: init_client raises RuntimeError at lifespan startup when STORAGE_BACKEND=blob and OFFLINE_DEMO=false and token empty (mirror of db_postgres.init_pool line 98-104). Bad config fails the deploy, not graceful-degrade. Wave 4 test asserts. |
| T-10-05 | Tampering | OFFLINE_DEMO firewall bypass via Blob startup HTTP | high | mitigate | D-18 hard-override at dispatcher (backend/storage/__init__.py). Wave 4 test (test_offline_demo_firewall.py) asserts zero httpx mock calls during full lifespan startup with OFFLINE_DEMO=true. Phase 13 DEMO-02 CI smoke is the production gate. |

**Block-on:** all severity=high rows. T-10-03 is medium (URL leak alone without token leak is bounded).
</threat_model>

---

## Wave 0 — Smoke deploy and sanity (D-22)

**Wave dependencies:** none. Runs BEFORE any code changes ship. Mirrors Phase 9 D-14 wave-0 posture.

This wave is `autonomous: false`. The executor cannot create a Vercel Blob store or paste a Railway env var.

<task type="checkpoint:human-action" gate="blocking">
  <name>Task 0.1: User creates Vercel Blob store + Railway env vars</name>
  <what-built>Nothing yet — pre-flight setup before code lands.</what-built>
  <how-to-verify>
1. User confirms a Vercel Blob store exists in Vercel Dashboard, Storage. Note the store_id (visible in the auto-generated subdomain).
2. User has copied a BLOB_READ_WRITE_TOKEN (format `vercel_blob_rw_<store_id>_<random>`) from Vercel, Storage, Tokens.
3. User has set the following on Railway, newz-backend, Variables:
   - BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... (paste from step 2)
   - STORAGE_BACKEND=blob (will take effect after Wave 1 lands; harmless for now since `backend/storage/` doesn't exist yet)
4. User confirms Vercel Blob plan tier (Hobby OK; Pro recommended if production traffic anticipated — amendment 6).
  </how-to-verify>
  <resume-signal>Type "blob env ready" — executor will then proceed to Wave 1.</resume-signal>
</task>

<task type="auto">
  <name>Task 0.2: Local sanity ping (offline scratch test)</name>
  <files>(no files committed — scratch)</files>
  <action>
Before writing any production code, verify the Vercel Blob REST surface from a scratch interpreter to flush DNS / TLS / token-format surprises early.

Run inside backend's venv (token must be exported in the shell environment first; never paste it into the script):

```
python - <<'PY'
import os, httpx
token = os.environ["BLOB_READ_WRITE_TOKEN"]
r = httpx.put(
    "https://vercel.com/api/blob",
    params={"pathname": "smoketest/hello.txt"},
    headers={
        "Authorization": f"Bearer {token}",
        "x-api-version": "11",
        "x-content-type": "text/plain",
        "x-content-length": "5",
        "x-vercel-blob-access": "private",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
    },
    content=b"hello",
    timeout=30.0,
)
print(r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])
PY
```

Acceptance:
  - HTTP 200, JSON response includes `"pathname": "smoketest/hello.txt"` and a `url` starting with `https://`.
  - If 401/403 → token is wrong; halt and ask user to re-issue.
  - If DNS/TLS error → halt and ask user.

After success, DELETE the scratch blob:

```
python - <<'PY'
import os, httpx
token = os.environ["BLOB_READ_WRITE_TOKEN"]
store_id = token.split("_")[3]
url = f"https://{store_id}.private.blob.vercel-storage.com/smoketest/hello.txt"
r = httpx.post(
    "https://vercel.com/api/blob/delete",
    headers={"Authorization": f"Bearer {token}", "x-api-version": "11", "Content-Type": "application/json"},
    json={"urls": [url]},
    timeout=30.0,
)
print(r.status_code, r.text[:200])
PY
```

This is a one-shot scratch script; do NOT commit it.
  </action>
  <verify>
    <automated>echo "see manual output above; expect 200 on PUT and 200 on DELETE"</automated>
  </verify>
  <done>PUT returns 200 with JSON; DELETE returns 200. Token shape is confirmed (`vercel_blob_rw_<store_id>_<random>`). store_id parses cleanly. If anything failed, fix before Wave 1.</done>
</task>

---

## Wave 1 — Storage package and config (BLOB-06 partial; foundations)

**Wave dependencies:** Wave 0 (env vars exist).

### Task 1.1: Add STORAGE_BACKEND + BLOB_READ_WRITE_TOKEN to config.py

<task type="auto">
  <name>Task 1.1: Add Phase 10 env vars to backend/config.py</name>
  <files>backend/config.py</files>
  <action>
Append a new section AFTER the Phase 9 block (currently ends at line 56). Mirror the comment-block density of lines 42-56 verbatim — section header naming the locked decisions, per-var docstring with rationale, fail-loud justification.

Add exactly these two vars (per D-23 / amendment 8):

```
# Phase 10: Vercel Blob migration (D-12, D-19, D-23; amendments 1-8 in 10-PLAN.md)
# STORAGE_BACKEND: 'local' (default — v1.0 path, kept indefinitely for OFFLINE_DEMO + rollback)
#   or 'blob' (v1.1 cutover — Vercel Blob via raw httpx wrapper, D-01).
#   OFFLINE_DEMO=true hard-overrides to local regardless of this value (D-18).
STORAGE_BACKEND: str = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
# BLOB_READ_WRITE_TOKEN: Vercel-issued read/write token for the Blob store.
#   Format: vercel_blob_rw_<store_id>_<random>. Loaded once at module import.
#   Never logged, never sent to browser (L-02). Empty when STORAGE_BACKEND=blob
#   AND OFFLINE_DEMO=false fails fast at lifespan startup (D-19).
BLOB_READ_WRITE_TOKEN: str = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
```

Implements: BLOB-06 (rollback flag).
  </action>
  <verify>
    <automated>cd backend && python -c "import importlib, config; importlib.reload(config); print(config.STORAGE_BACKEND, len(config.BLOB_READ_WRITE_TOKEN))"</automated>
  </verify>
  <done>`python -c` prints `local 0` by default. With env vars set, prints `blob NN` where NN > 30.</done>
</task>

### Task 1.2: Update .env.example

<task type="auto">
  <name>Task 1.2: Document new env vars in backend/.env.example</name>
  <files>backend/.env.example</files>
  <action>
Append a section AFTER the current Phase 9 block. Mirror the comment density of the existing Phase 9 block (one `#` line per var explaining the locked decision, then `KEY=value`).

Append exactly:

```
# Phase 10: Vercel Blob (D-12, D-19, D-23). STORAGE_BACKEND=blob enables
# Vercel Blob storage. OFFLINE_DEMO=true hard-overrides to local (D-18).
STORAGE_BACKEND=local
# BLOB_READ_WRITE_TOKEN: paste from Vercel Dashboard, Storage, Tokens.
# Empty default — required when STORAGE_BACKEND=blob and OFFLINE_DEMO=false.
BLOB_READ_WRITE_TOKEN=
```

Do NOT add any default value for the token. Empty is the correct default for the example file.

Implements: BLOB-06 (documents the flag).
  </action>
  <verify>
    <automated>grep -E "^STORAGE_BACKEND=|^BLOB_READ_WRITE_TOKEN=" backend/.env.example | wc -l</automated>
  </verify>
  <done>grep returns `2` — both vars are present.</done>
</task>

### Task 1.3: Pin httpx and tenacity in requirements.txt

<task type="auto">
  <name>Task 1.3: Pin httpx and tenacity (amendment 8)</name>
  <files>backend/requirements.txt</files>
  <action>
The current requirements.txt has `tenacity` unpinned (line 8) and `httpx` only transitively (via twelvelabs==1.2.3). Replace `tenacity` with `tenacity==9.1.4` and add `httpx==0.28.1` directly above it (alphabetical-ish style preserved).

Final delta:
  - line 8 was: `tenacity`
  - new lines 8-9 become:
    ```
    httpx==0.28.1
    tenacity==9.1.4
    ```

Verify with `pip install -r requirements.txt` in a scratch venv that resolution still succeeds. If twelvelabs's transitive httpx range conflicts (it requires `>=0.21.2`), 0.28.1 satisfies it — no further pinning needed.

Implements: defense-in-depth for BLOB-01..04 (no silent breakage).
  </action>
  <verify>
    <automated>cd backend && grep -E "^httpx==0\.28\.1$|^tenacity==9\.1\.4$" requirements.txt | wc -l</automated>
  </verify>
  <done>grep returns `2`. `pip install -r requirements.txt` runs without conflict resolution errors in a scratch venv.</done>
</task>

### Task 1.4: Create backend/storage/blob_client.py (httpx wrapper)

<task type="auto">
  <name>Task 1.4: Implement raw httpx wrapper</name>
  <files>backend/storage/blob_client.py</files>
  <action>
Create the raw async httpx wrapper. Mirror `backend/db_postgres.py:64-124` structure verbatim for lifecycle (init_client / close_client / get_client / module-level _client singleton). Implementation guided by RESEARCH section 11 Example 2 and amendments 1, 6, 8.

Required surface (per amendment 1):
  - Module-level `_client: httpx.AsyncClient | None = None`.
  - `def get_client() -> httpx.AsyncClient` — raises RuntimeError("httpx blob client not initialized — backend.app.lifespan must call init_client() first") (verbatim shape mirroring db_postgres line 77-79).
  - `async def init_client() -> None`:
    * idempotent (warn-and-return if `_client is not None`, mirror db_postgres line 96)
    * fail-loud on missing token (mirror db_postgres lines 98-104):
      ```
      if not config.BLOB_READ_WRITE_TOKEN:
          raise RuntimeError(
              "BLOB_READ_WRITE_TOKEN is empty but STORAGE_BACKEND=blob and OFFLINE_DEMO=false. "
              "Set BLOB_READ_WRITE_TOKEN or flip STORAGE_BACKEND=local to use the local-FS path."
          )
      ```
    * defensive token-format check: if `len(BLOB_READ_WRITE_TOKEN.split("_")) <= 3`, raise RuntimeError "BLOB_READ_WRITE_TOKEN has unexpected format (expected vercel_blob_rw_<store_id>_<random>)" — RESEARCH Assumption A3 mitigation.
    * create `_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))`
    * log `"httpx blob client created"` — NEVER log the token. On exception, sanitize: `log.error("blob client init failed: %s (token redacted)", type(exc).__name__)` (mirror db_postgres line 114).
  - `async def close_client() -> None` — calls `await _client.aclose()`, sets `_client = None`.

HTTP operations (RESEARCH section 11 Example 2 is the canonical reference; copy the request shapes verbatim):
  - `async def upload(*, pathname, body, content_type, access) -> BlobObject`:
    * PUT `https://vercel.com/api/blob?pathname={pathname}`
    * headers: `Authorization: Bearer <token>`, `x-api-version: 11`, `x-api-blob-request-id: <store_id>:<ms>:<uuid8>`, `x-api-blob-request-attempt: 1`, `x-content-type: <content_type>`, `x-content-length: <len(body)>`, `x-vercel-blob-access: <access>`, `x-add-random-suffix: 0`, `x-allow-overwrite: 1` (amendment 5).
    * 404/410 → raise `BlobNotFound(pathname)`. Other 4xx → `resp.raise_for_status()`.
    * log structured kwargs only: `log.info("blob op=upload pathname=%s latency_ms=%d bytes=%d", pathname, ms, len(body))` — NEVER log `headers` dict, NEVER log body bytes.
  - `async def delete(*, pathname) -> None`:
    * POST `https://vercel.com/api/blob/delete` with JSON body `{"urls": [private_url, public_url]}` (try both — control plane accepts either domain).
    * idempotent: NEVER raises on 404 (mirror Vercel-py contract). 5xx still retries via tenacity.
    * log: `log.info("blob op=delete pathname=%s latency_ms=%d", ...)`.
  - `async def head(*, pathname) -> BlobObject | None`:
    * GET `https://vercel.com/api/blob?url=<private_url>`.
    * 404 → return None.
    * Used for smoke checks only.

Retry posture (amendments 6, D-24): use tenacity decorator on `upload` and `head` (NOT on `delete`, which has its own idempotent semantics):

```
_blob_retry = retry(
    retry=retry_if_exception_type((httpx.TransportError, _RetryableHTTPError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
    reraise=True,
)
```

Define `_RetryableHTTPError` as a custom exception raised inside the function body for HTTP 429 and 5xx (so 4xx other than 429 fail-fast — D-24). On 401/403, re-raise as-is (no retry).

Helper: `def _store_id_from_token(token: str) -> str` — split on `_`, return parts[3]. Raise on len <= 3 (defensive — A3).

Module docstring: cite D-01, D-02, D-25, amendment 1, amendment 6. Note `--workers 1` justification for the module-level singleton (mirror db_postgres lines 8-10).

NO comments inside function bodies unless the WHY is non-obvious (CLAUDE.md). The retry decorator name + tenacity stack + the `x-allow-overwrite` header value (amendment 5) are the three places a brief comment IS warranted.

Implements: foundation for BLOB-01, BLOB-02, BLOB-08; supports T-10-01, T-10-04 mitigations.
  </action>
  <verify>
    <automated>cd backend && python -c "from storage import blob_client; print('ok' if hasattr(blob_client, 'init_client') and hasattr(blob_client, 'upload') and hasattr(blob_client, 'delete') and hasattr(blob_client, 'head') else 'FAIL')"</automated>
  </verify>
  <done>Module imports cleanly. `get_client()` raises RuntimeError when called pre-init. Function signatures match the `<interfaces>` block above.</done>
</task>

### Task 1.5: Create backend/storage/_url.py (URL helpers)

<task type="auto">
  <name>Task 1.5: URL parsing helpers</name>
  <files>backend/storage/_url.py</files>
  <action>
Pure-function module. No imports from `backend.storage.blob` or `backend.storage.local` (avoid circulars). Imports only `urllib.parse`.

Public functions:
  - `def is_absolute_url(s: str | None) -> bool` — returns True iff `s` is non-None and `s.startswith(("http://", "https://"))`.
  - `def pathname_of_blob_url(url: str) -> str` — `urlparse(url).path.lstrip("/")`. Used by `blob.delete_clip(absolute_url)` to extract `uploads/abc.mp4` for the delete API call.

Module docstring: cite "Phase 10: pure URL helpers shared by storage/local.py and storage/blob.py."

Implements: shared infrastructure.
  </action>
  <verify>
    <automated>cd backend && python -c "from storage._url import is_absolute_url, pathname_of_blob_url; assert is_absolute_url('https://x.com/a'); assert not is_absolute_url('/media/x'); assert pathname_of_blob_url('https://x.vercel-storage.com/uploads/abc.mp4')=='uploads/abc.mp4'; print('ok')"</automated>
  </verify>
  <done>Both helpers behave per docstring. Module has no dependencies on the rest of `backend/storage/`.</done>
</task>

### Task 1.6: Create backend/storage/local.py (lift-and-shift)

<task type="auto">
  <name>Task 1.6: Lift-and-shift v1.0 local-FS to storage/local.py</name>
  <files>backend/storage/local.py</files>
  <action>
Lift-and-shift the v1.0 local-FS write/read/delete logic from `db_sqlite.py` and `db_postgres.py` into a new module. This is the OFFLINE_DEMO + rollback path; signatures MUST match the `<interfaces>` block above byte-for-byte (D-12 parity).

Module structure (mirror PATTERNS line 86-119):
  - module docstring naming D-12 and the source-of-truth lift line numbers (db_sqlite.py:168; db_postgres.py:167).
  - `import logging; from pathlib import Path; from .. import config; from . import _url`.
  - `log = logging.getLogger(__name__)`.
  - `CLIPS_DIR = config.DATA_DIR / "clips"` (constant — mirror db_sqlite.py:16).
  - `__all__ = ["save_clip_bytes", "delete_clip", "get_playable_url", "cleanup_blocked_clip", "stitch_input_for", "authorized_blob_input"]`.

Function bodies (per `<interfaces>`):

```
async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{clip_id}.{ext}"
    path.write_bytes(contents)
    log.info("save_clip id=%s bytes=%d", clip_id, len(contents))
    return str(path)


async def delete_clip(path_or_url: str) -> None:
    if not path_or_url:
        return
    if _url.is_absolute_url(path_or_url):
        # Mixed-mode rollback window: a blob_url showing up while in local mode.
        # Skip — local backend can't authenticate to Vercel. caller (admin/reset)
        # already swallows per-path errors at app.py:420-430 anyway.
        return
    try:
        p = Path(path_or_url)
        if p.is_file():
            p.unlink()
    except FileNotFoundError:
        pass


def get_playable_url(row: dict) -> str | None:
    blob_url = row.get("blob_url")
    if blob_url:
        return blob_url
    path = row.get("path")
    if not path:
        return None
    return f"/media/{Path(path).name}"


async def cleanup_blocked_clip(clip_id: str) -> None:
    # Phase 10 contract — D-20. Phase 11 calls this after marking blocked.
    # In local mode: best-effort unlink. Idempotent.
    from .. import db
    row = await db.get_clip(clip_id)
    if row is None:
        return
    path = row.get("path") or row.get("blob_url")
    if path:
        await delete_clip(path)


def stitch_input_for(run_row: dict) -> tuple[str, dict[str, str] | None]:
    return (run_row["parent_path"], None)


def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str] | None]:
    return (str(CLIPS_DIR / Path(pathname).name), None)
```

Implements: BLOB-06 (rollback path); foundations for BLOB-08 (cleanup hook stub).
  </action>
  <verify>
    <automated>cd backend && python -c "from storage import local; assert callable(local.save_clip_bytes); assert hasattr(local, 'cleanup_blocked_clip'); assert hasattr(local, 'stitch_input_for'); print('ok')"</automated>
  </verify>
  <done>All six exports present. `get_playable_url({'blob_url': 'https://x', 'path': '/y'})` returns `'https://x'` (forward-compat). `get_playable_url({'path': '/y/abc.mp4'})` returns `'/media/abc.mp4'`.</done>
</task>

### Task 1.7: Create backend/storage/blob.py (Vercel Blob impl)

<task type="auto">
  <name>Task 1.7: Implement storage/blob.py (parity with local.py)</name>
  <files>backend/storage/blob.py</files>
  <action>
Implement the Blob backend. Signatures match `local.py` byte-for-byte (D-12 parity). Defer all HTTP details to `blob_client` (D-25 — never `import httpx` here).

Module structure (mirror PATTERNS line 122-161):
  - module docstring citing D-01, D-12, D-20, amendment 1, amendment 5.
  - `import logging; from pathlib import Path; from .. import config; from . import blob_client, _url`.
  - `__all__ = [...]` (same six names as local.py).

Function bodies:

```
async def save_clip_bytes(clip_id: str, ext: str, contents: bytes) -> str:
    # uploads/ is private (D-05 / amendment 2). content_type matches inbound MIME.
    mime = f"video/{ext}" if ext in ("mp4", "webm") else "application/octet-stream"
    obj = await blob_client.upload(
        pathname=f"uploads/{clip_id}.{ext}",
        body=contents,
        content_type=mime,
        access="private",
    )
    return obj["url"]


async def delete_clip(path_or_url: str) -> None:
    if not path_or_url:
        return
    if not _url.is_absolute_url(path_or_url):
        return  # legacy filesystem path during mixed-mode rollback — ignore.
    pathname = _url.pathname_of_blob_url(path_or_url)
    try:
        await blob_client.delete(pathname=pathname)
    except Exception as exc:
        log.warning("blob delete failed pathname=%s err=%s (idempotent — ignored)", pathname, type(exc).__name__)


def get_playable_url(row: dict) -> str | None:
    blob_url = row.get("blob_url")
    if blob_url:
        return blob_url
    path = row.get("path")
    if path:
        return f"/media/{Path(path).name}"
    return None


async def cleanup_blocked_clip(clip_id: str) -> None:
    # D-20 BLOB-08 hook — Phase 11 caller. Idempotent.
    from .. import db
    row = await db.get_clip(clip_id)
    if row is None:
        return
    target = row.get("blob_url") or row.get("path")
    if target:
        await delete_clip(target)


def stitch_input_for(run_row: dict) -> tuple[str, dict[str, str] | None]:
    # Pure function — no network call (amendment 1 supersedes D-06 mint logic).
    parent_blob_url = run_row.get("parent_blob_url")
    if not parent_blob_url:
        # Migration window: row only has path. Fall back to local-mode-style ref so trim still works.
        return (run_row["parent_path"], None)
    headers = {"Authorization": f"Bearer {config.BLOB_READ_WRITE_TOKEN}"}
    return (parent_blob_url, headers)


def authorized_blob_input(pathname: str) -> tuple[str, dict[str, str]]:
    # Pure helper — replaces D-03 mint_signed_url. No network. Token interpolation only.
    token = config.BLOB_READ_WRITE_TOKEN
    store_id = blob_client._store_id_from_token(token)
    url = f"https://{store_id}.private.blob.vercel-storage.com/{pathname}"
    headers = {"Authorization": f"Bearer {token}"}
    return (url, headers)
```

Logging: only `log.warning` on delete-failure (already shown). Do NOT add a `log.info` per call here — `blob_client` already logs at the HTTP boundary (D-28).

Implements: BLOB-01 (`save_clip_bytes` writes to uploads/), BLOB-02 (runs/ is set by compile.py via `blob_client.upload(pathname='runs/...', access='public')`), BLOB-08 (`cleanup_blocked_clip`).
  </action>
  <verify>
    <automated>cd backend && python -c "from storage import blob, local; assert set(blob.__all__) == set(local.__all__); print('parity ok')"</automated>
  </verify>
  <done>Symmetric exports. Both modules expose the same six names. `import` succeeds without HTTP requests (no top-level network calls).</done>
</task>

### Task 1.8: Create backend/storage/__init__.py (dispatcher)

<task type="auto">
  <name>Task 1.8: Implement storage dispatcher (D-13 / D-18)</name>
  <files>backend/storage/__init__.py</files>
  <action>
Mirror `backend/db.py` verbatim. Three-arm if/elif/else, module-import-time selection, OFFLINE_DEMO hard-override. Note the parent-package import (`..`) since `storage` is a subpackage.

Exact contents:

```
"""Phase 10 (D-12, D-13, D-18): STORAGE_BACKEND dispatcher — module-import-time selection.

OFFLINE_DEMO=true hard-overrides to local regardless of STORAGE_BACKEND (D-18).
Mirrors backend/db.py:1-24 verbatim — same three-arm shape.

Per-request branching is FORBIDDEN (D-13 / PATTERNS Anti-Patterns). The if/elif
below runs once at import; downstream callers see exactly one function table.
"""
import logging

from .. import config

log = logging.getLogger(__name__)

if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
    from .blob import *  # noqa: F401, F403
    log.info("storage_backend=blob")
elif config.STORAGE_BACKEND == "blob" and config.OFFLINE_DEMO:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local (forced by OFFLINE_DEMO=true; D-18)")
else:
    from .local import *  # noqa: F401, F403
    log.info("storage_backend=local")
```

Implements: BLOB-06 (the flag's actual switch); supports T-10-05 (firewall: blob arm unreachable under OFFLINE_DEMO).
  </action>
  <verify>
    <automated>cd backend && OFFLINE_DEMO=true STORAGE_BACKEND=blob python -c "import importlib, storage; importlib.reload(storage); from storage import save_clip_bytes; print(save_clip_bytes.__module__)"</automated>
  </verify>
  <done>The OFFLINE_DEMO=true + STORAGE_BACKEND=blob test prints `backend.storage.local` (proves D-18 hard-override is wired). Without OFFLINE_DEMO and STORAGE_BACKEND=blob, prints `backend.storage.blob`.</done>
</task>

---

## Wave 2 — DB callsite refactor and lifespan integration

**Wave dependencies:** Wave 1 (storage package exists).

### Task 2.1: Refactor db_sqlite.py call sites

<task type="auto">
  <name>Task 2.1: Replace path.write_bytes / /media URL builder with storage dispatcher</name>
  <files>backend/db_sqlite.py</files>
  <action>
Five call sites, all listed at CONTEXT line 153 (line numbers: 16, 94, 168, 205, 375-379, 599, 677). Touch ONLY these and preserve everything else.

1. **Line 168 (`insert_clip`):** Replace `path = CLIPS_DIR / f"{clip_id}.{ext}"; path.write_bytes(contents)` with the storage call. Final block becomes:

   ```
   from . import storage  # local import — avoid circular at module load
   result = await storage.save_clip_bytes(clip_id, ext, contents)
   # Storage returns either a filesystem path string (local) or absolute Blob URL (blob).
   is_blob_url = result.startswith("http")
   async with aiosqlite.connect(DB_PATH) as conn:
       await conn.execute(
           "INSERT INTO clips (id, path, blob_url, lat, lng, ts, session_id, created_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           (clip_id, None if is_blob_url else result,
            result if is_blob_url else None,
            lat, lng, ts, session_id, now),
       )
       await conn.commit()
   ```

   NOTE: SQLite v1.0 schema may not have a `blob_url` column. The Phase 9 Alembic migration applies to Postgres only. For sqlite, run a one-time `ALTER TABLE clips ADD COLUMN blob_url TEXT` inside `init()` if the column is missing — guard via `PRAGMA table_info(clips)` lookup. This preserves the OFFLINE_DEMO + sqlite path without requiring a fresh DB.

2. **Lines 202-205 (`fetch_recent_clips`):** Replace inline `f"/media/{filename}"` with `storage.get_playable_url(r)` call. Drop the `Path(r["path"]).name` line (it lives behind `get_playable_url` now).

3. **Lines 374-379 (`fetch_recent_segments._url`):** Same swap — use `storage.get_playable_url`. The `_run_*` branch should prefer `seg.get("video_url")` directly when populated (already absolute or already relative — RESEARCH Open Question 4).

4. **Lines 597-613 / 666-695 (`reset_all` / `delete_recent_clips` `paths_to_delete`):** No SQL change needed — keep returning `paths_to_delete: list[str]`. The list may now contain absolute Blob URLs in blob mode. The `app.py` shim is updated separately (Task 2.4).

Preserve EVERYTHING else: SCHEMA_SQL, indexing, async with patterns, logging keyword style. Do NOT introduce new external imports beyond `from . import storage`.

Implements: BLOB-01 (uploads via storage dispatcher), BLOB-05 (URL builder routes through storage layer), BLOB-07 (DB stores absolute URL when blob mode).
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/ -k "sqlite" -x --tb=short 2>&1 | tail -30</automated>
  </verify>
  <done>Existing sqlite tests pass. `insert_clip` writes a row with `path` populated under local mode and `blob_url` populated under blob mode (verified in Wave 4 fixture).</done>
</task>

### Task 2.2: Mirror refactor in db_postgres.py

<task type="auto">
  <name>Task 2.2: Apply identical changes to db_postgres.py</name>
  <files>backend/db_postgres.py</files>
  <action>
Mirror Task 2.1 1:1 in the postgres branch. Line numbers per CONTEXT line 154: 32, 58-61, 145-150, 167, 199, 379-383, 612, 695.

1. **Line 167 (`insert_clip`):** Replace `path.write_bytes(contents)` and the surrounding INSERT with the storage call. The Postgres INSERT becomes:

   ```
   from . import storage
   result = await storage.save_clip_bytes(clip_id, ext, contents)
   is_blob_url = result.startswith("http")
   async with pool.acquire() as conn:
       await conn.execute(
           "INSERT INTO clips (id, path, blob_url, lat, lng, ts, session_id, created_at) "
           "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
           clip_id, None if is_blob_url else result,
           result if is_blob_url else None,
           lat, lng, ts, session_id, now,
       )
   ```

   (Postgres `clips.blob_url` already exists per L-04; no ALTER needed.)

2. **Line 199 (`fetch_recent_clips` URL builder):** Replace inline `f"/media/{filename}"` with `storage.get_playable_url(r)`.

3. **Lines 379-383 (`fetch_recent_segments._url`):** Same swap. Prefer `seg.get("video_url")` directly when populated.

4. **Lines 612 / 695 (paths_to_delete):** No change to return shape — list[str] continues to mix absolute paths and absolute URLs.

Preserve `pool.execute / pool.fetch / pool.fetchrow` patterns and `ANY($1::text[])` style. Do NOT introduce SQLAlchemy.

Implements: BLOB-01, BLOB-05, BLOB-07 (postgres branch parity).
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/ -k "postgres" -x --tb=short 2>&1 | tail -30</automated>
  </verify>
  <done>Postgres tests pass (skip cleanly if `DATABASE_URL` not set in CI). Insertion writes `blob_url` in blob mode.</done>
</task>

### Task 2.3: Wire blob_client into app.py lifespan

<task type="auto">
  <name>Task 2.3: Add httpx Blob client init/close to lifespan + conditional /media mount</name>
  <files>backend/app.py</files>
  <action>
Two edits in this file. The ordering of lifespan steps is fixed by Phase 9 + amendment ordering (CONTEXT line 201).

**Edit 1 — lifespan (current lines 87-127):** Insert init AFTER `cluster_mod.rebuild_cache()` (current line 105) and BEFORE the keepalive task creation (current line 109-110). Insert close AFTER keepalive cancel (line 125-127) and BEFORE `db.close_pool()`.

Final lifespan order: asyncpg pool, db.init, cluster rebuild, blob client init (NEW), Neon keepalive, pre-warms, yield, keepalive cancel, blob client close (NEW), asyncpg pool close.

Insertion blocks (verbatim from RESEARCH section 11 Example 3):

```
# 3.5. Phase 10 (D-02, D-19): httpx Blob client init — only when blob mode active.
# OFFLINE_DEMO=true short-circuits to local at the dispatcher (D-18), so this
# branch is unreachable under firewalled-CI; enforces D-19 fail-loud on missing token.
if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
    from .storage import blob_client
    await blob_client.init_client()
```

Shutdown insertion (in the `finally:` block):

```
if config.STORAGE_BACKEND == "blob" and not config.OFFLINE_DEMO:
    from .storage import blob_client
    await blob_client.close_client()
```

**Edit 2 — /media mount (current line 151):** Wrap in conditional per D-16. Replace line 151 with:

```
if config.STORAGE_BACKEND == "local" or config.OFFLINE_DEMO:
    app.mount("/media", StaticFiles(directory=str(config.DATA_DIR / "clips")), name="media")
```

Keep lines 149-150 (`mkdir(parents=True, exist_ok=True)`) UNCONDITIONAL — `DATA_DIR` is still used by sqlite/Alembic and the local rollback path; mkdir is cheap and safe.

Preserve the Phase 8 D-12 middleware order. Do NOT touch lines 132-147.

Implements: BLOB-02 (lifespan creates the client that uploads runs/), BLOB-05 (/media mount removed in blob mode), BLOB-06 (rollback re-enables /media), T-10-04 (fail-loud), T-10-05 (firewall guard).
  </action>
  <verify>
    <automated>cd backend && OFFLINE_DEMO=true STORAGE_BACKEND=blob python -c "import asyncio; from app import app; print('lifespan importable')"</automated>
  </verify>
  <done>Module imports under both env combos. Under STORAGE_BACKEND=blob + OFFLINE_DEMO=true, `app.routes` does NOT contain a /media mount (verified in Wave 4 test).</done>
</task>

### Task 2.4: Update _delete_files for absolute URLs

<task type="auto">
  <name>Task 2.4: admin/reset honors blob URLs in paths_to_delete</name>
  <files>backend/app.py</files>
  <action>
Update `_delete_files` (current lines 420-430) to route URL-shaped entries through the storage dispatcher. Replace the function body with an async version, then update its callers:

```
async def _delete_paths_async(paths: list[str]) -> int:
    from . import storage  # local import — avoid circular
    n = 0
    for path_str in paths:
        try:
            await storage.delete_clip(path_str)
            # storage layer is best-effort; count "n+1" if the path looked deletable.
            n += 1
        except Exception as e:
            log.warning("admin_reset: could not delete %s: %s", path_str, e)
    return n
```

Update the two call sites (lines ~472, ~483):

  - Line 472: `deleted_files = _delete_files(out["paths_to_delete"])` becomes `deleted_files = await _delete_paths_async(out["paths_to_delete"])`.
  - Line 483: same swap.

For `mode=all` (lines 460-466): leave as-is — it physically scans the local clips dir, which is empty in blob mode (no harm). The Blob-side bulk wipe is achieved by `db.reset_all()` truncating rows and the cleanup hook in Phase 11; for v1.1 demo cutover (D-15) we expect a small number of test uploads, so leaving stale Blob objects is acceptable for the demo path. Add a 2-line WHY comment above the loop (this IS non-obvious — comment is justified per CLAUDE.md).

Remove the OLD `_delete_files` function. Verify with `grep _delete_files backend/` — only `admin_reset` should reference it; if so, fully remove.

Implements: BLOB-08 partial (delete path now flows through storage layer for /admin/reset entrypoints — see Task 4.x for the actual hook test).
  </action>
  <verify>
    <automated>cd backend && grep -E "_delete_files|_delete_paths_async" app.py</automated>
  </verify>
  <done>`_delete_paths_async` is the only deletion helper. Old `_delete_files` removed. `admin_reset` `await`s the new helper.</done>
</task>

---

## Wave 3 — Pipeline integration (BLOB-02, BLOB-03, BLOB-04)

**Wave dependencies:** Wave 2 (DB returns blob_url; storage dispatcher works).

### Task 3.1: Modify _sync_trim to forward auth headers to ffmpeg

<task type="auto">
  <name>Task 3.1: Add ffmpeg -headers passthrough in stitch.py:_sync_trim</name>
  <files>backend/pipeline/stitch.py</files>
  <action>
Per amendment 4 + RESEARCH section 11 Example 4, modify `_sync_trim` (current line 112) to accept an optional `headers` dict in `ref` and pass it to ffmpeg via the `headers=` kwarg with CRLF terminator.

Add ONE block before the existing `ffmpeg.input(...)` call:

```
input_kwargs: dict = {"ss": start}
if end is not None:
    input_kwargs["to"] = end
# Phase 10 (amendment 4): forward auth headers to ffmpeg's -headers flag.
# CRLF terminator is mandatory per ffmpeg HTTP protocol docs (Pitfall 2).
headers_dict = ref.get("headers")
if headers_dict:
    input_kwargs["headers"] = "".join(f"{k}: {v}\r\n" for k, v in headers_dict.items())
```

Then change the existing `ffmpeg.input(ref["path"], ss=start, to=end)` to `ffmpeg.input(ref["path"], **input_kwargs)`.

PRESERVE:
  - Atomic-rename: `tmp_path = f"{output_path}.part-{int(time.time() * 1000)}-{os.getpid()}"` and `os.replace(tmp_path, output_path)` (lines 132-155 region).
  - `vcodec="copy", acodec="copy"` (BLOB-03 byte-range trim).
  - `.global_args("-loglevel", "error")`.
  - The `try / except / unlink-on-failure / re-raise` shape.
  - `log.info("trim ok output=%s", output_path)` final line.

Do NOT modify `_sync_stitch` (line 30) — its internals stay path-based. The CALLER (compile.py — Task 3.3) downloads sources into a tempdir and rewrites refs to local paths before calling `_sync_stitch`.

Implements: BLOB-03 (HTTP-Range trim from private Blob with bearer header).
  </action>
  <verify>
    <automated>cd backend && python -c "import inspect, pipeline.stitch as s; src=inspect.getsource(s._sync_trim); assert 'headers' in src and chr(13)+chr(10) in src; print('ok')"</automated>
  </verify>
  <done>`_sync_trim` references `ref.get(\"headers\")` and assembles a CRLF-terminated string. `vcodec=\"copy\"` preserved.</done>
</task>

### Task 3.2: Modify trim_window and stitch_clips async wrappers to upload runs/

<task type="auto">
  <name>Task 3.2: Upload trim/stitch output to runs/ in async wrappers</name>
  <files>backend/pipeline/stitch.py</files>
  <action>
The `trim_window` async wrapper (current lines ~166-176) currently returns `output_path`. Per D-10 sequential trim, then upload, modify it to upload the local temp .mp4 to `runs/{run_id}.mp4` AFTER `_sync_trim` succeeds, and return the absolute Blob URL.

Add an optional kwarg `run_id: str | None = None`. When None, behavior is unchanged (returns output_path). When set, upload after trim.

Final shape:

```
async def trim_window(ref: dict, output_path: str, *, run_id: str | None = None) -> str:
    if not ref:
        return ""
    fallback_path = ref["path"]
    try:
        loop = asyncio.get_event_loop()
        local_out = await loop.run_in_executor(None, _sync_trim, ref, output_path)
    except Exception as exc:
        log.warning("trim FAILED — falling back to source path: %s", exc)
        return fallback_path

    # Phase 10 (D-10): upload to runs/{run_id}.mp4 when run_id provided.
    if run_id is None or config.STORAGE_BACKEND != "blob" or config.OFFLINE_DEMO:
        return local_out
    try:
        with open(local_out, "rb") as f:
            body = f.read()
        from ..storage import blob_client
        obj = await blob_client.upload(
            pathname=f"runs/{run_id}.mp4",
            body=body,
            content_type="video/mp4",
            access="public",  # amendment 2: runs/ is public
        )
        log.info("trim+upload ok run_id=%s pathname=runs/%s.mp4", run_id, run_id)
        return obj["url"]
    except Exception as exc:
        log.warning("runs/ upload FAILED for run_id=%s — returning local path: %s", run_id, exc)
        return local_out
```

Apply the SAME upload tail (with the same `run_id` kwarg) to `stitch_clips` (current lines ~90-109). The `stitch_clips` wrapper produces a stitched .mp4 from multiple inputs; that output is also a `runs/{run_id}.mp4` candidate.

PRESERVE: existing `try/except` structure for `_sync_trim`, `log.warning` shape, `loop.run_in_executor` boundary (no blocking I/O in the event loop). The pathname log line uses `pathname=runs/{run_id}.mp4` — never log the absolute URL (T-10-01).

Implements: BLOB-02 (runs/ uploads).
  </action>
  <verify>
    <automated>cd backend && python -c "import inspect, pipeline.stitch as s; src1=inspect.getsource(s.trim_window); src2=inspect.getsource(s.stitch_clips); assert 'runs/' in src1 and 'runs/' in src2 and 'access=\"public\"' in src1 and 'access=\"public\"' in src2; print('ok')"</automated>
  </verify>
  <done>Both `trim_window` and `stitch_clips` call `blob_client.upload(pathname=f\"runs/{run_id}.mp4\", ..., access=\"public\")` AFTER ffmpeg succeeds. Both preserve the failure-fallback (return local path on upload failure).</done>
</task>

### Task 3.3: Modify compile.py — _resolve_run_ids_to_stitch_refs + _stitch_segment_runs

<task type="auto">
  <name>Task 3.3: Inject Blob URL refs and tempdir-stitch in compile.py</name>
  <files>backend/pipeline/compile.py</files>
  <action>
Two distinct edits in this file.

**Edit A — `_resolve_run_ids_to_stitch_refs` (lines 194-217):** Replace the `path` builder with `storage.stitch_input_for(...)` (RESEARCH section 11 Example 5). Also add the `run_id: str` to the dict so the downstream caller knows what to name the upload.

Final shape of the inner loop:

```
from .. import storage
...
for rid in ordered_run_ids:
    r = by_id.get(rid)
    if r is None:
        log.warning("resolve: unknown run_id=%s cluster_id=%s", rid, cluster_id)
        continue
    end = None if not r.member_child_ids else r.end_offset_sec
    # Phase 10 (D-08, D-11, amendment 1): stitch_input_for returns
    # (path_or_url, headers_dict_or_None). Pure function — no network call.
    path_or_url, headers = storage.stitch_input_for({
        "parent_path": r.parent_path,
        "parent_blob_url": getattr(r, "parent_blob_url", None),
    })
    refs.append({
        "path": path_or_url,
        "start_offset_sec": r.start_offset_sec,
        "end_offset_sec": end,
        "headers": headers,
        "run_id": rid,
    })
```

NOTE: The `Run` model may not have a `parent_blob_url` attribute today. Read the file to confirm, then add via `compute_runs_for_cluster` join — read the clip row's `blob_url` column and surface it on the Run dataclass. If `Run` is a dataclass, add `parent_blob_url: str | None = None` field; populate inside `compute_runs_for_cluster` from the same query that fetches `parent_path`.

**Edit B — `_stitch_segment_runs` (lines 312-359):** Replace the path-based output and add tempdir-download for stitch sources (BLOB-04 / D-09 / RESEARCH Pattern 4).

Replace `output_path = str(config.DATA_DIR / "clips" / f"{run_id}.mp4")` (line ~343) with a `tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)` allocation. Use it as the local output that `_sync_trim` writes to (atomic-rename inside `_sync_trim` is preserved). Pass `run_id=run_id` into `trim_window(ref, output_path, run_id=run_id)`.

For the multi-source stitch path (when the cluster has ≥2 distinct refs that need normalize-and-concat), wrap the `_sync_stitch` invocation in:

```
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    # Pre-download sources in parallel (BLOB-04 / D-09).
    async def _download_one(ref, idx):
        src_url = ref["path"]
        if not src_url.startswith("http"):
            return ref  # local mode: already a path
        local_path = f"{tmpdir}/src-{idx}.mp4"
        from ..storage import blob_client
        client = blob_client.get_client()
        headers = ref.get("headers") or {}
        async with client.stream("GET", src_url, headers=headers) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
        return {**ref, "path": local_path, "headers": None}
    local_refs = await asyncio.gather(*[_download_one(r, i) for i, r in enumerate(refs)])
    # Now invoke the existing libx264 normalize-and-concat with file-path inputs.
    stitched_url = await stitch_clips(local_refs, tmp_output_path, run_id=run_id)
    # tempdir auto-cleans on context exit.
```

Use `httpx.stream` for download to avoid loading entire source clips into memory (some are up to 100 MiB).

**Edit C — lines 425, 439, 462:** Replace any inline `/media/{run_id}.mp4` literals. The return value from `trim_window` / `stitch_clips` IS the absolute Blob URL (or local path); store it directly as `segment.video_url`. Drop any `/media` prefix construction.

PRESERVE:
  - `asyncio.gather` parallelism over runs.
  - `log.info("trim ok run_id=%s elapsed_ms=%d", ...)` style.
  - W=720, H=1280, FPS=30 constants in stitch.py (calibration-locked).
  - The `_run_*.mp4` filename convention — it's still the Blob `pathname`.

Implements: BLOB-02 (runs/ written), BLOB-03 (private trim from URL), BLOB-04 (tempdir stitch), BLOB-07 (no /data dependency).
  </action>
  <verify>
    <automated>cd backend && python -c "import inspect, pipeline.compile as c; src=inspect.getsource(c); assert 'stitch_input_for' in src and 'TemporaryDirectory' in src and 'aiter_bytes' in src; print('ok')"</automated>
  </verify>
  <done>compile.py builds refs via `storage.stitch_input_for`, stitches via tempdir-download, and never writes to `config.DATA_DIR / "clips"` for run output.</done>
</task>

---

## Wave 4 — Tests

**Wave dependencies:** Waves 1-3 (full implementation lands).

### Task 4.1: Extend conftest.py — STORAGE_BACKEND parametrize fixture

<task type="auto">
  <name>Task 4.1: Add storage_backend fixture (D-21 + Pitfall 5 respx auto-tear-down)</name>
  <files>backend/tests/conftest.py</files>
  <action>
Per RESEARCH section 11 Example 6 and Pitfall 5 (use the `respx_mock` pytest fixture, NOT the bare `@respx.mock` decorator).

First confirm `respx` is in `requirements-dev.txt`. If absent, add `respx>=0.21` to it (NOT to `requirements.txt`).

Then append to `backend/tests/conftest.py` (after the existing `metadata_backend` fixture at lines 19-40):

```
@pytest.fixture(params=["local", "blob"], ids=["local", "blob"])
def storage_backend(request, monkeypatch, respx_mock):
    """D-21: parametrize STORAGE_BACKEND alongside METADATA_BACKEND.

    Cells where STORAGE_BACKEND=blob register respx mocks for Vercel Blob's
    REST endpoints. NEVER hits real Vercel Blob from CI. respx_mock is the
    pytest-fixture form (auto-tear-down per-test) — Pitfall 5.
    """
    backend = request.param
    monkeypatch.setenv("STORAGE_BACKEND", backend)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    if backend == "blob":
        monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_TESTSTORE_xxxxx")
        respx_mock.put("https://vercel.com/api/blob").respond(
            json={
                "url": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4",
                "downloadUrl": "https://teststore.private.blob.vercel-storage.com/uploads/abc.mp4?download=1",
                "pathname": "uploads/abc.mp4",
                "contentType": "video/mp4",
                "contentDisposition": 'attachment; filename="abc.mp4"',
            },
        )
        respx_mock.post("https://vercel.com/api/blob/delete").respond(200)
        respx_mock.get("https://vercel.com/api/blob").respond(
            json={"size": 1024, "uploadedAt": "2026-04-29T00:00:00Z",
                  "pathname": "uploads/abc.mp4", "contentType": "video/mp4",
                  "contentDisposition": "", "url": "...", "downloadUrl": "...",
                  "cacheControl": "public, max-age=2592000"},
        )
    import importlib
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)
    yield backend
```

Cross-product with `metadata_backend` is automatic when a test consumes both fixtures (D-21 2x2 matrix = 4 cells).

Implements: BLOB-06 verification (rollback path tested), test infra for BLOB-01..04.
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/conftest.py --collect-only 2>&1 | tail -10</automated>
  </verify>
  <done>Pytest collects without error. `storage_backend` shows up in fixture list. Tests using both fixtures show 4 cells.</done>
</task>

### Task 4.2: Add OFFLINE_DEMO firewall test

<task type="auto">
  <name>Task 4.2: Test that OFFLINE_DEMO=true never opens Blob HTTP traffic</name>
  <files>backend/tests/test_offline_demo_firewall.py</files>
  <action>
Create a new test that boots the FastAPI app under `OFFLINE_DEMO=true STORAGE_BACKEND=blob` and asserts:
  1. `/media` route IS registered (D-16 fallback).
  2. `backend.storage.save_clip_bytes.__module__ == "backend.storage.local"` (D-18 hard-override).
  3. No httpx PUT/POST/GET to `vercel.com/api/blob` or `*.vercel-storage.com` was issued during lifespan startup.

Test:

```
import importlib
import pytest
import respx
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_offline_demo_firewall_no_blob_calls(monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("STORAGE_BACKEND", "blob")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "")  # also empty — would normally fail-loud
    import backend.config
    import backend.storage
    importlib.reload(backend.config)
    importlib.reload(backend.storage)

    # Sanity: dispatcher resolved to local even with STORAGE_BACKEND=blob.
    assert backend.storage.save_clip_bytes.__module__ == "backend.storage.local"

    with respx.mock(base_url="https://vercel.com") as router, \
         respx.mock(base_url="https://teststore.private.blob.vercel-storage.com") as router2:
        import backend.app
        importlib.reload(backend.app)
        transport = ASGITransport(app=backend.app.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/health")
            assert r.status_code == 200
        assert router.call_count == 0, f"Blob API was called under OFFLINE_DEMO=true: {router.calls}"
        assert router2.call_count == 0, f"Blob storage was called under OFFLINE_DEMO=true: {router2.calls}"

    # /media mount IS registered.
    paths = [r.path for r in backend.app.app.routes if hasattr(r, "path")]
    assert any(p.startswith("/media") for p in paths), "/media mount missing under OFFLINE_DEMO=true"
```

Implements: T-10-05 mitigation (firewall verified); BLOB-06 partial (OFFLINE_DEMO interaction); supports Phase 13 DEMO-02.
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/test_offline_demo_firewall.py -x --tb=short</automated>
  </verify>
  <done>Test passes. Zero Blob HTTP calls during startup under OFFLINE_DEMO=true. /media mount present.</done>
</task>

### Task 4.3: Storage dispatcher unit tests

<task type="auto">
  <name>Task 4.3: Unit tests for dispatcher selection and parity</name>
  <files>backend/tests/test_storage_dispatcher.py</files>
  <action>
Add four small tests:

  1. **test_dispatcher_local_default**: with STORAGE_BACKEND unset, `storage.save_clip_bytes.__module__ == 'backend.storage.local'`.
  2. **test_dispatcher_blob_when_set**: with STORAGE_BACKEND=blob + OFFLINE_DEMO=false + BLOB_READ_WRITE_TOKEN set, dispatcher selects blob.
  3. **test_dispatcher_offline_demo_overrides**: with STORAGE_BACKEND=blob + OFFLINE_DEMO=true, dispatcher selects local.
  4. **test_local_blob_signature_parity**: assert `set(local.__all__) == set(blob.__all__)` and that each function in both modules has the same kind (sync vs async) and parameter count (use `inspect.signature` and `inspect.iscoroutinefunction`).

Use `monkeypatch.setenv` + `importlib.reload(backend.config); importlib.reload(backend.storage)` (mirror Phase 9 fixture pattern at lines 31-39).

Implements: BLOB-06 verification (flag works), D-12 parity guard.
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/test_storage_dispatcher.py -x --tb=short</automated>
  </verify>
  <done>All four assertions pass.</done>
</task>

### Task 4.4: blob_client unit tests

<task type="auto">
  <name>Task 4.4: blob_client httpx mock tests</name>
  <files>backend/tests/test_blob_client.py</files>
  <action>
Use `respx_mock` fixture (Pitfall 5) to test the wrapper without real network. Cases:

  1. **test_init_fails_loud_on_empty_token**: With BLOB_READ_WRITE_TOKEN unset, `await blob_client.init_client()` raises RuntimeError matching the D-19 message ("BLOB_READ_WRITE_TOKEN is empty but STORAGE_BACKEND=blob...").
  2. **test_init_fails_on_malformed_token**: With BLOB_READ_WRITE_TOKEN="garbage_no_underscores", init_client raises (A3 mitigation).
  3. **test_upload_happy_path**: respx_mock returns 200 on PUT to `https://vercel.com/api/blob`, `await upload(pathname='uploads/x.mp4', body=b'data', content_type='video/mp4', access='private')` returns the parsed BlobObject.
  4. **test_upload_includes_required_headers**: assert that the PUT request had `Authorization: Bearer ...`, `x-api-version: 11`, `x-vercel-blob-access: private`, `x-allow-overwrite: 1` (amendment 5).
  5. **test_delete_idempotent_on_404**: respx_mock returns 404 on POST to `/api/blob/delete`, `await delete(pathname='uploads/missing.mp4')` does NOT raise.
  6. **test_5xx_retries_three_times**: respx_mock returns 500 three times then 200 → upload succeeds. Returns 500 four times → raises (D-24).
  7. **test_429_retries**: respx_mock returns 429 with Retry-After header twice then 200 → succeeds (amendment 6).
  8. **test_no_token_in_logs**: capture log records during a successful upload; assert the bearer string never appears in any record's message (T-10-01 mitigation).

Implements: T-10-01, T-10-04 mitigation tests; BLOB-01/02/08 happy paths.
  </action>
  <verify>
    <automated>cd backend && python -m pytest tests/test_blob_client.py -x --tb=short</automated>
  </verify>
  <done>All 8 tests pass. The token-leak test (case 8) explicitly fails if the token string `vercel_blob_rw_TESTSTORE` appears in any log record.</done>
</task>

---

## Wave 5 — Frontend audit and docs

**Wave dependencies:** Waves 2-3 (backend now returns absolute URLs).

### Task 5.1: Audit + guard frontend api.ts double-prefix

<task type="auto">
  <name>Task 5.1: Add absolute-URL guard in frontend/src/api.ts</name>
  <files>frontend/src/api.ts</files>
  <action>
Per RESEARCH section 13 Pitfall 6, add a one-line `_abs` helper that guards `${API_BASE}${...}` from double-prefixing absolute URLs.

Read the current file lines 27-33 first to find the exact construction. Add helper above the response transform:

```
const _abs = (u: string | null | undefined): string | null =>
  u == null ? null : (u.startsWith("http") ? u : `${API_BASE}${u}`);
```

Replace any inline `${API_BASE}${s.video_url}` with `_abs(s.video_url)` and any `s.video_urls?.map(...)` mapping with `s.video_urls?.map(_abs) ?? null`. Apply the same guard to clip `s.url` if present.

Implements: BLOB-05 frontend half (renders absolute Blob URLs without double-prefix).
  </action>
  <verify>
    <automated>cd frontend && grep -E "_abs|startsWith\(\"http\"\)" src/api.ts | wc -l</automated>
  </verify>
  <done>grep returns 2 or more (helper + guard). `npm run build` succeeds.</done>
</task>

### Task 5.2: Update types.ts doc-strings

<task type="auto">
  <name>Task 5.2: Document absolute-URL possibility in types.ts</name>
  <files>frontend/src/types.ts</files>
  <action>
Update the JSDoc on `Clip.url` (line ~7-9) and `Segment.video_url` (line ~69-72) to acknowledge absolute Blob URLs. Type stays `string | null`. Suggested copy:

```
/**
 * Absolute Vercel Blob URL (e.g. https://...vercel-storage.com/runs/abc.mp4)
 * when STORAGE_BACKEND=blob, or relative `/media/...` path under
 * STORAGE_BACKEND=local rollback. Frontend renders directly via the _abs()
 * helper in api.ts.
 */
```

Apply identical comment block to both fields. Do NOT change the type.

Implements: doc/test alignment with BLOB-05.
  </action>
  <verify>
    <automated>cd frontend && grep -E "vercel-storage\.com|/media/" src/types.ts | wc -l</automated>
  </verify>
  <done>grep returns 2 or more (one match per docstring). `npm run build` succeeds.</done>
</task>

### Task 5.3: Add absolute-URL fixture to SegmentCard.test.tsx

<task type="auto">
  <name>Task 5.3: SegmentCard test renders both URL shapes</name>
  <files>frontend/src/components/SegmentCard.test.tsx</files>
  <action>
Add a parallel `blobSegment` fixture (mirror PATTERNS line 354-374) with absolute Blob URL. Run the existing render test once with `segment` and once with `blobSegment`. Assert in both cases that the `<video>` element's `src` attribute matches what was passed in (no double-prefix).

```
const blobSegment: Segment & { url: string | null } = {
  ...segment,
  video_url: "https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4",
  video_urls: ["https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4"],
  url: "https://teststore.public.blob.vercel-storage.com/runs/seg-1.mp4",
};

it.each([segment, blobSegment])("renders without double-prefix", (s) => {
  // ... existing render assertions, parameterized
});
```

Implements: BLOB-05 frontend regression guard.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- src/components/SegmentCard.test.tsx --run 2>&1 | tail -20</automated>
  </verify>
  <done>Both fixture cells pass. No double-prefix in rendered DOM.</done>
</task>

### Task 5.4: Frontend api.ts unit test for _abs guard

<task type="auto">
  <name>Task 5.4: api.ts double-prefix unit test</name>
  <files>frontend/src/api.test.ts</files>
  <action>
Create a small unit test to lock in the `_abs` guard behavior. Cases:

  1. `_abs("/media/x.mp4")` returns `${API_BASE}/media/x.mp4`.
  2. `_abs("https://store.public.blob.vercel-storage.com/runs/x.mp4")` returns the same string unchanged.
  3. `_abs(null)` returns `null`.
  4. `_abs(undefined)` returns `null`.

Export `_abs` from `api.ts` (or extract into a small helper module if preferred) so the test can import it. If extraction is preferred, create `frontend/src/_url.ts` with the helper and re-import in `api.ts`.

Implements: BLOB-05 unit-level regression guard.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- src/api.test.ts --run 2>&1 | tail -10</automated>
  </verify>
  <done>All 4 cases pass.</done>
</task>

### Task 5.5: Manual moderation-block hook smoke

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 5.5: Verify cleanup_blocked_clip works end-to-end (manual)</name>
  <what-built>cleanup_blocked_clip(clip_id) — Phase 11 will call this. Phase 10 verifies the storage hook works in isolation.</what-built>
  <how-to-verify>
1. With STORAGE_BACKEND=blob and the backend running locally:
   ```
   curl -X POST http://localhost:8000/clips -F file=@backend/seed/demo/sample.mp4 -F lat=34.14 -F lng=-118.13 -F ts=$(date +%s)
   ```
2. Note the returned `clip_id`. Confirm in Vercel Blob console (Storage, Browse) that `uploads/{clip_id}.mp4` exists.
3. Invoke the cleanup hook directly via a Python shell inside the backend venv:
   ```
   python -c "import asyncio; from backend.storage import cleanup_blocked_clip; asyncio.run(cleanup_blocked_clip('<clip_id>'))"
   ```
4. Refresh the Vercel Blob console — the object should be gone within a few seconds.
5. Run the same command a second time (idempotency) — should NOT raise.
  </how-to-verify>
  <resume-signal>Type "cleanup verified" to proceed.</resume-signal>
</task>

---

## Wave 6 — Seed script and cutover doc

**Wave dependencies:** Waves 1-3 (storage works end-to-end).

### Task 6.1: Ship seed_demo_to_blob.py

<task type="auto">
  <name>Task 6.1: Ship backend/scripts/seed_demo_to_blob.py</name>
  <files>backend/scripts/seed_demo_to_blob.py</files>
  <action>
Per amendment 7 (D-15 supplement). ~30 LOC. Mirror docstring shape of `backend/scripts/sqlite_to_postgres.py:1-60` (Usage, Pre-requisites, Idempotency, Security sections).

Behavior:
  - Walks `backend/seed/demo/*.mp4`.
  - For each file, POSTs to `http://localhost:8000/clips` (or `BACKEND_URL` env var) with stub `lat=34.14`, `lng=-118.13`, `ts=time.time()` and `Content-Type: multipart/form-data` containing the file bytes.
  - Reads the X-Admin-Token from `ADMIN_TOKEN` env var (NOT argparse — secrets discipline mirror).
  - `--reset` flag: pre-call `POST /admin/reset?mode=all` (idempotent helper) before seeding.
  - Idempotency: if `/clips` returns a 4xx, log and continue; do not crash.
  - Logging: structured kwargs (path, clip_id, latency_ms).
  - Invocation: `python -m backend.scripts.seed_demo_to_blob [--reset]`.

Exact skeleton:

```
"""Phase 10: re-seed demo corpus through POST /clips.

Usage:
    BACKEND_URL=http://localhost:8000 ADMIN_TOKEN=... \
        python -m backend.scripts.seed_demo_to_blob [--reset]

Pre-requisites:
    - Backend running with STORAGE_BACKEND=blob and BLOB_READ_WRITE_TOKEN set.
    - backend/seed/demo/*.mp4 fixtures present.

Idempotency: --reset flag wipes via POST /admin/reset before seeding. Without
--reset, re-running creates duplicate rows (clip_id is uuid; harmless for demo).

Security: ADMIN_TOKEN read from environment, NEVER from argparse (mirror
sqlite_to_postgres.py:16-17 — avoids shell-history capture).
"""
import argparse
import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
DEMO_DIR = Path(__file__).resolve().parent.parent / "seed" / "demo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="POST /admin/reset before seeding")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with httpx.Client(timeout=60.0) as client:
        if args.reset:
            r = client.post(
                f"{BACKEND_URL}/admin/reset",
                params={"mode": "all"},
                headers={"X-Admin-Token": ADMIN_TOKEN},
            )
            log.info("reset status=%s body=%s", r.status_code, r.text[:200])

        for mp4 in sorted(DEMO_DIR.glob("*.mp4")):
            t0 = time.monotonic()
            with mp4.open("rb") as fh:
                r = client.post(
                    f"{BACKEND_URL}/clips",
                    files={"file": (mp4.name, fh, "video/mp4")},
                    data={"lat": "34.14", "lng": "-118.13", "ts": str(time.time())},
                )
            ms = int((time.monotonic() - t0) * 1000)
            log.info("seed path=%s status=%s latency_ms=%d body=%s", mp4.name, r.status_code, ms, r.text[:120])


if __name__ == "__main__":
    main()
```

Implements: amendment 7 (re-seed after demo reset).
  </action>
  <verify>
    <automated>cd backend && python -c "import scripts.seed_demo_to_blob as s; assert callable(s.main); print('ok')"</automated>
  </verify>
  <done>Module imports cleanly. With backend running locally and ADMIN_TOKEN set, `python -m backend.scripts.seed_demo_to_blob --reset` POSTs every fixture in `backend/seed/demo/` and prints 202 status codes.</done>
</task>

---

## Verification

Each subsection corresponds to one ROADMAP success criterion (1 through 6). Executor runs these to prove the phase ships.

### SC-1: Backend redeploys to Railway and existing clip media still plays from the feed (BLOB-05, BLOB-07)

  - Manual: trigger a Railway redeploy with `STORAGE_BACKEND=blob` set. After deploy completes, load the production frontend URL and confirm at least one segment plays in the feed without 404s in DevTools network.
  - Automated: `pytest backend/tests/test_offline_demo_firewall.py -x` passes (proves /media mount conditional logic is correct).

### SC-2: New clip lands in Vercel Blob under uploads/{clip_id}.{ext} (BLOB-01)

  - Manual: from iOS Safari PWA, record + upload a clip. Note the clip_id. Open Vercel Dashboard, Storage, (Blob store), Browse — confirm `uploads/{clip_id}.mp4` exists.
  - Automated: with the storage_backend=blob fixture, `pytest backend/tests/ -k "test_insert_clip and blob"` passes (the fixture's respx mock catches the PUT and the test asserts the row's blob_url column matches the mocked URL).

### SC-3: Compiled run segments under runs/{run_id}.mp4; frontend renders absolute URLs (BLOB-02, BLOB-05)

  - Manual: trigger a recompile via `POST /debug/compile/{cluster_id}` for a cluster that has ≥2 distinct parents. Confirm `runs/{run_id}.mp4` appears in Blob console. Refresh the feed — the segment plays from the absolute URL (verify in DevTools network: request URL starts with `https://*.public.blob.vercel-storage.com/runs/`).
  - Automated: `pytest backend/tests/ -k "test_stitch_runs and blob"` (any test that exercises `_stitch_segment_runs` under blob mode) passes.

### SC-4: Direct browser PUT to Vercel Blob is rejected (L-02, T-10-02)

  - Manual: from the browser DevTools console, attempt:
    ```
    fetch("https://teststore.private.blob.vercel-storage.com/uploads/test.mp4", { method: "PUT", body: new Blob(["test"]) })
    ```
    Confirm the response is 401 or 403. (No bearer token is present in the request.)
  - Automated: `pytest backend/tests/test_blob_client.py::test_init_fails_loud_on_empty_token` proves the server-side guard.

### SC-5: After moderation block, Blob object is hard-deleted (BLOB-08)

  - Manual: Wave 5.5 checkpoint above (cleanup_blocked_clip end-to-end smoke).
  - Automated: `pytest backend/tests/test_blob_client.py::test_delete_idempotent_on_404` proves idempotency. Phase 11 will add the integration test that wires moderation_status='blocked' → cleanup_blocked_clip.

### SC-6: Setting STORAGE_BACKEND=local rolls back without code changes (BLOB-06)

  - Manual: in a local terminal, run `STORAGE_BACKEND=local OFFLINE_DEMO=false python -m uvicorn backend.app:app`. Upload a clip via curl. Confirm it lands in `backend/data/clips/`. Confirm `/media/{clip_id}.mp4` is served by the StaticFiles mount.
  - Automated: `pytest backend/tests/test_storage_dispatcher.py::test_dispatcher_local_default` passes; `pytest backend/tests/ -k "test_insert_clip and local"` passes.

### Cross-cutting verifications

  - **Phase 8 D-12 middleware order preserved:** `grep -nE "add_middleware|app.mount" backend/app.py` — order must still be MetricsMiddleware, then RequestIDAndContextvarsBind, then XFFStrip; /media mount sits AFTER all middleware adds.
  - **No new PII in log lines (T-10-01):** `pytest backend/tests/test_blob_client.py::test_no_token_in_logs` passes.
  - **OFFLINE_DEMO firewall (T-10-05):** `pytest backend/tests/test_offline_demo_firewall.py` passes.
  - **2x2 fixture matrix (D-21):** `pytest backend/tests/ -v --collect-only | grep "\\[" | wc -l` shows 4-cell parametrization for tests using both fixtures.
  - **Schema confirmation:** `grep -n "blob_url\|is_hidden" backend/migrations/versions/20260428_0001_initial_v1_1_schema.py` — both columns exist; NO new migration file added in Phase 10.

<success_criteria>
- All six SC subsections pass (manual + automated as listed).
- Cross-cutting verifications pass.
- All 8 BLOB-01..08 requirement IDs are exercised by at least one task or test.
- The 5 STRIDE threats (T-10-01..05) have their mitigations either implemented or unit-tested.
- `git diff --stat` shows no SQLAlchemy imports added; no `pgvector`, no `Pinecone`, no Redis.
- The Wave 5.5 manual cleanup_blocked_clip smoke succeeded (or the executor has flagged a blocker for the user).
</success_criteria>

<output>
After all waves complete, create `.planning/phases/10-vercel-blob-migration/10-01-SUMMARY.md` per the GSD summary template, including:
  - Files modified (count + list)
  - Each BLOB-01..08 requirement: status (Done / Deferred / Blocked) with the specific test or manual step that proved it
  - All 5 amendments confirmed implemented
  - Threat-model dispositions actually shipped vs. planned
  - Next-phase handoff: confirm `cleanup_blocked_clip` is callable from `backend.storage` for Phase 11.
</output>
</content>

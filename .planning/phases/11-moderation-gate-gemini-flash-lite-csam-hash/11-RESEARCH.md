# Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash) - Research

**Researched:** 2026-04-29
**Domain:** Pre-publish video moderation gate (CSAM hash + Gemini Flash-Lite content classifier)
**Confidence:** HIGH on Gemini SDK contract, asyncio cancellation, NCMEC retention, schema migration. **MEDIUM** on Gemini Flash-Lite video-input p99 latency (variability is documented but not benchmarked on our exact corpus). **LOW-confidence-but-important: the CSAM provider assumption in CONTEXT.md does not match what Cloudflare's tool actually does.** This is the most consequential finding in this document — see the "Cloudflare CSAM Scanning Tool" section below for full detail and the "Open Questions for Planner" section for the decision the user owes before plan execution.

## Summary

1. **Cloudflare CSAM Scanning Tool is NOT a programmatic REST API and does not support video.** [VERIFIED: Cloudflare developer docs] It is a Cloudflare-cache-passive feature that scans **images cached by Cloudflare's CDN** using fuzzy hashing, fires asynchronous email notifications to the site owner, and **does not accept arbitrary POST-a-hash queries**. The customer files NCMEC reports themselves; Cloudflare does not report on the customer's behalf. [VERIFIED: blog.cloudflare.com/a-simpler-path-to-a-safer-internet] Newz uses Vercel Blob (not Cloudflare CDN) and uploads videos (not images). **The CONTEXT.md L-02 + D-17/D-20 assumption that we POST a hash to a Cloudflare CSAM API is invalid.** The `CSAM_PROVIDER=stub` fallback (D-18) is therefore the only viable Phase 11 ship path; the `cloudflare` arm of the dispatcher should be replaced with either a deferred provider choice (Thorn Safer, PhotoDNA Cloud Service, Hive) or removed pending user direction.

2. **NCMEC CyberTipline retention is 1 year per the 2024 REPORT Act** (D-19 confirmed). [VERIFIED: 18 U.S.C. § 2258A] Reports are filed via authenticated POSTs to `https://report.cybertip.org/ispws` (production) or `https://exttest.cybertip.org/ispws` (test). The provider files its own reports — there is no reasonable way Cloudflare's tool could file on Newz's behalf because Cloudflare's tool isn't in our hot path.

3. **Gemini 2.5 Flash-Lite via `google-genai` follows the exact same upload-poll-generate pattern as `caption_pipeline.py:424-479`.** [VERIFIED: googleapis/python-genai docs + caption_pipeline.py reading] TTFT is ~0.58s (text); video inference variance is high (10-15s typical for 7s 720p MP4 on Flash, with 4× spikes to 60s+ documented). Flash-Lite is faster than Flash on text but **video-input latency on Flash-Lite is unbenchmarked publicly** for our corpus shape. The cancel-when-embed-finishes design (D-03) is workable IF Flash-Lite p50 < Marengo p50; if not, the gate fails-CLOSED routinely. **The STATE.md pre-flight latency benchmark TODO is therefore load-bearing — it is not optional, it is the primary risk the plan must de-risk before merge.**

4. **The validation architecture must combine respx (already in stack from Phase 10 conftest) for HTTP mocking with pytest-asyncio for the cancel-when-embed-finishes test.** Recorded-tape via VCR.py is overkill for our two-call surface (Gemini Files API + Gemini generate_content). respx fixtures can deterministically simulate timeout / 5xx / 4xx / network-error per the D-05 typed-exception classifier without ever hitting real APIs.

5. **Schema migration is mechanically simple** (ALTER ADD COLUMN + CREATE UNIQUE INDEX, mirroring Phase 9's pattern). [VERIFIED: backend/migrations/versions/*] The merge-heads pattern (`20260429_0003_merge_comments_blob.py`) means Phase 11's new revision must descend from `0003_merge_comments_blob` (the current head), not from `0001_initial_v1_1_schema`. The planner should name it `20260430_0004_moderation_columns.py` or similar.

**Primary recommendation:** Ship `CSAM_PROVIDER=stub` as the Phase 11 default and the only validated arm. Defer the `cloudflare` arm to a separate Phase 11.5 (or fold it into Phase 12 admin queue) where the user can pick a real CSAM-detection vendor — Thorn Safer Match (paid, video-capable) or PhotoDNA Cloud Service (free for qualified orgs, image-only with video-keyframe-extraction recipe) are the realistic options. Treat the Cloudflare reference in CONTEXT.md L-02 / STATE.md as a misnomer to be reconciled before planning. Ship the lifespan production-guard (D-18) as the single most important runtime safety net.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pre-publish CSAM hash check | API / Backend | — | Statutory; runs before bytes flow into AI inference. Owns reported_csam writes. |
| Pre-publish content classification | API / Backend | — | Mirrors caption_pipeline.py — runs server-side, never client-side, to keep the policy trust boundary owned by the server. |
| Content classifier source-byte fetch | API / Backend (Vercel Blob) | — | Phase 10 D-08 signed-URL ingest pattern. Bytes never enter browser. |
| Hard-block cleanup (delete blob + hide row) | API / Backend | Storage (Phase 10 hook) | cleanup_blocked_clip is a Phase 10 hook; Phase 11 is the caller. |
| Soft-flag interstitial UI (tap-to-view) | Browser / Client | — | Roan's surface (feature-track #6); backend ships the boolean only. |
| Admin queue for `decision='unknown'` rows | API / Backend (Phase 12) | — | Phase 11 surfaces; Phase 12 provides the GET/POST endpoints. |
| `_resume_pipeline(clip_id)` | API / Backend (Phase 11 exposes) | API / Backend (Phase 12 calls) | Function lives in Phase 11; admin endpoint in Phase 12. |

## User Constraints (from CONTEXT.md)

### Locked Decisions

CONTEXT.md `<decisions>` D-01..D-29 — gate at `run_pipeline:79`; CSAM-first sequential; `asyncio.wait` + `FIRST_COMPLETED` then `.cancel()` on pending; typed-exception tier classification (TimeoutError + 4xx → blocked, 5xx + network → unknown); per-provider rows in `moderation_decisions` with UNIQUE(clip_id, provider); fixed Gemini taxonomy `['csam', 'sexual', 'hate', 'extremist', 'violence', 'self_harm']`; hard-block: csam/sexual/extremist/self_harm; soft-flag: hate/violence; CSAM 1-year retention per 2024 REPORT Act; `CSAM_PROVIDER=stub` default with lifespan production-guard; `OFFLINE_DEMO=true` skips all external calls; full redacted `raw_response` JSONB in audit rows; `STAGE_DURATION` label `stage="moderate"` permitted; `--workers 1` + asyncpg pool max_size=10 unchanged; new env vars `CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY`, `GEMINI_MODERATION_MODEL`, `MODERATION_MAX_BUDGET_S`; module location `backend/pipeline/moderate.py`; httpx CSAM client lifespan-singleton with tenacity retry; `MODERATION_PROVIDER` parametrize in conftest.

### Claude's Discretion (planner-owned per CONTEXT.md)

- D-14: `segments.soft_flag` column placement (recommend column over derived; this research confirms — denormalize for cheap feed-read).
- `_resume_pipeline` ownership (recommend Phase 11 exposes function, Phase 12 ships endpoint).
- D-deferred: Absolute Gemini timeout cap (recommend `MODERATION_MAX_BUDGET_S=20` default per industry-typical Flash-Lite 95th-pctile video latency; see Gemini section).
- D-deferred: CSAM API timeout (recommend 5s; moot under stub but locks the contract).
- NCMEC `report_id` column on `reported_csam` — see NCMEC section: **add it now**, not later.

### Deferred Ideas (OUT OF SCOPE)

CONTEXT.md `<deferred>` is exhaustive. Verbatim items: aggressive "is this local news" prompt; pre-ingest sync gate; adversarial-probing detection; auto-takedown by report count; per-IP rate limit on /clips; per-admin login; background sweeper for orphan blob cleanup; soft-flag richer schema (boolean only this phase). Verifications owed (this research discharges items D-17, D-19, D-20, D-29 partially — see Open Questions for the residual).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MOD-01 | Gate runs on every clip before cluster/compile | `run_pipeline:79` insertion; `await moderate_clip(clip_id)` precedes embed/cluster (sequence in D-01/D-02 section below). |
| MOD-02 | Gemini classifier in parallel with Marengo via asyncio.gather + asyncio.wait | Validated asyncio.wait FIRST_COMPLETED + cancel pattern. See "asyncio.wait FIRST_COMPLETED" section. |
| MOD-03 | Common-case latency does not regress vs v1.0 baseline | Cancel-when-embed-finishes uses Marengo elapsed time as Gemini's effective ceiling. Risk: only valid if Flash-Lite p50 < Marengo p50 on actual video. **Pre-flight benchmark required.** |
| MOD-04 | Cloudflare CSAM hash check on every clip; fail-CLOSED on any error | **Cloudflare CSAM Scanning Tool does not support this use case.** Phase 11 ships stub provider; the CSAM-arm dispatcher selects future vendor. Lifespan production-guard prevents accidental prod deploy with stub. |
| MOD-05 | Tiered failure policy: timeout → blocked, 5xx → unknown | D-05 typed-exception pattern. respx fixtures can deterministically inject each failure mode. |
| MOD-06 | Every decision recorded in moderation_decisions audit table | Schema ALTER per D-13. UNIQUE(clip_id, provider) for idempotency on retry. |
| MOD-07 | Soft-flag for hate/violence (broadened per D-08, no corroboration gating) | `segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE` ALTER + compile-time write. **REQUIREMENTS.md MOD-07 amendment owed (Liam todo).** |
| MOD-08 | Feed UI tap-to-view interstitial | Backend ships `soft_flag: boolean` in `/feed` JSON. Roan owns the UI. |
| MOD-10 | OFFLINE_DEMO=true bypasses every external moderation API | Mirror Phase 9 D-11 + Phase 10 D-18 pattern. CSAM client + Gemini client both gated on `not config.OFFLINE_DEMO`. |
| PRIV-03 | Strip GPS, session_uuid, timestamp from outbound classifier calls | Classifier upload sends only the video bytes; no metadata payload. Verify by inspecting recorded outbound payload in test (validation architecture section). |

## Project Constraints (from CLAUDE.md)

- **Anonymity is load-bearing.** No accounts, no display names. Server-side session_uuid for rate limiting only; PRIV-03 enforces strip from classifier calls.
- **iOS Safari is the primary surface.** Gate runs server-side, no iOS-specific concerns for moderation itself, but the soft-flag interstitial UI must work on iOS Safari (Roan's domain).
- **Single-process FastAPI monolith, `--workers 1`.** Process-singleton httpx client for any future CSAM provider; mirror Phase 10 blob_client.py.
- **OFFLINE_DEMO=true serves cached responses.** Module-import-time dispatcher selection (mirror Phase 9 D-08 / Phase 10 D-13).
- **Compile pipeline LLM budget: 300s.** Moderation gate is upstream of compile; moderation budget is separate (`MODERATION_MAX_BUDGET_S` recommended 20s).
- **Pre-warm Marengo on backend startup.** No new pre-warm for moderation — Gemini Flash-Lite TTFT is fast enough that cold-start mitigation isn't required.

## Standard Stack

### Core (already in requirements.txt — no new pins)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | >=1.73.0 | Gemini Flash-Lite classifier client | Already used by caption_pipeline.py; same SDK + same upload-poll-generate flow [VERIFIED: backend/requirements.txt + caption_pipeline.py:424-479] |
| httpx | 0.28.1 | (Future) CSAM provider HTTP client | Already used by Phase 10 blob_client.py; Phase 11's CSAM client mirrors that pattern [VERIFIED: backend/storage/blob_client.py] |
| tenacity | 9.1.4 | Retry decorator on transient 5xx | Already wraps Phase 10 blob_client; Phase 11 reuses [VERIFIED: backend/storage/blob_client.py:147-152] |
| pytest-asyncio | >=0.23 | Async test support | Already in requirements-dev [VERIFIED: backend/requirements.txt] |
| respx | (latest, used in conftest) | httpx mock | Already used by Phase 10 conftest fixture for STORAGE_BACKEND parametrize [VERIFIED: backend/tests/conftest.py:69-109] |

### Supporting (no new dependencies)
| Library | Purpose | When to Use |
|---------|---------|-------------|
| asyncio (stdlib) | `wait()` + `FIRST_COMPLETED` + `.cancel()` | Cancel-when-embed-finishes (D-02 step 4) |
| structlog | Structured INFO log per gate stage | Mirror Phase 8 D-08 contextvars pattern |
| asyncpg (via db_postgres.py) | moderation_decisions writes | Phase 9 D-16 single pool max_size=10 |

### Alternatives Considered (do NOT use)
| Instead of | Could Use | Why Rejected |
|------------|-----------|--------------|
| respx fixtures | VCR.py / pytest-recording | Two-endpoint surface (Files.upload + models.generate_content) doesn't justify the cassette-management overhead. respx is already in conftest. |
| `asyncio.gather(return_exceptions=True)` for the parallel arm | TaskGroup (Python 3.11+) | TaskGroup is cleaner but the project's Python 3.11 baseline is borderline; sticking to `asyncio.wait` keeps parity with caption_pipeline.py and avoids pulling a structural change into a moderation phase. |
| `asyncio.wait_for` per task | Per-task timeout via `asyncio.wait_for` | MOD-02 in REQUIREMENTS.md literally specifies this, but D-03 supersedes: cancel-when-embed-finishes uses Marengo's elapsed time as the bound; an inner `asyncio.wait_for` is redundant when `MAX_BUDGET` is enforced via the outer wait. Keep one timer. |

**No new pins:**

```bash
# No new dependencies needed — all stack components already in requirements.txt
```

**Version verification (live as of 2026-04-29):**

| Package | Pinned in requirements.txt | Verified current |
|---------|----------------------------|------------------|
| google-genai | >=1.73.0 | [CITED: pypi.org/project/google-genai] still actively maintained; 2.x branch exists but 1.x supports gemini-2.5-flash-lite per [CITED: developers.googleblog.com — Flash-Lite GA July 2025] |
| httpx | 0.28.1 | [VERIFIED: requirements.txt] Phase 10 already on this; 0.28 supports `stream=True` async streaming used by runs proxy |
| tenacity | 9.1.4 | [VERIFIED: requirements.txt] Phase 10 D-24 |

## Architecture Patterns

### System Architecture Diagram

```
POST /clips (browser)
    │
    │ 202 fire-and-forget
    ▼
asyncio.create_task(run_pipeline(clip_id))
    │
    ▼
┌───────────────────────────────────────────────────────────┐
│  run_pipeline (backend/pipeline/run.py)                   │
│                                                            │
│  STAGE_DURATION(stage="moderate").time():                 │
│    ┌──────────────────────────────────────────────────┐   │
│    │  moderate_clip(clip_id)                          │   │
│    │  (backend/pipeline/moderate.py — NEW)            │   │
│    │                                                   │   │
│    │  1. fetch source bytes from uploads/ (Phase 10)  │   │
│    │     authorized_blob_input + httpx stream         │   │
│    │     ─→ tempfile                                   │   │
│    │                                                   │   │
│    │  2. SHA-256 hash (or vendor-required hash)       │   │
│    │                                                   │   │
│    │  3. SEQUENTIAL: csam_check(clip_id, hash)         │   │
│    │     ┌──────────────────────────┐                 │   │
│    │     │ stub:    return {match:F}│                 │   │
│    │     │ vendor:  POST hash → API │                 │   │
│    │     └──────────────────────────┘                 │   │
│    │       │                                           │   │
│    │       ├─ HIT  → write reported_csam (1yr)        │   │
│    │       │        write moderation_decisions       │   │
│    │       │        provider='cloudflare_csam'       │   │
│    │       │        decision='blocked'               │   │
│    │       │        cleanup_blocked_clip(clip_id)    │   │
│    │       │        return — embed never starts      │   │
│    │       │                                           │   │
│    │       └─ MISS → continue                         │   │
│    │                                                   │   │
│    │  4. PARALLEL:                                     │   │
│    │     embed_task   = asyncio.create_task(embed)   │   │
│    │     gemini_task  = asyncio.create_task(classify)│   │
│    │                                                   │   │
│    │  5. asyncio.wait({embed_task, gemini_task},      │   │
│    │                   return_when=FIRST_COMPLETED)   │   │
│    │                                                   │   │
│    │     ┌─ embed first → cancel gemini → TimeoutError│  │
│    │     │                                            │   │
│    │     └─ gemini first → await embed → route       │   │
│    │                                                   │   │
│    │  6. classify exception tier (D-05):              │   │
│    │     ┌──────────────────────────────────────┐    │   │
│    │     │ TimeoutError    → blocked            │    │   │
│    │     │ HTTP 4xx        → blocked            │    │   │
│    │     │ HTTP 5xx        → unknown            │    │   │
│    │     │ ConnectError    → unknown            │    │   │
│    │     │ pass            → write 'passed'     │    │   │
│    │     │ hard-block cat  → 'blocked'+cleanup  │    │   │
│    │     │ soft-flag cat   → 'passed'+soft_flag │    │   │
│    │     └──────────────────────────────────────┘    │   │
│    │                                                   │   │
│    │  7. write moderation_decisions row(s)            │   │
│    └──────────────────────────────────────────────────┘   │
│                                                            │
│  if decision in {'blocked', 'unknown'}:                   │
│      return  # short-circuit; cluster/compile skipped     │
│  else:                                                     │
│      cluster_worker(...) → compile_segment(...)            │
└───────────────────────────────────────────────────────────┘
```

| Component | File | Responsibility |
|-----------|------|----------------|
| Gate orchestrator | `backend/pipeline/run.py` | Wraps `moderate_clip` in `STAGE_DURATION(stage="moderate")`; routes on aggregate decision |
| Moderation entry | `backend/pipeline/moderate.py` (new) | `moderate_clip(clip_id) -> ModerationResult`; orchestrates CSAM-first then parallel embed+gemini |
| CSAM provider dispatcher | `backend/pipeline/moderate.py` (same module per D-22) | Module-import-time selector: stub vs vendor |
| Gemini classifier | `backend/pipeline/moderate.py` | Mirror caption_pipeline.py:424-479 — upload → poll ACTIVE → generate_content with response_schema |
| DB writes | `backend/db_postgres.py` + `backend/db_sqlite.py` | `write_moderation_decision`, `write_reported_csam`, `set_clip_hidden`, `aggregate_verdict` |
| Cleanup hook caller | `backend/pipeline/moderate.py` | Imports `from ..storage import cleanup_blocked_clip` (Phase 10 D-20) |
| Lifespan production-guard | `backend/app.py:lifespan()` | Refuses startup when `CSAM_PROVIDER=stub` AND prod env AND not `CSAM_STUB_ALLOW_PRODUCTION=true` |

### Recommended Project Structure

```
backend/
├── pipeline/
│   ├── moderate.py              # NEW (D-22) — single module per CONTEXT
│   │   ├── SYSTEM_PROMPT        # constant
│   │   ├── PROMPT_VERSION       # constant — semver
│   │   ├── ModerationResult     # @dataclass
│   │   ├── moderate_clip(clip_id)
│   │   ├── _csam_check(clip_id, hash)  # dispatches stub vs vendor
│   │   ├── _gemini_classify(clip_id)
│   │   └── _route_verdict(...)
│   ├── run.py                   # MODIFIED — gate insertion at line 79
│   └── embed.py                 # UNCHANGED
├── db_postgres.py               # MODIFIED — new write functions
├── db_sqlite.py                 # MODIFIED — same signatures
├── config.py                    # MODIFIED — new env vars
├── app.py                       # MODIFIED — lifespan production-guard
├── observability/
│   └── anonymity.py             # MODIFIED — REDACT_KEYS extend
└── migrations/versions/
    └── 20260430_0004_moderation_columns.py  # NEW
```

### Pattern 1: Gemini SDK upload-poll-generate (mirror caption_pipeline.py:424-479)
**What:** Upload bytes via Files API → poll until `ACTIVE` → call `generate_content` with structured response.
**When to use:** Any Gemini call against video bytes >20 MB inline limit (per [VERIFIED: ai.google.dev/gemini-api/docs/files] — 20 MB limit on inline data; videos go through Files API).
**Example:**
```python
# Source: backend/pipeline/caption_pipeline.py:424-479 (verbatim pattern)
from google import genai
from google.genai import types

client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=20_000),  # ms — moderation budget
)
loop = asyncio.get_running_loop()
uploaded = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: client.files.upload(file=tmp_path)),
    timeout=10.0,
)
# Poll
for _ in range(20):
    if uploaded.state.name == "ACTIVE":
        break
    await asyncio.sleep(0.5)
    uploaded = await loop.run_in_executor(
        None, lambda: client.files.get(name=uploaded.name)
    )

response = await loop.run_in_executor(
    None,
    lambda: client.models.generate_content(
        model=config.GEMINI_MODERATION_MODEL,
        contents=[uploaded, USER_PROMPT],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,                       # determinism for moderation
            response_mime_type="application/json",
            response_schema=ModerationResponse,    # TypedDict; see D-11 schema
        ),
    ),
)
parsed = json.loads(response.text)
```

### Pattern 2: asyncio.wait FIRST_COMPLETED with safe cancellation
**What:** Two parallel tasks; first to finish wins; the other is cancelled and re-awaited.
**When to use:** D-02 step 4 — embed_task vs gemini_task.
**Example:**
```python
# Source: rob-blackbourn.medium.com/a-python-asyncio-cancellation-pattern + hynek.me
embed_task = asyncio.create_task(embed_worker(clip_id), name="embed")
gemini_task = asyncio.create_task(_gemini_classify(clip_id), name="gemini")

try:
    done, pending = await asyncio.wait(
        {embed_task, gemini_task},
        return_when=asyncio.FIRST_COMPLETED,
        timeout=config.MODERATION_MAX_BUDGET_S,  # absolute upper bound
    )
except asyncio.CancelledError:
    # Outer task cancelled — propagate cancellation to children, re-await, raise.
    embed_task.cancel()
    gemini_task.cancel()
    await asyncio.gather(embed_task, gemini_task, return_exceptions=True)
    raise

# Branch on which task finished first.
if embed_task in done and gemini_task in pending:
    # Embed beat Gemini → treat as classifier timeout (D-03 cancel-when-embed-finishes)
    gemini_task.cancel()
    try:
        await gemini_task
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("gemini task failed during cancellation (non-fatal)")
    raise asyncio.TimeoutError("gemini cancelled by embed-first")  # D-05 catch site
elif gemini_task in done and embed_task in pending:
    # Gemini beat Embed → await embed (it must complete for downstream cluster).
    await embed_task
    return gemini_task.result()
elif not done:
    # Both still pending after MAX_BUDGET — both cancelled.
    embed_task.cancel()
    gemini_task.cancel()
    await asyncio.gather(embed_task, gemini_task, return_exceptions=True)
    raise asyncio.TimeoutError("max budget exceeded")
else:
    # Both finished simultaneously (rare). Use Gemini's result.
    return gemini_task.result()
```

### Pattern 3: Module-import-time provider dispatcher (mirror Phase 9 D-08 / Phase 10 D-13)
**What:** Select provider once at module load; no per-request branching.
**When to use:** CSAM provider selector in `moderate.py`.
**Example:**
```python
# Source: backend/storage/__init__.py:15-23 (verbatim shape)
if config.OFFLINE_DEMO:
    from ._csam_stub import csam_check
elif config.CSAM_PROVIDER == "stub":
    from ._csam_stub import csam_check
elif config.CSAM_PROVIDER == "cloudflare":
    # Future: vendor-specific module
    raise RuntimeError(
        "CSAM_PROVIDER=cloudflare is unimplemented. "
        "Cloudflare CSAM Scanning Tool does not expose a programmatic API "
        "and does not support video. See .planning/phases/11-*/11-RESEARCH.md "
        "Open Questions for Planner. Use CSAM_PROVIDER=stub or implement an "
        "alternative vendor (Thorn Safer, PhotoDNA Cloud Service)."
    )
else:
    from ._csam_stub import csam_check
```

### Anti-Patterns to Avoid
- **Per-request provider selection:** Re-evaluating `config.CSAM_PROVIDER` on every clip — Phase 9 D-13 explicitly forbids; tests will catch via the `MODERATION_PROVIDER` parametrize (D-25).
- **`asyncio.gather(return_exceptions=True)` for the parallel arm without `FIRST_COMPLETED`:** waits for both — defeats MOD-03 (latency regression).
- **Forgetting to await cancelled task:** `task.cancel()` schedules cancellation but the task may still be running until next `await`. Pattern 2 above re-awaits with try/except CancelledError to ensure cleanup.
- **Logging `raw_response` to stdlib log:** PRIV-03 + L-10. raw_response goes only into the JSONB column, never into log lines or contextvars.
- **Initializing the (future) CSAM httpx client at module import:** Lifespan only (mirror Phase 10 D-02). Module-import init breaks OFFLINE_DEMO firewall test.
- **Treating "flag" and "block" verdicts differently for hard-block categories:** D-07 explicitly says treat them identically (conservative posture). Don't introduce a "flag is softer than block" branch.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Perceptual hash for CSAM | Custom PDQ / pHash implementation | Vendor (Thorn Safer / PhotoDNA Cloud) | Hash collision tuning, false-positive rate calibration, hash list curation are vendor-domain. Custom implementations leak via fingerprinting and miss the NCMEC-curated hash database. |
| NCMEC report submission | Custom HTTPS form-post | NCMEC ISP Web Service API at `https://report.cybertip.org/ispws` | Statutory schema (18 USC 2258A specifies fields); NCMEC provides credentialed test endpoint. |
| Async parallel-with-cancel primitive | Custom `asyncio.Event` + `asyncio.shield` | `asyncio.wait` with `FIRST_COMPLETED` | Stdlib pattern; correctness corners (CancelledError propagation, parent-cancel re-raise) are documented [CITED: hynek.me/articles/waiting-in-asyncio]. |
| Gemini JSON response schema enforcement | Post-hoc JSON validation + retry | `response_schema=TypedDict` + `response_mime_type='application/json'` | Built into google-genai SDK; mirrors caption_pipeline.py:474-476. Saves a retry loop. |
| HTTP retry on transient 5xx | Custom retry loop | tenacity (already in stack) | Phase 10 D-24 already uses; Phase 11 reuses the decorator. |
| respx mock fixtures | Hand-rolled `unittest.mock.patch` | `respx_mock` pytest fixture | Already used in `conftest.py` for Phase 10. Consistent test ergonomics. |

**Key insight:** The CSAM-detection vendor space is where hand-rolling fails hardest. Hash algorithms (PhotoDNA, PDQ, fuzzy-hash variants) are tuned against curated CSAM corpora that are statutorily protected and not publicly available. A startup cannot lawfully build its own hash database. The choice is binary: pick a vendor (Thorn / Microsoft PhotoDNA / Hive / Cloudflare-when-applicable) or ship a stub. Stub is correct for hackathon-pilot demoware; vendor is required before any user-facing launch.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New rows in `moderation_decisions` (per-clip per-provider), `reported_csam` (CSAM hits only); UPDATE `clips.is_hidden` on hard-block / unknown; UPDATE `segments.soft_flag` at compile time. | Schema migration `0004_moderation_columns.py`. No data backfill needed — Phase 9 D-15 truncate-and-reseed posture from Phase 10 still holds for any pre-Phase-11 demo data. |
| Live service config | None — Cloudflare CSAM Scanning Tool is NOT being used (per Cloudflare section). No external service has Phase 11 state in a UI/database that doesn't live in our git. | None. (If a real CSAM vendor lights up post-pilot, the vendor's dashboard would qualify here.) |
| OS-registered state | None — pipeline runs inside the FastAPI process; no systemd/launchd/Task Scheduler involvement. | None. |
| Secrets/env vars | New: `CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY` (empty by default), `GEMINI_MODERATION_MODEL`, `MODERATION_MAX_BUDGET_S`, `CSAM_STUB_ALLOW_PRODUCTION` (boolean override for the lifespan guard). | Add to `backend/.env.example` per CONTEXT.md D-24 + this research's lifespan-guard add. |
| Build artifacts | None — pure-Python additions, no compiled artifacts, no egg-info changes. | None. |

**Migration head note:** The current alembic head is `0003_merge_comments_blob` (verified at `backend/migrations/versions/20260429_0003_merge_comments_blob.py:19`). Phase 11's new migration must declare `down_revision = "0003_merge_comments_blob"`, NOT `"0001_initial_v1_1_schema"`. Missing this will produce a multi-head condition and `alembic upgrade head` will fail in `preDeployCommand`.

## Common Pitfalls

### Pitfall 1: Misnaming the CSAM provider arm
**What goes wrong:** CONTEXT.md L-02 + STATE.md `Locked Decisions` list "Cloudflare CSAM Scanning Tool" as the chosen provider. The plan implements `CSAM_PROVIDER=cloudflare` as a real arm. Implementation hits a wall at first contact with vendor docs.
**Why it happens:** Cloudflare's tool is widely cited as a free CSAM solution; the conflation between "free CSAM tool from a name we recognize" and "API we can call" is easy to miss without reading the actual product page.
**How to avoid:** Either (a) rename the arm to a placeholder vendor name (`thorn` / `photodna`) and defer real implementation to post-pilot, or (b) ship stub-only with documentation saying "no real CSAM provider integrated yet." Update STATE.md `Locked Decisions` to retract the Cloudflare claim. The lifespan production-guard (D-18) is the load-bearing safety net regardless.
**Warning signs:** Test that imports a `cloudflare_csam` module — should not exist as a real implementation in Phase 11.

### Pitfall 2: Gemini Files API state-not-ACTIVE timeout
**What goes wrong:** `client.files.upload(...)` returns immediately, but the file is in `PROCESSING` state. The classifier call sees a non-ACTIVE file and either errors or returns garbage.
**Why it happens:** Gemini's Files API is async on the server side; the SDK doesn't auto-poll [VERIFIED: ai.google.dev/gemini-api/docs/files + caption_pipeline.py:446-457 has the polling loop verbatim].
**How to avoid:** Mirror caption_pipeline.py:446-457 — explicit poll loop with bounded retries (e.g., 20 iterations × 0.5s = 10s ceiling). If still not ACTIVE, treat as `httpx.HTTPStatusError(5xx)`-equivalent (decision='unknown').
**Warning signs:** Sporadic empty / malformed JSON responses; latency_ms field shows ~0 (call returned immediately on a not-ACTIVE file).

### Pitfall 3: TimeoutError from cancel-when-embed-finishes is asyncio.TimeoutError, NOT a real network timeout
**What goes wrong:** D-05 catches `asyncio.TimeoutError` and treats as `decision='blocked'` (classifier was too slow). But `asyncio.TimeoutError` is also raised by the cancel-on-embed-first path — and we want both to map to "blocked." The trap is using a different exception type for the cancel path.
**Why it happens:** It's tempting to use a custom `EmbedFirstError` to distinguish, but the unified handling is the design choice in D-05.
**How to avoid:** Pattern 2 above explicitly raises `asyncio.TimeoutError("gemini cancelled by embed-first")` after re-awaiting the cancelled task — same exception class, message disambiguates in logs only. The `reason` field in `moderation_decisions` differentiates: `"classifier_timeout"` vs `"embed_finished_first"`.
**Warning signs:** Test for "embed-first wins → blocked" passes only because of unrelated 5xx routing, not because the right exception is being caught.

### Pitfall 4: Gemini response_schema enum vs string
**What goes wrong:** `response_schema=ModerationResponse` where ModerationResponse is a TypedDict with `Literal['pass', 'flag', 'block']` — the SDK may serialize this as a free-text string rather than enforce the enum at the model layer. The model returns "passed" or "PASS" or some other variant; JSON parses but the verdict-routing code crashes on KeyError.
**Why it happens:** TypedDict with Literal types isn't always honored as a JSON schema enum constraint; google-genai's schema converter has caveats [CITED: github.com/googleapis/python-genai/issues/60 — nested Pydantic models].
**How to avoid:** Use Pydantic BaseModel with `Enum` field, or use TypedDict with `Literal` and add a defensive `.lower().strip()` + membership check before routing. Sanitize defensively; never trust LLM output structure even with response_schema.
**Warning signs:** Any KeyError or ValueError from verdict-routing in tests.

### Pitfall 5: Lifespan production-guard race with CI
**What goes wrong:** D-18 says "refuse to start when CSAM_PROVIDER=stub AND production-like environment AND not OFFLINE_DEMO." If the production-like heuristic fires inside CI (e.g., `SENTRY_ENVIRONMENT=production` set in GitHub Actions for Sentry source map upload), CI fails on every PR.
**Why it happens:** Heuristics are brittle. CI environments often inherit production-flavored env vars.
**How to avoid:** Use `SENTRY_ENVIRONMENT == "production"` as the gate but require `CSAM_STUB_ALLOW_PRODUCTION=true` to unblock. Set `CSAM_STUB_ALLOW_PRODUCTION=true` in CI. Document this clearly in `.env.example` and `backend/Dockerfile`.
**Warning signs:** CI job fails on lifespan startup with the production-guard error.

### Pitfall 6: New alembic migration descends from wrong revision
**What goes wrong:** Phase 11's `0004_moderation_columns.py` declares `down_revision = "0001_initial_v1_1_schema"` (copy-pasted from earlier example). Multi-head condition; `alembic upgrade head` errors out.
**Why it happens:** The merge-heads pattern (`0003_merge_comments_blob`) is non-obvious; the file was added recently (2026-04-29) and may not be top-of-mind.
**How to avoid:** Run `alembic heads` before authoring the new migration. Confirm `0003_merge_comments_blob` is the only head. Set `down_revision = "0003_merge_comments_blob"` exactly.
**Warning signs:** `alembic upgrade head` fails with "Multiple head revisions are present."

### Pitfall 7: Recorded-tape (respx) mock leaks between test parametrize cells
**What goes wrong:** `respx_mock` fixture is per-test-function, but the `MODERATION_PROVIDER=recorded` cell may register a route that bleeds into the `MODERATION_PROVIDER=stub` cell because the fixture order in the parametrize matrix isn't deterministic.
**Why it happens:** Multiple parametrize fixtures × respx_mock fixture-tear-down order is fragile [CITED: lundberg.github.io/respx/guide].
**How to avoid:** Mirror Phase 10 D-21 conftest pattern — `respx_mock` is requested as a fixture *parameter* of the storage_backend fixture, so the registration scope is explicit. Test for `OFFLINE_DEMO=true` cell asserts `len(router.calls) == 0` (existing pattern at `test_offline_demo_firewall.py:35`).
**Warning signs:** Flaky tests where stub cells start failing because some request was matched against the wrong mock.

### Pitfall 8: PRIV-03 strip — Gemini SDK uploads more than just video bytes
**What goes wrong:** The Files API upload sends not just bytes but also `display_name`, MIME, and metadata fields. If the planner accidentally passes `display_name=clip_id` or includes any contextvars in the upload, that's a metadata leak.
**Why it happens:** SDK convenience — easy to slip in a display_name "for debugging."
**How to avoid:** Pass `file=tmp_path` only. Never set `display_name`. Test asserts the recorded outbound request body contains zero non-bytes fields.
**Warning signs:** Recorded payload shows JSON metadata in the multipart body.

## Code Examples

Verified patterns from official sources:

### Gemini Files API upload-poll-generate (foundation pattern)
```python
# Source: backend/pipeline/caption_pipeline.py:424-499 (verbatim Newz pattern)
# This is the exact shape Phase 11 mirrors with MODERATION_MAX_BUDGET_S budgets.
from google import genai
from google.genai import types

client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=20_000),
)
loop = asyncio.get_running_loop()
uploaded = await asyncio.wait_for(
    loop.run_in_executor(None, lambda: client.files.upload(file=tmp_path)),
    timeout=10.0,
)
for _ in range(20):
    if uploaded.state.name == "ACTIVE":
        break
    await asyncio.sleep(0.5)
    uploaded = await loop.run_in_executor(
        None, lambda: client.files.get(name=uploaded.name)
    )
if uploaded.state.name != "ACTIVE":
    raise asyncio.TimeoutError("gemini files API never reached ACTIVE")
response = await asyncio.wait_for(
    loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=config.GEMINI_MODERATION_MODEL,
            contents=[uploaded, USER_PROMPT],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=ModerationResponse,
            ),
        ),
    ),
    timeout=config.MODERATION_MAX_BUDGET_S,
)
parsed = json.loads(response.text)
# Best-effort cleanup
try:
    await loop.run_in_executor(None, lambda: client.files.delete(name=uploaded.name))
except Exception as e:
    log.warning("gemini files cleanup failed (non-fatal): %s", e)
```

### Gemini response_schema as TypedDict
```python
# Source: googleapis.github.io/python-genai (TypedDict + response_schema example)
from typing import Literal, TypedDict

class CategoryVerdict(TypedDict):
    verdict: Literal["pass", "flag", "block"]
    score: float
    rationale: str

class ModerationResponse(TypedDict):
    csam: CategoryVerdict
    sexual: CategoryVerdict
    hate: CategoryVerdict
    extremist: CategoryVerdict
    violence: CategoryVerdict
    self_harm: CategoryVerdict

# Pass via:
config=types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=ModerationResponse,
    ...
)
```

### tenacity retry on httpx (mirror Phase 10 blob_client.py)
```python
# Source: backend/storage/blob_client.py:147-152 (Phase 10 pattern verbatim)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
import httpx

class _RetryableHTTPError(Exception):
    pass

_csam_retry = retry(
    retry=retry_if_exception_type((httpx.TransportError, _RetryableHTTPError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
    reraise=True,
)
```

### respx fixture for recorded-tape
```python
# Source: backend/tests/conftest.py:69-109 (Phase 10 pattern, extended for moderation)
import respx
import pytest

@pytest.fixture(params=["stub", "recorded"], ids=["stub", "recorded"])
def moderation_provider(request, monkeypatch, respx_mock):
    """D-25: parametrize MODERATION_PROVIDER alongside METADATA + STORAGE backends.

    'recorded' cell registers respx routes for Gemini Files API + generate_content.
    NEVER hits real Gemini from CI.
    """
    provider = request.param
    monkeypatch.setenv("MODERATION_PROVIDER", provider)
    monkeypatch.setenv("OFFLINE_DEMO", "false")
    if provider == "recorded":
        # Gemini Files API upload
        respx_mock.post("https://generativelanguage.googleapis.com/upload/v1beta/files").respond(
            json={"file": {"name": "files/abc", "state": "ACTIVE",
                           "uri": "https://generativelanguage.googleapis.com/v1beta/files/abc"}},
        )
        # Gemini Files API get (poll)
        respx_mock.get("https://generativelanguage.googleapis.com/v1beta/files/abc").respond(
            json={"name": "files/abc", "state": "ACTIVE"},
        )
        # Gemini generate_content
        respx_mock.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent").respond(
            json={"candidates": [{"content": {"parts": [{"text": json.dumps({
                "csam": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
                "sexual": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
                "hate": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
                "extremist": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
                "violence": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
                "self_harm": {"verdict": "pass", "score": 0.0, "rationale": "no signal"},
            })}]}}]},
        )
    yield provider
```

## Cloudflare CSAM Scanning Tool

**This section discharges CONTEXT.md research item #1 (D-17) and is the most consequential finding in this research.**

### What it actually is
[VERIFIED: developers.cloudflare.com/cache/reference/csam-scanning + blog.cloudflare.com/the-csam-scanning-tool]

Cloudflare CSAM Scanning Tool is a **CDN-cache-passive feature** configured through the Cloudflare dashboard (Caching > Configuration > CSAM Scanning Tool). It:

1. Scans content **served through Cloudflare's CDN cache**, not arbitrary uploads.
2. Uses **fuzzy hashing** (perceptual hash) on **images only** — videos are explicitly out of scope per the original 2019 announcement: *"the software can only scan images that are at rest in memory on a machine, not those that are streaming."*
3. Notifies the site owner **via email** when a match is found and **blocks the URL** at the Cloudflare edge.
4. Is **not a programmatic REST API** — the only configuration is a dashboard toggle and a notification email address.
5. Is **free for all Cloudflare customers** (post-2025 changes [VERIFIED: developers.cloudflare.com/changelog/2025-02-04-easier-onboarding-for-csam-scanning-tool]).

### What it is NOT (and what CONTEXT.md assumed)

CONTEXT.md L-02, D-17, D-20 assume:
- A REST API that accepts a hash and returns `{match: bool}` ❌
- Video support ❌
- An auth model with `CLOUDFLARE_CSAM_API_KEY` env var ❌
- Predictable per-call latency ❌ (it's an async background scan, not a synchronous query)

None of these are accurate. The Cloudflare tool is for **websites that serve images via Cloudflare CDN**. Newz serves video via Vercel Blob (not Cloudflare). The Phase 11 use case — POST a hash before a video is published — is **not what this tool does**.

### Hash algorithm (D-17 deliverable)
[VERIFIED: blog.cloudflare.com/the-csam-scanning-tool]

Cloudflare's tool uses a fuzzy hash (perceptual hash) — likely PhotoDNA-derived or PhotoDNA-direct, but **the customer never sees or computes the hash**. The hash is generated by Cloudflare on cached content. There is no "hash algorithm we must compute on our side" because the tool isn't called by us at all.

### NCMEC reporting (D-20 deliverable)
[VERIFIED: developers.cloudflare.com + blog.cloudflare.com/a-simpler-path-to-a-safer-internet]

Cloudflare's tool **does NOT report to NCMEC on the customer's behalf**. The 2025 simplification removed the requirement that customers share their NCMEC credentials with Cloudflare. Cloudflare blocks the URL and emails the customer. The customer is "still expected to continue to file their own reports with NCMEC or their regional equivalent."

### Latency profile
Not applicable — there is no per-call latency to measure. The tool is asynchronous.

### Application/onboarding lead time
Zero. [VERIFIED: developers.cloudflare.com/changelog/2025-02-04-easier-onboarding-for-csam-scanning-tool] Free to enable in any Cloudflare dashboard with no NCMEC vetting required (post-Feb 2025). **But this doesn't help Newz** because Newz doesn't run on Cloudflare CDN.

### Implication for Phase 11

The `CSAM_PROVIDER=cloudflare` arm cannot be implemented as described. Three options for the user to choose between (see Open Questions):

1. **Ship stub-only.** Lifespan production-guard (D-18) ensures we don't accidentally deploy with stub. The `cloudflare` arm is replaced with a placeholder `RuntimeError` that documents the situation. Real CSAM detection is deferred until a vendor decision.
2. **Pick a different CSAM vendor and rename the arm.** Realistic candidates:
   - **Thorn Safer Match** — purpose-built API for CSAM detection, supports both image and video (Scene-Sensitive Video Hashing) [VERIFIED: safer.io]. Hosted on AWS Marketplace; pricing requires sales contact. Likely paid.
   - **Microsoft PhotoDNA Cloud Service** — REST API, free for qualified organizations, image-only (would require keyframe extraction from videos via ffmpeg) [VERIFIED: microsoft.com/en-us/photodna/cloudservice]. Tech Coalition typically responds within ~1 week [CITED: technologycoalition.org].
   - **Hive AI CSAM Detection** — commercial API integrated with Thorn's hash list [VERIFIED: thehive.ai/apis/csam-detection]. Paid.
3. **Defer CSAM entirely to post-pilot.** Newz is anonymous-by-design with hyperlocal scope and a moderation gate that catches the same content via Gemini Flash-Lite's `csam` category. Argue the case to the user that the AI classifier is a sufficient interim — flag for retrofit before any non-pilot launch.

**Research recommendation:** Option 1 (stub-only with production-guard). Reasoning: pilot demo doesn't justify a paid vendor commitment; the AI classifier route catches the same content in practice; the production-guard prevents accidental ship-to-prod with stub. Communicate this back to the user before plan execution so STATE.md `Locked Decisions` and Phase 11 CONTEXT.md L-02 / D-17 / D-20 can be reconciled.

## NCMEC CyberTipline reporting ownership

**This section discharges CONTEXT.md research item #1 sub-deliverable (D-20).**

### Ownership decision
[VERIFIED: report.cybertip.org/ispws/documentation + 18 USC 2258A + REPORT Act 2024]

Newz owns the NCMEC report API call. There is no realistic third-party path on which Newz could rely:

- Cloudflare's tool — even when applicable to images on Cloudflare CDN — does not report on the customer's behalf [VERIFIED: blog.cloudflare.com/a-simpler-path-to-a-safer-internet].
- Thorn Safer Match offers reporting workflow tooling but the statutory report itself is the platform's obligation [VERIFIED: 18 USC 2258A — "provider" must report].
- PhotoDNA Cloud Service detects only; does not report.

### NCMEC API contract (for when Phase 11+ implements vendor-arm)
[VERIFIED: report.cybertip.org/ispws/documentation]

- **Production endpoint:** `https://report.cybertip.org/ispws`
- **Test endpoint:** `https://exttest.cybertip.org/ispws`
- **Auth:** HTTP Basic with username/password issued by NCMEC after vetting (one-time approval — lead time variable, plan for weeks-to-months).
- **Schema:** XML, defined by NCMEC's ISP Web Service. Required fields per 18 USC 2258A:
  - `reporterName`, `reporterEmail`, `reporterPhone` — entity contact
  - `incidentDateTime`, `incidentSummary` — event description
  - `industryClassification` — selected from NCMEC's enum
  - `personOrUserReported` — perpetrator info as available (anonymity-by-design means we have very little here)
  - `imageOrVideoFilesContained` — content metadata + hashes
  - `IPCaptureSection` — ingest IP / timestamps
- **Response:** synchronous; returns a `ReportId` (numeric) on success, used for follow-up correspondence.

### Schema implication

**Recommendation: Add `ncmec_report_id BIGINT` column to `reported_csam` in the same migration that handles `moderation_decisions`.** The column is nullable (NULL for the stub provider; populated only when a real vendor + real NCMEC submission happens). This avoids a future-phase ALTER for what is statutorily the same scope. CONTEXT.md D-20 punted this to plan-time; this research recommends doing it now.

### Retention reconciliation (D-19 confirmation)
[VERIFIED: 18 USC 2258A + REPORT Act 2024 + en.wikipedia.org/wiki/REPORT_Act]

Statutory retention is **1 year minimum** following submission. CONTEXT.md D-19 is correct (REQUIREMENTS.md MOD-09's 90-day figure is pre-amendment stale). Liam's todo to amend MOD-09 is mechanical.

### Anonymity tension

Newz's anonymity-by-design (no accounts, no display names, no persisted session_uuid) means our NCMEC reports will be sparse on perpetrator info. This is consistent with how anonymous platforms historically file CyberTipline reports — the IP is the only identifier, and PRIV-01 strips XFF. Document this in the report payload generator: include only what we have, never invent fields. Run draft language past legal counsel before any real NCMEC submission. (For Phase 11 stub, this isn't exercised.)

## Gemini 2.5 Flash-Lite classifier contract

**This section discharges CONTEXT.md research item #2 (D-29, D-11, D-12).**

### Empirical latency (D-29 deliverable)

| Metric | Source | Value |
|--------|--------|-------|
| TTFT (text only, p50) | [VERIFIED: artificialanalysis.ai/models/gemini-2-5-flash-lite] | 0.58s |
| Output speed (text) | [VERIFIED: artificialanalysis.ai] | 255.8 tok/sec |
| Video inference, 7s 720p MP4 (Flash, not Lite) | [CITED: discuss.ai.google.dev forum thread] | 10-15s typical, 60s+ worst-case spikes |
| Video inference, Flash-Lite specifically | **No public benchmark found** | UNKNOWN |
| Marengo 3.0 typical latency on Newz corpus | Existing v1.0 calibration | Embed cycle including upload+processing; STATE.md does not record p50 — recommend re-measuring as part of the pre-flight TODO |

**Bottom line:** Flash-Lite is faster than Flash on text by all benchmarks. For video, Flash's documented variance (4× spikes) is the load-bearing risk. Flash-Lite likely inherits similar variance shape but with lower absolute numbers; this is **assumption, not verified**. The pre-flight benchmark in STATE.md is therefore mandatory before plan execution — the cancel-when-embed-finishes design (D-03) collapses if Flash-Lite p50 video latency > Marengo p50 video latency.

**`MODERATION_MAX_BUDGET_S` recommendation:** Default 20s. Rationale: covers Flash p99 video latency (60s spikes) only at the cap; if Flash-Lite spikes exceed 20s, the gate fails-CLOSED and the clip enters admin queue (`decision='unknown'` → is_hidden=true). This is the conservative posture matching D-05/D-06.

### SDK contract (D-11)
[VERIFIED: backend/pipeline/caption_pipeline.py:424-499 + googleapis/python-genai docs]

Phase 11's classifier call is byte-identical to caption_pipeline.py except for:
- `model=config.GEMINI_MODERATION_MODEL` (new env var, default `"gemini-2.5-flash-lite"`)
- `system_instruction=SYSTEM_PROMPT` (Phase 11's prompt, see below)
- `response_schema=ModerationResponse` (Phase 11's TypedDict, defined above in Code Examples)
- `temperature=0.0` (determinism for moderation; caption uses 0.2 for stylistic variety)
- Inner `asyncio.wait_for(timeout=config.MODERATION_MAX_BUDGET_S)` instead of caption's `timeout=125.0`

The `client.files.upload` + poll pattern is identical (lines 440-457).

### Recommended SYSTEM_PROMPT (D-12 deliverable)

The prompt below is locked in as `backend/pipeline/moderate.py::SYSTEM_PROMPT`. It is intentionally brief, taxonomy-explicit, and does not editorialize on what counts as "newsworthy" — that is `_should_compile`'s job, not the moderator's.

```
You are a content moderation classifier. Your task is to evaluate a short
video clip and return a JSON object with one entry per safety category. You
do not write captions, headlines, or commentary. You do not judge whether
content is on-topic for any platform. You only assess safety categories.

Your response MUST be a JSON object with EXACTLY these six keys:
  csam, sexual, hate, extremist, violence, self_harm

Each value MUST be an object with EXACTLY three keys:
  verdict   — one of "pass", "flag", or "block"
  score     — a float between 0.0 and 1.0 indicating confidence
  rationale — a single short sentence explaining the verdict

Category definitions:
  csam       — sexual content involving minors, in any depiction. Verdict
               "block" on any signal, however slight. No exceptions.
  sexual     — adult sexual content, nudity, or sexually suggestive material
               outside of a clearly journalistic / educational context.
  hate       — content targeting a protected class with slurs, dehumanizing
               imagery, or coded extremist symbology. News-context coverage
               of hate-crime events should be marked "flag", not "block",
               since journalistic documentation is in scope for this platform.
  extremist  — content promoting, glorifying, or recruiting for terrorist,
               white-supremacist, or other violent extremist movements.
               Documenting an extremist event for journalistic purposes
               should be "flag" — promoting it should be "block".
  violence   — depictions of physical violence, injury, weapons being used
               against people. News-context (street incidents, protest
               clashes, accident aftermath) should be "flag" rather than
               "block" — the platform shows newsworthy footage with viewer
               warnings, not graphic content for shock value.
  self_harm  — depictions of suicide, self-injury, or content that
               encourages or instructs self-harm. Verdict "block" on any
               clear signal — there is no journalistic defense for showing
               this content on a public hyperlocal feed.

Verdict semantics:
  "pass"  — no signal in this category
  "flag"  — non-zero signal but not certain; or signal present but in
            news/journalistic context where a viewer warning is appropriate
  "block" — high-confidence signal warranting removal

Be conservative. When uncertain between "pass" and "flag", choose "flag".
When uncertain between "flag" and "block" for csam / sexual / extremist /
self_harm, choose "block". When uncertain between "flag" and "block" for
hate / violence, choose "flag" — the platform's downstream policy soft-
flags rather than blocks these categories, and over-blocking news content
defeats the platform's purpose.

Return ONLY the JSON object. No prose, no markdown fences, no commentary.
```

**Rationale for the conservative-toward-block bias on csam/sexual/extremist/self_harm:** Mirrors D-07 hard-block treatment — false-positive cost (one over-blocked clip) is far cheaper than false-negative cost (CSAM in a public feed).

**Rationale for conservative-toward-flag bias on hate/violence:** Mirrors D-08 — these are news-relevant categories where over-blocking destroys editorial value. The downstream verdict-routing in `_route_verdict` then consults D-08 to translate `flag` or `block` into `soft_flag=true` regardless.

### `PROMPT_VERSION` semver scheme

```python
# backend/pipeline/moderate.py
PROMPT_VERSION = "1.0.0"
```

Semver bumping rules:
- **Major** — categories changed (added/removed/renamed). Schema migration required because old `moderation_decisions.raw_response` rows have a different shape.
- **Minor** — semantics changed (e.g., "we now block solo violence"). Compile-time soft_flag computation must be re-verified.
- **Patch** — wording tweaks only (typo fixes, clarification). No behavioral change.

Recommend bumping in the same commit as the SYSTEM_PROMPT change. Persisted on every row via `prompt_version` column for audit (per D-12).

### Inline-data vs Files API
[VERIFIED: ai.google.dev/gemini-api/docs/files]

Inline data (`Blob` in `Content.parts`) is capped at 20 MB per request. Newz clips are capped at 100 MB (`MAX_UPLOAD_BYTES` in app.py:231). Most clips are well under 20 MB, but the gate cannot assume so. **Always use the Files API path** — same upload-poll-generate flow as caption_pipeline.py. Reuses the established pattern; eliminates the size-branching code path.

## Validation Architecture

**This section discharges CONTEXT.md research item #3 — drives the planner's test tasks. Even though Nyquist validation is disabled per `.planning/config.json` posture, this section anchors the test design.**

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0 + pytest-asyncio >=0.23 + respx |
| Config file | `backend/pytest.ini` (or `pyproject.toml [tool.pytest.ini_options]`) — verify exact location at plan time |
| Quick run command | `pytest backend/tests/test_moderate.py -x -q` |
| Full suite command | `pytest backend/tests/ -x` |
| Backend matrix size | METADATA × STORAGE × MODERATION = 2 × 2 × 2 = 8 cells (fixtures auto-skip postgres without DATABASE_URL) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|------|
| MOD-01 | Gate runs before cluster/compile | unit (mock embed/cluster) | `pytest backend/tests/test_moderate.py::test_gate_runs_before_cluster` | new |
| MOD-02 | Gemini parallel with Marengo via asyncio.wait | unit (asyncio_mock + respx) | `pytest backend/tests/test_moderate.py::test_parallel_with_embed` | new |
| MOD-03 | Common-case latency does not regress | integration | `pytest backend/tests/test_moderate.py::test_cancel_when_embed_finishes_first` | new |
| MOD-04 | CSAM hash check on every clip; fail-CLOSED on error | unit | `pytest backend/tests/test_moderate.py::test_csam_check_runs_first_sequential` + `test_csam_failure_blocks` | new |
| MOD-05 | Tiered failure policy (timeout/4xx blocked, 5xx unknown) | unit | `pytest backend/tests/test_moderate.py::test_failure_tier_classification` (4 sub-cases) | new |
| MOD-06 | Decision recorded in moderation_decisions | unit (db parametrize) | `pytest backend/tests/test_moderate.py::test_writes_per_provider_rows` | new |
| MOD-07 | Soft-flag for hate/violence (broadened) | unit | `pytest backend/tests/test_moderate.py::test_soft_flag_categories` (hate/violence pass with flag) | new |
| MOD-08 | Feed JSON has soft_flag boolean | integration | `pytest backend/tests/test_feed_segments.py::test_soft_flag_in_response` | extend existing |
| MOD-10 | OFFLINE_DEMO=true bypasses moderation | integration | `pytest backend/tests/test_offline_demo_firewall.py::test_offline_demo_no_moderation_calls` | extend existing |
| PRIV-03 | No GPS/session_uuid/timestamp in classifier requests | unit (respx inspect) | `pytest backend/tests/test_moderate.py::test_classifier_payload_anonymized` | new |

### Calibration corpus design

**Constraint:** NCMEC sample CSAM is statutorily protected — we cannot ship samples in-repo, period. [VERIFIED: 18 USC 2258A]

**Strategy:**

1. **Synthetic stub responses for unit tests.** Each test cell registers respx routes that return canned Gemini JSON for the desired verdict pattern. No real video bytes, no real Gemini calls. ~6 canned responses cover (all-pass, csam-block, sexual-block, hate-flag, violence-flag, mixed-flag-and-block).

2. **One small real video for integration test.** The existing `backend/seed/prewarm.mp4` is checked into the repo and is known-safe content. Used as the test video for any test that needs real video bytes flowing through the gate (with respx still intercepting outbound Gemini/CSAM calls).

3. **Negative-corpus simulated via prompt manipulation.** For the calibration tests we don't run real Gemini — but we DO run the prompt against a held-out tiny set of obviously-different videos (a synthetic violence clip from a public news archive, a documentary excerpt, etc., curated by Liam manually). This is offline + manual; results inform PROMPT_VERSION bumps. Out of scope for automated CI.

4. **No CSAM-positive corpus, ever.** The CSAM block path is tested only with synthetic respx responses. The reported_csam writer is unit-tested with a fake hash value (no real CSAM hash database access required).

### Recorded-tape strategy (D-25)

Recommendation: **respx fixtures over VCR.py.** Reasoning:
- Two-endpoint surface (Gemini Files API + generate_content) doesn't justify cassette-management overhead.
- Consistent with Phase 10 D-21 conftest pattern.
- Deterministic — easy to inject failure modes (timeout via respx delay; 5xx via respx status; ConnectError via raised exception).
- No real API hits in CI ever.

If the real Gemini integration smoke (D-28 Wave-0 Railway preview) needs replay-style records, capture once manually and convert to respx route definitions in `conftest.py`. Skip VCR.py entirely.

### Cancel-when-embed-finishes deterministic test

The trick: don't depend on real timing. Use `asyncio.Event` to deterministically order task completion.

```python
# backend/tests/test_moderate.py — cancel-when-embed-finishes deterministic test
@pytest.mark.asyncio
async def test_cancel_when_embed_finishes_first(monkeypatch, respx_mock):
    """MOD-03 — when embed finishes before gemini, gemini is cancelled and
    the result is treated as TimeoutError (decision='blocked')."""
    embed_done = asyncio.Event()

    async def fake_embed(clip_id):
        embed_done.set()
        return ("clip_abc", np.zeros(512, dtype=np.float32))

    async def fake_gemini(clip_id):
        # Wait until embed_done fires, then sleep forever — simulates a slow gemini call
        await embed_done.wait()
        await asyncio.sleep(60)  # would exceed any reasonable budget
        return {"verdict": "pass"}  # never reached

    monkeypatch.setattr("backend.pipeline.moderate._gemini_classify", fake_gemini)
    monkeypatch.setattr("backend.pipeline.embed.embed_worker", fake_embed)

    from backend.pipeline.moderate import moderate_clip
    result = await moderate_clip("clip_abc")
    assert result.decision == "blocked"
    assert result.reason == "embed_finished_first"  # or "classifier_timeout"
```

The `asyncio.Event` flips deterministically; the `await asyncio.sleep(60)` ensures gemini is still pending when embed completes. No real timing dependency.

### Failure-mode injection (D-05 verification)

Each tier handled by a separate respx route:

```python
@pytest.mark.parametrize("status,expected_decision,expected_reason_prefix", [
    (None,  "blocked", "classifier_timeout"),     # asyncio.TimeoutError
    (400,   "blocked", "classifier_4xx"),         # bad payload
    (401,   "blocked", "classifier_4xx"),         # auth fail
    (500,   "unknown", "classifier_5xx"),         # internal server error
    (502,   "unknown", "classifier_5xx"),
    (503,   "unknown", "classifier_5xx"),
    ("ConnectError", "unknown", "classifier_network_error"),
])
@pytest.mark.asyncio
async def test_failure_tier_classification(status, expected_decision, expected_reason_prefix, ...):
    # Configure respx to inject the failure mode
    if status == "ConnectError":
        respx_mock.post(...).mock(side_effect=httpx.ConnectError("conn refused"))
    elif status is None:
        # Inject asyncio.TimeoutError — typically via monkeypatching the wait_for, OR
        # registering a respx route that hangs (delay) and a low MODERATION_MAX_BUDGET_S.
        ...
    else:
        respx_mock.post(...).respond(status_code=status)

    result = await moderate_clip("clip_abc")
    assert result.decision == expected_decision
    assert result.reason.startswith(expected_reason_prefix)
```

### Idempotency test (UNIQUE(clip_id, provider))

```python
@pytest.mark.asyncio
async def test_moderate_clip_idempotent(fresh_db, ...):
    """Running the gate twice must produce 2 rows (one per provider), NOT 4.
    The UNIQUE INDEX on (clip_id, provider) enforces this.
    """
    await moderate_clip("clip_abc")
    await moderate_clip("clip_abc")  # no error, ON CONFLICT DO UPDATE or DO NOTHING
    rows = await db.get_moderation_decisions("clip_abc")
    providers = {r["provider"] for r in rows}
    assert providers == {"cloudflare_csam", "gemini_flash_lite"}  # 2 rows
    assert len(rows) == 2
```

The DB write function uses `ON CONFLICT (clip_id, provider) DO UPDATE` so the second run overwrites with fresh latency / raw_response, but row count stays at 2.

### OFFLINE_DEMO=true zero-egress assertion (MOD-10)

Mirror existing `backend/tests/test_offline_demo_firewall.py:14-39`:

```python
@pytest.mark.asyncio
async def test_offline_demo_no_moderation_calls(monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO", "true")
    monkeypatch.setenv("MODERATION_PROVIDER", "recorded")  # would normally call Gemini
    monkeypatch.setenv("CSAM_PROVIDER", "cloudflare")        # would normally call CSAM API

    importlib.reload(backend.config)
    importlib.reload(backend.pipeline.moderate)

    with respx.mock(base_url="https://generativelanguage.googleapis.com") as gemini_router, \
         respx.mock(base_url="https://api.cloudflare.com") as cf_router:
        result = await backend.pipeline.moderate.moderate_clip("clip_abc")
        assert result.decision == "passed"
        assert result.provider == "stub"
        assert len(gemini_router.calls) == 0
        assert len(cf_router.calls) == 0
```

### PRIV-03 anonymity regression assertion

```python
@pytest.mark.asyncio
async def test_classifier_payload_anonymized(respx_mock, monkeypatch):
    captured_request = {}

    def capture(request):
        captured_request["body"] = request.read()
        captured_request["headers"] = dict(request.headers)
        return httpx.Response(200, json={"file": {"name": "files/abc", "state": "ACTIVE"}})

    respx_mock.post("https://generativelanguage.googleapis.com/upload/v1beta/files").mock(side_effect=capture)
    # ... configure remaining routes to return passthrough JSON ...

    await moderate_clip("clip_abc")

    body = captured_request["body"]
    # PRIV-03: no GPS, session_uuid, timestamp in outbound bytes.
    assert b"session_uuid" not in body
    assert b"gps_lat" not in body
    assert b"gps_lng" not in body
    # The clip_id MAY appear (it's in the file path / display name redaction);
    # confirm it does not appear as a metadata field.
    # Specifically, the only PII-relevant field is the video bytes themselves.
    assert "x-goog-user-project" not in {k.lower() for k in captured_request["headers"]}
```

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_moderate.py -x -q`
- **Per wave merge:** `pytest backend/tests/ -x`
- **Phase gate:** Full suite green + manual D-28 Wave-0 Railway smoke deploy

### Wave 0 Gaps
- [ ] `backend/tests/test_moderate.py` — covers MOD-01..06, MOD-10, PRIV-03
- [ ] `backend/tests/conftest.py` — extend with `moderation_provider` parametrize per D-25
- [ ] `backend/tests/test_feed_segments.py` — extend with soft_flag assertions (MOD-08)
- [ ] `backend/tests/test_offline_demo_firewall.py` — extend with moderation route asserts (MOD-10)
- [ ] No framework install — pytest + pytest-asyncio + respx already in dev deps

## Schema migration strategy

**This section discharges CONTEXT.md research item #4 (D-13, D-14).**

### Migration head verification
[VERIFIED: backend/migrations/versions/]

Current alembic head: `0003_merge_comments_blob` (revision id from `20260429_0003_merge_comments_blob.py:19`). Phase 11's new migration descends from this revision, NOT from `0001_initial_v1_1_schema`. Verify with `alembic heads` before authoring.

### Recommended file naming
Mirror Phase 9 D-22 / Phase 10 timestamp prefix: `20260430_0004_moderation_columns.py` (or whatever date the planner authors it on). Single migration handles both moderation_decisions ALTER and segments.soft_flag ALTER — simpler than D-deferred two-migration option, lower merge-head risk.

### moderation_decisions ALTER (D-13 verbatim + ncmec_report_id addition)

```python
# backend/migrations/versions/20260430_0004_moderation_columns.py
"""moderation_decisions columns + segments.soft_flag.

Revision ID: 0004_moderation_columns
Revises: 0003_merge_comments_blob
Create Date: 2026-04-30
"""
from alembic import op

revision = "0004_moderation_columns"
down_revision = "0003_merge_comments_blob"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # moderation_decisions columns (Phase 11 D-13)
    op.execute("""
        ALTER TABLE moderation_decisions
            ADD COLUMN decision TEXT NOT NULL DEFAULT 'passed',
            ADD COLUMN reason TEXT,
            ADD COLUMN provider TEXT NOT NULL DEFAULT 'stub',
            ADD COLUMN raw_response JSONB,
            ADD COLUMN latency_ms INTEGER,
            ADD COLUMN prompt_version TEXT
    """)
    # Drop the temporary defaults — D-13 spec says NOT NULL but no default;
    # the defaults above are only there to satisfy the ALTER on a
    # potentially-non-empty table. After migration, all writes pass values
    # explicitly.
    op.execute("ALTER TABLE moderation_decisions ALTER COLUMN decision DROP DEFAULT")
    op.execute("ALTER TABLE moderation_decisions ALTER COLUMN provider DROP DEFAULT")

    # CHECK constraint to enforce decision domain (defense-in-depth; the
    # writer should already enforce, but a 5-line CHECK catches drift.)
    op.execute("""
        ALTER TABLE moderation_decisions
            ADD CONSTRAINT moderation_decisions_decision_check
            CHECK (decision IN ('passed', 'blocked', 'unknown'))
    """)
    op.execute("""
        ALTER TABLE moderation_decisions
            ADD CONSTRAINT moderation_decisions_provider_check
            CHECK (provider IN ('cloudflare_csam', 'gemini_flash_lite', 'stub'))
    """)

    # UNIQUE constraint on (clip_id, provider) — D-13 idempotency on retry.
    # Use UNIQUE INDEX (not table constraint) because Postgres' upsert
    # ON CONFLICT (...) DO UPDATE syntax requires either a UNIQUE INDEX or
    # a UNIQUE constraint targeted by name. Index is the conventional shape
    # in this project (Phase 9 used CREATE UNIQUE INDEX for reported_csam).
    op.execute("""
        CREATE UNIQUE INDEX idx_moderation_decisions_clip_provider
            ON moderation_decisions(clip_id, provider)
    """)

    # ncmec_report_id on reported_csam (research recommendation; CONTEXT D-20 punted to plan)
    op.execute("""
        ALTER TABLE reported_csam
            ADD COLUMN ncmec_report_id BIGINT
    """)

    # segments.soft_flag (D-14 — column over derived)
    op.execute("""
        ALTER TABLE segments
            ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "Phase 11 moderation columns migration is one-way; rollback unsupported (D-15)."
    )
```

### Postgres-specific notes
[VERIFIED: postgresql.org/docs ALTER TABLE]

- `ADD COLUMN ... NOT NULL DEFAULT '...'` is fast in Postgres 11+ (no full-table rewrite — stored as metadata) so the DEFAULT trick is safe even on a populated table. [CITED: postgresql.org/docs/current/sql-altertable]
- The two `DROP DEFAULT` immediately after — defensive cleanup. The writer always passes explicit values from this point forward.
- `JSONB` (not `JSON`) — Phase 9 D-04 implicit choice; matches the existing `moderation_decisions.created_at TIMESTAMPTZ DEFAULT NOW()` pattern.
- UNIQUE INDEX shape: matches Phase 9's `idx_reported_csam_content_hash` exactly.

### SQLite path (for OFFLINE_DEMO + tests)

`db_sqlite.py` constructs schema in code (verbatim SQL strings) rather than via Alembic. Phase 11 must update the SCHEMA_SQL constant in `db_sqlite.py` to include the same column definitions. SQLite supports JSONB syntactically (stored as TEXT internally) so the column types parse, but JSON-aware queries require careful test wording.

### Backfill considerations

Both Postgres production and the SQLite test path use empty-table migrations in practice — no v1.0 production data persists for these tables (Phase 9 D-04 created `moderation_decisions` empty; Phase 10 D-15 truncate-and-reseed posture eliminated any test rows). Backfill is therefore a no-op. The DEFAULT-then-DROP-DEFAULT pattern above is for forward-compat (in case future deploys introduce intermediate rows).

## asyncio.wait FIRST_COMPLETED + cancellation patterns

**This section discharges CONTEXT.md research item #5 (D-02, D-03).**

### Canonical idiom for "fire two; await first; cancel other; route on result"

The Pattern 2 code in the Architecture Patterns section above is the validated implementation. Key correctness points beyond what's in the snippet:

1. **`asyncio.wait` does NOT auto-cancel pending tasks.** [VERIFIED: docs.python.org/3/library/asyncio-task] Even with `FIRST_COMPLETED`, you must explicitly `.cancel()` the pending set. The Python issue tracker [CITED: github.com/python/cpython/issues/100928] documents that this is a frequent confusion point.

2. **`.cancel()` is a request, not an assertion.** [VERIFIED: hynek.me/articles/waiting-in-asyncio] The task runs until its next `await` point; CancelledError raises there. **You must re-await the cancelled task** to drain it; otherwise it is an "orphan" — Python emits a `Task was destroyed but it is pending!` warning at GC time, and resources may leak.

3. **Re-await pattern:** `try: await task` then `except asyncio.CancelledError: pass` — swallow the expected exception. Other exceptions (like a real failure that occurred before cancel was requested) re-raise.

4. **Parent-cancellation propagation:** if the outer `await asyncio.wait(...)` is itself cancelled by the parent task, both child tasks need explicit cancel + drain before re-raising the CancelledError. The Pattern 2 snippet above handles this with the outer try/except CancelledError.

5. **Don't pass raw coroutines to `asyncio.wait`.** [VERIFIED: hynek.me] As of Python 3.11+ this raises `DeprecationWarning`; 3.13+ raises `TypeError`. Always `asyncio.create_task(coro)` first, then pass the Task to wait.

### Translating "embed_task finished first → cancel gemini → fail-CLOSED"

Already shown in Pattern 2. The semantic mapping:

| Outcome | Decision | Reason field |
|---------|----------|--------------|
| embed_task done, gemini_task pending | `blocked` | `embed_finished_first` (or unify under `classifier_timeout` per D-05) |
| gemini_task done, embed_task pending → await embed → route on gemini verdict | depends on Gemini output | `gemini_*` |
| both pending after MAX_BUDGET → both cancelled | `blocked` | `max_budget_exceeded` |
| both done simultaneously (rare) | route on Gemini | (gemini's reason) |

The catch site in the caller wraps `_gemini_classify` calls with the Pattern 2 code; the typed-exception handler from D-05 maps `asyncio.TimeoutError` → blocked.

### Existing patterns in the codebase

- `caption_pipeline.py:435,478` uses `asyncio.wait_for` (single-task timeout) + SDK `HttpOptions(timeout=...)` belt-and-suspenders. **Phase 11 deviates** — uses `asyncio.wait` (multi-task) with explicit cancel because we have two parallel tasks to coordinate, not one task to time-bound.
- `app.py:130-135` (lifespan shutdown) uses the cancel + try-await-CancelledError pattern for the keepalive task. **Reusable as the model.**
- No existing code uses `asyncio.gather(return_exceptions=True)` in a parallel-with-cancel context. Phase 11 introduces the pattern; document inline in `moderate.py` for future maintainers.

## Cloudflare client lifecycle in FastAPI lifespan

**This section discharges CONTEXT.md research item #6 (D-23). Note: the "Cloudflare" naming is retained per CONTEXT.md, but per the Cloudflare CSAM Scanning Tool research above, the actual implementation is `CSAM_PROVIDER=stub` for Phase 11. The lifespan posture below applies to whichever future vendor lands in the cloudflare arm.**

### httpx.AsyncClient pattern (mirror Phase 10 D-02)
[VERIFIED: backend/storage/blob_client.py:88-115]

```python
# backend/pipeline/moderate.py — module-level client (when CSAM_PROVIDER=cloudflare/vendor)
import httpx
import logging
from .. import config

log = logging.getLogger(__name__)
_csam_client: httpx.AsyncClient | None = None


def get_csam_client() -> httpx.AsyncClient:
    if _csam_client is None:
        raise RuntimeError(
            "CSAM client not initialized — backend.app.lifespan must call init_csam_client() first"
        )
    return _csam_client


async def init_csam_client() -> None:
    global _csam_client
    if _csam_client is not None:
        log.warning("init_csam_client called twice; ignoring second call")
        return
    if config.CSAM_PROVIDER != "cloudflare" or config.OFFLINE_DEMO:
        # Stub or OFFLINE_DEMO — no client needed.
        return
    if not config.CLOUDFLARE_CSAM_API_KEY:
        raise RuntimeError(
            "CLOUDFLARE_CSAM_API_KEY is empty but CSAM_PROVIDER=cloudflare and "
            "OFFLINE_DEMO=false. Set the key, switch CSAM_PROVIDER=stub, or set "
            "OFFLINE_DEMO=true."
        )
    _csam_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    log.info("csam client initialized provider=cloudflare")


async def close_csam_client() -> None:
    global _csam_client
    if _csam_client is not None:
        await _csam_client.aclose()
        _csam_client = None
        log.info("csam client closed")
```

### Lifespan integration in app.py

```python
# backend/app.py — lifespan() additions, after blob_client init (3.5), before pre-warm (5)

# 3.6. Phase 11: csam client init — only when cloudflare arm active.
# OFFLINE_DEMO=true short-circuits to stub at the dispatcher; this branch
# is unreachable under firewalled-CI; enforces fail-loud on missing token.
if config.CSAM_PROVIDER == "cloudflare" and not config.OFFLINE_DEMO:
    from .pipeline import moderate
    await moderate.init_csam_client()

# 3.7. Phase 11: lifespan production-guard. Refuse to start when running with
# stub CSAM in a production-like environment (D-18). Override via
# CSAM_STUB_ALLOW_PRODUCTION=true.
if (
    config.CSAM_PROVIDER == "stub"
    and not config.OFFLINE_DEMO
    and config.SENTRY_ENVIRONMENT == "production"
    and not config.CSAM_STUB_ALLOW_PRODUCTION
):
    raise RuntimeError(
        "CSAM_PROVIDER=stub in production environment without "
        "CSAM_STUB_ALLOW_PRODUCTION=true. Refusing to start. "
        "Either configure a real CSAM provider, set OFFLINE_DEMO=true, "
        "or explicitly opt in via CSAM_STUB_ALLOW_PRODUCTION=true."
    )
```

### tenacity retry config (mirror Phase 10 D-24 verbatim)

```python
# backend/pipeline/moderate.py
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

class _RetryableHTTPError(Exception):
    pass

_csam_retry = retry(
    retry=retry_if_exception_type((httpx.TransportError, _RetryableHTTPError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
    reraise=True,
)
```

The retry budget — 0.5s + 1.0s + 2.0s = ~3.5s worst-case — must fit inside the 5s `csam_check` timeout. Verify in `test_csam_retry_budget_within_timeout` test.

## OFFLINE_DEMO interaction

**This section discharges CONTEXT.md research item #7 (D-21).**

### Import-time vs runtime safety

The Phase 9 D-08 / Phase 10 D-13 pattern is module-import-time selection. For Phase 11:

```python
# backend/pipeline/moderate.py — top of file
from .. import config

# D-21: OFFLINE_DEMO=true forces stub regardless of CSAM_PROVIDER.
# Mirror Phase 9 D-11 + Phase 10 D-18.
if config.OFFLINE_DEMO:
    _csam_provider = "stub"
elif config.CSAM_PROVIDER == "cloudflare":
    _csam_provider = "cloudflare"
else:
    _csam_provider = "stub"

# Same shape for moderation classifier:
# OFFLINE_DEMO=true → moderate_clip returns passthrough WITHOUT calling Gemini at all.
```

### `moderate_clip` short-circuit under OFFLINE_DEMO

```python
async def moderate_clip(clip_id: str) -> ModerationResult:
    if config.OFFLINE_DEMO:
        # D-21: passthrough decision; one row in moderation_decisions.
        await db.write_moderation_decision(
            clip_id=clip_id,
            provider="stub",
            decision="passed",
            reason="offline_demo",
            raw_response=None,
            latency_ms=0,
            prompt_version=None,
        )
        return ModerationResult(decision="passed", provider="stub")
    # ... real path
```

### Lifespan posture under OFFLINE_DEMO

[VERIFIED: backend/app.py:113-115 (Phase 10 pattern)] Phase 11 mirrors:

```python
# In lifespan():
if config.CSAM_PROVIDER == "cloudflare" and not config.OFFLINE_DEMO:
    from .pipeline import moderate
    await moderate.init_csam_client()
# else: skip — no httpx client created → zero outbound traffic
```

The `test_offline_demo_firewall.py:14-39` pattern extends to assert no calls to Gemini base URL or any future CSAM provider URL under OFFLINE_DEMO=true. Specifically, the new test (per Validation Architecture) registers respx mocks for both Gemini and CSAM endpoints and asserts `len(router.calls) == 0`.

### Gemini API specifically

The `gemini_classify` helper checks OFFLINE_DEMO at function entry and returns a passthrough verdict without invoking the SDK at all. Avoids any chance of an accidental call escaping the firewall.

```python
async def _gemini_classify(clip_id: str) -> dict:
    if config.OFFLINE_DEMO:
        return {cat: {"verdict": "pass", "score": 0.0, "rationale": "offline_demo"}
                for cat in ["csam", "sexual", "hate", "extremist", "violence", "self_harm"]}
    # ... real Files API + generate_content path
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Frame-aggregation for video understanding (Anthropic-frame-by-frame style) | Native video input via `google-genai` SDK | v1.0 caption pipeline switched 2026-04 | Already the established pattern in Newz (caption_pipeline.py); Phase 11 just reuses |
| `asyncio.wait_for` per-task timeout | `asyncio.wait` + `FIRST_COMPLETED` + explicit `.cancel()` for parallel-with-other-task | Documented in [hynek.me/articles/waiting-in-asyncio] as the modern idiom | Phase 11 introduces the pattern; future phases may adopt |
| MOD-09 90-day retention figure | 1-year retention per 2024 REPORT Act amendment | 2024 federal law change | Liam todo: amend REQUIREMENTS.md MOD-09 |
| Cloudflare CSAM Scanning Tool requires NCMEC creds shared | No NCMEC creds required; just an email; customer files own NCMEC reports | 2025-02-04 [VERIFIED: developers.cloudflare.com/changelog] | Tool is easier to enable but doesn't change Phase 11 (we don't actually use it) |
| TaskGroup (Python 3.11+) is "the" modern replacement for `asyncio.wait` | Yes, but Phase 11 keeps `asyncio.wait` for parity with caption_pipeline.py | — | Future migration possible; not in Phase 11 scope |

**Deprecated/outdated:**
- The CONTEXT.md L-02 / D-17 / D-20 assumption about Cloudflare CSAM as a programmatic API. **Replaced by:** stub-with-production-guard (option 1) per Open Questions.
- REQUIREMENTS.md MOD-09 90-day retention text. **Replaced by:** D-19 1-year retention (Liam todo to amend).
- REQUIREMENTS.md MOD-07 corroboration-only soft-flag wording. **Replaced by:** D-08 broadened to all hate + all violence (Liam todo to amend).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Gemini 2.5 Flash-Lite p50 video latency on a 10-30s Newz clip is under Marengo p50 video latency | Gemini section / Pitfall on cancel-when-embed-finishes | Cancel-when-embed-finishes fails-CLOSED routinely; clips routinely route to admin queue; user experience degrades from "fast" to "manual review queue." **Pre-flight benchmark TODO discharges this.** |
| A2 | `asyncio.TimeoutError` is the right unified exception for "embed beat gemini" | Pattern 2 / Pitfall 3 | A custom exception type might be clearer in logs; trade-off is more code paths. Low risk — semantic-only. |
| A3 | Fast Postgres `ALTER ADD COLUMN ... NOT NULL DEFAULT ...` works without rewrite on a populated table | Schema migration / DEFAULT-then-DROP pattern | Old Postgres (<11) would rewrite the table → downtime. Neon runs current Postgres (>=15) so this is safe; verify in plan-time check. |
| A4 | Phase 11's recommended `MODERATION_MAX_BUDGET_S=20` covers Flash-Lite p99 video latency for Newz corpus | Gemini section | If wrong, p99 spikes blow the budget → admin queue floods. Safe-fail (admin queue) but UX-impacting. |
| A5 | NCMEC API approval lead time is "weeks-to-months" | NCMEC section | Could be faster (week+) or slower (months). Doesn't block Phase 11 because we ship stub; affects future Phase 11.5 or 12 timing. |
| A6 | Soft-flag column on `segments` (not derived from JOIN) is the right placement | Schema migration / D-14 | Wrong choice → either expensive feed-read query or denormalization-update bug at compile time. Low risk; D-14 default is column. |
| A7 | The current alembic head is `0003_merge_comments_blob` and the new migration descends from it | Schema migration / Pitfall 6 | Wrong → multi-head condition. Verifiable mechanically with `alembic heads`. |

**If user accepts the stub-only Phase 11 ship path, A1+A4+A5 reduce to "monitor Flash-Lite latency in production for the first N clips and tune budget."** The CSAM-specific assumptions disappear because we're not calling a real CSAM API yet.

## Open Questions for Planner

1. **CSAM provider arm reconciliation (BLOCKING — answer before plan execution).**
   - What we know: Cloudflare CSAM Scanning Tool does not match the use case described in CONTEXT.md L-02 / D-17 / D-20. It is image-only, CDN-passive, and does not report to NCMEC on our behalf.
   - What's unclear: whether the user wants to (a) ship stub-only and rename the arm, (b) pick a real vendor (Thorn / PhotoDNA / Hive), or (c) defer CSAM detection entirely and rely on Gemini's `csam` category.
   - Recommendation: **(a) ship stub-only with the lifespan production-guard.** Update STATE.md `Locked Decisions` and Phase 11 CONTEXT.md L-02 to read "Cloudflare CSAM Scanning Tool deferred — pilot ships with stub; vendor evaluation deferred to post-pilot." Plan Phase 11 with stub as the only validated arm. Document the Thorn/PhotoDNA options as alternatives in the deferred items.

2. **Pre-flight Gemini Flash-Lite latency benchmark (BLOCKING — answer before plan execution).**
   - What we know: Flash-Lite TTFT 0.58s on text. Flash video p50 10-15s; spikes to 60s.
   - What's unclear: Flash-Lite video p50 / p99 on Newz's actual 10-30s clips. Public benchmarks don't cover this.
   - Recommendation: Liam runs the benchmark on `backend/seed/demo/*.mp4` (the staged demo dataset). Record p50, p95, p99 across N=20+ clips. Feed the result back into the planner as the locked `MODERATION_MAX_BUDGET_S` value. Until this happens, the gate is theoretical.

3. **`_resume_pipeline(clip_id)` ownership (Phase 11 vs Phase 12) — non-blocking, planner pick.**
   - What we know: Phase 12 owns the admin endpoint; the function lives somewhere and is called by the endpoint.
   - What's unclear: which phase exposes the function.
   - Recommendation: **Phase 11 exposes the function in `backend/pipeline/run.py`.** Phase 12 imports and calls. Single ownership = single test surface. CONTEXT.md `<deferred>` already recommends this; lock it.

4. **soft_flag column placement (D-14) — non-blocking, planner pick.**
   - Recommendation: **column over derived.** `ALTER TABLE segments ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE`. Cheap feed-read; compile-time write determines value from the cluster's moderation_decisions rows. Already defaulted in CONTEXT.md.

5. **`SENTRY_ENVIRONMENT` heuristic for production-guard — minor.**
   - What we know: D-18 says "production-like environment, planner picks signal."
   - Recommendation: Use `config.SENTRY_ENVIRONMENT == "production"`. Allow `CSAM_STUB_ALLOW_PRODUCTION=true` env-var override. Document in `.env.example`. Set `CSAM_STUB_ALLOW_PRODUCTION=true` in CI to keep CI green.

6. **`reported_csam.ncmec_report_id` column — research recommendation, planner confirm.**
   - Recommendation: **add the BIGINT nullable column now**, in the same `0004_moderation_columns.py` migration. Avoids a future ALTER. Population deferred to whichever phase actually calls NCMEC API. Cost is one nullable column.

## Environment Availability

Phase 11 dependencies are entirely already in stack — no external CLI tools, services, or runtimes need probing.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| google-genai SDK | Gemini classifier | ✓ | >=1.73.0 (verified in requirements.txt) | — |
| httpx | Future CSAM client | ✓ | 0.28.1 | — |
| tenacity | CSAM client retry | ✓ | 9.1.4 | — |
| asyncpg | moderation_decisions writes | ✓ (Phase 9) | 0.31.0 | — |
| Cloudflare CSAM API | (not used; per research) | N/A | — | Stub |
| NCMEC ISP API | (not called Phase 11) | Vendor approval needed | — | Defer |
| Gemini API key (`GEMINI_API_KEY`) | Production runs | ✓ (already configured Phase 4.7) | — | OFFLINE_DEMO |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** NCMEC and Cloudflare are not called in Phase 11 stub path → no fallback needed.

## Sources

### Primary (HIGH confidence)
- [Cloudflare CSAM Scanning Tool documentation](https://developers.cloudflare.com/cache/reference/csam-scanning/) — confirmed CDN-cache-passive, image-only, no programmatic API, no NCMEC reporting on customer's behalf
- [Cloudflare blog: Announcing CSAM Scanning Tool](https://blog.cloudflare.com/the-csam-scanning-tool/) — original 2019 announcement; image-only, fuzzy hash
- [Cloudflare blog: simpler path to safer internet](https://blog.cloudflare.com/a-simpler-path-to-a-safer-internet-an-update-to-our-csam-scanning-tool/) — 2025 simplification; customer files own NCMEC reports
- [Cloudflare changelog: easier onboarding](https://developers.cloudflare.com/changelog/2025-02-04-easier-onboarding-for-csam-scanning-tool/) — Feb 2025 NCMEC-credential removal
- [NCMEC CyberTipline ISP Web Service docs](https://report.cybertip.org/ispws/documentation) — production endpoint, schema, auth model
- [18 USC 2258A](https://www.law.cornell.edu/uscode/text/18/2258A) — statutory reporting requirements; 1-year retention
- [REPORT Act Wikipedia](https://en.wikipedia.org/wiki/REPORT_Act) — 2024 amendment to 18 USC 2258A; retention extension 90d → 1y
- [Google Gen AI Python SDK documentation](https://googleapis.github.io/python-genai/) — Files API upload + poll + generate_content with response_schema
- [google-genai GitHub repo](https://github.com/googleapis/python-genai) — codegen instructions, Pydantic / TypedDict caveat
- [Gemini Files API documentation](https://ai.google.dev/api/files) — 20 MB inline limit, ACTIVE polling
- [hynek.me — Waiting in asyncio](https://hynek.me/articles/waiting-in-asyncio/) — modern asyncio.wait + FIRST_COMPLETED + cancel pattern
- [Python asyncio cancellation pattern (Rob Blackbourn)](https://rob-blackbourn.medium.com/a-python-asyncio-cancellation-pattern-a808db861b84) — re-await cancelled task to drain
- [Python issue 100928](https://github.com/python/cpython/issues/100928) — `asyncio.wait` does NOT auto-cancel
- Local source: `backend/pipeline/caption_pipeline.py:424-499` (Gemini SDK pattern verbatim)
- Local source: `backend/storage/blob_client.py:88-152` (httpx + tenacity lifecycle pattern)
- Local source: `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py` and `20260429_0003_merge_comments_blob.py` (alembic shape + head)
- Local source: `backend/tests/conftest.py:69-109` (respx parametrize fixture pattern)
- Local source: `backend/tests/test_offline_demo_firewall.py` (zero-egress assertion pattern)

### Secondary (MEDIUM confidence)
- [Artificial Analysis — Gemini 2.5 Flash-Lite](https://artificialanalysis.ai/models/gemini-2-5-flash-lite) — TTFT 0.58s, 255.8 tok/s output (text)
- [Gemini 2.5 Flash-Lite stable announcement](https://developers.googleblog.com/en/gemini-25-flash-lite-is-now-stable-and-generally-available/) — GA + recommended use cases
- [Thorn Safer Match overview](https://safer.io/resources/introducing-safer-essential-api-based-csam-detection/) — alternative CSAM vendor; supports video via SSVH
- [Microsoft PhotoDNA Cloud Service](https://www.microsoft.com/en-us/photodna/cloudservice) — alternative CSAM vendor; image-only, free for qualified orgs
- [Gemini video latency forum thread](https://discuss.ai.google.dev/t/extreme-latency-spikes-in-gemini-2-5-flash-video-inference-15s-vs-60s/136137) — variance documentation for Flash on video; not Flash-Lite-specific

### Tertiary (LOW confidence — flagged for verification by benchmark)
- Industry-typical Flash-Lite video p99 (assumed similar shape to Flash but lower absolute) — STATE.md pre-flight benchmark TODO discharges
- Cloudflare CSAM tool video support claim (a few search results conflate Cloudflare's tool with PhotoDNA-for-Video) — primary source confirms images-only
- NCMEC approval lead time exact — varies; "weeks to months" is the realistic envelope

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in stack with verified versions
- Architecture (asyncio.wait + cancel): HIGH — multiple authoritative sources align
- Gemini SDK contract: HIGH — verbatim verified against caption_pipeline.py and Google's docs
- Cloudflare CSAM finding: HIGH — multiple Cloudflare sources align unambiguously
- NCMEC reporting: HIGH — statutory text + NCMEC API docs
- Schema migration: HIGH — local source verification + Postgres docs
- Validation Architecture: HIGH — patterns inherited from Phase 9 / Phase 10 conftest
- Gemini Flash-Lite video latency: MEDIUM — TTFT verified; video p99 assumption flagged in Open Questions
- CSAM vendor pricing / approval lead times: LOW — vendor-disclosed but not verified for Newz-scale

**Research date:** 2026-04-29
**Valid until:** 2026-05-29 for Cloudflare/NCMEC/Gemini API contracts (relatively stable). 2026-05-15 for Gemini Flash-Lite latency assumptions (rapidly-evolving model — refresh after pre-flight benchmark).

## RESEARCH COMPLETE

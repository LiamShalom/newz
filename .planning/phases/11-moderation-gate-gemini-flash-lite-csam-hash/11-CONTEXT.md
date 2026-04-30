# Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash) - Context

**Gathered:** 2026-04-29
**Reconciled:** 2026-04-29 (Option 4 — classifier-only CSAM detection)
**Status:** Ready for planning

> ## ⚠ RECONCILIATION (2026-04-29) — read this before any other section
>
> Phase 11 plan-phase researcher (see `11-RESEARCH.md` § "Cloudflare CSAM Scanning Tool") confirmed that Cloudflare CSAM Scanning Tool is a **CDN-cache-passive image-only feature** that emails the customer when matches are found in CDN-cached content. It is **not** a programmatic POST-a-hash API, does **not** support video, does **not** run on Vercel-hosted blobs, and does **not** report to NCMEC on the customer's behalf. The original CONTEXT.md L-02 + D-17 + D-20 assumption that we POST a hash to a Cloudflare CSAM API is structurally invalid.
>
> **User decision (2026-04-29):** Ship Phase 11 with **classifier-only CSAM detection** for the pilot. The Gemini Flash-Lite classifier's locked `csam` category (D-11) routes to hard-block (D-07) and writes a `reported_csam` preservation row. No CSAM hash dispatcher, no `CSAM_PROVIDER` env var, no `csam_check()` function, no Cloudflare httpx client, no automated NCMEC reporting. Real CSAM hash vendor (Thorn Safer Match for video / PhotoDNA Cloud Service / Hive) and automated NCMEC CyberTipline reporting deferred to post-pilot, before public launch.
>
> **Decisions superseded by this reconciliation (each is annotated `[SUPERSEDED]` in-place below — read both the original text AND the reconciliation note for full context):**
> - **L-02** — Cloudflare CSAM Scanning Tool is no longer a locked decision; CSAM detection is the Gemini classifier's `csam` category.
> - **D-02** — Sequence simplifies from 7 steps to 4: hash compute (SHA-256 for `reported_csam` preservation only), parallel `embed_task` + `gemini_task`, `asyncio.wait` FIRST_COMPLETED, route on Gemini verdict. **CSAM-first sequential is removed.**
> - **D-10** — Per-provider rows in `moderation_decisions` collapse to one row per clip (`provider='gemini_flash_lite'`). UNIQUE(clip_id, provider) still enforces idempotency.
> - **D-13** — Migration content unchanged (`decision`, `reason`, `provider`, `raw_response`, `latency_ms`, `prompt_version`, UNIQUE INDEX). Naming changes from `0003_moderation_decisions_columns` to `0004_moderation_columns` because Phase 11 must descend from the current head `20260429_0003_merge_comments_blob` per researcher finding.
> - **D-16** — CSAM-first sequential dropped.
> - **D-17** — Cloudflare hash algorithm research item dropped. SHA-256 of clip bytes is sufficient for `reported_csam` preservation (de-dup fingerprint, not perceptual hash).
> - **D-18** — `CSAM_PROVIDER` env var dropped. Lifespan production-guard becomes a non-blocking `WARN` log line: "Phase 11 pilot ships classifier-only CSAM detection. Real hash vendor + NCMEC reporting deferred." emitted when `OFFLINE_DEMO=false` AND production-like env (`SENTRY_ENVIRONMENT=production` or similar). Goal: visible reminder, not a startup-refusal.
> - **D-20** — NCMEC CyberTipline report API ownership: pilot defers automated reporting. Manual workflow: Liam files via report.cybertip.org when admin queue surfaces `reason='gemini_csam_block'`. `reported_csam.ncmec_report_id BIGINT` column is **still added** in the migration (additive; nullable; populated when the manual report receipt comes back so we have an audit trail per § 2258A). Cheaper to add now than ALTER later.
> - **D-21** — OFFLINE_DEMO bypass simplifies: only Gemini client init is conditional on `not OFFLINE_DEMO`. No Cloudflare client to skip.
> - **D-22** — Module location stays `backend/pipeline/moderate.py`. Drops `csam_check(clip_id, hash)` function. Keeps `moderate_clip(clip_id) -> ModerationResult`, `SYSTEM_PROMPT`, `PROMPT_VERSION`, internal Gemini classifier helper. **No** `csam_client.py` split.
> - **D-23** — httpx Cloudflare client lifecycle dropped (no client to manage). Gemini SDK client lifecycle continues to mirror `caption_pipeline.py`.
> - **D-24** — `CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY` dropped. `GEMINI_MODERATION_MODEL` and `MODERATION_MAX_BUDGET_S` retained.
> - **D-25** — Test conftest `MODERATION_PROVIDER` parametrize collapses to a single Gemini-mock fixture using respx (already in stack from Phase 10). No CSAM provider parametrize needed.
> - **D-27** — Sentry scrubber extension drops `csam_hash` (no separate hash field). Keeps `raw_response`, `prompt_version` redaction.
> - **D-28** — Wave-0 smoke deploy validates only the Gemini arm (one classifier call → one `moderation_decisions` row → correct verdict routing).
> - **D-29** — "Cloudflare CSAM/NCMEC approval status" pre-flight TODO dropped from blocking list. "Gemini Flash-Lite latency benchmark on demo dataset" remains load-bearing per researcher finding (cancel-when-embed-finishes is the latency primitive — only valid if Flash-Lite p50 < Marengo p50 on actual corpus).
>
> **Decisions UNCHANGED by this reconciliation:**
> - **L-01, L-03..L-12** — all locked-elsewhere decisions stand.
> - **D-01** — gate insertion at `run.py:79`; `STAGE_DURATION(stage="moderate")` wrap unchanged.
> - **D-03** — cancel-when-embed-finishes is the load-bearing latency primitive. Now governs the whole gate (no CSAM-first prefix).
> - **D-04** — no pre-ingest sync gate; 202 fire-and-forget preserved.
> - **D-05** — typed-exception tier classification unchanged.
> - **D-06** — unknown-tier handling: `decision='unknown'`, `is_hidden=true`, clustering paused, admin queue surface, `_resume_pipeline(clip_id)` re-entry on admin clear.
> - **D-07** — hard-block categories (`csam`, `sexual`, `extremist`, `self_harm`) — `csam` is the operative CSAM detection signal under Option 4.
> - **D-08** — soft-flag categories (`hate`, `violence`), broadened per the broadening rationale; REQUIREMENTS.md MOD-07 now reflects this.
> - **D-09** — off-topic safe content passes the gate.
> - **D-11** — Gemini response schema (locked taxonomy + verdict + score + rationale per category).
> - **D-12** — `SYSTEM_PROMPT` + `PROMPT_VERSION` constants in `moderate.py`. The researcher provides a copy-paste-ready prompt in RESEARCH.md.
> - **D-14** — `segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE` column ALTER. Compile-time write when any cluster member's `moderation_decisions` row has a soft-flag-category signal.
> - **D-15** — `/feed` JSON ships `soft_flag: boolean`; Roan owns the UI under feature-track #6.
> - **D-19** — `reported_csam.content_preserved_until = NOW() + INTERVAL '1 year'` per 2024 REPORT Act. REQUIREMENTS.md MOD-09 now reflects this.
> - **D-26** — structured INFO log per gate stage; raw responses in JSONB only.
>
> **Behavioral consequences for the planner:**
> - File set shrinks: no `csam_client.py`, no Cloudflare wiring in `lifespan()`, no `CSAM_PROVIDER` dispatcher tests.
> - `moderation_decisions` writes one row per clip (Gemini), not two. Latency drops by ~1s on the happy path (no CSAM-first prefix).
> - On classifier `csam` hit: write `reported_csam` row (SHA-256 hash + 1-year retention), write `moderation_decisions` row (`provider='gemini_flash_lite'`, `decision='blocked'`, `reason='gemini_csam_block'`), call `cleanup_blocked_clip(clip_id)`. Manual NCMEC reporting via admin queue.
> - `ncmec_report_id BIGINT` nullable column on `reported_csam` is added in the same migration so manual report receipts can be persisted without a follow-up ALTER.
> - Wave-0 smoke deploy is simpler: spin up backend, upload one clip, confirm one `moderation_decisions` row + correct routing.
> - Phase 11 ships **fewer plans** than the original CONTEXT.md envisioned. Latency is **lower** by removing the CSAM-first prefix.



<domain>
## Phase Boundary

Every uploaded clip passes through a pre-publish moderation gate before entering cluster/compile. Two providers run per clip: a Cloudflare CSAM hash check (sequential, first), then a Gemini 2.5 Flash-Lite content classifier (parallel-with-Marengo embed). Tiered failure policy: timeout → fail-CLOSED (block); 5xx outage → fail-OPEN (`moderation_status=unknown`, admin queue); CSAM hit → fail-CLOSED with statutory preserve. ≥0-corroboration soft-flag for hate/violence (broader than MOD-07's literal corroboration-only wording — see D-07 deviation note).

**In scope (from REQUIREMENTS.md MOD-01..08, MOD-10, PRIV-03):**
- Gate runs on every clip before cluster/compile (MOD-01)
- Gemini classifier in parallel with Marengo via `asyncio.gather` + `asyncio.wait` (MOD-02)
- Common-case latency does not regress vs v1.0 baseline (MOD-03; cancel-when-embed-finishes)
- Cloudflare CSAM hash on every clip; fail-CLOSED on any error (MOD-04)
- Tiered failure policy: timeout → blocked; 5xx → unknown (MOD-05)
- Every decision recorded in `moderation_decisions` audit table (MOD-06)
- Soft-flag for hate/violence — interstitial, not hard-block (MOD-07, broadened per D-07)
- Feed UI tap-to-view interstitial (MOD-08; backend ships the `soft_flag` boolean, Roan owns the UI under feature-track #6)
- `OFFLINE_DEMO=true` bypasses every external moderation API; passthrough decision (MOD-10)
- PRIV-03: GPS, session_uuid, timestamp stripped from outbound classifier calls
- `reported_csam` writes (Phase 9 D-06 created the table; Phase 11 owns the writes; 1-year retention per 2024 REPORT Act amendment, NOT the stale 90-day figure)
- Calls Phase 10's `cleanup_blocked_clip(clip_id)` hook on every hard-block

**Out of scope (deferred):**
- Reactive reporting + admin queue endpoints (Phase 12) — Phase 11 surfaces clips into the queue via `is_hidden=true + decision='unknown'`; Phase 12 owns the queue UI/endpoints
- Logfire span tracing on the new `moderate` stage (Phase 13 OBS-05)
- Custom signal calibration / threshold tuning (defer to post-pilot if traffic shows misses)
- `_resume_pipeline(clip_id)` ownership decision (Phase 11 vs Phase 12) — punt to planner
- Frontend interstitial UI (feature-track #6 — Roan)
- Per-IP rate limit on `/clips` (deferred v1.2; abuse controls explicitly deferred per PROJECT.md)
- Adversarial-probing defenses against classifier mapping (v1.2)
- Pre-ingest hard-rejection (sync gate inside `POST /clips` handler) — rejected; current 202 fire-and-forget design preserved (D-04)

</domain>

<decisions>
## Implementation Decisions

### Inherited (locked elsewhere; do NOT re-litigate)
- **L-01:** Gemini 2.5 Flash-Lite as the classifier — STATE.md `Locked Decisions` (uses google-genai SDK already in stack via caption_pipeline.py).
- **L-02:** Cloudflare CSAM Scanning Tool as the hash check — STATE.md `Locked Decisions` (statutory 18 U.S.C. § 2258A).
- **L-03:** `moderation_decisions` table exists with `id`, `clip_id`, `created_at` (Phase 9 D-04). Phase 11 ALTERs to add columns per D-13.
- **L-04:** `reported_csam` table exists with `id`, `content_hash`, `content_preserved_until`, `created_at` (Phase 9 D-06). Phase 11 owns the writes.
- **L-05:** `clips.is_hidden BOOLEAN NOT NULL DEFAULT FALSE` exists (Phase 9 D-05). Phase 11 owns the writes (block path → true; admin clear → false).
- **L-06:** `cleanup_blocked_clip(clip_id)` hook exists (Phase 10 D-20). Phase 11 calls it immediately after writing `decision='blocked'`. Idempotent; no-ops if already deleted.
- **L-07:** Sentry `before_send` already redacts `session_uuid`, `gps_lat`, `gps_lng`, `blob_url` (Phase 8 D-14). Phase 11 must extend the scrubber list to include moderation classifier raw responses (`raw_response`) and any new `csam_hash` fields if they reach error contexts.
- **L-08:** `--workers 1` Procfile pin holds (Phase 9 L-02). New `httpx.AsyncClient` for Cloudflare CSAM is process-singleton in `lifespan()`.
- **L-09:** Single asyncpg pool, max_size=10 (Phase 9 D-16). Moderation writes use the existing pool.
- **L-10:** PRIV-02 contextvars whitelist: `request_id`, `session_hash`, `clip_id` only. Phase 11 must NOT add classifier responses, raw bytes, or hash values as contextvars — log them as kwargs only.
- **L-11:** Phase 8 D-17 Prometheus label policy: bounded labels only. New `stage="moderate"` label added to `STAGE_DURATION` is permitted (already a bounded enum); per-category metrics may not use category names as high-cardinality labels.
- **L-12:** OFFLINE_DEMO graceful-degrade pattern (Phase 8 D-16, Phase 9 D-11, Phase 10 D-18) — Phase 11 mirrors: `OFFLINE_DEMO=true` → moderate_clip returns passthrough decision; CSAM hash check skipped; no httpx Cloudflare client init.

### Pipeline shape (D-01..04)

- **D-01:** **Gate runs at the `run_pipeline` call site in `backend/pipeline/run.py:79`.** Replace `await embed_worker(clip_id)` with a CSAM-first sequential gate, then `asyncio.gather(embed_task, gemini_task, return_exceptions=True)`. `embed_worker` and the new `moderate_clip` stay orthogonal modules. New `stage="moderate"` STAGE_DURATION label spans the full gate (CSAM + Gemini).
- **D-02:** **Sequence:**
  1. Compute SHA hash of clip bytes (or whatever Cloudflare's CSAM API requires — research item).
  2. Sequential `await csam_check(clip_id, hash)`. On hit → fail-CLOSED, write `reported_csam`, write `moderation_decisions` decision='blocked' provider='cloudflare_csam', call `cleanup_blocked_clip`, return.
  3. On CSAM miss → fire `embed_task` and `gemini_task` in parallel.
  4. `asyncio.wait({embed_task, gemini_task}, return_when=FIRST_COMPLETED)`.
  5. If `embed_task` finishes first and `gemini_task` is pending → cancel `gemini_task` → treat as `asyncio.TimeoutError` → fail-CLOSED.
  6. If `gemini_task` finishes first → await `embed_task`, then route on Gemini verdict.
  7. Write `moderation_decisions` row(s) per provider, route on aggregate verdict, continue or short-circuit pipeline.
- **D-03:** **Cancel-when-embed-finishes uses Marengo's elapsed time as Gemini's effective ceiling.** No fixed Gemini timeout. Implementation: `asyncio.wait` with `FIRST_COMPLETED`, then explicit `.cancel()` on any pending task. Open: absolute upper-bound cap (e.g., `min(marengo_elapsed, MAX_BUDGET=20s)`) — planner choice based on Gemini Flash-Lite latency benchmark (STATE.md pre-flight TODO; see verifications_owed).
- **D-04:** **No pre-ingest sync gate.** `POST /clips` retains 202 fire-and-forget design. Bytes land in private `uploads/` (Phase 10 D-05), gate runs in the background pipeline task, hard-block decision triggers `cleanup_blocked_clip` within sub-second of decision (effectively "never persists" from a feed-visibility perspective). User's "don't even need to ingest vid" intent satisfied via fast cleanup, not pre-ingest rejection.

### Failure-mode tier classification (D-05..06)

- **D-05:** **Typed-exception tier classification.** Catch sites distinguish:
  ```python
  except asyncio.TimeoutError:        # cancel-when-embed-finishes raised this
      decision = "blocked"
      reason = "classifier_timeout"
  except httpx.HTTPStatusError as e:
      if 500 <= e.response.status_code < 600:
          decision = "unknown"        # 5xx outage → admin queue
          reason = f"classifier_5xx_{e.response.status_code}"
      else:
          decision = "blocked"        # 4xx is suspicious (bad payload, auth fail)
          reason = f"classifier_4xx_{e.response.status_code}"
  except (httpx.ConnectError, httpx.ReadError):
      decision = "unknown"
      reason = "classifier_network_error"
  ```
  Catch by exception type so the catch site can route by type — clean, no string inspection. 4xx-as-blocked is the load-bearing piece (matches "completely block" posture for hard-block category misconfigurations).
- **D-06:** **Unknown clip handling:** `moderation_decisions` written with `decision='unknown'`, `clips.is_hidden=true`, **clustering paused** (return from `run_pipeline` after writing). Admin endpoint flips `is_hidden=false` + writes a fresh `decision='passed'` row + fires `_resume_pipeline(clip_id)` which re-enters the pipeline at `cluster_worker(parent_clip_id, parent_vec)`. The parent embedding is still on the row (embed completed even though gate didn't), so resume is cheap.

### Policy taxonomy + verdict map (D-07..09)

- **D-07:** **Hard-block categories (signal=immediate cleanup_blocked_clip):** `csam`, `sexual`, `extremist`, `self_harm`. ANY signal in these categories — `verdict ∈ {flag, block}` — routes to hard-block (treat 'flag' and 'block' identically; conservative posture per "completely block from being ingested").
- **D-08:** **Soft-flag categories (signal=segment.soft_flag=true; never hard-block):** `hate`, `violence`. `verdict ∈ {flag, block}` from Gemini routes to `soft_flag=true`. Pass to feed; tap-to-view interstitial gates autoplay. Rationale: news-context categories — hate-crime reporting and street-violence footage are journalism, not inappropriate content. **DEVIATION FROM REQUIREMENTS.md MOD-07** which specifies corroboration-only soft-flag (≥2-parent + violence). Phase 11 broadens to: all violence + all hate, no corroboration gating. **Liam todo before plan execution: amend REQUIREMENTS.md MOD-07 + STATE.md `Locked Decisions` to reflect the broader soft-flag policy.**
- **D-09:** **Pass:** off-topic safe content (e.g., a clip of a dog, a sunset, an unrelated random video). Not blocked, not flagged. Passes the gate, enters clustering, may end up in the feed as normal. Admin queue (Phase 12) is the human-in-the-loop for "this is off-topic for hyperlocal news, hide it."

### Schema + classifier (D-10..15)

- **D-10:** **Per-provider rows in `moderation_decisions`.** Two rows per clip on the happy path: one `provider='cloudflare_csam'` + one `provider='gemini_flash_lite'`. Stub/OFFLINE_DEMO writes `provider='stub'`. Aggregate verdict computed at read time (any-block-wins). UNIQUE(clip_id, provider) for idempotency on retry.
- **D-11:** **Gemini response schema (fixed taxonomy):** locked enum `categories ∈ ['csam', 'sexual', 'hate', 'extremist', 'violence', 'self_harm']`. Each category returns `{verdict: 'pass'|'flag'|'block', score: float (0..1), rationale: str}`. JSON schema mirrors `caption_pipeline.py:474-476` pattern (`response_mime_type='application/json'` + `response_schema=...`).
- **D-12:** **Prompt is planner-owned + research-informed.** `gsd-phase-researcher` proposes `SYSTEM_PROMPT` text in RESEARCH.md based on Gemini Flash-Lite docs + the policy in D-07/D-08. Lives in `backend/pipeline/moderate.py` as `SYSTEM_PROMPT` constant + `PROMPT_VERSION` constant (semver string). Stored in every `moderation_decisions` row via `prompt_version` column for audit. Iterates as misses surface in admin queue.
- **D-13:** **moderation_decisions ALTER (Phase 11 owns):**
  ```sql
  ALTER TABLE moderation_decisions ADD COLUMN decision TEXT NOT NULL;        -- 'passed' | 'blocked' | 'unknown'
  ALTER TABLE moderation_decisions ADD COLUMN reason TEXT;                   -- short tag, e.g. 'csam_match', 'classifier_timeout', 'gemini_extremist_block'
  ALTER TABLE moderation_decisions ADD COLUMN provider TEXT NOT NULL;        -- 'cloudflare_csam' | 'gemini_flash_lite' | 'stub'
  ALTER TABLE moderation_decisions ADD COLUMN raw_response JSONB;            -- redacted (PRIV-03 strip applied at write time)
  ALTER TABLE moderation_decisions ADD COLUMN latency_ms INTEGER;
  ALTER TABLE moderation_decisions ADD COLUMN prompt_version TEXT;           -- nullable; CSAM rows leave NULL
  CREATE UNIQUE INDEX idx_moderation_decisions_clip_provider ON moderation_decisions(clip_id, provider);
  ```
  Migration name: `0003_moderation_decisions_columns` (planner picks final naming; convention from Phase 9 D-22).
- **D-14:** **Soft-flag column placement** — punt to planner. Two viable shapes:
  - `segments.soft_flag BOOLEAN NOT NULL DEFAULT FALSE` — denormalized; written at compile time when any cluster member's moderation_decisions row has a soft-flag-category signal. Cheap feed-read.
  - Derived at feed-read via JOIN segments→clips→moderation_decisions. No ALTER; expensive query.
  Planner default: column. Confirms via the existing Phase 9 D-04 ALTER ADD COLUMN posture.
- **D-15:** **Feed JSON contract for Roan:** `/feed` segment objects gain `soft_flag: boolean`. SegmentCard checks this and conditionally wraps autoplay in a tap-to-reveal overlay. Phase 11 ships the field; Roan picks up the UI under feature-track #6 (video censoring). No `soft_flag_reason` field this phase — minimum-contract (D-15 trades richer audit for simpler frontend; if Roan needs context strings, a follow-up ALTER is cheap).

### CSAM specifics (D-16..20)

- **D-16:** **CSAM-first sequential.** CSAM check runs BEFORE Gemini fires. On hit, Gemini (and embed) never start — saves Gemini tokens + Marengo cost on confirmed CSAM. CSAM is a strict pre-condition per MOD-04, not a parallel arm. Adds CSAM API latency (~1s typical) to upload-to-publish; acceptable per statute.
- **D-17:** **Hash location: server-side, after blob upload.** Gate task downloads bytes from private `uploads/` via Phase 10 D-08 signed URL, computes hash (algorithm per Cloudflare contract — research item), POSTs hash-only to Cloudflare API. Bytes never leave our infra except to the classifier provider (Gemini); Cloudflare receives only the hash. PRIV-03 strip rules apply trivially (no metadata on a hash payload).
- **D-18:** **Approval-risk fallback: stub-and-ship.** New env var `CSAM_PROVIDER` (values: `cloudflare` | `stub`). Default: `stub`. Stub returns `{match: false}` always. Real Cloudflare integration lights up via `CSAM_PROVIDER=cloudflare`. **Lifespan guard:** when `CSAM_PROVIDER=stub` AND `OFFLINE_DEMO=false` AND environment is production-like (heuristic: `SENTRY_ENVIRONMENT=production` or similar — planner picks signal), startup logs a LOUD WARNING and refuses to start, OR refuses unless explicit `CSAM_STUB_ALLOW_PRODUCTION=true` override. Goal: no accidental "ship to prod with stub" deploys.
- **D-19:** **1-year retention.** `content_preserved_until = NOW() + INTERVAL '1 year'`. Matches 2024 REPORT Act amendment to 18 U.S.C. § 2258A. **Liam todo before plan execution: amend REQUIREMENTS.md MOD-09 + STATE.md `Locked Decisions` to drop the stale "90 days" figure.** No buffer (no 13-month padding) — exact statutory floor; if compliance team wants a buffer, env var or planner-side bump is cheap.
- **D-20:** **NCMEC CyberTipline reporting** — Cloudflare CSAM Scanning Tool MAY report on our behalf, OR we may be responsible for the report API call ourselves. **Research deliverable for `gsd-phase-researcher`.** Either way, `reported_csam` row preserves the hash + retention timestamp; if we own the report call, the row also needs a `ncmec_report_id TEXT` column (additive — handled in plan, not blocking CONTEXT).

### OFFLINE_DEMO (D-21)

- **D-21:** **OFFLINE_DEMO=true bypasses every external moderation API** (MOD-10). `moderate_clip` short-circuits to `{decision: 'passed', provider: 'stub'}` and writes a single passthrough row. CSAM hash check is skipped (no Cloudflare call). No httpx Cloudflare client init at lifespan. Mirrors Phase 9 D-11 + Phase 10 D-18 patterns. CI smoke test (Phase 13 DEMO-02) asserts startup makes zero outbound calls under this flag.

### Claude's Discretion (locked-in defaults the planner can act on)

- **D-22:** Module location: `backend/pipeline/moderate.py` (single module exposing `moderate_clip(clip_id) -> ModerationResult`, `csam_check(clip_id, hash) -> CSAMResult`, internal Gemini + Cloudflare helpers). Mirrors `embed.py`/`caption_pipeline.py` shape.
- **D-23:** httpx Cloudflare client lifecycle: process-singleton in `lifespan()`, mirroring Phase 10 D-02. Closed in shutdown. Tenacity retry on transient 5xx (already in requirements.txt; see Phase 10 D-24). Retry budget MUST fit inside the gate's wall-clock window.
- **D-24:** New env vars in `backend/config.py`:
  - `CSAM_PROVIDER` (default `stub`, values `cloudflare`|`stub`)
  - `CLOUDFLARE_CSAM_API_KEY` (default empty — required when `CSAM_PROVIDER=cloudflare`)
  - `GEMINI_MODERATION_MODEL` (default `gemini-2.5-flash-lite`; separate from `GEMINI_MODEL=gemini-2.5-flash` used by caption_pipeline)
  - `MODERATION_MAX_BUDGET_S` (optional planner-defined absolute cap on the gate; default e.g. 20s)
- **D-25:** Test discipline: extend Phase 9 D-10 / Phase 10 D-21 conftest fixture with `MODERATION_PROVIDER` parametrize (values: `stub`, `recorded` — vcr/recorded-tape style for Gemini and Cloudflare). DO NOT hit real APIs from CI. The `OFFLINE_DEMO=true + sqlite + local_storage + stub_moderation` cell is the firewalled-startup smoke test path; must stay green.
- **D-26:** Logging: every gate stage logs structured INFO line with `op` (csam_check|gemini_classify|gate_decision), `decision`, `provider`, `latency_ms`, `clip_id` (auto via contextvars). Standard Phase 8 structlog kwargs style. Raw responses NOT in log lines (PII surface) — they go in `moderation_decisions.raw_response` JSONB.
- **D-27:** Sentry `before_send` scrubber list extension (Phase 8 D-14): add `raw_response` (any field), `csam_hash`, `prompt_version` redaction. Phase 11 contributes a one-liner to the scrubber's redaction list.
- **D-28:** Wave-0 smoke deploy: deploy `CSAM_PROVIDER=stub + GEMINI_MODERATION_MODEL=gemini-2.5-flash-lite` on Railway preview; upload one clip; confirm two `moderation_decisions` rows + correct verdict routing. Mirrors Phase 9 D-14 + Phase 10 D-22 wave-0 posture. Catches token-format / response-schema / latency surprises before integration tests are wired.
- **D-29:** Pre-flight TODO carry-over: STATE.md `Pending Todos` flags "Benchmark Gemini 2.5 Flash-Lite latency on actual demo dataset before Phase 11 planning" and "Start Cloudflare CSAM/NCMEC approval application (unknown lead time)." Both surface in `gsd-phase-researcher`'s deliverables: latency benchmark sets the `MODERATION_MAX_BUDGET_S` default; approval status sets whether `CSAM_PROVIDER=cloudflare` is reachable for pilot ship vs. ships-with-stub.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and acceptance criteria
- `.planning/ROADMAP.md` §"Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash)" — phase goal, depends-on (Phase 9 + Phase 10), success criteria
- `.planning/REQUIREMENTS.md` §"Pre-Publish Moderation Gate" (MOD-01..08, MOD-10) — gate placement, parallel-with-Marengo, latency, CSAM hash, tiered failure, audit table, soft-flag, OFFLINE_DEMO bypass
- `.planning/REQUIREMENTS.md` §"Anonymity Invariants" (PRIV-03) — strip GPS/session_uuid/timestamp before classifier calls
- `.planning/REQUIREMENTS.md` MOD-09 — `reported_csam` retention (**STALE 90-day figure; corrected to 1 year per 2024 REPORT Act in D-19**)

### Project-level constraints (cross-phase)
- `.planning/PROJECT.md` §"Constraints" — anonymity load-bearing, single Uvicorn worker, OFFLINE_DEMO end-to-end
- `.planning/PROJECT.md` §"Out of Scope" — abuse controls deferred v1.2 (rate limits, bans), no accounts/login/profiles, no per-user persistence
- `.planning/PROJECT.md` §"Hard Constraints" — pre-warm Marengo on backend startup; OFFLINE_DEMO=true serves cached responses
- `.planning/STATE.md` §"Locked Decisions (backbone)" — Gemini 2.5 Flash-Lite chosen, Cloudflare CSAM Scanning Tool chosen, Sentry traces_sample_rate=0, --workers 1, asyncpg pool max_size=10, BYTEA centroids
- `.planning/STATE.md` §"Pending Todos" — Gemini Flash-Lite latency benchmark (D-29); Cloudflare CSAM/NCMEC approval status (D-18, D-29)

### Phase 8 inheritance (must not regress)
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-12 — middleware order (XFFStrip → RequestID → Metrics → CORS → routes); Phase 11 changes nothing
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-14 — Sentry before_send scrubber. Phase 11 D-27 extends it (`raw_response`, `csam_hash`, `prompt_version`).
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-17 — Prometheus bounded label policy. Phase 11 D-26 + L-11 enforce: new `stage="moderate"` label OK; per-category labels NOT.
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-08 (PRIV-02) — structlog contextvars whitelist (`request_id`, `session_hash`, `clip_id`). Phase 11 L-10 enforces: classifier responses + raw bytes + hash NEVER as contextvars.
- `.planning/phases/08-observability-scaffolding/08-CONTEXT.md` D-16 — graceful-degrade pattern (empty `SENTRY_DSN` → skip Sentry init). Phase 11 D-21 mirrors for `OFFLINE_DEMO=true` + classifier bypass.

### Phase 9 inheritance (must not regress)
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-04 — Phase 11 owns `moderation_decisions` column shape (D-13 fulfills).
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-05 — `clips.is_hidden` already nullable in initial migration; Phase 11 owns the writes.
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-06 — `reported_csam` table created Phase 9; Phase 11 owns the writes (D-19 retention).
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` "Reconciliations Owed" — MOD-09 1-year reconciliation explicitly punted to Phase 11. **D-19 + Liam REQUIREMENTS.md amendment todo discharges this.**
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-11 — `OFFLINE_DEMO=true` hard-overrides backend selection (template for D-21).
- `.planning/phases/09-postgres-migration-neon-asyncpg-alembic/09-CONTEXT.md` D-16 — asyncpg pool init in lifespan() (template for httpx Cloudflare client init).

### Phase 10 inheritance (must not regress)
- `.planning/phases/10-vercel-blob-migration/10-CONTEXT.md` D-05, D-06 — split access (`uploads/` private, `runs/` public); 15-min signed URL TTL. Phase 11 reads `uploads/` via signed URL for hash + classifier source bytes.
- `.planning/phases/10-vercel-blob-migration/10-CONTEXT.md` D-08 — ffmpeg/Marengo signed-URL ingest pattern. Phase 11's classifier byte-fetch follows the same pattern (mint signed URL + httpx GET stream into tempfile).
- `.planning/phases/10-vercel-blob-migration/10-CONTEXT.md` D-20 — `cleanup_blocked_clip(clip_id)` hook contract. **Phase 11 D-02 + D-07 are the live callers.**
- `.planning/phases/10-vercel-blob-migration/10-CONTEXT.md` D-18 — `OFFLINE_DEMO=true` hard-overrides STORAGE_BACKEND to local; Phase 11 D-21 mirrors classifier bypass.

### v1.0 / v1.1 architecture being modified
- `backend/pipeline/run.py:55-111` — `run_pipeline(clip_id)` orchestrator. **Insertion point for the gate at line 79 (replaces the bare `embed_worker` await).**
- `backend/pipeline/run.py:41-52` — `_should_compile()` ≥2-parent gate. Phase 11 does NOT modify this; it remains the cluster-level corroboration gate. (Note: D-08 broadens MOD-07 soft-flag to no-corroboration-required, so the corroboration logic stays in `_should_compile` for compile-eligibility only, not soft-flag determination.)
- `backend/pipeline/embed.py` — `embed_worker(clip_id)` signature unchanged. Phase 11 wraps the call in a parallel task.
- `backend/pipeline/caption_pipeline.py:424-479` — Gemini SDK upload + generate_content + JSON `response_schema` pattern. **Phase 11 D-11 mirrors this exact pattern for the classifier call.**
- `backend/config.py:17-18` — `GEMINI_API_KEY`, `GEMINI_MODEL`. Phase 11 D-24 adds `GEMINI_MODERATION_MODEL` (separate from caption model), `CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY`, `MODERATION_MAX_BUDGET_S`.
- `backend/app.py:235-266` — `POST /clips` ingest route. Phase 11 changes NOTHING here (D-04: 202 fire-and-forget preserved; gate runs in the spawned `run_pipeline` task).
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py:104-114` — `moderation_decisions` table (id, clip_id, created_at). Phase 11 ALTER ADD COLUMN per D-13.
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py:127-141` — `reported_csam` table (id, content_hash, content_preserved_until, created_at). Phase 11 owns the writes per D-19.
- `backend/migrations/versions/20260428_0001_initial_v1_1_schema.py:35-55` — `clips` table including `is_hidden BOOLEAN NOT NULL DEFAULT FALSE`. Phase 11 owns the writes per D-06.
- `backend/observability/__init__.py` (Phase 8) — Sentry `before_send` scrubber. Phase 11 D-27 extends.
- `backend/storage/blob_client.py` (Phase 10) — httpx Blob client; signed-URL minting. Phase 11 reads classifier source bytes via `mint_signed_url(pathname=uploads/{clip_id}.{ext})`.
- `backend/storage/__init__.py` (Phase 10) — `cleanup_blocked_clip(clip_id)` is exported here. Phase 11 imports + calls.
- `backend/Procfile`, `backend/railway.toml` — single `--workers 1`. Phase 11 changes neither.
- `backend/.env.example` — add `CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY`, `GEMINI_MODERATION_MODEL`, `MODERATION_MAX_BUDGET_S` per D-24.
- `backend/requirements.txt` — `httpx`, `tenacity`, `google-genai` already present (verify per Phase 10 D-23). No new pins beyond what Phase 10 added.
- `backend/tests/conftest.py` — extend with `MODERATION_PROVIDER` parametrize per D-25 (after Phase 10's `STORAGE_BACKEND` extension).
- `frontend/src/api.ts`, `frontend/src/types.ts` — `Segment` type gains `soft_flag: boolean`. Backend handoff only; UI lives in feature-track #6 (Roan).

### Forward-looking (do NOT implement now, but plan for)
- Phase 12 (REPORT-01..10) builds the admin queue. Phase 11 surfaces clips into the queue via `decision='unknown' + is_hidden=true` rows. Phase 12 owns the GET endpoint that lists these. **`_resume_pipeline(clip_id)` ownership: planner picks Phase 11 vs Phase 12.** If Phase 12, Phase 11 exposes `_resume_pipeline` as a function in `backend/pipeline/run.py`; Phase 12's admin endpoint imports + calls it. Recommendation: Phase 11 ships the function; Phase 12 ships the endpoint that calls it. Single ownership = single test surface.
- Phase 13 (OBS-05) wraps `stage="moderate"` in a Logfire span. Phase 11 keeps the gate in clean async boundaries (no blocking I/O in event loop) so Logfire's `span()` instrumentation works.
- Phase 13 (DEMO-02) firewalled CI smoke test asserts `OFFLINE_DEMO=true` startup makes zero outbound calls — Phase 11 D-21 is what that test asserts for the moderation surface.
- Phase 13 anonymity regression test asserts no `session_uuid`/`gps_lat`/`gps_lng`/`raw_response` ever appears in logs or span attributes. Phase 11 D-26 + D-27 + L-10 must stay aligned.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/pipeline/caption_pipeline.py:424-479`** — Gemini SDK upload + generate_content + JSON response_schema pattern. **D-11 reuses this verbatim** for the classifier — same SDK, same upload-poll-generate flow, same `response_mime_type='application/json'` + `response_schema=...`. Reduces Phase 11 to a config + prompt + schema diff over an existing pattern.
- **`backend/storage/blob_client.py` `mint_signed_url(pathname, ttl_seconds=900)`** (Phase 10 D-03) — exact tool for fetching classifier source bytes from private `uploads/`. No new storage abstraction needed.
- **`backend/storage/__init__.py` `cleanup_blocked_clip(clip_id)`** (Phase 10 D-20) — hard-block path's blob deleter. Phase 11 calls it; never reaches inside.
- **`tenacity` retry decorator** (already in requirements.txt, Phase 10 D-24) — transient 5xx retry posture for the Cloudflare CSAM client. Reuse the Phase 10 retry config.
- **structlog `bind_contextvars(clip_id=...)`** (Phase 8 D-08, called at `app.py:263` and `run.py:76`) — gate logs inherit `clip_id` automatically. No new contextvar bindings in Phase 11.
- **`asyncio.wait` with `return_when=FIRST_COMPLETED`** — Python stdlib pattern for the cancel-when-embed-finishes logic in D-02/D-03.
- **Phase 9 D-10 / Phase 10 D-21 conftest fixture** — parametrizes backends. Phase 11 D-25 extends with `MODERATION_PROVIDER`.

### Established Patterns
- **OFFLINE_DEMO graceful-degrade** (Phase 8 D-16, Phase 9 D-11, Phase 10 D-18) — Phase 11 D-21 mirrors: `OFFLINE_DEMO=true` → skip Cloudflare client init, return passthrough decision. One INFO log line per startup.
- **Empty-token-disables-endpoint** (Phase 8 `/metrics`, `/admin/reset`; Phase 10 `BLOB_READ_WRITE_TOKEN`) — Phase 11 mirrors with `CLOUDFLARE_CSAM_API_KEY` (empty + `CSAM_PROVIDER=cloudflare` + `OFFLINE_DEMO=false` → fail-loud at lifespan).
- **Single module-level httpx client** (Phase 10 D-02 Blob client; asyncpg pool from Phase 9 D-16) — Phase 11's Cloudflare CSAM client follows the same pattern: init in `lifespan()`, close in shutdown, fail-loud on missing config.
- **JSON response_schema for Gemini** (`caption_pipeline.py:474-476`) — established pattern; Phase 11 D-11 reuses for classifier.
- **`asyncio.create_task` + structlog contextvars survive task boundaries** (Phase 8 D-08) — gate spawns embed/Gemini tasks; both inherit `clip_id` automatically.
- **`asyncio.wait_for` outer + SDK-internal HTTP timeout** (`caption_pipeline.py:435,478`) — belt-and-suspenders timeout pattern. Phase 11's Gemini call mirrors (HTTP-level timeout via google-genai `HttpOptions(timeout=...)` + asyncio.wait or wait_for at the call site).
- **Lift-and-shift module-split dispatcher** (Phase 9 D-07/D-08; Phase 10 D-12/D-13) — `CSAM_PROVIDER` selector in `backend/pipeline/moderate.py` mirrors the pattern: import-time selection, no per-request branching, OFFLINE_DEMO hard-overrides to stub.

### Integration Points
- **`backend/pipeline/run.py:79`** — `await embed_worker(clip_id)` becomes the orchestrated gate per D-01/D-02. STAGE_DURATION wrap extended to `stage="moderate"`.
- **`backend/pipeline/moderate.py`** (new, D-22) — `moderate_clip(clip_id)` entry point + `csam_check(clip_id, hash)` + Gemini classifier helper + `SYSTEM_PROMPT` + `PROMPT_VERSION` constants.
- **`backend/pipeline/csam_client.py`** (new, optional split — D-22 keeps it inside moderate.py; planner can split if it grows). Cloudflare CSAM HTTP client wrapper.
- **`backend/db_postgres.py` / `backend/db_sqlite.py`** — new functions: `write_moderation_decision(clip_id, provider, decision, reason, raw_response, latency_ms, prompt_version)`, `set_clip_hidden(clip_id, hidden)`, `write_reported_csam(content_hash, preserved_until)`, `get_moderation_decisions(clip_id)`, `aggregate_verdict(clip_id) -> 'passed'|'blocked'|'unknown'`. Both backends mirror Phase 9 D-07 module-split contract.
- **`backend/migrations/versions/20260429_0003_moderation_decisions_columns.py`** (new) — ALTER ADD COLUMN per D-13. Naming convention from Phase 9 D-22.
- **`backend/migrations/versions/20260429_0004_segments_soft_flag.py`** (new, conditional on D-14 column-vs-derived choice) — `ALTER TABLE segments ADD COLUMN soft_flag BOOLEAN NOT NULL DEFAULT FALSE`.
- **`backend/app.py` `lifespan()`** — add Cloudflare CSAM client init (after asyncpg pool, after Blob client, before pre-warm). Order: XFFStrip middleware → asyncpg pool → Blob httpx client → CSAM httpx client → Marengo pre-warm → CLUSTERS rebuild → Neon keepalive → yield.
- **`backend/config.py`** — new env vars per D-24. Phase 8/9/10 comment-block style.
- **`backend/.env.example`** — document new env vars per D-24.
- **`backend/observability/__init__.py`** — extend Sentry `before_send` scrubber list per D-27.
- **`backend/observability/metrics.py`** — `STAGE_DURATION` Histogram already exists from Phase 8 D-17. Phase 11 just adds `stage="moderate"` as an enum value at the call site (no metric definition change).
- **`backend/tests/conftest.py`** — extend backend matrix with `MODERATION_PROVIDER` parametrize per D-25.
- **`backend/pipeline/compile.py`** — when `segments.soft_flag` column lands (D-14), compile_segment writes `soft_flag=true` if any cluster member's moderation_decisions has a soft-flag-category signal. Compile-time read of decisions via `get_moderation_decisions(clip_id)` for each member.
- **`backend/app.py` admin endpoints** (Phase 12 will add `POST /admin/reports/{id}/action` and `GET /admin/reports`) — Phase 12 imports `_resume_pipeline(clip_id)` from `backend/pipeline/run.py` (Phase 11 exposes it; Phase 12 calls it).
- **`frontend/src/types.ts`** — `Segment` interface gains `soft_flag: boolean`. Backend handoff to Roan; frontend UI implementation lives in feature-track #6.

</code_context>

<specifics>
## Specific Ideas

- **Cancel-when-embed-finishes (D-03) is the load-bearing latency primitive.** Tying Gemini's effective ceiling to Marengo's elapsed time means common-case latency is exactly Marengo's latency — zero regression by construction. The fragility (false-positive blocks when Gemini is genuinely slow) is bounded by the optional `MODERATION_MAX_BUDGET_S` cap and the admin-queue path for the `unknown` tier.
- **CSAM-first sequential (D-16) trades ~1s of latency for token-cost savings + statutory clarity.** Cloudflare CSAM hash check is fast (~1s); running it before Gemini means confirmed CSAM never spends Gemini tokens AND we have a clean "we never ingested the bytes for AI inference" audit trail for the worst case.
- **`CSAM_PROVIDER=stub` + lifespan production-guard (D-18) is the hackathon-pilot bridge.** Cloudflare CSAM/NCMEC approval has unknown lead time. Without the stub-and-ship pattern, Phase 11 blocks indefinitely on a process gate. The lifespan guard is the safety net that prevents accidental "shipped to prod with stub still on" disasters.
- **Per-provider rows in moderation_decisions (D-10) is the audit-friendly choice.** When Gemini hallucinates a verdict and we want to debug, the row is right there with `raw_response` JSONB. When CSAM hits and we need to reconstruct what was reported to NCMEC, the CSAM row is right there. UNIQUE(clip_id, provider) enforces idempotency on retry — running the gate twice produces the same row count.
- **The hate/violence soft-flag broadening (D-08) is policy-significant.** MOD-07 as written is corroboration-only ("≥2 distinct parents AND violence signal"). User direction broadens to all hate/violence regardless of corroboration, with the rationale that solo violence in news context (an isolated incident filmed once) should still appear with a tap-to-view warning. The corroboration gate stays in `_should_compile` for compile-eligibility (don't waste tokens on solo-source compiles), but the soft-flag is decoupled from it. **REQUIREMENTS.md amendment owed before plan execution.**
- **Off-topic safe content passes (D-09).** A clip of a dog or a sunset isn't blocked by the moderation gate — the gate is about safety, not editorial fit. Phase 12's admin queue is the human-in-the-loop for "this is off-topic; hide it." Keeps Phase 11's automation conservative and reversible.

</specifics>

<deferred>
## Deferred Ideas

- **`segments.soft_flag` column placement (D-14)** — Punted to planner. Default recommendation: column (not derived). Migration: `0004_segments_soft_flag.py`.
- **`_resume_pipeline(clip_id)` ownership (Phase 11 vs Phase 12)** — Punted to planner. Recommendation: Phase 11 exposes the function; Phase 12 ships the admin endpoint that calls it.
- **Absolute upper-bound cap on classifier timeout** — Punted to planner via `MODERATION_MAX_BUDGET_S` env var (D-24). Default to be set after Gemini Flash-Lite latency benchmark (D-29 pre-flight TODO) — recommendation pending: 20s.
- **CSAM API timeout budget** — Punted to planner. Cloudflare CSAM API latency unknown until research validates. Sequential gate position (D-16) means CSAM timeout adds directly to upload-to-publish latency; recommendation: 5s hard cap.
- **NCMEC CyberTipline report API call ownership** — Cloudflare may handle on our behalf; if not, Phase 11 owns it. **Research deliverable for `gsd-phase-researcher`** (D-20). May add `ncmec_report_id TEXT` column to `reported_csam` (additive, plan-time decision).
- **Aggressive prompt for "is this local news"** — Out of scope. User explicitly rejected ("dont prohibit off topic"). Off-topic detection lives in Phase 12 admin queue, not Phase 11 automation.
- **Pre-ingest sync moderation gate** — Rejected (D-04). 202 fire-and-forget preserved. Fast-cleanup post-ingest path satisfies "don't persist weird bytes" intent.
- **Adversarial-probing detection (classifier-mapping defense)** — Deferred v1.2 (REQUIREMENTS.md "Future Requirements").
- **Auto-takedown by report count** — Deferred v1.2 (REQUIREMENTS.md "Future Requirements" — also explicitly rejected by REPORT-10 for Phase 12).
- **Per-IP rate limit on /clips** — Deferred v1.2 (PROJECT.md "Out of Scope"; rate_limit.py already exists for /report-style flows but not /clips).
- **Per-admin login system** — Deferred v1.2 (REPORT-09 Phase 12 uses single shared `ADMIN_TOKEN`).
- **Background sweeper for orphan blob cleanup** — Out of scope. BLOB-08 synchronous hook (Phase 10 D-20) is sufficient. Phase 11 always calls it on hard-block.
- **Soft-flag richer schema (`soft_flag_reason` string + i18n)** — Phase 11 ships boolean only (D-15). If Roan's UI needs context strings, follow-up ALTER is cheap.

### Verifications Owed (research / planning surface)
- **D-29 Gemini Flash-Lite latency benchmark** — Run on the v1.0 staged demo dataset before plan execution. Sets `MODERATION_MAX_BUDGET_S` default. STATE.md `Pending Todos` already flags this.
- **D-29 Cloudflare CSAM/NCMEC approval status** — Liam to surface application status before plan execution. If approved → `CSAM_PROVIDER=cloudflare` ships; if not → `CSAM_PROVIDER=stub` ships with the production-guard caveat in D-18. STATE.md `Pending Todos` already flags this.
- **D-20 NCMEC CyberTipline reporting workflow** — Research: does Cloudflare CSAM Scanning Tool report to NCMEC on our behalf, or do we own the report API call? Determines whether `reported_csam` needs an `ncmec_report_id TEXT` column.
- **D-08 REQUIREMENTS.md MOD-07 amendment** — Liam to update REQUIREMENTS.md MOD-07 wording and STATE.md `Locked Decisions` to reflect "all hate + all violence soft-flag, no corroboration gating" before plan execution.
- **D-19 REQUIREMENTS.md MOD-09 amendment** — Liam to update REQUIREMENTS.md MOD-09 + STATE.md `Locked Decisions` to drop the stale 90-day figure; lock 1-year retention.
- **D-17 Cloudflare hash algorithm** — Research: what hash format does Cloudflare CSAM Scanning Tool require (PDQ? PhotoDNA? plain SHA?)? Determines the hash-compute step in D-02.
- **D-21 OFFLINE_DEMO firewalled CI smoke test extension** — Phase 13 owns DEMO-02 but Phase 11 must guarantee zero outbound calls under OFFLINE_DEMO=true. Wave-0 smoke deploy (D-28) verifies in staging.

</deferred>

---

*Phase: 11-moderation-gate-gemini-flash-lite-csam-hash*
*Context gathered: 2026-04-29*

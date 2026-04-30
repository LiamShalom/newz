# Phase 11: Moderation Gate (Gemini Flash-Lite + CSAM hash) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 11-moderation-gate-gemini-flash-lite-csam-hash
**Areas discussed:** Failure-mode + budget, Soft-flag (MOD-07/08), CSAM + retention, Schema + classifier

---

## Failure-mode + budget

### Q1 — Gemini classifier timeout budget

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed 8s wait_for | Hard cap at 8s. Below typical Marengo p50; misses → fail-CLOSED. Simple. (Originally recommended pending benchmark.) | |
| Match embed window | Tied to Marengo's elapsed time as Gemini's effective ceiling. Self-tuning. | ✓ |
| Block on benchmark first | Refuse to lock budget until Gemini Flash-Lite latency benchmark TODO from STATE.md is run. | |

**User's choice:** Match embed window — clarified during follow-up to mean cancel-when-embed-finishes (`asyncio.wait` + `FIRST_COMPLETED` then explicit `.cancel()`). Common-case latency = Marengo's latency by construction.
**Notes:** Absolute upper-bound cap (e.g., `min(marengo_elapsed, MAX_BUDGET=20s)`) punted to planner via `MODERATION_MAX_BUDGET_S` env var (CONTEXT.md D-24). Default to be set after Gemini Flash-Lite latency benchmark.

### Q2 — Timeout vs 5xx outage tier classification in code

| Option | Description | Selected |
|--------|-------------|----------|
| asyncio.TimeoutError vs HTTP | Typed exceptions. TimeoutError + 4xx → blocked. 5xx + network errors → unknown. Clean catch-by-type. | ✓ |
| Anything-non-2xx = unknown | Only TimeoutError blocks; all HTTP failures route to admin queue. Bad config silently floods admin queue. | |
| Separate retry layer | Tenacity retry around classifier; tier-classify only after retry exhaustion. Eats budget; masks signal. | |

**User's choice:** Option A (typed exceptions, 4xx blocks).
**Notes:** Locked because the tier distinction is functionally important (anonymity vs reliability tradeoff). 4xx-as-blocked is the load-bearing piece — bad payload / auth fail / weird codec are suspicious, not "the world is broken."

### Q3 — Unknown clip handling (admin queue path)

| Option | Description | Selected |
|--------|-------------|----------|
| is_hidden=true; pause cluster | Set is_hidden=true, skip clustering/compile. Admin must clear before clip enters feed. Conservative. | ✓ |
| is_hidden=true; cluster runs | Hidden but speculatively cluster + compile. Faster admin-clear UX; wastes Claude tokens on potentially-blocked clips. | |
| Hidden until ANY decision | Don't write moderation_decisions; auto-retry classifier on backoff. Reintroduces broker pattern v1.0 avoided. | |

**User's choice:** Option 1 (pause cluster). Admin endpoint flips `is_hidden=false` + writes fresh `decision='passed'` row + fires `_resume_pipeline(clip_id)`.
**Notes:** `_resume_pipeline` ownership (Phase 11 vs Phase 12) punted to planner. Recommendation: Phase 11 exposes the function; Phase 12 ships the admin endpoint that calls it.

### Q4 — Gate placement in pipeline

| Option | Description | Selected |
|--------|-------------|----------|
| Replace embed_worker call site | Swap bare `await embed_worker` for `asyncio.gather(embed, moderate)` in `run_pipeline`. Maps 1:1 to MOD-02. | ✓ |
| Inside embed_worker | Spawn moderate as sibling task inside embed_worker. Couples two concerns into one module. | |
| Pre-embed sequential gate | Sequential moderation before embed. Violates MOD-03 (latency regresses). | |

**User's choice:** Option 1 — `run_pipeline:79` is the call site. `embed_worker` and `moderate_clip` stay orthogonal modules.
**Notes:** New `stage="moderate"` STAGE_DURATION label permitted under Phase 8 D-17 bounded-label policy.

---

## Soft-flag (MOD-07/08)

### Q1 — Verdict map from Gemini classifier output → action

| Option | Description | Selected |
|--------|-------------|----------|
| Block-weird, soft-corroborated | CSAM/sexual/weird → block. Solo violence → pass. Corroborated violence → soft-flag. Matches MOD-07 literal. | |
| Block-weird, soft ALL violence | Same as above but all violence (solo or corroborated) soft-flags. | |
| Block-weird, no soft-flag | Drop MOD-07 entirely. Violence passes; weird blocks. No interstitial system. | |
| (User-provided refinement) | "block weird, soft violence, dont prohibit off topic" — and later: hard-block CSAM/sexual/extremist/self_harm; soft-flag hate/violence; off-topic safe → pass. | ✓ |

**User's choice:** Custom policy via two iterations:
1. First pass: "block weird, soft violence, dont prohibit off topic" — narrowed scope to safety categories only; off-topic safe content passes.
2. Refinement after summary: "hard flag on anything sexual, extremist, self harm. Soft flag on hate, or violence since these things should appear in news but be warned against. The hard flags should completely block those from being ingested" — moved hate from hard-block to soft-flag (news-context); moved self_harm from soft-flag to hard-block (no news-context defense on a public hyperlocal feed).

**Final lock:**
- Hard-block: csam, sexual, extremist, self_harm. Any signal in these categories (verdict ∈ {flag, block}) → immediate `cleanup_blocked_clip`.
- Soft-flag: hate, violence. Any signal → `soft_flag=true` on segment; never hard-block regardless of corroboration.
- Pass: off-topic safe content.

**Notes:** **Deviation from REQUIREMENTS.md MOD-07** which specifies corroboration-only soft-flag. Liam todo: amend MOD-07 + STATE.md `Locked Decisions` before plan execution.

### Q2 — Detection aggressiveness for "weird non-news"

| Option | Description | Selected |
|--------|-------------|----------|
| Punt to research | gsd-phase-researcher probes Gemini Flash-Lite category reliability + proposes prompt + JSON schema. | ✓ |
| Safety-only + admin queue | Phase 11 detects only stock safety categories; admin queue handles weirdness. | |
| Aggressive prompt up front | Lock strict "is this local news?" prompt; accept high false-positive risk. | |

**User's choice:** Punt to research.
**Notes:** Made more tractable by the user's "dont prohibit off topic" — narrows scope to Gemini stock safety categories (well-trained), not domain-specific "is this local news" judgment.

### Q3 — Pre-ingest reject vs post-ingest cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| Post-ingest, fast cleanup | Bytes land in private uploads/, classifier runs in parallel with embed, on block call cleanup_blocked_clip immediately. Sub-second persistence on block. 202 fire-and-forget preserved. | ✓ |
| Pre-ingest sync gate | POST /clips runs Gemini synchronously before blob write. User waits 5–15s. Violates 202 design. | |
| Pre-ingest cheap + post-ingest deep | Existing pre-ingest sanity (size/MIME) + post-ingest classifier. Functionally same as option 1. | |

**User's choice:** "whichever is most efficient" → Option 1 (post-ingest, fast cleanup).
**Notes:** User's "don't even need to ingest vid" intent satisfied via fast cleanup, not pre-ingest rejection.

### Q4 — Roan's contract for tap-to-view interstitial

| Option | Description | Selected |
|--------|-------------|----------|
| Boolean in /feed | Add `soft_flag: boolean` to each segment in /feed JSON. Roan picks up under feature-track #6. | ✓ |
| Boolean + reason | `{soft_flag: true, soft_flag_reason: 'graphic_content'}`. One extra field; one i18n surface. | |
| Skip if Q1=no-soft-flag | (Conditional fallback for Q1=option3.) | |

**User's choice:** Boolean in /feed.
**Notes:** Minimum-contract. If Roan needs context strings later, follow-up ALTER is cheap.

---

## CSAM + retention

### Q1 — MOD-09 retention reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| 1 year (statutory minimum) | content_preserved_until = NOW() + INTERVAL '1 year'. Matches 2024 REPORT Act amendment to 18 U.S.C. § 2258A. | ✓ |
| 1 year + 30 day buffer | 13-month padding for clock skew / time-zone edge cases. | |
| Make it env var | CSAM_RETENTION_DAYS env var, default 365. | |

**User's choice:** 1 year exactly.
**Notes:** **Liam todo:** amend REQUIREMENTS.md MOD-09 + STATE.md `Locked Decisions` to drop the stale 90-day figure before plan execution. Phase 9 explicitly punted this reconciliation to Phase 11.

### Q2 — Order of CSAM hash vs Gemini classifier

| Option | Description | Selected |
|--------|-------------|----------|
| CSAM-first sequential | Hash + Cloudflare check first (~1s). On hit → fail-CLOSED, skip Gemini. On miss → embed + Gemini parallel. Saves Gemini tokens on confirmed CSAM. | ✓ |
| Both parallel inside gather | asyncio.gather(embed, gemini, csam, return_exceptions=True). Spends Gemini tokens even on CSAM hit. | |
| Hash-only first; defer Gemini | Sequential CSAM, then Gemini AFTER embed completes. Violates MOD-03 (latency regression). | |

**User's choice:** CSAM-first sequential.
**Notes:** Adds ~1s of CSAM latency to upload-to-publish; acceptable per statutory requirement (CSAM is a strict pre-condition per MOD-04, not a parallel arm). CSAM check timeout budget punted to planner; recommendation 5s hard cap.

### Q3 — Cloudflare CSAM/NCMEC approval risk fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Stub-and-ship | CSAM_PROVIDER env var (cloudflare | stub). Stub returns "no match" always. Lifespan guard against accidental "ship to prod with stub" deploys. | ✓ |
| Block ship until approval | Don't ship Phase 11 until approval in hand. | |
| Try interim provider | PhotoDNA / Thorn / open-source PDQ. Each has own approval/cost story. | |

**User's choice:** Stub-and-ship.
**Notes:** Pre-flight TODO from STATE.md (Cloudflare CSAM/NCMEC approval lead time) becomes a research deliverable. Lifespan production-guard recommendation: refuse to start when `CSAM_PROVIDER=stub` AND `OFFLINE_DEMO=false` AND production environment, unless explicit `CSAM_STUB_ALLOW_PRODUCTION=true` override.

### Q4 — Hash location (server-side vs client-side)

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side after blob upload | Gate task downloads bytes from private uploads/ via signed URL, computes hash, POSTs to Cloudflare. | ✓ |
| Server-side at ingest | Hash inline in POST /clips before 202. Adds ~200ms–1s to upload response. | |
| Streaming hash during upload | Hash bytes incrementally as they stream from client to blob. More complex; marginal benefit at <100 MiB cap. | |

**User's choice:** Server-side after blob upload.
**Notes:** Mirrors Phase 10 D-08 signed-URL ingest pattern. Bytes never leave our infra except to classifier provider; Cloudflare receives hash only. PRIV-03 strip rules apply trivially.

---

## Schema + classifier

### Q1 — moderation_decisions row granularity

| Option | Description | Selected |
|--------|-------------|----------|
| One row per provider call | Two rows per clip: provider='cloudflare_csam' + provider='gemini_flash_lite'. Aggregate verdict computed at read time. | ✓ |
| One aggregate row per clip | Single row holds both verdicts in JSONB. Mushes audit boundaries. | |
| Per-call rows + materialized aggregate | Both: per-provider rows + denormalized clips.moderation_status. | |

**User's choice:** One row per provider call.
**Notes:** UNIQUE(clip_id, provider) for idempotency on retry. Easier to swap a provider without schema churn.

### Q2 — Gemini classifier response schema

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed category enum | Locked taxonomy ['csam', 'sexual', 'hate', 'extremist', 'violence', 'self_harm']. Each {verdict, score, rationale}. Stable test target. | ✓ |
| Categories punted to research | gsd-phase-researcher proposes the category list based on Flash-Lite training. | |
| Freeform JSON | Gemini returns {decision, primary_concern, notes}. No category breakdown. | |

**User's choice:** Fixed category enum.
**Notes:** Mirrors `caption_pipeline.py:474-476` `response_schema` pattern. Verdict ∈ {pass, flag, block}.

### Q3 — System prompt ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Planner-owned + research-informed | gsd-phase-researcher proposes prompt in RESEARCH.md; lives in moderate.py with SYSTEM_PROMPT + PROMPT_VERSION constants. | ✓ |
| Lock the prompt now | Draft exact prompt during this discussion. | |
| Use Gemini's safety filters only | Skip custom prompt; rely on HARM_CATEGORY_*. Limits to Google's taxonomy. | |

**User's choice:** Planner-owned + research-informed.
**Notes:** PROMPT_VERSION stored on every moderation_decisions row for audit. Iterates as misses surface in admin queue.

### Q4 — Audit data per row

| Option | Description | Selected |
|--------|-------------|----------|
| Full redacted response | decision + reason + provider + raw_response (JSONB, PRIV-03 stripped) + latency_ms + prompt_version + created_at. | ✓ |
| Decision + reason only | Minimal columns; loses post-hoc debugging value. | |
| Redacted summary | Categories JSONB summary, no full response. Middle-ground. | |

**User's choice:** Full redacted response.
**Notes:** PRIV-03 strip enforced at write time via dedicated helper. Sentry `before_send` scrubber list extended to include `raw_response` (CONTEXT.md D-27).

---

## Claude's Discretion

Items captured in CONTEXT.md `<decisions>` D-22..29 where the user said "you decide" implicitly by not raising concerns:

- D-22: Module location (`backend/pipeline/moderate.py` single module)
- D-23: httpx Cloudflare client lifecycle (lifespan-managed singleton; tenacity retry)
- D-24: New env var names (`CSAM_PROVIDER`, `CLOUDFLARE_CSAM_API_KEY`, `GEMINI_MODERATION_MODEL`, `MODERATION_MAX_BUDGET_S`)
- D-25: Test fixture extension (`MODERATION_PROVIDER` parametrize; recorded-tape style mocks)
- D-26: Logging shape (structured INFO line per gate stage; raw responses NOT in logs)
- D-27: Sentry scrubber list extension (raw_response, csam_hash, prompt_version)
- D-28: Wave-0 smoke deploy posture (mirror Phase 9/10)
- D-29: Pre-flight TODO carry-overs (latency benchmark, approval status) → research deliverables

Punted to planner (recommendations in CONTEXT.md `<deferred>`):
- `segments.soft_flag` column placement (D-14): recommended column over derived
- `_resume_pipeline(clip_id)` ownership (Phase 11 vs Phase 12): recommended Phase 11 exposes function, Phase 12 owns endpoint
- Absolute upper-bound cap on Gemini timeout: recommended 20s default
- CSAM API timeout budget: recommended 5s hard cap

---

## Deferred Ideas

- **Aggressive "is this local news" prompt** — User explicitly rejected ("dont prohibit off topic"). Off-topic detection lives in Phase 12 admin queue.
- **Pre-ingest sync moderation gate** — Rejected (D-04). 202 fire-and-forget preserved.
- **Adversarial-probing detection** — v1.2 (REQUIREMENTS.md "Future Requirements").
- **Auto-takedown by report count** — v1.2; also explicitly rejected by REPORT-10 for Phase 12.
- **Per-IP rate limit on /clips** — v1.2 (PROJECT.md "Out of Scope").
- **Per-admin login system** — v1.2 (Phase 12 uses single shared ADMIN_TOKEN).
- **Background sweeper for orphan blob cleanup** — Out of scope. BLOB-08 synchronous hook is sufficient.
- **Soft-flag richer schema (`soft_flag_reason` + i18n)** — Phase 11 ships boolean only; follow-up ALTER if Roan's UI needs context.

### Verifications Owed (research / planning surface)
- Gemini Flash-Lite latency benchmark on demo dataset (sets `MODERATION_MAX_BUDGET_S`)
- Cloudflare CSAM/NCMEC approval status (determines whether `CSAM_PROVIDER=cloudflare` ships or stub-and-defer)
- NCMEC CyberTipline reporting workflow (does Cloudflare report on our behalf, or do we own the API call?)
- REQUIREMENTS.md MOD-07 amendment (broaden soft-flag to all hate + all violence, drop corroboration gating)
- REQUIREMENTS.md MOD-09 amendment (1-year retention, drop stale 90-day figure)
- Cloudflare hash algorithm (PDQ? PhotoDNA? plain SHA?)
- OFFLINE_DEMO firewalled CI smoke test extension to moderation surface

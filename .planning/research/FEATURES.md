# Feature Research

**Domain:** Anonymous citizen-journalism UGC video platform — production-readiness backbone (DB persistence, object storage, AI moderation, reactive reporting, observability)
**Researched:** 2026-04-27
**Confidence:** MEDIUM-HIGH (HIGH on infra patterns, MEDIUM on moderation policy specifics — citizen-journalism is an awkward middle ground between social UGC and news platforms, with little public playbook)

## Scope Note

This is **subsequent-milestone** research for v1.1. v1.0 features (capture, embed, cluster, compile, feed, SSE, MIME ladder, admin reset) are shipped and out of scope here. Each feature below is positioned **relative to the existing v1.0 hot path**: `Browser → POST /clips (202) → embed → cluster → compile → stitch → SSE`.

The five v1.1 feature areas:
1. DB persistence (SQLite-on-volume → managed Postgres)
2. Object storage (Railway volume → Vercel Blob, with an open question about whether Blob is even the right choice)
3. Pre-publish AI moderation gate
4. Reactive reporting + admin review queue
5. Production observability

## Anonymity-by-Default Tension (Read First)

This product's load-bearing constraint creates specific feature tradeoffs that recur across the five areas. Calling them out once here so the per-feature tables can stay tight:

| Tension | Where it bites |
|---------|----------------|
| **No accounts → no per-user reputation** | Can't weight reports from "trusted" reporters higher; can't shadow-ban; can't soft-suspend repeat offenders |
| **No accounts → no ban-evasion defense** | Session UUID in localStorage is trivially reset; IP fingerprints leak to backend even if not stored, and storing them retroactively breaks the anonymity narrative |
| **No accounts → no creator notifications** | Can't tell uploader their clip was rejected; rejection happens silently from their POV |
| **No accounts → no appeals process** | If moderation false-positives, the uploader has no identity to appeal under |
| **No accounts → mass-report brigading is harder to detect** | Can't correlate reports to "this account always reports X" |

**Implication:** Several feature patterns from major platforms (X, Reddit, BlueSky) are **anti-features for Newz** because they assume accounts. Flagged inline below.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist on a public-facing video platform in 2026. Missing these = product feels broken or unsafe.

#### Area 1: Database persistence

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Managed Postgres (Neon or Supabase) | SQLite-on-volume is a single-instance death sentence the moment Railway restarts mid-write | LOW (1-2 days) | Neon = serverless/scale-to-zero, native Vercel integration; Supabase = always-on, full BaaS. **Recommend Neon** — Newz is bursty (zero traffic between live demos), Vercel-hosted frontend, and we don't need Supabase auth/storage/realtime (we have anonymity, Blob, SSE) |
| Schema migrations via Alembic | SQLAlchemy is the FastAPI-Postgres standard; ad-hoc DDL is unmaintainable | LOW (1 day) | Alembic + async SQLAlchemy is the canonical FastAPI stack. Initial migration recreates v1.0 schema (`clips`, `child_clips`, `clusters`, `segments`) |
| Connection pooling | FastAPI async + Postgres without pooling = connection exhaustion under any load | LOW | Neon ships native pooling via WebSocket driver; Supabase uses PgBouncer transaction-mode. Either works for asyncpg/SQLAlchemy async |
| Daily automated backups | Data loss = product death; managed providers do this for free on the lowest paid tier | LOW (config flag) | Neon free tier has 7-day history; Supabase Pro has daily backups + 7-day retention by default |
| `CLUSTERS` rebuild on startup from Postgres | v1.0 already does this from SQLite; same code path, different driver | LOW | Already designed for this — in-memory dict rebuilt at boot. Driver swap is the only change |
| Connection-level retries / circuit breaker | Managed Postgres has occasional cold starts (Neon scale-to-zero) and transient network hiccups | LOW | `tenacity` already in stack from Marengo retry; reuse for asyncpg |

#### Area 2: Object storage for clip media

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Off-host blob storage | Single-volume storage = single-host failure = total media loss; also blocks horizontal scaling | LOW-MED (2-3 days) | **OPEN QUESTION**: Vercel Blob has confirmed limitations — no native TTL/lifecycle policies, signed URL support is incomplete per GitHub issue #544. **Cloudflare R2 is the safer bet** for a video-heavy workload: zero egress, signed URLs work, lifecycle rules supported, ~98% cheaper than S3 at video bandwidth scale. Flag this for requirements/roadmap discussion |
| Direct browser upload to blob (presigned URL) | Round-tripping clips through the FastAPI host doubles bandwidth and adds latency | MED (3-4 days) | Frontend hits backend → backend returns presigned PUT URL → browser uploads directly. Backend gets a `POST /clips/finalize` callback after upload. Removes a whole class of memory/timeout bugs from FastAPI |
| Signed read URLs with TTL on segment playback | Public URLs leak forever, hot-link, exfiltrate; signed URLs let us rotate access | LOW | R2/S3: trivial. Vercel Blob: incomplete — ANTI-PATTERN if Vercel Blob is chosen and we need access control |
| HTTP range request support for video scrubbing | iOS Safari `<video>` will stall/fail without `Accept-Ranges: bytes` for non-trivial clips | LOW | All major blob services support this natively; just don't proxy through FastAPI without explicitly supporting ranges |
| Lifecycle: orphan-clip deletion after N days | Clips that never cluster (singletons aged > N days) cost money and contribute nothing; clips uploaded but never finalized are orphans | LOW (R2/S3) / HIGH (Vercel Blob — manual cron) | R2: lifecycle rules. S3: lifecycle rules. Vercel Blob: must implement manual sweeper job (community-confirmed limitation). Suggest 30 days for unclustered, indefinite for clustered |
| Stitched-segment cache (re-stitching is expensive) | Don't re-run ffmpeg on every replay | LOW | Already on disk in v1.0; just becomes a Blob put. Cache key = sorted parent_clip_ids hash |

#### Area 3: Pre-publish AI moderation

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **CSAM hash matching against NCMEC database** | **18 U.S.C. § 2258A makes reporting CSAM legally mandatory the moment a US-jurisdiction provider becomes aware of it.** Failure = federal crime, $150K-$300K fine. Non-negotiable. | MED (2-3 days) | **PhotoDNA Cloud Service** (free for qualifying platforms) is the right path; **Cloudflare CSAM Scanning Tool** is the easier-onboard option since direct PhotoDNA access requires NCMEC approval. Hash check happens on the first frame(s); no model inference needed for the hash check itself. **Must preserve content + records 90 days post-CyberTipline report** — this constrains DB schema (need a `reported_csam` table that doesn't auto-purge) |
| Pre-publish moderation gate (parallel with embed) | Once published, takedown is reactive; moderation must happen before SSE broadcast | MED (3-5 days) | Run moderation API call concurrently with Marengo embed via `asyncio.gather`. Cluster step is gated on both passing. Categories to gate: nudity (any), CSAM (hard block + report), explicit hate symbols, weapons-aimed-at-camera. Categories to NOT gate as hard-block: violence (newsworthy in citizen journalism context), drugs, alcohol, blood/injury (news context) |
| Vendor for visual moderation | Hive, AWS Rekognition, Sightengine, Google Vision SafeSearch all viable | LOW (vendor swap) | **Recommend Hive** for citizen-journalism: 50+ granular classes lets us distinguish "weapon brandished" (gate) from "weapon visible at scene" (allow with warning). Rekognition is cheaper but coarser. Avoid OpenAI Moderation API — text-only |
| Soft gate (interstitial warning) for graphic-but-newsworthy content | X's playbook: gory + newsworthy = allowed, behind click-to-view interstitial. This is the standard for news content per X's published Violent Content Policy | MED | Add `sensitive` boolean to segment record; frontend shows "Tap to view sensitive content" overlay. **This is a differentiator-grade table-stakes feature** — without it, the moderation gate either becomes useless (passes everything) or kills the news use case (blocks dramatic real events) |
| Failure-open vs failure-closed decision | Moderation API down = should we block all uploads or let them through? | LOW (config) | Standard in production: failure-open with retry queue + alerting. Justification: false-block on legitimate news event = product credibility death. **Verify and document this decision explicitly**. Counterargument: failure-open during outage means CSAM could slip through PhotoDNA gate. Recommend **failure-closed for CSAM hash, failure-open for everything else** |

#### Area 4: Reactive reporting

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| "Report" button on every segment | Post-publish, users are the second moderation layer; without this, public launch is reckless | LOW (1-2 days frontend + backend) | Anonymous report: user picks category from short list (CSAM / Violence-promoting / Hate / Misinformation / Spam / Other), optional 200-char text, submit. POST `/segments/{id}/report` with session UUID + report. Returns 204. **Frontend MUST show "thanks" toast even if backend fails** — never let the user know whether the report "took" (defeats trolls who probe for grief) |
| Admin review queue | Reports that don't reach a human are theater | MED (3-5 days) | Simple admin SPA route at `/admin/queue` (token-guarded same as `/admin/reset`). Queue ordered by report-count DESC, timestamp ASC. Each row: thumbnail, segment metadata, all reports, action buttons (Dismiss / Take Down / Add Sensitive Tag). Take-Down sets `segment.status = 'removed'`, broadcasts SSE removal, leaves DB row for audit |
| Per-segment report deduplication | Otherwise N anonymous users reporting once each is indistinguishable from 1 user reporting N times via localStorage reset | MED | Fingerprint = hash(session_uuid + IP-prefix + segment_id) — best-effort dedup. **Trade-off**: storing IP-prefix is a small anonymity compromise. Alternative: dedupe only on session_uuid and accept brigading risk. **Flag for product decision** |
| Report rate limiting per session | One session shouldn't be able to mass-report 100 segments in 60s — that's brigading | LOW | Token bucket per session_uuid: 10 reports/hour, 50/day. Aligns with Meta's published anti-brigading approach |
| Report SLA target | Volunteer-reviewed at small scale = "within 24 hours for P1 (CSAM/violence-promoting), 72 hours for P2 (everything else)" | N/A (policy, not code) | Industry standard for small UGC platforms. Document in pitch deck / TOS, not in code |
| Auto-takedown threshold (kill switch) | If a segment hits N reports in M minutes, auto-pull pending review (to limit blast radius) | LOW | Suggest 10 reports / 1 hour → auto-mark `status='under_review'`, hide from feed, restore on admin clear. **CAREFUL**: this is exactly the brigading vector Meta calls out. Tune conservatively, log every auto-takedown for audit |

#### Area 5: Production observability

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Structured JSON logs | grepping unstructured logs across pipeline stages doesn't scale past 1 person | LOW (1 day) | `structlog` with `contextvars` for request correlation. Every log has `request_id`, `session_uuid`, `pipeline_stage`. FastAPI middleware injects request_id |
| Sentry for error tracking | Unhandled exceptions in `asyncio.create_task` fire-and-forget pipelines silently disappear without it | LOW (half day) | `sentry_sdk[fastapi]` with `AsyncioIntegration()` — this is the canonical wiring. Set `traces_sample_rate=0.1` for perf, 1.0 for errors. **Critical**: must wrap every `create_task` callsite in error-capturing wrapper, or async exceptions will be swallowed |
| Per-pipeline-stage success rate metrics | "20% of uploads fail" is useless; "20% of uploads fail at the cluster stage with reason X" is actionable | MED (2-3 days) | Counters: `clips_received`, `embed_success/fail`, `moderation_pass/block/error`, `cluster_assigned/created/orphan`, `compile_started/succeeded/timeout/error`, `stitch_succeeded/error`, `segments_published`. Histogram per stage for latency. Export to Sentry or Prometheus |
| Span-level tracing across multi-agent compile | The Claude Agent SDK pipeline has 3+ subagents in parallel; a single failed agent shows as "compile timeout" without spans | MED (3-4 days) | **Langfuse** is the right tool here — purpose-built for LLM/multi-agent traces, OpenTelemetry-compatible. Each subagent (Angle Selector, Caption Writer) becomes a child span; Gemini call becomes a span; ffmpeg stitch becomes a span. Alternative: OpenLLMetry + Sentry traces, but Langfuse has prompt management + eval as bonus |
| Per-model latency tracking with percentiles | p50 hides tail latency; the 300s compile budget exists because we already learned this | LOW (covered by tracing) | p50/p95/p99 for: Marengo embed, moderation API, Gemini caption, Claude subagents (each), ffmpeg stitch. Surface in Langfuse dashboard or Grafana |
| Error categorization (taxonomy, not free text) | "Compile failed" doesn't help — was it timeout, throttle, model refusal, ffmpeg error? | LOW | Enum: `MODEL_TIMEOUT`, `MODEL_THROTTLE`, `MODEL_REFUSAL`, `FFMPEG_DECODE`, `FFMPEG_ENCODE`, `BLOB_UPLOAD`, `MODERATION_FAIL_OPEN`, `MODERATION_FAIL_CLOSED`, `DB_TRANSIENT`, `UNKNOWN`. Tag every captured exception |
| Live demo dashboard | Liam-on-stage needs one-glance "is the pipeline healthy right now" before the pitch | LOW (Grafana or similar) | Single dashboard: ingest rate, last 10 segments published, current pipeline backlog, error rate last 5 min, moderation block rate. Especially important post-v1.1 because the moderation gate could silently kill the demo |

---

### Differentiators (Competitive Advantage)

Features that are **specific to citizen-journalism + anonymity** that other UGC platforms don't have to think about. These are where Newz competes.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Newsworthy-context override on violence detection** | Mainstream UGC moderation reflexively blocks violence; citizen-journalism platforms can't. The differentiator is admitting graphic content is part of the news mission and gating it correctly (interstitial, not block) | MED | Combine moderation API output with Marengo cluster context: if 2+ uploads from distinct sessions cluster on the same event AND show similar violence signal, treat as "newsworthy" → interstitial path. Single isolated violent clip with no corroboration → harder gate. **This is novel and on-brand for the AI thesis of the project.** Worth featuring in the v1.1 narrative |
| **Anonymity-preserving report deduplication** | Hash(session+ip-prefix+segment) without storing raw IP. Trades a small fingerprint risk for actually-meaningful dedupe | MED | Standard ban-evasion-detection patterns leak too much; this is the minimum viable anti-brigading without identity |
| **Compile-pipeline tracing as a product surface** | The multi-agent narrative was load-bearing in the v1.0 pitch. Surface span data publicly (e.g. "Caption written by 1 agent, angles selected by 2 agents") on each segment | LOW (read-only Langfuse projection) | Reuses observability work for marketing/credibility. v1.0 had this as a debug overlay; v1.1 makes it presentational |
| **Failure-open moderation with audit trail** | Most platforms refuse to publish what their failure mode is. Documenting "we fail open on most categories, fail closed on CSAM, with full audit" is itself a trust signal | LOW (policy + log) | Sentry + structured logs already capture this; just commit to publishing it |
| **Segment provenance from Postgres** | Once data is durable, we can show "captured at 2026-04-27 14:32 PDT, 3 angles from 3 distinct sessions" with cryptographic-ish credibility | LOW (DB query + UI) | v1.0 has this in debug; productize for trust. Doesn't cost much given Postgres is already shipping |

---

### Anti-Features (Tempting, Wrong for Newz)

Features common in major platform playbooks that **conflict with Newz's anonymity-by-default constraint** or are simply over-scoped for v1.1.

| Feature | Why Requested / Tempting | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Shadow-banning** | Standard X / Reddit / BlueSky tool: silently suppress repeat offenders without notifying them | Requires persistent identity to attach the shadow-ban to. Anonymity-by-default = no identity = no shadow target. Trying to shadow-ban by IP is privacy theater (mobile users rotate IPs constantly) and explicitly compromises the anonymity promise | Trust the moderation gate + reactive report combo. Accept that determined bad actors will resubmit; assume the moderation gate catches the content regardless of who uploaded it |
| **Per-user reputation / "trusted reporter" scoring** | Industry-standard for weighting reports — "this user reports accurately" → fast-track their reports | Same problem: no users. Implementing this requires accounts, full stop | Instead, **weight by report-count-on-segment** (N distinct sessions reporting the same segment is the signal), not per-reporter trust |
| **Appeals process for rejected uploads** | Standard for any moderated platform; ECRA/DSA arguably require it for EU users | No persistent identity to appeal under; the user has already closed the tab and forgotten by the time their clip is rejected. v1.0 design is fire-and-forget, no upload-status UI | **Don't implement appeals.** Instead, on the rare event the gate rejects, log enough context that a human can audit. If we ever add accounts, revisit |
| **Per-user rate limits (uploads/hour)** | Standard abuse control | Session UUID is trivially reset (clear localStorage). IP rate limits leak privacy and break behind NAT/CGNAT (mobile carriers). Already explicitly **deferred to v1.2** in PROJECT.md | Defer. v1.1 ships without; if abuse appears in early launch, revisit with a real signal |
| **Live moderation status to uploader** ("Your clip is being reviewed") | Common UX pattern; reduces uploader anxiety | Breaks the 202 fire-and-forget model that's load-bearing for upload UX. Also, tells uploader that their clip was flagged → tells bad actors what triggered the gate → adversarial probing | Stay silent. If clip never appears in feed, uploader assumes it didn't cluster. This is the same UX as v1.0's "no cluster yet" state |
| **Comment / reply threads on segments** | Engagement driver for any UGC | Already explicitly out of scope ("anonymity friction" — PROJECT.md line 92) | Don't reopen this in v1.1 |
| **Vector DB (Pinecone, Qdrant)** | Common scaling reflex when "embeddings + Postgres" comes up | NumPy in-memory cosine is sufficient at <1000 vectors per local geo. Premature scaling. PROJECT.md flags this explicitly | Stay with NumPy. If a single locale crosses 10K vectors, revisit |
| **Server-side video transcoding to HLS** | Common for "production video" — multi-bitrate ladder, adaptive streaming | We're playing 5-15s clips on iOS Safari; HLS is over-engineered. Single-bitrate MP4 with ffmpeg copy is what's been working | Stay with current libx264 ultrafast normalize-and-concat. Revisit if clips ever exceed 60s or we add cellular-degradation feedback |
| **Postgres + Redis for session state** | Common stack reflex | We have no session state worth caching. SSE state is process-local and fine. PROJECT.md explicitly defers this | Don't add Redis until there's a measured need |
| **Auto-ban on repeated reports** | Tempting "self-cleaning platform" feature | Anonymity = no ban target. Becomes brigading vector instantly. Meta's own published learnings warn against this exact pattern | Use auto-takedown of *content* (segment hidden pending review), never auto-ban of *uploaders* |
| **Real-name verification / phone-bound accounts** | The big-platform-trust answer | Catastrophically off-mission. Newz exists *because* anonymity lets people film sensitive events | Hard line: never |

---

## Feature Dependencies

```
[Postgres migration]
    └──blocks──> [Reactive reporting]              (reports table has nowhere durable to live)
    └──blocks──> [Admin review queue]              (queue is a query against reports table)
    └──blocks──> [Observability metrics persistence] (metrics need a durable schema for historical queries)
    └──blocks──> [Sensitive content tag durability] (need persistent segment.sensitive flag)
    └──enables──> [Segment provenance UI]           (cluster history queryable across restarts)

[Object storage migration]
    └──blocks──> [Signed-URL serving for sensitive content]
    └──enables──> [Stitched-segment caching]
    └──enables──> [Lifecycle: orphan deletion]
    └──blocks──> [Horizontal-scale-readiness]       (volume = single-host-pinned)

[Pre-publish moderation gate]
    └──depends-on──> [Marengo embed pipeline]      (runs in parallel via asyncio.gather)
    └──blocks──> [Sensitive-content interstitial]  (gate sets the flag the UI reads)
    └──blocks──> [CSAM legal compliance]           (statutory requirement — not optional)
    └──independent-of──> [Postgres migration]      (could ship moderation against SQLite, then migrate)

[Reactive reporting]
    └──depends-on──> [Stable segment IDs]          (already true in v1.0; reaffirm in Postgres schema)
    └──depends-on──> [Postgres migration]
    └──enhances──> [Pre-publish moderation gate]   (post-publish second-line defense)

[Observability]
    └──independent-of──> [everything else]         (can ship first, in fact SHOULD)
    └──enhances──> [all other v1.1 work]           (you'll learn what's actually breaking)
```

### Dependency Notes

- **Postgres migration is the keystone.** Reporting, review queue, persistent moderation flags, and metric history all need durable storage. Schedule it first or in parallel with observability.
- **Object storage migration is independent of Postgres** but shares deploy risk. Doing them in the same phase is cheap (one downtime window for v1.0 → v1.1 cutover); doing them separately means two cutovers.
- **Moderation gate and reporting are paired.** Pre-publish gate catches the easy 80%, reactive reporting catches the contextual 20%. Shipping only one is incomplete; shipping both ships "moderation" as a coherent product.
- **Observability should ship FIRST, not last.** Conventional wisdom puts it last; that's wrong. Ship Sentry + structured logs in week 1 of v1.1 so the rest of the v1.1 work happens with visibility. Cost: half a day. Value: every other phase becomes debuggable.

---

## MVP Definition (for v1.1)

### Launch With (v1.1 P1 — required for "public-launch-ready" claim)

- [ ] **Postgres migration with Alembic** — durable metadata, otherwise no point in any of the rest
- [ ] **Object storage migration (Cloudflare R2 — recommend over Vercel Blob)** — durable media, signed URLs, lifecycle support
- [ ] **CSAM hash check (PhotoDNA via Cloudflare's tool)** — non-negotiable legal floor
- [ ] **Pre-publish AI moderation gate (Hive)** — parallel with embed, fail-open with audit
- [ ] **Sensitive-content interstitial UI** — newsworthy content stays viewable behind tap
- [ ] **Anonymous report button + admin review queue** — second-line defense
- [ ] **Sentry + structured JSON logs** — error visibility
- [ ] **Per-pipeline-stage metrics** — operational visibility
- [ ] **Documented failure-mode policy** — fail-open vs fail-closed per category, in writing

### Add After v1.1 Validation (v1.2)

- [ ] **Langfuse multi-agent tracing** — nice-to-have for v1.1, hard to live without by v1.2
- [ ] **Per-session rate limits** — already deferred to v1.2 in PROJECT.md
- [ ] **Auto-takedown threshold tuning** — needs real report data to tune; conservative initial values for v1.1
- [ ] **Stitched-segment caching** — only matters once replay traffic is non-trivial
- [ ] **Live demo dashboard (Grafana)** — Sentry's built-in views are enough for v1.1
- [ ] **Compile-pipeline-trace as user-facing surface** (differentiator) — productize once Langfuse is in

### Future Consideration (v2+)

- [ ] **Geographic moderation policy variation** — EU DSA compliance, regional sensitivity tuning. Out of scope until we have EU users
- [ ] **Vector DB** — only when single-locale crosses 10K vectors
- [ ] **HLS adaptive bitrate** — only when clips exceed 60s
- [ ] **Multi-region Postgres + Blob** — only when we have multi-region users

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Postgres migration | HIGH (durability) | LOW | P1 |
| Object storage migration | HIGH (durability + scaling) | MED | P1 |
| CSAM hash check | HIGH (legal compliance) | MED | P1 |
| Pre-publish moderation gate | HIGH (trust + safety) | MED | P1 |
| Sensitive-content interstitial | HIGH (preserves news mission) | LOW | P1 |
| Anonymous report flow | HIGH (trust + completeness) | LOW | P1 |
| Admin review queue | HIGH (closes the loop) | MED | P1 |
| Sentry + structured logs | HIGH (operability) | LOW | P1 |
| Per-stage metrics | MED-HIGH (operability) | MED | P1 |
| Langfuse multi-agent tracing | MED (debuggability + brand) | MED | P2 |
| Stitched-segment caching | LOW (perf, no current pain) | LOW | P2 |
| Auto-takedown threshold | MED (abuse defense) | LOW | P2 |
| Per-session rate limits | MED (abuse defense) | MED | P2 (deferred to v1.2 per PROJECT.md) |
| Compile-trace as UI surface | LOW (brand) | LOW | P3 |
| Vector DB | LOW (premature) | HIGH | P3 |
| HLS streaming | LOW (premature) | HIGH | P3 |

---

## Competitor / Reference Pattern Analysis

How do platforms that share *some* of Newz's traits handle these areas?

| Feature | X (Twitter) | Reddit | BlueSky | Mastodon | Newz Approach |
|---------|-------------|--------|---------|----------|---------------|
| **Anonymous posting** | Pseudonymous (account required) | Pseudonymous (account required) | Pseudonymous (account required) | Pseudonymous (instance account) | **Truly anonymous** (session UUID only) |
| **Violent / news content** | Interstitial + newsworthy exemption (published policy) | Subreddit-level rules + NSFW tagging | User-stackable filters + central baseline | Per-instance, varies wildly | **Interstitial + newsworthy exemption** — closest to X model |
| **Reporting** | Account-attributed, weighted by reporter history | Account + subreddit mod escalation | Modular: third-party labelers | Per-instance admin (volunteers) | **Anonymous report + central admin queue** — most Mastodon-like in scale, but centralized for consistent policy |
| **Moderation review** | Thousands of paid mods + AI | Volunteer subreddit mods + paid admins | Small central team + community labelers | Single volunteer per instance | **Small founding team in v1.1** (volunteer-equivalent), 24/72h SLA |
| **Repeat-offender control** | Suspensions, shadow-bans | Bans, shadow-bans | Account-level moderation | Instance-level federation cuts | **None — content-only takedowns**, anonymity precludes user-targeting |
| **Mass-report defense** | Reporter reputation weighting | Mod review absorbs noise | Modular labelers route around brigades | Trust per-instance admin | **Per-session report rate limits + report-count threshold for auto-takedown** — most fragile of the five; flag for monitoring |

**Honest takeaway:** No existing platform has the exact constraint set Newz has (true anonymity + news-context + small team). The closest analog for *content policy* is X's newsworthy exemption; the closest analog for *operational scale* is a single Mastodon instance. We're cherry-picking from both.

---

## Quality Gate Self-Check

- ✓ Categories clear (table stakes / differentiator / anti-feature)
- ✓ Complexity noted per feature (LOW / MEDIUM / HIGH with day estimates where useful)
- ✓ Dependencies on v1.0 explicit (segment ID stability, parent-clustering, asyncio fire-and-forget, MIME ladder, etc.)
- ✓ Anonymity-by-default tension called out at the top and tagged in each anti-feature
- ✓ Anti-features list explicit (shadow-banning, reputation, appeals, real-name — all named with "why wrong for Newz")
- ✓ Open question flagged: **Vercel Blob vs Cloudflare R2** — research suggests R2 is the better technical choice; PROJECT.md commits to Vercel Blob. **Roadmap should resolve this before object-storage phase starts.**

---

## Sources

### Database persistence
- [Best PostgreSQL Hosting in 2026: RDS vs Supabase vs Neon vs Self-Hosted](https://dev.to/philip_mcclarence_2ef9475/best-postgresql-hosting-in-2026-rds-vs-supabase-vs-neon-vs-self-hosted-5fkp)
- [Neon vs Supabase: Benchmarks, Pricing & When to Use Each](https://designrevision.com/blog/supabase-vs-neon)
- [Supabase Database Backups (PITR, retention)](https://supabase.com/docs/guides/platform/manage-your-usage/point-in-time-recovery)
- [Neon Point-In-Time Restore](https://neon.com/blog/point-in-time-recovery-in-postgres)
- [Zero-Downtime Alembic Migrations on PostgreSQL](https://goldlapel.com/grounds/replication-scaling-cloud/alembic-zero-downtime-migrations)
- [37 Alembic Migrations, Zero Downtime: How We Moved a Live SaaS From Single-Tenant to Multi-Tenant](https://dev.to/grommash9/37-alembic-migrations-zero-downtime-how-we-moved-a-live-saas-from-single-tenant-to-multi-tenant-4i6n)

### Object storage
- [Vercel Blob: Any file, any format, on Vercel](https://vercel.com/storage/blob)
- [Vercel Blob expiry (TTL) discussion — community confirms no native TTL](https://community.vercel.com/t/vercel-blob-expiry-ttl-possible-workaround/17650)
- [Vercel Storage signed URL issue #544](https://github.com/vercel/storage/issues/544)
- [Cloudflare R2 vs S3 vs Vercel Blob 2026 cost comparison](https://www.pump.co/blog/cloudflare-vs-s3)
- [Cloudflare R2 Pricing 2026](https://leanopstech.com/blog/cloudflare-r2-pricing-2026/)
- [Object Storage Comparison 2026: 21 S3 Providers Compared](https://mixpeek.com/blog/object-storage-comparison-2026)

### Content moderation
- [X Violent Content Policy — newsworthy exemption + interstitial](https://help.x.com/en/rules-and-policies/violent-content)
- [X Media Settings — sensitive content interstitials](https://help.x.com/en/rules-and-policies/media-settings)
- [Top AI Moderation Platforms for UGC in 2026](https://www.foiwe.com/top-ai-moderation-platforms-for-user-generated-content/)
- [Best Image Moderation APIs in 2026 (Eden AI)](https://www.edenai.co/post/best-image-moderation-apis)
- [The Future of Content Moderation: Trends for 2026 and Beyond — Imagga](https://imagga.com/blog/the-future-of-content-moderation-trends-for-2026-and-beyond/)
- [AWS Rekognition Content Moderation](https://aws.amazon.com/rekognition/content-moderation/)
- [NCMEC Mandatory Reporting for Online Platforms — what developers need to know](https://dev.to/sentinelsafety/ncmec-mandatory-reporting-for-online-platforms-what-developers-need-to-know-4k74)
- [CSAM Reporting Obligations — what platforms must do to stay compliant (2026)](https://removeyourmedia.com/2026/03/07/csam-reporting-obligations-what-platforms-must-do-to-stay-compliant/)
- [PhotoDNA + CSAM filtering options compared](https://prostasia.org/blog/csam-filtering-options-compared/)
- [Deploying a cost-effective PhotoDNA system (Scribd, 2026)](https://tech.scribd.com/blog/2026/photodna-csam-detection.html)

### Reactive reporting / brigading
- [Meta — Combatting mass reporting and brigading](https://www.socialmediatoday.com/news/meta-outlines-evolving-efforts-to-combat-mass-reporting-and-brigading-in/628958/)
- [Reporting online abuse to platforms — factors, interfaces, potential for care (2026)](https://journals.sagepub.com/doi/10.1177/13548565251324508)
- [General Best Practices for Content Takedown Reporting (New America OTI)](https://www.newamerica.org/oti/reports/transparency-reporting-toolkit-content-takedown-reporting/general-best-practices-for-content-takedown-reporting/)
- [Bluesky vs Mastodon moderation architecture](https://softwaremill.com/blueskys-decentralized-architecture-compared-to-mastodon-and-twitter-x/)

### Observability
- [OpenLLMetry: OpenTelemetry for LLMs Explained (2026)](https://tokenmix.ai/blog/openllmetry-opentelemetry-for-llms-explained-2026)
- [OpenTelemetry for AI Systems: LLM and Agent Observability (2026)](https://uptrace.dev/blog/opentelemetry-ai-systems)
- [Langfuse — open-source LLM observability with OpenTelemetry](https://langfuse.com/integrations/native/opentelemetry)
- [Sentry FastAPI integration](https://docs.sentry.io/platforms/python/integrations/fastapi/)
- [Sentry Python logging / structured logs](https://docs.sentry.io/platforms/python/integrations/logging/)
- [FastAPI structured logging best practices (community)](https://community.sap.com/t5/artificial-intelligence-blogs-posts/implementing-thread-safe-structured-logging-for-python-fastapi/ba-p/14292907)

---

*Feature research for: Newz v1.1 Public-Launch-Ready Backbone*
*Researched: 2026-04-27*

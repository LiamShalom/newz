---
quick: 260501-bet-structured-evidence-cluster-intent-synth
type: summary
status: shipped
date: 2026-05-01
commits:
  - f51b71d  # Task 1 — caption_pipeline + migration + insert_segment kwargs
  - bd76ae3  # Task 2 — compile wiring + 7 unit tests
files_modified:
  - backend/pipeline/caption_pipeline.py
  - backend/pipeline/compile.py
  - backend/db_postgres.py
  - backend/migrations/versions/20260501_0006_segments_evidence_intent.py
  - backend/config.py
files_added:
  - backend/migrations/versions/20260501_0006_segments_evidence_intent.py
  - backend/tests/pipeline/test_caption_pipeline.py
---

# Quick Task 260501-bet — Summary

Two-stage caption pipeline: per-parent Gemini structured-evidence extraction →
cluster-level Claude intent synthesis. Replaces the prior single-Gemini-call-on-
stitched-composite approach.

## What Changed

### Stage 1 — per-parent evidence extraction (Gemini)

`extract_evidence_for_parent(parent_clip)` uploads the FULL parent
videorecording (not a stitched composite) so audio is preserved end-to-end,
then asks Gemini 2.5 Flash for structured EvidenceJSON via
`response_schema`. The prompt explicitly directs attention to AUDIO ("transcribe
chants, speech, announcements VERBATIM — at least as load-bearing as on-screen
text") and carries the anonymity guard.

### Stage 2 — cluster-level intent synthesis (Claude)

`synthesize_intent(evidence_list, location, when_iso)` calls
`claude_agent_sdk.query` with `model="sonnet"`, `max_turns=3`, no MCP tools.
The reasoner takes the array of per-parent evidence dicts as JSON in the prompt
body, plus the schema + an example, and emits an IntentJSON. Wrapped in
`asyncio.wait_for(timeout=60.0)` so cluster synthesis cannot blow the 300s
compile budget.

### Top-level orchestrator

`run_evidence_to_intent_pipeline(cluster_id, parents, location)` fans out
extractions via `asyncio.gather(..., return_exceptions=True)`, filters
exceptions/None, synthesizes from the surviving evidence. Returns the standard
`{"title", "caption", "location", "source": "vision", "evidence", "intent"}`
shape — `source="vision"` preserves the discriminator at `compile.py:611`.

### Backward-compat shim

`generate_caption(cluster_id, centroid, children)` is now a thin shim that
resolves parents from children via the new helper
`_resolve_parents_from_children` and routes through
`run_evidence_to_intent_pipeline`. The legacy contract (top-level
`title`/`caption`/`location`/`source`) is preserved verbatim, so
`compile.py:_branch_caption` and the discriminator branch at
`compile.py:611` keep working without any structural change at the call site.

### compile.py wiring

- `compile_segment` final segment-row write (`compile.py:692-712`) threads
  `caption_result.get("evidence")` + `caption_result.get("intent")` into
  `insert_segment(...)` kwargs.
- `_save_fallback_segment` (`compile.py:377-392`) passes `evidence=None` and
  `intent=None` explicitly so a recompile-after-failure clears stale JSONB via
  the ON CONFLICT refresh.

### DB schema

Migration `0006_segments_evidence_intent` adds two nullable JSONB columns to
`segments`: `evidence` (array of per-parent evidence) and `intent` (cluster-
level synthesis output). `db_postgres.insert_segment` grew `evidence: list[dict]
| None` and `intent: dict | None` kwargs (default None), wired through the
INSERT column list and the ON CONFLICT(cluster_id) DO UPDATE refresh list.
JSON-encoded via `json.dumps` to match the existing `moderation_decisions`
pattern (the asyncpg jsonb codec round-trips on read).

### Config flag

`EVIDENCE_FAIL_OPEN_TO_LEGACY_PROSE` (default `True` for pilot) — when the
two-stage pipeline returns None, `compile_segment` falls through to the
existing `_save_fallback_segment` path so a playable segment still lands. Set
False post-pilot to fail-CLOSED.

## New Schemas

### EvidenceJSON (per-parent — Gemini emit, validated post-hoc)

```json
{
  "signs": [{"text": "STIPEND NOW", "context": "held by 4 in front row"}],
  "audio_transcript": "What do we want? Stipend! When do we want it? Now!",
  "visual_cues": ["approximately 30 people", "Caltech south gate visible"],
  "affiliations": ["Caltech graduate student union banner"],
  "summary": "About 30 people gather at the Caltech south gate chanting for stipend increase."
}
```

### IntentJSON (cluster-level — Claude emit, validated post-hoc)

```json
{
  "topic": "Caltech grad student walkout",
  "what_is_happening": "About 30 graduate students rally at the Caltech south gate demanding a stipend increase.",
  "why_it_matters": "The walkout escalates an ongoing labor dispute between the graduate union and the institute.",
  "evidence_trail": [
    {"claim": "Walkout demands stipend increase",
     "supporting_evidence": ["STIPEND NOW", "Stipend! When do we want it?"]}
  ],
  "title": "Grad Students Rally At Caltech Gate",
  "caption": "About thirty graduate students gather at the south gate chanting for a stipend increase. A union banner and audible call-and-response are visible in the early-evening light."
}
```

`title` + `caption` are derived inside the synthesis call so the existing
frontend `Segment.title` / `Segment.caption` contract holds without UI changes.

## New Columns

```sql
ALTER TABLE segments ADD COLUMN evidence JSONB;
ALTER TABLE segments ADD COLUMN intent   JSONB;
```

Both nullable. Existing rows + the OFFLINE_DEMO / classifier-fail fallback
paths continue to write valid segment rows without these fields.

## Test Coverage

7/7 unit tests pass in `backend/tests/pipeline/test_caption_pipeline.py`:

| # | Test                                                              | Approach                                              |
|---|-------------------------------------------------------------------|-------------------------------------------------------|
| 1 | extract_evidence_for_parent_returns_schema_shape                  | monkeypatch `google.genai.Client` -> stub SDK         |
| 2 | extract_evidence_for_parent_returns_none_when_no_api_key          | `config.GEMINI_API_KEY = ""`; client never built      |
| 3 | synthesize_intent_parses_response_and_derives_title_caption       | monkeypatch `claude_agent_sdk.query` -> ResultMessage |
| 4 | synthesize_intent_returns_none_on_unparseable                     | garbage response payload                              |
| 5 | run_evidence_to_intent_pipeline_skips_failed_parents              | monkeypatch extract -> [evidence, None, evidence]     |
| 6 | run_evidence_to_intent_pipeline_returns_none_when_all_evidence_fails | all extractions None; synthesize NOT called        |
| 7 | anonymity_prompt_blocks_face_descriptions                         | static prompt-content check                           |

NO real Gemini calls. NO real claude_agent_sdk calls. Wider regression check:
the full `backend/tests/` (excluding DB-touching tests that need
`DATABASE_URL`) still produces 114 passed / 1 skipped — no regressions
introduced by this task.

## Migration Status

The plan's verify step calls for `alembic upgrade head` against local Neon.
Per the executor constraints, the migration file itself was smoke-loaded
(import, revision id check) but `alembic upgrade head` was NOT run against
any real Neon database from the worktree. Migration deferred to deploy.

## Latency Observation

No live smoke run was performed (executor constraints — no real API calls).
Plan-level prediction stands: ~5-15s per Gemini per-parent upload + ACTIVE
poll + generate_content; for a typical 2-6 parent cluster, fan-out via
`asyncio.gather` puts wall-clock at ~15s, plus ~30s for Claude synthesis ≈
~45s total. Comfortably inside the 300s compile budget. Expect to confirm
post-deploy on Railway logs (`compile success cluster_id=<id> elapsed_ms=...`).

## Anonymity Verification

`EVIDENCE_SYSTEM_PROMPT` contains:
- Explicit "MUST NOT" clause for faces of bystanders, identifying details of
  private individuals, license plates, home addresses, and personal contact
  info.
- Carve-out for public figures speaking AT podiums / FROM stages, visible
  affiliations (org names, logos, banners, flags, insignia), symbols, and
  sign/placard/banner text VERBATIM.
- Test 7 codifies these as a regression sentinel.

`INTENT_SYSTEM_INSTRUCTION` carries the same anonymity instruction so the
synthesizer strips bystander descriptions even if the upstream evidence
accidentally surfaces them.

## OFFLINE_DEMO Survival

Confirmed via code path: `extract_evidence_for_parent` early-returns None
when `config.GEMINI_API_KEY` is empty (Test 2). `run_evidence_to_intent_pipeline`
short-circuits to None when ALL parents fail extraction (Test 6).
`compile_segment` then falls through to `_save_fallback_segment`, which now
passes `evidence=None, intent=None` explicitly. Segment row still ships with
the deterministic-run-pick `video_url`, generic "Submitted footage from N
contributor(s)." caption, and NULL evidence/intent. Frontend renders unchanged.

## Deviations From Plan

None of substance. The plan's `<execution_context>` accidentally referenced
Roan's desktop path; ignored per executor constraints. The plan's verify step
calls for `alembic upgrade head` against local Neon; per constraints, only
the import smoke + pytest tests were run from the worktree — migration
applied at deploy time.

The legacy `SYSTEM_PROMPT`, `RESPONSE_SCHEMA`, `_sanitize_output`,
`_select_caption_children`, `_build_stitch_refs`, and the `stitch_clips`
import in `caption_pipeline.py` are now dead code (the refactored
`generate_caption` no longer uses them). Left in place per the plan's
"leave it for later" guidance on title sanitization. `_strip_forbidden_words`
+ `_truncate_to_word_boundary` + `_shares_long_run` are still live —
`_validate_intent_shape` reuses them on the synthesized title.

## Open Questions Carried Forward

(Verbatim from PLAN.md — left unanswered for follow-up phases.)

- **UI surfacing of intent.** Where do `intent.topic` / `intent.why_it_matters`
  / `intent.evidence_trail` show up in the SegmentCard / Montage view? Today
  only `title` + `caption` render. Roan's domain — separate phase.

- **Re-running on historical recordings.** Forward-only per spec. Backfill
  would require a one-off script that re-runs the pipeline against existing
  clusters; not in this quick task.

- **Multi-language audio.** Prompt assumes English transcription. Spanish
  chants at a Pasadena protest will get transliterated or dropped depending on
  Gemini's behavior. Flag for v1.2.

- **Fact-checking / external grounding.** Claude synthesis is grounded only
  in the evidence array — no external news search. If a sign reads
  "STOP HR 1234" the model can describe but not explain the bill. Out of
  scope; future phase could add a Brave/Tavily search step keyed on
  `intent.topic`.

- **Per-parent parent-clip duration.** Parent uploads can be up to ~100MB /
  multi-minute. Gemini Files API accepts these but ACTIVE-poll latency scales
  with file size. If a 2-minute parent blows the per-parent 60s budget, we
  need a clip-window upload (use the centroid-closest 30s window instead of
  the full file). Defer until measured.

- **Evidence-trail validation.** Current implementation trusts Claude to
  reference real evidence items. Lightweight post-hoc check would verify each
  `evidence_trail[].supporting_evidence[]` string appears as a substring in
  some evidence item's `summary`/`signs`/`audio_transcript`. Not done here;
  would catch hallucinated citations.

- **Soft-flag interaction.** Phase 11's `soft_flag` derivation
  (compile.py:657-681) reads moderation_decisions, not evidence. If the
  evidence pipeline surfaces a Nazi flag in `affiliations` but moderation
  didn't flag the source clip, the segment ships visible-by-default. Probably
  OK (moderation is the gate); flag for Phase 11 retro.

- **Cost.** Two LLM calls per cluster (N Gemini + 1 Claude) instead of one
  Gemini. At pilot scale (<100 clusters/day) this is rounding error, but
  worth measuring once and noting.

## Self-Check: PASSED

- `backend/migrations/versions/20260501_0006_segments_evidence_intent.py` — FOUND
- `backend/tests/pipeline/test_caption_pipeline.py` — FOUND
- Commit `f51b71d` — FOUND in git log
- Commit `bd76ae3` — FOUND in git log
- Import smoke (`extract_evidence_for_parent`, `synthesize_intent`,
  `run_evidence_to_intent_pipeline`, `generate_caption`) — PASSES
- Pytest (`tests/pipeline/test_caption_pipeline.py`) — 7/7 PASS
- Wider pytest suite — 114 PASS / 1 SKIP, no regressions

---
quick: 260501-bet-structured-evidence-cluster-intent-synth
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/pipeline/caption_pipeline.py
  - backend/pipeline/compile.py
  - backend/db_postgres.py
  - backend/migrations/versions/20260501_0006_segments_evidence_intent.py
  - backend/config.py
  - backend/tests/pipeline/test_caption_pipeline.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "Per-parent evidence extraction emits structured JSON (signs, audio_transcript, visual_cues, affiliations, summary) instead of prose captions"
    - "Cluster-level Claude synthesis takes the array of per-parent evidence JSON and produces an intent object (topic, what_is_happening, why_it_matters, evidence_trail)"
    - "The downstream segment row still receives a usable title + caption (derived from the Claude intent synthesis) so existing frontend consumers do not break"
    - "The two-stage flow fits inside the existing 300s compile budget"
    - "Anonymity invariant holds: evidence captures affiliations/symbols/logos/public-figures-at-podiums but not identifying detail about private bystanders"
    - "OFFLINE_DEMO=true still produces a playable segment (falls back gracefully when Gemini/Claude calls are skipped)"
  artifacts:
    - path: backend/pipeline/caption_pipeline.py
      provides: "extract_evidence(parent_clip) per-parent + synthesize_intent(evidence_list) cluster-level"
    - path: backend/migrations/versions/20260501_0006_segments_evidence_intent.py
      provides: "Adds segments.evidence JSONB and segments.intent JSONB columns"
    - path: backend/tests/pipeline/test_caption_pipeline.py
      provides: "Unit tests for evidence schema validation + intent synthesis fallback"
  key_links:
    - from: backend/pipeline/compile.py:_branch_caption
      to: caption_pipeline.run_evidence_to_intent_pipeline
      via: "async call inside compile_segment Phase-1 LLM gather"
      pattern: "run_evidence_to_intent_pipeline\\(cluster_id"
    - from: backend/pipeline/caption_pipeline.py:synthesize_intent
      to: claude_agent_sdk.query
      via: "single non-tool query() call with system prompt + JSON schema response"
      pattern: "query\\(prompt=.*options="
    - from: backend/pipeline/compile.py:compile_segment
      to: db.insert_segment
      via: "evidence + intent kwargs threaded into segments row"
      pattern: "insert_segment\\(.*evidence=.*intent="
---

<objective>
Replace the existing single-cluster-Gemini caption call with a two-stage flow:
(1) per-parent-videorecording Gemini 2.5 Flash call emits **structured evidence JSON** (signs, audio_transcript, visual_cues, affiliations, summary);
(2) one cluster-level **Claude synthesis** call (via the already-wired claude_agent_sdk) takes the evidence array and produces an **intent object** (topic, what_is_happening, why_it_matters, evidence_trail). Title + caption for the segment row are derived from the intent object so existing frontend consumers (`SegmentCard`, `Montage`, `Masthead`) keep rendering.

Purpose: The current pipeline produces generic captions ("people walking with signs") because Gemini is asked for prose, not evidence. Asking the model to surface what's *on the signs* and *being chanted* — and then handing that evidence to a stronger reasoner — is what turns "people walking with signs" into "Caltech grad students walk out demanding stipend increase."

Output:
- Per-parent evidence JSON stored on each parent clip (or carried in-memory through compile)
- Cluster-level intent JSON stored on `segments.intent`
- `segments.evidence` JSONB column holds the array of per-parent evidence used for traceability
- `segments.title` + `segments.caption` derived from intent (downstream consumers unchanged)
</objective>

<execution_context>
@/Users/roanhoward/Desktop/newz/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@/Users/liamshalom/Hacktech/CLAUDE.md
@/Users/liamshalom/Hacktech/.planning/PROJECT.md
@/Users/liamshalom/Hacktech/.planning/STATE.md
@/Users/liamshalom/Hacktech/backend/pipeline/caption_pipeline.py
@/Users/liamshalom/Hacktech/backend/pipeline/compile.py
@/Users/liamshalom/Hacktech/backend/db_postgres.py
@/Users/liamshalom/Hacktech/backend/config.py

<interfaces>
<!-- Key contracts the executor needs. Extracted from codebase 2026-05-01. -->

Existing — will be modified:

```python
# backend/pipeline/caption_pipeline.py — current public API
async def generate_caption(
    cluster_id: str,
    centroid: np.ndarray,
    children: list[dict],  # each: {id, parent_path, parent_blob_url?, start_offset_sec, end_offset_sec, lat, lng, ts, vec, parent_id?}
) -> dict | None:
    """Returns {title, caption, location, source: 'vision'} or None on failure."""
```

```python
# backend/pipeline/compile.py — call site (line 268-283)
async def _branch_caption(cluster_id: str) -> dict | None:
    children = await _get_children_with_vecs(cluster_id)
    return await generate_caption(cluster_id, cluster_cache.centroid, children)

# Discriminator at line 611:
if isinstance(b_result, dict) and b_result.get("source") == "vision":
    caption_result = b_result
```

```python
# backend/db_postgres.py — current insert_segment signature
async def insert_segment(
    cluster_id: str,
    ordered_clip_ids: list[str],
    caption: str,
    location: str,
    source_count: int,
    video_url: str | None = None,
    title: str | None = None,
    soft_flag: bool = False,
) -> str:  # idempotent ON CONFLICT(cluster_id) DO UPDATE
```

```python
# backend/db_postgres.py — clip walk for cluster (line 646)
async def fetch_cluster_clips_with_children(cluster_id: str) -> list[dict]:
    """Returns rows with parent_id IS NULL flagged via parent_id field.
       Each row: {id, path, blob_url, lat, lng, ts, parent_id, start_offset_sec, end_offset_sec}.
       Parents have parent_id IS NULL; children have parent_id == <parent_row.id>."""
```

```python
# backend/config.py — already wired
GEMINI_API_KEY: str
GEMINI_MODEL: str = "gemini-2.5-flash"   # used by caption_pipeline
OFFLINE_DEMO: bool                       # MUST short-circuit external calls
```

```python
# claude_agent_sdk — already used in compile.py for orchestrator chain
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
# Pattern (compile.py:198-225): options=ClaudeAgentOptions(model="sonnet", max_turns=N),
#   then `async for msg in query(prompt=..., options=options): if isinstance(msg, ResultMessage): final_text = msg.result`
```

Existing — frontend consumers (DO NOT BREAK; field shape held constant):

```typescript
// frontend/src/types.ts
export interface Segment {
  id: string;
  title: string | null;   // 4-8 words AP-wire headline
  caption: string;        // 2-3 sentence lede
  location: string;
  // ...
}
```

New contracts this plan creates:

```python
# Per-parent evidence schema (Gemini response_schema enforced)
EvidenceJSON = {
    "signs": [{"text": str, "context": str}],
    "audio_transcript": str,         # verbatim chants/speech/announcements; "" if no audio info
    "visual_cues": [str],            # clothing/symbols/objects/setting tokens
    "affiliations": [str],           # org names, flags, logos visible — anonymity-safe
    "summary": str,                  # 1-sentence neutral description
}

# Cluster-level intent schema (Claude response, validated post-hoc)
IntentJSON = {
    "topic": str,                    # short noun phrase ("Caltech grad student walkout")
    "what_is_happening": str,        # 1-2 sentences, neutral
    "why_it_matters": str,           # 1-2 sentences, evidence-grounded
    "evidence_trail": [               # which evidence items support which claims
        {"claim": str, "supporting_evidence": [str]},
    ],
    "title": str,                    # 4-8 words, AP-wire — DERIVED for backward compat
    "caption": str,                  # 2-3 sentences, AP-wire — DERIVED for backward compat
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Refactor caption pipeline to per-parent evidence extraction + add segments.evidence/intent JSONB columns</name>
  <files>
    backend/pipeline/caption_pipeline.py,
    backend/migrations/versions/20260501_0006_segments_evidence_intent.py,
    backend/db_postgres.py,
    backend/config.py
  </files>
  <action>
**1a. Add migration `backend/migrations/versions/20260501_0006_segments_evidence_intent.py`:**
- `down_revision = "20260430_0005"` (segments_soft_flag — confirm by reading the file's `revision = ` line; if it differs use the actual id)
- `op.add_column("segments", sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True))`
- `op.add_column("segments", sa.Column("intent", postgresql.JSONB(astext_type=sa.Text()), nullable=True))`
- `downgrade()` drops both columns
- Run `alembic upgrade head` against local Neon as part of verify

**1b. Extend `backend/db_postgres.py:insert_segment()`:**
- Add kwargs `evidence: list[dict] | None = None, intent: dict | None = None`
- Add `evidence` and `intent` to INSERT column list and ON CONFLICT DO UPDATE refresh list (mirror the existing `soft_flag` pattern at lines 360-372)
- Pass `json.dumps(evidence) if evidence else None` and `json.dumps(intent) if intent else None` as bind params (asyncpg JSONB accepts text via dumps; matches existing `ordered_clip_ids` pattern at line 373)

**1c. Refactor `backend/pipeline/caption_pipeline.py`:**
- Keep the file but add THREE new async functions and refactor `generate_caption` into a thin wrapper:

```python
async def extract_evidence_for_parent(parent_clip: dict) -> dict | None:
    """Per-parent Gemini call. Uploads the FULL parent video (not stitched composite)
    so audio is preserved. Returns EvidenceJSON or None on failure."""
```
  - Use Gemini 2.5 Flash with new `EVIDENCE_SYSTEM_PROMPT` (write it inline) + new `EVIDENCE_RESPONSE_SCHEMA`
  - Prompt MUST explicitly direct attention to AUDIO ("transcribe chants, speech, announcements verbatim — audio is at least as load-bearing as on-screen text")
  - Anonymity guard in the prompt: "Affiliations, symbols, logos, flags, and public figures speaking at podiums are reportable. Faces of bystanders, identifying details of private individuals, license plates, and home addresses MUST NOT appear in the output."
  - Same Gemini Files API upload + ACTIVE poll pattern as current `generate_caption` (lines 438-458). Reuse `_strip_forbidden_words` / sanitization where applicable; new schema does NOT have a title field so most title sanitization is dead — leave it for later
  - Honors `OFFLINE_DEMO`: if `not config.GEMINI_API_KEY`, return `None` (caller fallback handles)

```python
async def synthesize_intent(evidence_list: list[dict], location: str, when_iso: str) -> dict | None:
    """Cluster-level Claude call. Takes the evidence array, returns IntentJSON.
    Uses claude_agent_sdk.query() with model='sonnet', no MCP tools (pure synthesis)."""
```
  - Build the prompt as: "Below is structured evidence extracted by a vision model from N independent recordings of the same event. Synthesize the event's topic, what is happening, and why it matters. Cite which evidence items support each claim. Then derive a 4-8 word AP-wire title and 2-3 sentence caption."
  - Inline the `evidence_list` as JSON in the prompt body
  - Inline the IntentJSON schema in the prompt with example
  - `ClaudeAgentOptions(model="sonnet", max_turns=3)` — no tool calls needed; tighten max_turns vs the angle-selector's 20
  - Iterate `async for msg in query(...)` like compile.py:212-225, capture `ResultMessage.result`
  - Parse JSON tolerantly (reuse `_extract_run_ids`-style fence-aware parser; or copy the pattern: try direct json.loads, else regex out ```json blocks)
  - Title sanitization: apply existing `_strip_forbidden_words` + `_truncate_to_word_boundary` to the derived title (lines 166-188)
  - On any parse/timeout failure → return None (caller falls back)
  - Wrap the SDK call in `asyncio.wait_for(..., timeout=60.0)` so the cluster-level synthesis can't blow the 300s budget

```python
async def run_evidence_to_intent_pipeline(
    cluster_id: str,
    parents: list[dict],
    location: str,
) -> dict | None:
    """Top-level: fan-out evidence extraction across parents, then synthesize."""
```
  - `evidence_list = await asyncio.gather(*[extract_evidence_for_parent(p) for p in parents], return_exceptions=True)`
  - Filter out exceptions / None — if zero successful evidence extractions, return None
  - `intent = await synthesize_intent([e for e in evidence_list if isinstance(e, dict)], location, when_iso)`
  - On success return `{"title": intent["title"], "caption": intent["caption"], "location": location, "source": "vision", "evidence": [...successful evidence...], "intent": intent}` — note `source: "vision"` is preserved verbatim so the discriminator at compile.py:611 stays green

**1d. Refactor existing `generate_caption` into a backward-compat shim:**
- Resolve `parents` from `children` (filter `parent_id is None`, or use the parent_id mapping)
- Call `run_evidence_to_intent_pipeline(cluster_id, parents, location)`
- Return its result directly

**1e. Add `EVIDENCE_FAIL_OPEN_TO_LEGACY_PROSE` config flag in `backend/config.py`** (default `True` for pilot). When True and the new pipeline returns None, the existing `_save_fallback_segment` path (compile.py:350) still produces a playable segment with the generic "Submitted footage from N contributor(s)" caption — no extra wiring needed; falsy `caption_result` already triggers fallback at compile.py:611. Document the flag for future flip.

**Per-parent uploads concern:** A cluster can have N parents (typically 2-6). Each parent upload + ACTIVE-poll + generate_content takes ~5-15s. Six parallel Gemini calls at ~15s each = ~15s wall-clock (parallel via asyncio.gather), plus ~30s for Claude synthesis = ~45s total. Comfortably inside the 300s compile budget. If parent counts ever grow, add a cap (e.g. process top-K parents by centroid cosine like the v1 path did with children).
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/backend && .venv/bin/python -m alembic upgrade head && .venv/bin/python -c "from pipeline.caption_pipeline import extract_evidence_for_parent, synthesize_intent, run_evidence_to_intent_pipeline, generate_caption; print('imports ok')"</automated>
  </verify>
  <done>
    - Migration 0006 applied; `\d segments` shows `evidence jsonb`, `intent jsonb` columns
    - `caption_pipeline.py` exports the three new functions + retains backward-compat `generate_caption`
    - `insert_segment` accepts `evidence=` and `intent=` kwargs and round-trips them through ON CONFLICT
    - `import` smoke succeeds; module-load is side-effect-free (no Gemini/Claude calls at import time)
  </done>
</task>

<task type="auto">
  <name>Task 2: Wire two-stage flow into compile_segment + persist evidence/intent on segment row + tests</name>
  <files>
    backend/pipeline/compile.py,
    backend/tests/pipeline/test_caption_pipeline.py
  </files>
  <action>
**2a. Update `backend/pipeline/compile.py:_branch_caption`:**
- Keep the function name + signature for backward compat
- Internally still call `generate_caption(cluster_id, centroid, children)` — the shim from Task 1d already routes through the new two-stage pipeline. **No structural change needed at this call site if Task 1d's shim is in place.** Verify by reading the shim once tests pass.

**2b. Thread `evidence` + `intent` into the segments row write at `compile.py:692-701`:**
- Where `caption_result` is unpacked into `insert_segment(...)` arguments (line 692-701), add:
  - `evidence=caption_result.get("evidence") if caption_result else None,`
  - `intent=caption_result.get("intent") if caption_result else None,`
- Cosmetic: leave the existing `title` / `caption` / `location` derivation untouched — the shim already emits those keys at the top level, so the existing `caption_result["caption"]` / `caption_result.get("title", "")` paths keep working

**2c. Update `_save_fallback_segment` (compile.py:350):**
- Pass `evidence=None, intent=None` explicitly into `insert_segment(...)` (line 377-385) so a fallback segment doesn't carry stale JSONB from a prior compile of the same cluster — relies on Task 1b's ON CONFLICT refresh including these columns

**2d. Tests `backend/tests/pipeline/test_caption_pipeline.py`:**
- Match the existing test layout (look at `backend/tests/pipeline/test_recompile.py` and `test_moderate.py` for the asyncpg + monkeypatch fixture pattern)
- Test 1: `test_extract_evidence_for_parent_returns_schema_shape` — monkeypatch `google.genai.Client` to return a stub response with the EvidenceJSON shape; assert keys present, types correct, `affiliations` is a list, `signs` is a list-of-dicts
- Test 2: `test_extract_evidence_for_parent_returns_none_when_no_api_key` — set `config.GEMINI_API_KEY = ""`, assert returns None
- Test 3: `test_synthesize_intent_parses_response_and_derives_title_caption` — monkeypatch the `claude_agent_sdk.query` async generator to yield a single `ResultMessage` with a JSON IntentJSON; assert `result["title"]` ≤ 60 chars, `result["caption"]` length 80–400, `result["evidence_trail"]` is a list
- Test 4: `test_synthesize_intent_returns_none_on_unparseable` — `query` yields garbage; assert None
- Test 5: `test_run_evidence_to_intent_pipeline_skips_failed_parents` — pass 3 parents, monkeypatch `extract_evidence_for_parent` to return `[evidence, None, evidence]`, assert synthesis sees 2 evidence items and returns the dict
- Test 6: `test_run_evidence_to_intent_pipeline_returns_none_when_all_evidence_fails` — all parents fail extraction, assert overall returns None
- Test 7: `test_anonymity_prompt_blocks_face_descriptions` — assert the EVIDENCE_SYSTEM_PROMPT string contains both "MUST NOT" and one of "faces of bystanders" / "identifying details" — not behavioral but prevents accidental prompt regression
- Use `pytest.mark.asyncio` (project pattern) and `monkeypatch` for SDK stubs; no real API calls
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech/backend && .venv/bin/python -m pytest tests/pipeline/test_caption_pipeline.py -x -q</automated>
  </verify>
  <done>
    - All 7 tests pass
    - `insert_segment` is called with `evidence=` and `intent=` from the success path in `compile_segment`
    - `_save_fallback_segment` clears stale evidence/intent on cluster recompile-after-failure
    - Backward compat verified: `generate_caption` still returns `{title, caption, location, source: "vision"}` at minimum (now plus evidence/intent keys)
  </done>
</task>

</tasks>

<verification>
**End-to-end smoke (manual, post-merge):**
1. With `OFFLINE_DEMO=false`, GEMINI_API_KEY + ANTHROPIC_API_KEY set, ingest 2 parent recordings into the same cluster (use the staged demo dataset — pick 2 clips with audio).
2. Wait for compile to fire (`>=2 distinct parents` gate).
3. Query Postgres: `SELECT id, title, caption, evidence, intent FROM segments WHERE cluster_id = '<id>';`
4. Verify:
   - `title` is non-empty and ≤60 chars
   - `caption` is 2-3 sentences
   - `evidence` is a JSON array with one entry per parent, each with all five keys
   - `intent` is a JSON object with `topic`, `what_is_happening`, `why_it_matters`, `evidence_trail`
   - `evidence_trail` references at least one item from `evidence`

**OFFLINE_DEMO survival:**
- Set `OFFLINE_DEMO=true`, run the same ingest. Compile should still emit a fallback segment (generic caption from `_save_fallback_segment`); `evidence` and `intent` are NULL — feed renders unchanged.

**Latency check:**
- Tail Railway logs for `compile success cluster_id=<id> elapsed_ms=<n>`. n should be < 90000 (90s) for a 2-parent cluster on the staged dataset. Compare against pre-change p50 from the last known compile log line; aim for parity ±20%. If latency regressed >50%, consider capping parents-to-evidence at top-3 by centroid cosine.

**Anonymity regression:**
- Inspect 3 emitted evidence JSONs from the smoke clusters. Confirm none contain face descriptions of private bystanders, license plate strings, or home addresses. Affiliations / org names / public-figure names at podiums are OK.
</verification>

<success_criteria>
- Per-parent Gemini call emits structured EvidenceJSON conforming to the response_schema
- Cluster-level Claude call emits structured IntentJSON; title + caption derived from it
- `segments.evidence` (JSONB) and `segments.intent` (JSONB) populated on success
- Existing `Segment.title` / `Segment.caption` frontend contract unchanged — no UI changes required
- Compile-pipeline wall-clock stays ≤ 300s budget on a 2-6 parent cluster
- OFFLINE_DEMO=true still produces a renderable segment (fallback path)
- Anonymity guards present in the EVIDENCE_SYSTEM_PROMPT and verified by Test 7
- All 7 unit tests in `test_caption_pipeline.py` pass; no real API calls in CI
</success_criteria>

<output>
After completion, write `.planning/quick/260501-bet-structured-evidence-cluster-intent-synth/260501-bet-SUMMARY.md` covering:
- What changed (per-parent evidence + cluster-level intent synthesis)
- New schemas (EvidenceJSON, IntentJSON) — paste both
- New columns (segments.evidence, segments.intent)
- Latency observation from the smoke run
- Open questions still unresolved (see below)
- Update `.planning/STATE.md` Quick Tasks Completed table with the row
</output>

---

## Open questions (flag for follow-up)

- **UI surfacing of intent.** Where does `intent.topic` / `intent.why_it_matters` / `intent.evidence_trail` show up in the SegmentCard / Montage view? Today only `title` + `caption` render. Roan's domain — separate phase. Until then, intent sits unread in the DB.
- **Re-running on historical recordings.** Forward-only per spec. If we ever want to backfill, write a one-off script that re-runs the pipeline against existing clusters; not in this quick task.
- **Multi-language audio.** Prompt assumes English transcription. Spanish chants at a Pasadena protest will get transliterated or dropped depending on Gemini's behavior. Flag for v1.2 — add a language hint to the prompt, or detect language and route to a language-specific synthesis prompt.
- **Fact-checking / external grounding.** Claude synthesis is grounded only in the evidence array — no external news search. If a sign reads "STOP HR 1234" the model can describe but not explain the bill. Out of scope for this task; future phase could add a Brave/Tavily search step keyed on `intent.topic` before synthesis.
- **Per-parent parent-clip duration.** Parent uploads can be up to ~100MB / multi-minute. Gemini Files API accepts these but ACTIVE-poll latency scales with file size. If a 2-minute parent blows the per-parent 60s budget, we need a clip-window upload (use the centroid-closest 30s window instead of the full file). Defer until measured.
- **Evidence-trail validation.** Current plan trusts Claude to reference real evidence items. Lightweight post-hoc check: verify each `evidence_trail[].supporting_evidence[]` string appears as a substring in some evidence item's `summary`/`signs`/`audio_transcript`. Not in this task; would catch hallucinated citations.
- **Soft-flag interaction.** Phase 11's `soft_flag` derivation (compile.py:657-681) reads moderation_decisions, not evidence. If the evidence pipeline surfaces a Nazi flag in `affiliations` but moderation didn't flag the source clip, the segment ships visible-by-default. Probably OK (moderation is the gate); flag for Phase 11 retro.
- **Cost.** Two LLM calls per cluster (N Gemini + 1 Claude) instead of one Gemini. At pilot scale (<100 clusters/day) this is rounding error, but worth measuring once and noting in SUMMARY.

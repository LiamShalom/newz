---
phase: 11-moderation-gate-gemini-flash-lite-csam-hash
reviewed: 2026-04-29T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - backend/.env.example
  - backend/app.py
  - backend/config.py
  - backend/db_postgres.py
  - backend/db_sqlite.py
  - backend/migrations/versions/20260430_0004_moderation_columns.py
  - backend/migrations/versions/20260430_0005_segments_soft_flag.py
  - backend/observability/anonymity.py
  - backend/observability/metrics.py
  - backend/pipeline/compile.py
  - backend/pipeline/moderate.py
  - backend/pipeline/run.py
  - backend/tests/conftest.py
  - backend/tests/pipeline/__init__.py
  - backend/tests/pipeline/test_moderate.py
  - backend/tests/test_feed_segments.py
  - backend/tests/test_offline_demo_firewall.py
  - frontend/src/components/SegmentCard.test.tsx
  - frontend/src/types.ts
findings:
  critical: 4
  warning: 7
  info: 6
  total: 17
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-04-29
**Depth:** standard
**Files Reviewed:** 19 (note: `backend/.env.example` access denied by tool permissions, treated as out-of-scope)
**Status:** issues_found

## Summary

Phase 11 lands the classifier-only Gemini Flash-Lite moderation gate (Option-4 reconciliation). Architecture is sound: parallel `asyncio.wait FIRST_COMPLETED` race, three-branch outcome routing, idempotent UPSERT writes, and statutory ordering for the CSAM preservation path are all in the right place.

Four critical issues prevent shipping as-is:

1. **`_drain_task` swallows `BaseException` including `KeyboardInterrupt`/`SystemExit`** — also breaks asyncio cancellation propagation.
2. **CSAM preservation failure does not abort cleanup** — bytes get deleted even when `write_reported_csam` raises, destroying § 2258A audit-trail evidence.
3. **Typed-exception ladder will not match real Gemini SDK errors** — production 4xx/5xx from the `google.genai` SDK raise `google.genai.errors.APIError`, not `httpx.HTTPStatusError`. The whole D-05 routing is a no-op against the real SDK; tests pass only because mocks raise raw httpx exceptions.
4. **SQLite path crashes on OFFLINE_DEMO** — `db_sqlite.SCHEMA_SQL` declares neither `moderation_decisions` nor `reported_csam` nor `clips.is_hidden`. The OFFLINE_DEMO short-circuit calls `write_moderation_decision` first thing, hits a missing table, run_pipeline crashes. Phase 11 docs acknowledge this as deferred; it still kills the OFFLINE_DEMO contract.

PRIV-03 anonymity holds in the active outbound path (Gemini receives only video bytes + system_instruction + USER_PROMPT). Hard-block ordering (`write_reported_csam` BEFORE `cleanup_blocked_clip`) is correct on the success path. UNIQUE(clip_id, provider) idempotency is correctly implemented in postgres; SQLite has a parity break in return-id semantics under conflict.

## Critical Issues

### CR-01: `_drain_task` swallows `BaseException` and breaks cancellation propagation

**File:** `backend/pipeline/moderate.py:413-425`
**Issue:** The handler `except (asyncio.CancelledError, BaseException)` is overly broad in two ways:

1. `BaseException` already covers `CancelledError` (it's a subclass since Python 3.8). The tuple is redundant.
2. More importantly, swallowing `BaseException` catches `KeyboardInterrupt` and `SystemExit`, which are explicitly carved out from `Exception` for a reason — `_drain_task` will silently absorb a Ctrl-C or `os._exit`-equivalent.
3. Swallowing `CancelledError` here is also wrong if `_moderate_real` is itself being cancelled by the outer `asyncio.wait_for` in `run_pipeline`'s `STAGE_DURATION` block. If `_moderate_real` is cancelled while inside `_drain_task`, the `await task` re-raises CancelledError; the `except` swallows it, and the cancellation does not propagate up through `_moderate_real`. The whole task may then run to completion despite the parent's cancel.

**Fix:**
```python
async def _drain_task(task: asyncio.Task) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # Expected — we just cancelled it. Do NOT swallow if we ourselves
        # are being cancelled by the outer scope.
        if asyncio.current_task() is not None and asyncio.current_task().cancelling() > 0:  # type: ignore[union-attr]
            raise
    except Exception:
        # Drained task's own exception — swallow, we already handled the
        # decision via gemini_task.exception() / embed_task.result().
        pass
```
On Python <3.11 where `cancelling()` isn't available, a simpler fix is to not catch `BaseException` and let `CancelledError` re-raise when appropriate. At minimum, drop `BaseException` from the tuple.

---

### CR-02: CSAM-block path deletes evidence when preservation write fails

**File:** `backend/pipeline/moderate.py:539-555`
**Issue:** Hard-block flow:
```python
if reason == "gemini_csam_block" and clip_bytes is not None:
    try:
        await db.write_reported_csam(...)
    except Exception:
        log.exception("moderate write_reported_csam failed clip_id=%s", clip_id)
# All hard-blocks: idempotent cleanup of the stored blob/file.
try:
    await cleanup_blocked_clip(clip_id)
except Exception:
    log.exception(...)
```

If `write_reported_csam` raises (DB outage, JSONB encoder failure, anything), the exception is logged-and-swallowed and we proceed straight to `cleanup_blocked_clip`, which deletes the only copy of the bytes. § 2258A requires 1-year retention. This is an audit-trail compliance bug — the test (`test_moderate_hard_block_csam`) asserts ordering on the success path but never the abort-on-preservation-failure path.

**Fix:** On CSAM-hit, only run cleanup if the preservation write succeeded. Surface the failure so ops can intervene before evidence is lost:
```python
if decision == "blocked":
    safe_to_cleanup = True
    if reason == "gemini_csam_block" and clip_bytes is not None:
        try:
            await db.write_reported_csam(
                content_hash=_content_hash(clip_bytes),
                preserved_until=_one_year_from_now_unix(),
            )
        except Exception:
            log.exception(
                "moderate write_reported_csam FAILED clip_id=%s — "
                "preserving bytes (cleanup deferred for manual reconciliation)",
                clip_id,
            )
            safe_to_cleanup = False
    if safe_to_cleanup:
        try:
            await cleanup_blocked_clip(clip_id)
        except Exception:
            log.exception("moderate cleanup_blocked_clip failed clip_id=%s", clip_id)
```
Add a corresponding test that injects a `write_reported_csam` failure and asserts `cleanup_blocked_clip` was NOT awaited.

---

### CR-03: Typed-exception ladder cannot match real Gemini SDK errors

**File:** `backend/pipeline/moderate.py:390-410`
**Issue:** `_classify_exception` matches on `asyncio.TimeoutError`, `httpx.HTTPStatusError`, `httpx.ConnectError`, `httpx.ReadError`, `httpx.TransportError`. The `google.genai` Python SDK does NOT surface raw `httpx.HTTPStatusError` from `client.models.generate_content` or `client.files.upload` — it wraps transport errors in its own exception hierarchy under `google.genai.errors` (`APIError`, `ClientError`, `ServerError`, `BadRequestError`, etc.).

Result in production:
- A real Gemini 4xx (e.g. quota, malformed request, blocked content from the SDK side) raises `google.genai.errors.ClientError`, falls through to the catch-all on line 410, returns `("unknown", "classifier_unknown_error")` instead of `("blocked", f"classifier_4xx_{status}")`.
- A real Gemini 5xx raises `google.genai.errors.ServerError`, also routes to `unknown` — but with reason `classifier_unknown_error` instead of `classifier_5xx_503`. The decision is the same (`unknown`), but the audit row reason is wrong.
- The 4xx-blocked test passes because it injects a synthetic `httpx.HTTPStatusError`; production never raises that type.

The D-05 spec ("4xx → blocked") is silently violated for real traffic.

**Fix:** Catch `google.genai.errors.ClientError` (4xx) and `google.genai.errors.ServerError` (5xx) explicitly:
```python
def _classify_exception(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, asyncio.TimeoutError):
        return ("blocked", "classifier_timeout")

    # google.genai SDK errors — local import keeps this module load-safe under
    # OFFLINE_DEMO (no genai dep needed in that branch).
    try:
        from google.genai import errors as genai_errors
    except ImportError:
        genai_errors = None  # type: ignore[assignment]

    if genai_errors is not None:
        if isinstance(exc, genai_errors.ClientError):
            status = getattr(exc, "code", 0) or 400
            return ("blocked", f"classifier_4xx_{status}")
        if isinstance(exc, genai_errors.ServerError):
            status = getattr(exc, "code", 0) or 500
            return ("unknown", f"classifier_5xx_{status}")

    if isinstance(exc, httpx.HTTPStatusError):
        # Kept for forward-compat / direct httpx callsites; not the prod path.
        status = exc.response.status_code if exc.response is not None else 0
        if 400 <= status < 500:
            return ("blocked", f"classifier_4xx_{status}")
        if 500 <= status < 600:
            return ("unknown", f"classifier_5xx_{status}")
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.TransportError)):
        return ("unknown", "classifier_network_error")
    return ("unknown", "classifier_unknown_error")
```
Add a test that injects a `google.genai.errors.ClientError(code=400, ...)` and asserts decision=blocked. Verify exact exception class names against the installed SDK version (`google.genai==X.Y.Z` — confirm in `requirements.txt`); the surface has shifted between minor versions.

---

### CR-04: SQLite OFFLINE_DEMO path crashes on first clip — missing tables/columns

**File:** `backend/db_sqlite.py:59-114` (SCHEMA_SQL + init())
**Issue:** Phase 11 introduced five new DB surfaces:
- `moderation_decisions` table (with Phase 11 columns)
- `reported_csam` table
- `clips.is_hidden` column
- `segments.soft_flag` column (✓ — added defensively at line 181-184)
- UNIQUE(clip_id, provider) index on moderation_decisions

Of these, only `segments.soft_flag` is actually patched into the SQLite schema by `init()`. The other four are NOT in `SCHEMA_SQL` and not patched in `init()`. Code comments in `db_sqlite.py:929-937` explicitly acknowledge this and call it "out-of-scope for Plan 03" because "the SQLite backend is slated for retirement."

But this is **not a future problem** — `OFFLINE_DEMO=true` is the documented hackathon-fallback path (see `CLAUDE.md` "Hard Constraints" + `config.py` D-11 comments). Under OFFLINE_DEMO=true, the very first thing `moderate_clip` does is:
```python
await db.write_moderation_decision(
    clip_id=clip_id, provider="stub", decision="passed", reason="offline_demo", ...
)
```
…which hits a non-existent table. `aiosqlite` raises `OperationalError: no such table: moderation_decisions`. The `except Exception` in `run_pipeline` catches it but the gate has already reported "passed" and clustering will be skipped — every upload becomes a pipeline_error broadcast.

The OFFLINE_DEMO firewall test (`test_offline_demo_no_moderation_calls`) hides this because it monkeypatches `write_moderation_decision` to an `AsyncMock`. There is no test that exercises the real SQLite write path under OFFLINE_DEMO=true.

**Fix:** Either:

1. **(Recommended)** Patch the missing tables/column into `db_sqlite.init()` exactly the way `segments.soft_flag` was added at line 181-184. Even if the SQLite backend is retiring, the OFFLINE_DEMO contract requires it work today:
```python
# Phase 11: moderation gate tables (parity with Alembic 0001 + 0004 on postgres).
await conn.executescript("""
    CREATE TABLE IF NOT EXISTS moderation_decisions (
      id TEXT PRIMARY KEY,
      clip_id TEXT NOT NULL,
      provider TEXT NOT NULL DEFAULT 'stub',
      decision TEXT NOT NULL DEFAULT 'passed',
      reason TEXT,
      raw_response TEXT,
      latency_ms INTEGER,
      prompt_version TEXT,
      created_at REAL NOT NULL DEFAULT (unixepoch())
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_moderation_decisions_clip_provider
      ON moderation_decisions(clip_id, provider);

    CREATE TABLE IF NOT EXISTS reported_csam (
      id TEXT PRIMARY KEY,
      content_hash TEXT NOT NULL,
      content_preserved_until REAL NOT NULL,
      ncmec_report_id INTEGER,
      created_at REAL NOT NULL DEFAULT (unixepoch())
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_reported_csam_content_hash
      ON reported_csam(content_hash);
""")
async with conn.execute("PRAGMA table_info(clips)") as cur:
    clip_cols2 = {row[1] for row in await cur.fetchall()}
if "is_hidden" not in clip_cols2:
    await conn.execute("ALTER TABLE clips ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
```

2. **(Alternative)** Add a guard in `moderate_clip` that detects SQLite + missing-tables and short-circuits before `db.write_moderation_decision`. Less robust; merely papers over.

Add a regression test: `test_offline_demo_writes_moderation_row_to_sqlite` that does NOT mock `write_moderation_decision` and asserts the row landed in the real SQLite DB.

## Warnings

### WR-01: Branch B masks gemini-passed decisions when embed fails

**File:** `backend/pipeline/moderate.py:501-517`
**Issue:** In Branch B (gemini done first), the code does `embed_result = await embed_task` inside a `try/except BaseException`. If `embed_task` already finished but raised an exception (e.g. Marengo 5xx, file vanished), `await` re-raises and we set `embed_result = None`. Then we proceed to read `gemini_task.exception()` / `gemini_task.result()` — that part is correct.

But the result is then returned with `embed_result=embed_result if decision == "passed" else None` (line 576). On `decision == "passed"` with embed failed, `embed_result` is None — so `run_pipeline` falls back to running `embed_worker` AGAIN at run.py:124. The clip already failed to embed once; the retry re-runs the entire upload-poll-generate cycle that just blew up.

Compounding this: the second `embed_worker` call is now OUTSIDE the moderation gate's `STAGE_DURATION.labels(stage="moderate")` block — its latency is attributed to `stage="embed"` in run.py, but the original failed embed_worker call inside moderate.py was attributed to `stage="moderate"`. Metrics get muddled.

**Fix:** When embed fails inside Branch B, surface a structured warning so ops can see the retry, and consider returning `decision="unknown"` if both embed AND gemini succeeded with passed but embed was actually a failure (genuine ambiguity here — your call):
```python
try:
    embed_result = await embed_task
except BaseException as exc:
    log.warning(
        "moderate embed_worker failed under gemini-done branch clip_id=%s: %s — "
        "run_pipeline will retry embed_worker outside moderation stage",
        clip_id, type(exc).__name__,
    )
    embed_result = None
```

---

### WR-02: `_fetch_clip_bytes` + outer `db.get_clip` is a duplicate read

**File:** `backend/pipeline/moderate.py:454-460`
**Issue:** `_fetch_clip_bytes(clip_id)` (line 239) calls `db.get_clip(clip_id)` internally to determine path vs blob_url. Immediately after returning, `_moderate_real` calls `db.get_clip(clip_id)` again to populate `blob_tempfile_to_unlink`. Two DB roundtrips on every clip; the only thing the second read is used for is whether to set `blob_tempfile_to_unlink`.

**Fix:** Have `_fetch_clip_bytes` return a third tuple member:
```python
async def _fetch_clip_bytes(clip_id: str) -> tuple[bytes, str, bool]:
    # third element: True iff the local_path is a tempfile we own and must unlink.
    ...
    if blob_url:
        ...
        return clip_bytes, tmp_path, True
    if db_path and Path(db_path).exists():
        return clip_bytes, db_path, False
```
Then `_moderate_real` reads the boolean directly instead of re-fetching the clip row.

---

### WR-03: `db_sqlite.write_moderation_decision` returns wrong id under conflict

**File:** `backend/db_sqlite.py:940-970` vs `backend/db_postgres.py:899-930`
**Issue:** Postgres `write_moderation_decision` uses `RETURNING id`, returning the ACTUAL row id (which on conflict is the original/existing id, since `ON CONFLICT DO UPDATE` updates an existing row but returns its primary key). SQLite version omits `RETURNING id` from the SQL and unconditionally returns the freshly-generated `dec_id` from the local variable.

Effect: under retry/idempotency scenarios, the two backends return different ids for the SAME (clip_id, provider) pair:
- Postgres: returns the original row's id.
- SQLite: returns a fresh UUID that doesn't match anything in the DB.

Callers that store the returned id and use it as a foreign key would diverge. Today no caller does — `moderate.py` discards the return value — but the dispatcher contract (D-07) requires byte-identical signatures AND parity in observable behavior.

**Fix:** Add `RETURNING id` to the SQLite SQL and read the actual returned id:
```python
async def write_moderation_decision(...) -> str:
    dec_id = uuid.uuid4().hex
    raw_json = json.dumps(raw_response) if raw_response is not None else None
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            """INSERT INTO moderation_decisions
                 (id, clip_id, provider, decision, reason, raw_response, latency_ms, prompt_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(clip_id, provider) DO UPDATE SET
                 decision       = excluded.decision,
                 reason         = excluded.reason,
                 raw_response   = excluded.raw_response,
                 latency_ms     = excluded.latency_ms,
                 prompt_version = excluded.prompt_version
               RETURNING id""",
            (dec_id, clip_id, provider, decision, reason, raw_json, latency_ms, prompt_version),
        )
        row = await cur.fetchone()
        await conn.commit()
    return row[0] if row else dec_id
```
SQLite supports `RETURNING` since 3.35.0 (2021). aiosqlite passes it through.

---

### WR-04: `db_postgres.get_moderation_decisions` doc-comment falsely claims auto-decode

**File:** `backend/db_postgres.py:962-974`
**Issue:** Comment says "raw_response is returned as a Python dict (asyncpg jsonb codec auto-decodes)". asyncpg's default JSONB representation is the raw JSON text (str), not a dict — you have to register a codec via `conn.set_type_codec('jsonb', ...)` for auto-decode. The current pool initialization does not register such a codec.

Effect:
- Callers reading `r["raw_response"]` get a string, not a dict.
- `compile.py:631-636` defensively re-parses with `json.loads(raw)` when it's a string — that branch is the LIVE path on postgres, contrary to its appearance as defensive dead code for SQLite-only.
- Any future caller that trusts the doc comment and treats it as a dict will silently break.

**Fix:** Either register a jsonb codec on pool init (preferred, matches the doc), or fix the doc + ensure all callers parse:
```python
# In init_pool, after create_pool:
async def _set_jsonb_codec(conn):
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
_pool = await asyncpg.create_pool(
    dsn=config.DATABASE_URL,
    min_size=1, max_size=10,
    init=_set_jsonb_codec,
)
```
Then update the doc to confirm the codec is registered. Also remove the `isinstance(raw, str)` branch in compile.py once you trust the codec.

---

### WR-05: Missing GEMINI_API_KEY produces silent unknown-everywhere outage

**File:** `backend/pipeline/moderate.py:293-297`
**Issue:** When `config.GEMINI_API_KEY` is empty, `_gemini_classify` raises `httpx.ConnectError("GEMINI_API_KEY unset")`, which `_classify_exception` routes to `("unknown", "classifier_network_error")`. Every clip then gets hidden via `set_clip_hidden`. The deploy failure is silent: the API still serves 202s on POST /clips, but every clip is invisible. Unlike the bait-and-switch with the typed-exception ladder (CR-03), this one fires at startup-config level and should be loud.

**Fix:** At `lifespan` startup, fail-loud when METADATA_BACKEND=postgres + OFFLINE_DEMO=false + GEMINI_API_KEY is empty (mirrors the existing DATABASE_URL fail-loud at db_postgres.py:104-110). Or at minimum emit a single WARNING log line at startup per the same pattern as `_pre_warm_sdk` for ANTHROPIC_API_KEY (app.py:55-59).

---

### WR-06: `_route_verdict` precedence — soft-flag drops categories on hard-block

**File:** `backend/pipeline/moderate.py:374-387`
**Issue:** When a hard-block category fires, the function returns `(("blocked", f"gemini_{cat}_block", []))` — empty soft_flag_categories. But the parsed JSON may also have hate or violence flagged on the same clip (e.g. CSAM-block + violence-flag on a violent abusive scene). That metadata is silently dropped from the ModerationResult, which means:
- compile.py never sees the soft-flag signal for THIS clip — but the clip is blocked anyway, so soft-flag derivation in compile.py reads the persisted `raw_response` JSONB at line 626-650, which DOES contain hate/violence verdicts. So the surface impact is contained.

The bug is only in the in-memory `ModerationResult.soft_flag_categories` (an `info` finding except the field is documented as the canonical signal). Worth flagging as warning because the dataclass field becomes inconsistent with persisted state.

**Fix:** Always populate `soft_flag_categories` from the parsed JSON, regardless of hard-block status:
```python
def _route_verdict(parsed: dict) -> tuple[str, str | None, list[str]]:
    soft_flag_categories = [
        cat for cat in SOFT_FLAG_CATEGORIES
        if (parsed.get(cat) or {}).get("verdict") in ("flag", "block")
    ]
    for cat in HARD_BLOCK_CATEGORIES:
        node = parsed.get(cat) or {}
        if node.get("verdict") in ("flag", "block"):
            return ("blocked", f"gemini_{cat}_block", soft_flag_categories)
    if soft_flag_categories:
        return ("passed", f"soft_flag_{soft_flag_categories[0]}", soft_flag_categories)
    return ("passed", None, [])
```

---

### WR-07: `compile.py` soft-flag derivation is N+1 over cluster members

**File:** `backend/pipeline/compile.py:624-650`
**Issue:** Reads `db.get_moderation_decisions(member["id"])` once per cluster member inside compile_segment. For a cluster with 5 parents this is 5 sequential DB roundtrips just to compute `soft_flag`. Each roundtrip in the postgres path acquires a pool conn from the asyncpg pool. Under demo load this is fine; under any pilot traffic burst it adds 5 × ~5-30ms = 25-150ms to compile latency for no good reason.

This is also called BEFORE `db.set_compile_in_flight` is cleared in the finally clause, so a slow soft-flag derivation extends the in-flight TTL (30s).

Performance is out of v1 scope, BUT the pattern is also a correctness-adjacent issue: any DB hiccup on member N causes `soft_flag = False` (the except block default) regardless of what members 1..N-1 said.

**Fix:** Single batched query — add a `db.get_moderation_decisions_for_clips(clip_ids: list[str])` helper that returns a flat list of decisions, then iterate in Python:
```python
async def get_moderation_decisions_for_clips(clip_ids: list[str]) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT clip_id, raw_response FROM moderation_decisions "
        "WHERE clip_id = ANY($1::text[])", clip_ids,
    )
    return [dict(r) for r in rows]
```
Then derive soft_flag in one pass over the result. Same idea on SQLite with `IN ({placeholders})`.

## Info

### IN-01: `ALL_CATEGORIES` constant is unused

**File:** `backend/pipeline/moderate.py:124`
**Issue:** Defined as `HARD_BLOCK_CATEGORIES + SOFT_FLAG_CATEGORIES` but never read by any function in the module. Dead constant.
**Fix:** Remove or wire it into a module-level invariant check (e.g., assert the parsed Gemini response keys ⊆ ALL_CATEGORIES before routing).

---

### IN-02: `_now_unix` and `_one_year_from_now_unix` are trivial wrappers

**File:** `backend/pipeline/moderate.py:177-183`
**Issue:** Two private helpers wrap `time.time()` and `time.time() + 365*24*60*60`. Single-use call sites; the named helpers don't add clarity.
**Fix:** Inline at the call site (`preserved_until=time.time() + 365 * 24 * 60 * 60`) — the constant is already documented in the dataclass + the migration. Or keep the helpers for testability (mockable). Either is fine; pick one and stick with it.

---

### IN-03: `db_sqlite.write_reported_csam` doesn't return existing id on conflict

**File:** `backend/db_sqlite.py:973-989`
**Issue:** Same parity issue as WR-03 — the SQLite version always returns the freshly-generated `rep_id`, never the existing row's id on conflict. The postgres version has the same surface behavior (DO NOTHING with RETURNING returns no row, so it also falls back to `rep_id`). Documented as "acceptable for the audit-trail use case" in the postgres doc. So the parity is preserved BUT the documented contract is misleading — neither backend returns the actual existing row id.
**Fix:** Update both doc comments to be precise: "On conflict the existing row is preserved; this writer returns the freshly-generated id even though the database has a different id for the dedup-collision row. Callers should not assume the return value is queryable."

---

### IN-04: `_strip_anonymity_metadata` recursion is unguarded against cycles

**File:** `backend/pipeline/moderate.py:157-174`
**Issue:** Mirrors `observability/anonymity._scrub` style. Both recurse without a depth limit or seen-set. JSON from Gemini can't be cyclic, but the helper is documented as "defense-in-depth for any future code path that might serialize a request body manually" — if that future code path passes a self-referential dict, this recurses forever.
**Fix:** Add a depth cap (e.g., 64) and return `obj` unchanged at the limit. Low-priority defense in defense.

---

### IN-05: `tests/pipeline/__init__.py` is empty

**File:** `backend/tests/pipeline/__init__.py:1`
**Issue:** Single empty line. Pytest doesn't require __init__.py for test-discovery (only when test names collide across directories). Harmless but not load-bearing.
**Fix:** Either delete the file or add a docstring documenting why it's required (if it actually is).

---

### IN-06: Migration 0004 ALTER assumes baseline `moderation_decisions` is empty-or-acceptable

**File:** `backend/migrations/versions/20260430_0004_moderation_columns.py:33-40`
**Issue:** Adds NOT NULL columns with DEFAULTs, then DROP DEFAULT after the ALTER lands. Comment notes "the Phase 9 table may be non-empty in production." If existing rows pre-date Phase 11, they get retro-decision='passed' and provider='stub' — which silently classifies them as having been moderated. If they were Phase 9 audit-trail entries from a stub provider, this is correct. If they were anything else, downstream `aggregate_verdict` reads them as passed + obscures real history.
**Fix:** Add a one-liner comment confirming the Phase 9 table is empty in current production (verify against the deploy snapshot), or write a precondition check in the migration that aborts if the table is non-empty.

---

_Reviewed: 2026-04-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

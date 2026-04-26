---
phase: quick-260425-pyj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/pipeline/embed.py
  - backend/pipeline/run.py
  - backend/db.py
  - backend/tests/test_pipeline_integration.py
  - backend/tests/test_cluster.py
autonomous: true
requirements:
  - CLU-01
  - CLU-02
  - CLU-03
  - CMP-05

must_haves:
  truths:
    - "embed_worker returns the parent's asset-scope vector (one entry) for clustering, not child entries"
    - "Child rows still exist in the clips table with parent_id, start_offset_sec, end_offset_sec, and embeddings stored — but their cluster_id stays NULL"
    - "cluster_worker is called exactly once per upload (with parent_id + parent_vec); CLUSTERS.member_ids contains parent ids"
    - "compile_segment only fires when a cluster has >=2 distinct parent uploads — solo-parent clusters NEVER trigger compile_segment, regardless of child count"
    - "Existing Phase 3 tests still pass (a single mock-embedded clip creates exactly one cluster, member_count=1, no compile fires)"
    - "OFFLINE_DEMO and USE_MOCK_EMBEDDINGS paths continue to work — mock parent vector is used as the cluster vector"
  artifacts:
    - path: "backend/pipeline/embed.py"
      provides: "embed_worker returns [(parent_clip_id, parent_vec)] only — children stored but not surfaced for clustering"
      contains: "return [(clip_id, parent_vec)]"
    - path: "backend/pipeline/run.py"
      provides: "Single cluster_worker call per upload using parent vec; _should_compile uses parent-distinct count"
      contains: "_count_distinct_parents"
    - path: "backend/db.py"
      provides: "count_distinct_parents_in_cluster helper that filters parent rows only (parent_id IS NULL)"
      contains: "WHERE cluster_id = ? AND parent_id IS NULL"
    - path: "backend/tests/test_pipeline_integration.py"
      provides: "Negative test: single-parent cluster (with N children) does NOT trigger compile; positive test: 2-parent cluster DOES"
      contains: "test_two_parents_triggers_compile"
  key_links:
    - from: "backend/pipeline/run.py"
      to: "backend/pipeline/cluster.py"
      via: "cluster_worker(parent_clip_id, parent_vec) — single call per upload"
      pattern: "await cluster_worker\\("
    - from: "backend/pipeline/run.py"
      to: "backend/db.py"
      via: "_should_compile -> count_distinct_parents_in_cluster"
      pattern: "count_distinct_parents_in_cluster"
    - from: "backend/db.py"
      to: "clips table"
      via: "SQL: SELECT COUNT(*) FROM clips WHERE cluster_id=? AND parent_id IS NULL"
      pattern: "parent_id IS NULL"
---

<objective>
Apply two LOCKED architectural pivots that revert Phase 4.5's child-level clustering decision and add the load-bearing 2-parent publish gate before the compile pipeline spawns.

**Pivot 1 — Clustering unit reverts to parents (asset-scope).**
Whole-upload Marengo embeddings (the asset-scope 512-d vector returned by Twelve Labs) are the unit of clustering. Children remain in the DB as compile-time slicing metadata only — their embeddings are stored for Angle Selector / Caption Writer to query later, but they do NOT enter the clustering loop and they do NOT carry a cluster_id. This restores the tuned-threshold context from the Phase 3 calibration notebook (which was tuned against parent embeddings before children existed).

**Pivot 2 — ≥2-parent publish gate.**
compile_segment is dispatched only when a cluster has ≥2 distinct parent uploads. A single-uploader cluster — even one with 5 children all clustered together (which was actually the Phase 4.5 bug; see code analysis below) — must NEVER produce a segment. Multi-angle clustering is the value prop; "no multi-angle = no compile" is the demo's pitch gate. The gate runs BEFORE compile_segment is spawned (don't waste tokens / 60s wall-clock budget on a doomed compile).

Purpose: The current code path (post-4.5) sends every child to cluster_worker and increments member_count per child, so a single 15s upload with 5 children fires compile on a solo cluster of member_count=5. That breaks the multi-angle pitch. This plan rewires both stages forward-only — no schema changes, no migrations, no Phase 3 history rewrite.

Output: One cluster_worker call per upload; cluster.member_count == distinct parent count; child rows have cluster_id = NULL by construction (we never call assign_clip_to_cluster on them); 2-parent gate enforced inline in run_pipeline; tests cover both negative (1-parent cluster, N children) and positive (2-parent cluster) cases.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@/Users/liamshalom/Hacktech/CLAUDE.md
@/Users/liamshalom/Hacktech/.planning/PROJECT.md
@/Users/liamshalom/Hacktech/.planning/STATE.md
@/Users/liamshalom/Hacktech/.planning/ROADMAP.md

<interfaces>
<!-- Key contracts the executor needs. Extracted from current code. -->

CURRENT (post-4.5) — backend/pipeline/embed.py — embed_worker returns:
```python
# When upload produces children (>3s clip):
return [(child_id, child_vec), (child_id, child_vec), ...]   # children dispatched to cluster
# When upload is short (<=3s, no children returned by Marengo):
return [(clip_id, parent_vec)]
```

CURRENT — backend/pipeline/run.py — votes loop:
```python
votes: dict[str, int] = {}
for cid, vec in child_pairs:
    cluster_id = await cluster_worker(cid, vec)   # called per CHILD — wrong unit per pivot 1
    votes[cluster_id] = votes.get(cluster_id, 0) + 1
parent_cluster_id = max(votes, key=lambda k: votes[k])
if await _should_compile(parent_cluster_id):  # member_count counts children — wrong per pivot 2
    asyncio.create_task(compile_segment(parent_cluster_id))
```

CURRENT — backend/pipeline/run.py — _should_compile:
```python
async def _should_compile(cluster_id: str) -> bool:
    cluster = await db.get_cluster(cluster_id)
    if cluster is None or cluster["member_count"] < 2:   # member_count is child count — wrong
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)
```

CURRENT — backend/pipeline/cluster.py — cluster_worker side effects:
```python
await db.upsert_cluster(updated)                  # persist cluster row
await db.assign_clip_to_cluster(clip_id, cluster.id)  # sets clips.cluster_id on the passed id
CLUSTERS[cluster.id] = updated                     # cache: member_count++, member_ids += [clip_id]
```

CURRENT — backend/db.py — schema (clips table relevant cols):
```sql
clips:
  id TEXT PRIMARY KEY,
  cluster_id TEXT,           -- set by assign_clip_to_cluster
  parent_id TEXT REFERENCES clips(id),  -- NULL for parents, set for children (4.5 migration)
  start_offset_sec REAL DEFAULT 0,
  end_offset_sec REAL DEFAULT NULL,
  ...
```

CURRENT — backend/db.py — fetch_cluster_clips_with_children:
```python
# Used by Angle Selector MCP tool to walk parent_id -> path + offsets.
# IMPORTANT: this function relies on clips.cluster_id being set on children today.
# After pivot 1, children have cluster_id=NULL, so this function MUST be rewritten
# to walk parent rows -> children via parent_id (see Task 2).
```

POST-PIVOT — backend/pipeline/embed.py — embed_worker contract:
```python
async def embed_worker(clip_id: str) -> tuple[str, np.ndarray]:
    """Returns (parent_clip_id, parent_vec). Always exactly one pair.
    Children are still inserted + embedded but are NOT returned for clustering."""
    return clip_id, parent_vec
```

POST-PIVOT — backend/pipeline/run.py — run_pipeline:
```python
parent_clip_id, parent_vec = await embed_worker(clip_id)
cluster_id = await cluster_worker(parent_clip_id, parent_vec)   # ONE call per upload
if await _should_compile(cluster_id):
    asyncio.create_task(compile_segment(cluster_id))
```

POST-PIVOT — backend/db.py — new helper:
```python
async def count_distinct_parents_in_cluster(cluster_id: str) -> int:
    """Returns number of parent (parent_id IS NULL) clip rows assigned to this cluster.
    Defensive count — should equal cluster.member_count under pivot 1, but resilient
    if cluster_id ever leaks onto a child row."""
    # SELECT COUNT(*) FROM clips WHERE cluster_id = ? AND parent_id IS NULL
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rewire embed_worker + run_pipeline to cluster on parents only</name>
  <files>backend/pipeline/embed.py, backend/pipeline/run.py</files>
  <action>
**Goal:** One cluster_worker call per upload, using the parent's asset-scope vector. Children stored but never reach the clusterer.

**Step 1 — backend/pipeline/embed.py — change `embed_worker` signature and behavior:**

Change the return type from `list[tuple[str, np.ndarray]]` to `tuple[str, np.ndarray]`. The function MUST always return exactly one pair: `(parent_clip_id, parent_vec)`.

Inside `embed_worker`:
- Keep the call to `_sync_embed` exactly as-is (it returns `(parent_vec, children, latency_ms)`).
- Keep `await db.store_embedding(clip_id, parent_vec, latency_ms)` — parent embedding is still stored on the parent row.
- Keep the loop that calls `db.insert_child_clip(...)` for each child and `db.store_embedding(child_id, child["vec"], latency_ms)`. Children remain in the DB with their embeddings — DO NOT remove this. Children are needed at compile time for Angle Selector / Caption Writer / stitch.
- After inserting children, return `(clip_id, parent_vec)` ALWAYS — short-clip branch (no children) and long-clip branch both return the parent pair. The list-of-pairs return value is gone.
- Update the docstring: change "Phase 4.5: returns list of (id, vec) pairs for cluster_worker" to "Phase 4.6: returns (parent_clip_id, parent_vec) — exactly one pair. Children are still inserted + embedded but cluster on the parent only (per locked architectural pivot)."

**Step 2 — backend/pipeline/run.py — simplify run_pipeline:**

Replace the `votes` loop with a single cluster_worker call:
```python
parent_clip_id, parent_vec = await embed_worker(clip_id)
log.info("pipeline embed done clip_id=%s parent_dims=%d", clip_id, len(parent_vec))
await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "embedded"})

cluster_id = await cluster_worker(parent_clip_id, parent_vec)
log.info("pipeline cluster done clip_id=%s cluster_id=%s", clip_id, cluster_id)
await events.broadcast({"type": "pipeline_progress", "clip_id": clip_id, "stage": "clustered"})

if await _should_compile(cluster_id):
    asyncio.create_task(compile_segment(cluster_id))
    log.info("compile triggered cluster_id=%s parent=%s", cluster_id, clip_id)
```

Delete the `votes: dict[str, int] = {}` block, the per-child loop, and the `parent_cluster_id = max(votes, ...)` resolution — they are obsolete.

**Step 3 — backend/pipeline/run.py — rewrite `_should_compile` to use distinct-parent count:**

```python
async def _should_compile(cluster_id: str) -> bool:
    """Pivot 2: compile only when cluster has >=2 distinct PARENT uploads.
    Solo-parent clusters never compile, even if they have many children."""
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    if parent_count < 2:
        return False
    return await db.set_compile_in_flight(cluster_id, True, ttl_seconds=30.0)
```

Drop the `await db.get_cluster(cluster_id)` lookup — `count_distinct_parents_in_cluster` is the single source of truth for the gate.

**Step 4 — backend/db.py — add `count_distinct_parents_in_cluster` helper:**

Add anywhere near the other cluster helpers (after `get_cluster`):
```python
async def count_distinct_parents_in_cluster(cluster_id: str) -> int:
    """Pivot 2 gate: count parent (parent_id IS NULL) clip rows in this cluster.
    Defensive — under pivot 1 cluster.member_count already equals this value,
    but if cluster_id ever leaks onto a child row this query stays correct."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM clips WHERE cluster_id = ? AND parent_id IS NULL",
            (cluster_id,),
        ) as cur:
            row = await cur.fetchone()
    return int(row[0]) if row else 0
```

**Step 5 — backend/db.py — patch `fetch_cluster_clips_with_children` to walk parent_id (not child cluster_id):**

The current implementation in db.py at lines 429-471 does:
```sql
SELECT ... FROM clips WHERE cluster_id = ? ORDER BY ts ASC, start_offset_sec ASC
```

This breaks under pivot 1 because children no longer have a cluster_id. Replace with a two-step query:
```python
# Step A: find parent ids in this cluster
SELECT id, path, lat, lng, ts FROM clips WHERE cluster_id = ? AND parent_id IS NULL ORDER BY ts ASC

# Step B: fetch children of those parents (parent_id IN (...)), include parents themselves too
SELECT id, path, lat, lng, ts, parent_id, start_offset_sec, end_offset_sec
FROM clips WHERE id IN (parent_ids) OR parent_id IN (parent_ids) ORDER BY ts ASC, start_offset_sec ASC
```

Output rows must keep the existing shape (id, path, parent_path, lat, lng, ts, parent_id, start_offset_sec, end_offset_sec) so compile.py's `_get_children_with_vecs` and the Angle Selector MCP tool stay backward compatible.

For each output row: `parent_path` is the parent's `path` (the actual video file). For parent rows, `path` and `parent_path` are equal. For child rows, `path` may be the empty string (children have `path=""` per insert_child_clip) so callers should fall back to `parent_path`.

**Step 6 — also make sure `compile_segment` (compile.py) still works:**

`compile_segment` calls `_get_children_with_vecs(cluster_id)` which calls `fetch_cluster_clips_with_children`. Once Step 5 is done, this transparently returns parents+children for the cluster. No changes to compile.py needed. (Verify by reading compile.py around line 307–315.)

**Anonymity / OFFLINE_DEMO check:** No new env vars, no new external calls, no auth changes. Mock-embedding path in `_sync_embed` still produces the same `parent_vec` and the same 3 fake children. `OFFLINE_DEMO=true` is unaffected.
  </action>
  <verify>
    <automated>cd /Users/liamshalom/Hacktech &amp;&amp; .venv/bin/python -c "import ast, sys; tree = ast.parse(open('backend/pipeline/embed.py').read()); fn = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'embed_worker'][0]; ret = fn.returns; assert ret is not None, 'embed_worker must have a return annotation'; src = ast.unparse(ret); assert 'tuple' in src.lower() and 'list' not in src.lower(), f'embed_worker should return tuple, got {src}'; print('OK embed_worker signature:', src)"</automated>
  </verify>
  <done>
- `embed_worker` returns `tuple[str, np.ndarray]` (one pair, not a list)
- `run_pipeline` calls `cluster_worker` exactly once per upload (no `votes` dict)
- `_should_compile` calls `db.count_distinct_parents_in_cluster` and gates on `>= 2`
- `db.count_distinct_parents_in_cluster` exists with the documented SQL
- `db.fetch_cluster_clips_with_children` walks parent_id, not child cluster_id
- `grep -n "votes" backend/pipeline/run.py` returns nothing
- `grep -n "cluster_id IS NOT NULL.*child\|assign_clip_to_cluster.*child" backend/pipeline/` returns nothing — children are never assigned a cluster_id
  </done>
</task>

<task type="auto">
  <name>Task 2: Update + extend tests to lock both pivots</name>
  <files>backend/tests/test_pipeline_integration.py, backend/tests/test_cluster.py</files>
  <action>
**Goal:** Tests prove (a) the negative gate (1-parent cluster with children does NOT compile), (b) the positive gate (2-parent cluster DOES compile), and (c) children never carry a cluster_id.

**Step 1 — Update existing tests in `test_pipeline_integration.py` for new embed_worker signature:**

The existing `test_run_pipeline_creates_cluster_for_first_clip` and `test_run_pipeline_chains_embed_then_cluster_in_order` call `run_pipeline(clip_id)` — they should still pass under the new contract because `run_pipeline` is the public surface. Run them first to confirm. If the broadcast order assertion fails because the old code emitted `cluster_assigned` once per child (so multiple events), update the assertion to match the new single-call contract: exactly one `cluster_assigned` per upload.

**Step 2 — Add negative test: 1-parent cluster (with children) does NOT trigger compile:**

In `test_pipeline_integration.py` add:
```python
@pytest.mark.asyncio
async def test_solo_parent_cluster_does_not_trigger_compile(tmp_db, monkeypatch):
    """Pivot 2 gate: a single-uploader cluster — even with N children — must NEVER compile."""
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)

    compile_calls: list[str] = []

    async def fake_compile(cluster_id: str) -> None:
        compile_calls.append(cluster_id)

    # Patch compile_segment AT THE IMPORT SITE inside run.py
    with patch("backend.pipeline.run.compile_segment", side_effect=fake_compile):
        clip_id = await _insert_fake_clip(tmp_db)
        await run_pipeline(clip_id)
        # Yield once so any stray asyncio.create_task can run
        await asyncio.sleep(0)

    # Cluster created
    assert len(cluster_mod.CLUSTERS) == 1
    cluster_id = next(iter(cluster_mod.CLUSTERS))
    cluster = cluster_mod.CLUSTERS[cluster_id]
    assert cluster.member_count == 1, (
        f"member_count must be 1 (one parent), got {cluster.member_count}. "
        "If this is 3 or 5, you're still counting children."
    )

    # Compile MUST NOT have been called
    assert compile_calls == [], (
        f"compile_segment was called for solo-parent cluster: {compile_calls}. "
        "Pivot 2 gate failed — multi-angle = the pitch."
    )

    # Children exist in DB but carry NO cluster_id
    children = await db.get_children_by_parent(clip_id)
    assert len(children) >= 1, "expected mock to insert at least 1 child"
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM clips WHERE parent_id IS NOT NULL AND cluster_id IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
    assert row[0] == 0, (
        f"{row[0]} child row(s) carry a cluster_id — Pivot 1 violated. "
        "Children must have cluster_id=NULL."
    )
```

**Step 3 — Add positive test: 2-parent cluster DOES trigger compile:**

```python
@pytest.mark.asyncio
async def test_two_parents_triggers_compile(tmp_db, monkeypatch):
    """Pivot 2 gate (positive): two parent uploads in same cluster -> compile fires exactly once."""
    monkeypatch.setattr(config, "USE_MOCK_EMBEDDINGS", True)

    # Force both uploads into the same cluster by stubbing _mock_embedding to return
    # the SAME parent vector for both clips (mock children are randomized via
    # int.from_bytes so they would naturally diverge — only the parent must match).
    from backend.pipeline import embed as embed_mod
    fixed_parent = np.ones(512, dtype=np.float32)
    fixed_parent /= np.linalg.norm(fixed_parent)
    real_mock = embed_mod._mock_embedding

    def stub_mock(clip_id: str) -> np.ndarray:
        # Parent ids look like uuid4().hex (32 chars no underscore); children look
        # like "<parent>_child_<offset>". Detect parent by absence of "_child_".
        if "_child_" in clip_id or clip_id == "__prewarm__":
            return real_mock(clip_id)
        return fixed_parent.copy()

    monkeypatch.setattr(embed_mod, "_mock_embedding", stub_mock)

    compile_calls: list[str] = []

    async def fake_compile(cluster_id: str) -> None:
        compile_calls.append(cluster_id)

    with patch("backend.pipeline.run.compile_segment", side_effect=fake_compile):
        # Same lat/lng/ts so GPS+time gates pass; parent vec match so visual floor passes
        clip_a = await _insert_fake_clip(tmp_db, lat=34.1, lng=-118.1, ts=1_000_000.0)
        await run_pipeline(clip_a)
        clip_b = await _insert_fake_clip(tmp_db, lat=34.1, lng=-118.1, ts=1_000_010.0)
        await run_pipeline(clip_b)
        await asyncio.sleep(0)

    # Single cluster of size 2
    assert len(cluster_mod.CLUSTERS) == 1, f"expected 1 cluster, got {len(cluster_mod.CLUSTERS)}"
    cluster_id = next(iter(cluster_mod.CLUSTERS))
    assert cluster_mod.CLUSTERS[cluster_id].member_count == 2

    # Distinct-parent count from DB matches
    parent_count = await db.count_distinct_parents_in_cluster(cluster_id)
    assert parent_count == 2, f"expected 2 distinct parents, got {parent_count}"

    # Compile fired exactly once for this cluster
    assert compile_calls == [cluster_id], (
        f"expected compile_segment called once with {cluster_id}, got {compile_calls}"
    )
```

**Step 4 — Add unit test for `count_distinct_parents_in_cluster` in `test_cluster.py` (or a new `test_db_parent_count.py` if the cluster test file is already crowded):**

```python
@pytest.mark.asyncio
async def test_count_distinct_parents_in_cluster_ignores_children(tmp_db):
    """Even if a child somehow gets a cluster_id, the helper still returns the parent count."""
    cid = uuid.uuid4().hex
    # Insert a parent in the cluster
    parent_id = await _insert_fake_clip(tmp_db)
    await db.assign_clip_to_cluster(parent_id, cid)
    # Insert children referencing the parent — DO NOT assign them to the cluster
    await db.insert_child_clip(parent_id=parent_id, start_offset_sec=0, end_offset_sec=3,
                               lat=34.1, lng=-118.1, ts=1_000_000.0, session_id=None)
    await db.insert_child_clip(parent_id=parent_id, start_offset_sec=3, end_offset_sec=6,
                               lat=34.1, lng=-118.1, ts=1_000_000.0, session_id=None)
    assert await db.count_distinct_parents_in_cluster(cid) == 1

    # Defensive: even if a child leaks a cluster_id, count stays at parent count
    children = await db.get_children_by_parent(parent_id)
    await db.assign_clip_to_cluster(children[0]["id"], cid)
    assert await db.count_distinct_parents_in_cluster(cid) == 1, \
        "helper must filter parent_id IS NULL"
```

If `_insert_fake_clip` is not in `test_cluster.py`, replicate the helper at the top of the test or import it.

**Step 5 — Sanity-grep for forbidden patterns (these are the verification hooks):**

After Tasks 1+2 land, the following greps must all return zero matches in `backend/pipeline/` and `backend/db.py`:
- `assign_clip_to_cluster.*child` — no child should ever be assigned
- `for cid, vec in child_pairs` — old votes loop is gone
- `member_count.*<.*2` in `_should_compile` — superseded by parent count
  </action>
  <verify>
    <automated>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/python -m pytest backend/tests/test_pipeline_integration.py -x -q 2>&amp;1 | tail -20</automated>
  </verify>
  <done>
- `pytest backend/tests/test_pipeline_integration.py -x` passes including the two new tests
- `pytest backend/tests/test_cluster.py -x` passes including the parent-count unit test
- `grep -rn "for cid, vec in child_pairs" backend/pipeline/` returns nothing
- `grep -rn "assign_clip_to_cluster.*child\|child.*assign_clip_to_cluster" backend/pipeline/` returns nothing
- New test names appear in test output: `test_solo_parent_cluster_does_not_trigger_compile`, `test_two_parents_triggers_compile`, `test_count_distinct_parents_in_cluster_ignores_children`
  </done>
</task>

<task type="auto">
  <name>Task 3: Final verification — run full backend suite + grep gates</name>
  <files>none (verification only)</files>
  <action>
Run the full backend test suite and the grep gates that prove both pivots landed. Capture the output to confirm green-on-green before considering the quick task complete.

**Step 1 — Full backend pytest run:**
```bash
cd /Users/liamshalom && backend/.venv/bin/python -m pytest backend/tests/ -x -q
```

All tests must pass. Particular attention to:
- `test_compile.py` — compile_segment happy-path tests still pass (Pivot 2 gate is upstream of compile_segment, so direct calls bypass it; that is correct — compile_segment itself is pure)
- `test_pipeline_integration.py` — old + new tests pass
- `test_cluster.py` — Phase 3 score-against tests untouched and passing
- `test_db_clusters.py` — DB persistence tests pass

**Step 2 — Grep gates (Pivot 1):**
```bash
# Children must never be assigned a cluster_id
grep -rn "assign_clip_to_cluster.*child" backend/pipeline/ backend/db.py
# Should return: nothing

# embed_worker must return a tuple, not a list of pairs
grep -n "list\[tuple\[str, np.ndarray\]\]" backend/pipeline/embed.py
# Should return: nothing

# embed_worker should return exactly one pair
grep -n "tuple\[str, np.ndarray\]" backend/pipeline/embed.py
# Should return: at least one match (the new return annotation)
```

**Step 3 — Grep gates (Pivot 2):**
```bash
# Old votes loop must be gone
grep -n "votes" backend/pipeline/run.py
# Should return: nothing

# New helper must exist
grep -n "count_distinct_parents_in_cluster" backend/db.py backend/pipeline/run.py
# Should return: at least one match in each file

# Old member_count gate must be gone from _should_compile
grep -n 'member_count.*< *2' backend/pipeline/run.py
# Should return: nothing
```

**Step 4 — Manual sanity check on db debug:**

Boot the backend in mock mode locally (or rely on the test harness) and confirm:
- After uploading a single mock clip: `cluster.member_count == 1`, `count_distinct_parents_in_cluster == 1`, no compile fires.
- After uploading a second mock clip with the same parent vec (or matching enough on visual+gps+time): `member_count == 2`, compile fires.

If running locally:
```bash
cd /Users/liamshalom && USE_MOCK_EMBEDDINGS=true backend/.venv/bin/python -m uvicorn backend.app:app --port 8001 &
# Then curl /clips twice and check /debug/clusters + /debug/dbstate
```

If skipping the live boot (acceptable since the new tests cover it), explicitly note "live boot skipped — covered by test_two_parents_triggers_compile" in the SUMMARY.

**Step 5 — Update STATE.md:**

Append a Quick Tasks Completed row:
```
| 260425-pyj | Cluster on parents + 2-parent compile gate (Pivots 1+2) | 2026-04-25 | <commit-sha> | [260425-pyj-clustering-parent-scope-clusters-2-paren](./quick/260425-pyj-clustering-parent-scope-clusters-2-paren/) |
```

Do NOT modify ROADMAP.md — Phase 4.6 entry already exists and tracks the architectural goal; this quick task is the implementation.
  </action>
  <verify>
    <automated>cd /Users/liamshalom &amp;&amp; backend/.venv/bin/python -m pytest backend/tests/ -x -q 2>&amp;1 | tail -10 &amp;&amp; echo "---grep gates---" &amp;&amp; (grep -rn "assign_clip_to_cluster.*child" backend/pipeline/ backend/db.py || echo "PIVOT1_OK_no_child_assign") &amp;&amp; (grep -n "votes" backend/pipeline/run.py || echo "PIVOT2_OK_no_votes_loop") &amp;&amp; (grep -n "count_distinct_parents_in_cluster" backend/db.py backend/pipeline/run.py)</automated>
  </verify>
  <done>
- Full `pytest backend/tests/ -x` is green
- All four grep gates pass (3 return nothing, 1 returns >=2 matches for the new helper)
- STATE.md has the new Quick Tasks Completed row
- Both pivots are forward-only (no Phase 3 history rewrite, no DB migration, no schema change)
  </done>
</task>

</tasks>

<verification>
**Both pivots provable by automation:**

| Pivot | Test | Grep gate |
|-------|------|-----------|
| 1: cluster on parents | `test_solo_parent_cluster_does_not_trigger_compile` asserts `cluster.member_count == 1` and zero child rows have a `cluster_id` after a single upload that produces 3 children | `grep "assign_clip_to_cluster.*child"` returns nothing |
| 2: ≥2-parent gate | `test_solo_parent_cluster_does_not_trigger_compile` asserts compile NOT called; `test_two_parents_triggers_compile` asserts compile called exactly once after second parent joins | `grep "count_distinct_parents_in_cluster"` returns matches in db.py and run.py; `grep "votes" run.py` returns nothing |

**Existing functionality preserved:**

- Phase 3 calibration notebook (CLU-07/CLU-08) re-runs cleanly because clustering is now back to operating on parent vectors — exactly what the notebook was tuned against.
- OFFLINE_DEMO=true and USE_MOCK_EMBEDDINGS=true paths continue to work — mock parent vec is still returned by `_sync_embed`, children are still inserted, but only the parent enters clustering.
- Anonymity preserved — no schema changes, no new tables, no session/auth touch.
- 60s compile cap and pre-warm logic untouched — gate is upstream of compile_segment.
- compile.py's vision caption-writer + 3-subagent chain unchanged — Pivot 2 only changes when compile_segment is invoked, not what it does.
</verification>

<success_criteria>
1. `embed_worker` returns exactly one `(parent_clip_id, parent_vec)` pair per upload (verified by AST inspection in Task 1 verify).
2. `cluster_worker` is called exactly once per upload (verified by removing the votes loop and by `test_run_pipeline_creates_cluster_for_first_clip` still passing — only one `cluster_assigned` event).
3. No child row in `clips` ever has a non-NULL `cluster_id` after running through `run_pipeline` (verified by SQL count in `test_solo_parent_cluster_does_not_trigger_compile`).
4. `compile_segment` is NOT spawned for a 1-parent cluster, regardless of child count (verified by `test_solo_parent_cluster_does_not_trigger_compile`).
5. `compile_segment` IS spawned exactly once when a cluster's distinct-parent count reaches 2 (verified by `test_two_parents_triggers_compile`).
6. `db.count_distinct_parents_in_cluster` filters on `parent_id IS NULL` (verified by `test_count_distinct_parents_in_cluster_ignores_children`).
7. Full `pytest backend/tests/` is green.
8. No DB migration was added (no `ALTER TABLE` introduced in this plan — verified by `git diff backend/db.py | grep ALTER` returning nothing).
</success_criteria>

<output>
After completion, append to STATE.md the Quick Tasks Completed row for `260425-pyj`. Do NOT touch ROADMAP.md (Phase 4.6 entry stays as-is — this quick task is its implementation).
</output>

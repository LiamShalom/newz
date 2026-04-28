---
phase: 09-postgres-migration-neon-asyncpg-alembic
plan: 06
subsystem: infra

tags: [railway, alembic, deploy, predeploycommand, postgres]

# Dependency graph
requires:
  - phase: 09-postgres-migration-neon-asyncpg-alembic
    provides: alembic versioned migrations (09-04 / 09-05) — preDeployCommand invokes `alembic upgrade head`
provides:
  - Railway preDeployCommand wired in railway.toml with array form ["alembic", "upgrade", "head"]
  - Railway preDeployCommand wired in railway.json with single-string array form ["alembic upgrade head"]
  - Migration gate: web container only starts after alembic upgrade head exits 0
  - Procfile deliberately unchanged (D-13 correction — Railway ignores `release:`)
affects:
  - 09-07-PLAN (deploy verification — depends on preDeployCommand working in Railway logs)
  - All future 09-* plans that ship schema changes (relies on this gate to apply migrations on deploy)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Railway preDeployCommand for pre-web migration gate (separate ephemeral container)"

key-files:
  created: []
  modified:
    - backend/railway.toml
    - backend/railway.json

key-decisions:
  - "preDeployCommand is the documented Railway mechanism — Procfile `release:` is silently ignored under Railway (D-13 correction confirmed by RESEARCH Pitfall 3)"
  - "TOML uses argv array form ['alembic', 'upgrade', 'head']; JSON mirrors RESEARCH §Code Examples line 828 with single-string array form ['alembic upgrade head'] — both shapes are accepted by Railway"
  - "preDeployCommand inserted as FIRST key in [deploy] / deploy block to keep diff minimal and visible"

patterns-established:
  - "Migration gate pattern: alembic upgrade head runs in separate ephemeral container before web container start; non-zero exit halts deploy and prevents un-migrated DB serving traffic"

requirements-completed:
  - DB-02

# Metrics
duration: 5min
completed: 2026-04-28
---

# Phase 09 Plan 06: Railway preDeployCommand for alembic Summary

**preDeployCommand wired into both railway.toml (TOML argv array) and railway.json (JSON single-string array) so Railway runs `alembic upgrade head` in a separate ephemeral container before web start; Procfile intentionally untouched per D-13 correction.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-28
- **Completed:** 2026-04-28
- **Tasks:** 2 of 3 (Task 3 is a checkpoint:human-verify gate — Railway probe deploy is owed by a human; see "Pending Human Verification" below)
- **Files modified:** 2

## Accomplishments
- backend/railway.toml [deploy] block now declares `preDeployCommand = ["alembic", "upgrade", "head"]` as its first key; existing healthcheck and restartPolicy keys preserved unchanged
- backend/railway.json deploy object now declares `"preDeployCommand": ["alembic upgrade head"]` as its first key; `$schema`, build.*, and existing deploy keys preserved unchanged
- backend/Procfile left untouched — confirms the D-13 correction (Railway silently ignores Procfile `release:` per RESEARCH Pitfall 3)
- Both files validated parse-clean (tomllib + json.load) with expected key sets

## Task Commits

Each task was committed atomically:

1. **Task 1: Add preDeployCommand to backend/railway.toml** — `051f4be` (chore)
2. **Task 2: Add preDeployCommand to backend/railway.json** — `badb37c` (chore)
3. **Task 3: Checkpoint — Railway probe deploy verification** — pending human action (D-14 / RESEARCH §A6 owed)

## Files Created/Modified
- `backend/railway.toml` — inserted preDeployCommand as first key in [deploy] block (10 lines total, was 9)
- `backend/railway.json` — inserted preDeployCommand as first key in deploy object (14 lines total, was 13)

## Decisions Made
- **TOML argv array form vs JSON single-string array form:** TOML uses `["alembic", "upgrade", "head"]` (3 tokens, unambiguous about argv splitting per RESEARCH §Architecture); JSON uses `["alembic upgrade head"]` (1 element matching RESEARCH §Code Examples line 828 template). Railway accepts both shapes — this preserves alignment with the documented research template per file format.
- **Insertion position:** preDeployCommand is the FIRST key in each deploy block. This makes the migration gate the most visible thing in the deploy config and keeps the diff minimal.
- **Procfile untouched:** Confirms the D-13 correction. Original CONTEXT.md called for adding `release: alembic upgrade head` to Procfile — RESEARCH Pitfall 3 invalidated that approach. This plan deliberately makes no Procfile changes.

## Deviations from Plan

None — plan executed exactly as written. Both file edits matched the exact final-state TOML and JSON in the plan's `<action>` blocks.

## Issues Encountered
None.

## User Setup Required

None for the code-side change. **However, a human-verify checkpoint is owed (Task 3) before this plan can be fully signed off:**

### Pending Human Verification (Task 3 — checkpoint:human-verify)

D-14 / RESEARCH §A6 verification owed: Railway Dockerfile-builder compatibility with `preDeployCommand`.

**Probe procedure (recommended before relying on the alembic gate):**

1. Push a temporary commit replacing `preDeployCommand` value in railway.toml with `["echo", "PHASE9-PREDEPLOY-PROBE"]`.
2. Trigger a Railway deploy. In Railway's build/deploy logs, confirm:
   - A pre-deploy container appears separately from the web container.
   - The line `PHASE9-PREDEPLOY-PROBE` appears in the pre-deploy container's stdout.
   - The web container only starts AFTER the pre-deploy container exits 0.
3. Revert the probe commit and re-push the real `["alembic", "upgrade", "head"]` value.

**If the probe fails** (Railway doesn't honor `preDeployCommand` under the Dockerfile builder), the documented fallback is RESEARCH §"State of the Art" — FastAPI lifespan + `pg_advisory_lock(deploy_lock_id)` migration runner. That fallback path is NOT implemented by this plan; it would be added in a follow-up plan.

### Quick syntactic re-verification

```bash
python -c "import tomllib; print(tomllib.loads(open('backend/railway.toml').read())['deploy']['preDeployCommand'])"
# Expect: ['alembic', 'upgrade', 'head']
python -c "import json; print(json.load(open('backend/railway.json'))['deploy']['preDeployCommand'])"
# Expect: ['alembic upgrade head']
```

## Verification Results

All plan-level `<verification>` block commands ran clean:

- ✅ `tomllib.loads(railway.toml)['deploy']['preDeployCommand'] == ['alembic', 'upgrade', 'head']`
- ✅ `json.load(railway.json)['deploy']['preDeployCommand'] == ['alembic upgrade head']`
- ✅ `git diff --quiet backend/Procfile` → exit 0 (Procfile unchanged)
- ✅ `grep -E "^release:" backend/Procfile` → exit 1 (no `release:` line — D-13 correction holds)
- ✅ Both deploy blocks contain exactly the 5 expected keys: `{preDeployCommand, healthcheckPath, healthcheckTimeout, restartPolicyType, restartPolicyMaxRetries}`

## Next Phase Readiness
- Wave 2 alembic plan's deploy verification can now lean on this preDeployCommand gate (modulo the D-14 probe).
- 09-07 deploy verification work depends on a human running the Railway probe deploy described above before fully signing off this gate.
- No blockers for code-side parallel waves.

## Self-Check: PASSED

- ✅ `backend/railway.toml` exists, line count 10, parses, preDeployCommand correct
- ✅ `backend/railway.json` exists, line count 14, parses, preDeployCommand correct
- ✅ Commit `051f4be` exists in `git log` (Task 1 — railway.toml)
- ✅ Commit `badb37c` exists in `git log` (Task 2 — railway.json)
- ✅ Procfile unchanged (no diff vs base)
- ✅ No `release:` line in Procfile

---
*Phase: 09-postgres-migration-neon-asyncpg-alembic*
*Plan: 06*
*Completed: 2026-04-28*

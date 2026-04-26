---
quick_id: 260425-pw1
description: Add anthropic dependency to backend requirements
status: complete
date: 2026-04-26
commit: e2236fe
---

# Quick Task 260425-pw1 — SUMMARY

## What changed

`backend/requirements.txt`: added `anthropic>=0.39.0` on line 13, immediately after `claude-agent-sdk==0.1.68`.

```diff
 claude-agent-sdk==0.1.68
+anthropic>=0.39.0
 sse-starlette==2.1.3
```

## Why

`backend/pipeline/caption_pipeline.py:116` imports `anthropic` for vision-grounded captions via `AsyncAnthropic`. The package was missing from the manifest; on Railway the import threw and every compiled segment silently took the `_fallback_caption` path. Local dev worked only because `anthropic-0.97.0` was installed transitively in the personal `.venv`.

## Verification

Ran in a fresh Python 3.11 venv (matches Railway runtime per CLAUDE.md):

```
pip install -r backend/requirements.txt
python -c "import anthropic; from anthropic import AsyncAnthropic; import claude_agent_sdk"
→ anthropic 0.97.0
→ AsyncAnthropic OK
→ claude_agent_sdk OK
```

No resolver conflict between `claude-agent-sdk==0.1.68` and `anthropic>=0.39.0`.

## Commits

- `e2236fe` — fix(backend): declare anthropic dep so caption pipeline works in prod

## Next action (deploy)

Push the branch Railway tracks (`main`) so Railway redeploys with the corrected manifest. After deploy, confirm vision-grounded captions are live by checking that compiled segments no longer hit `_fallback_caption` (logs in `pipeline.caption_pipeline`).

## Out of scope (left untouched)

- `backend/app.py` and `frontend/src/App.tsx` had unrelated unstaged edits — left alone.
- `frontend/src/components/Feed.tsx` has a pre-existing missing-import TS diagnostic (`RecordFAB`) — separate issue, not addressed here.

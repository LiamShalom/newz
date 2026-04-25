# Spike Conventions

Patterns established during baseline-measurement spikes (001–003). New spikes follow these unless the question requires otherwise.

## Stack
- **Language:** Python (matches `backend/`).
- **Interpreter:** `./backend/.venv/bin/python` — the project's existing venv with `twelvelabs`, `claude_agent_sdk`, `aiosqlite`, `numpy`, `imageio_ffmpeg` already installed. No separate spike venv.
- **Discovery:** spikes import directly from `backend.*` by inserting `REPO` (3 levels up from the spike file) into `sys.path`. No package install, no editable build.

## Structure
- One `bench.py` per spike. Markdown stdout output. No HTML, no UI — these spikes answer "how many ms" questions.
- Spike directories: `.planning/spikes/NNN-kebab-name/` with `bench.py` + `README.md`.
- Each `bench.py` accepts `-n / --runs` and prints a markdown summary table at the end (min / p50 / p95 / max).

## Patterns
- **Instrument, don't rewrite.** Spikes call the same module-level functions used in production (`_call_marengo`'s logic, `cluster_worker`, `extract_cluster_keyframes`, `_run_caption_writer_with_vision`, `_run_orchestrator_chain`) and slot timers between them. Production code is never edited for measurement.
- **Throwaway fixtures with bench-prefixed IDs.** Spikes that need DB rows insert clusters/clips with `bench`-prefixed IDs and clean them up via `DELETE WHERE id LIKE 'bench%'`. Fixtures must not pollute the live `newz.db`.
- **Mocks for harness validation, not for results.** Embed and compile spikes run cleanly under `USE_MOCK_EMBEDDINGS=1` to validate the harness — but real numbers come from real APIs.
- **Markdown output.** Console output is formatted as a markdown table that can be pasted directly into the spike README's Results section.

## Tools & Libraries
- `aiosqlite` — already a backend dep; spike uses it directly to set up/tear down fixtures.
- `numpy` — random unit vector helper for cluster-baseline.
- No new packages introduced by these spikes.

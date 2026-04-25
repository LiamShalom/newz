# Newz

AI-native local news from anonymous crowdsourced footage. Hackathon MVP, HackTech (Caltech) April 24-26, 2026. Co-founders: Liam, Roan, Claude.

Anonymous, GPS-tagged short clips → Twelve Labs Marengo 3.0 multimodal embeddings → composite-score event clustering → Claude Agent SDK multi-agent compile → hyperlocal feed. Every user is journalist and audience; there is no creator/consumer split.

## Local dev

Requires Python 3.11, Node 18+, pnpm.

```bash
make install
```

Then in two terminals:

```bash
make backend   # FastAPI on :8000 (http://localhost:8000/health)
```

```bash
make frontend  # Vite on :5173 (http://localhost:5173)
```

The Vite dev server is started with `--host` so a real iPhone on the same Wi-Fi can hit it (required for the Phase 5 iPhone gate).

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env` before first run.

## Deploy

See Plan 05 (Phase 5) for Vercel + Railway deploy instructions and the iPhone QR-code verification gate.

## Stack

| Layer            | Tool                                                                        |
| ---------------- | --------------------------------------------------------------------------- |
| Frontend         | React 18 + Vite + TypeScript + Tailwind 4 (Vercel)                          |
| Backend          | FastAPI + Uvicorn (Python 3.11) on Railway with persistent volume           |
| Video AI         | Twelve Labs `marengo3.0` via `twelvelabs==1.2.3` (512-d multimodal vectors) |
| Multi-agent AI   | Anthropic `claude-agent-sdk==0.1.68`                                        |
| Storage          | SQLite (aiosqlite, WAL) + local FS for clips                                |
| Vector search    | NumPy in-memory cosine over normalized 512-d vectors                        |

## Scope

Phase 1 (this milestone): bootable monorepo + iOS Safari camera + clip upload + raw feed playback. No AI yet — that lands in Phase 2.

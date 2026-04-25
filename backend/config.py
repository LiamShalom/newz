"""
backend/config.py — environment-driven configuration for the Newz backend.
All env vars are loaded from .env (via python-dotenv) with safe defaults for local dev.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Storage ──────────────────────────────────────────────────────────────────
# On Railway: set DATA_DIR=/data (persistent volume mount).
# Locally: defaults to ./data relative to backend/.
DATA_DIR: str = os.getenv("DATA_DIR", str(Path(__file__).parent / "data"))

# SQLite database file path.
DB_PATH: str = os.getenv("DB_PATH", os.path.join(DATA_DIR, "newz.db"))

# Directory where uploaded clips are stored on disk.
CLIPS_DIR: str = os.getenv("CLIPS_DIR", os.path.join(DATA_DIR, "clips"))

# ── Twelve Labs ───────────────────────────────────────────────────────────────
TWELVELABS_API_KEY: str = os.getenv("TWELVELABS_API_KEY", "")

# ── Embedding mode ────────────────────────────────────────────────────────────
# Set to "true" to return deterministic fake 512-d vectors — no API key needed.
# Used for offline dev, CI, and Phase 5 OFFLINE_DEMO path.
USE_MOCK_EMBEDDINGS: bool = os.getenv("USE_MOCK_EMBEDDINGS", "false").lower() == "true"

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")

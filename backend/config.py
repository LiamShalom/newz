import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.local")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()

# Phase 2: Marengo embedding
TWELVELABS_API_KEY: str = os.environ.get("TWELVELABS_API_KEY", "").strip()
PRE_WARM_CLIP_PATH: str = os.environ.get(
    "PRE_WARM_CLIP_PATH", str(Path(__file__).parent / "seed" / "prewarm.mp4")
)

# Phase 4.7: Gemini captioning (replaces Anthropic Haiku/Sonnet caption synthesis)
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Phase 3: Clustering
CLUSTER_THRESHOLD: float = float(os.environ.get("CLUSTER_THRESHOLD", "0.70"))
VISUAL_FLOOR: float = float(os.environ.get("VISUAL_FLOOR", "0.85"))

# Phase 4.6: Run detection (compile-time grouping of contiguous similar children)
# Threshold lowered 0.85 → 0.70 to catch gentle scene shifts (lighting, pan,
# subject change) that wouldn't break a 0.85 floor. The hard MAX_RUN_MEMBERS
# cap below dominates run length even when adjacent cosines stay high.
RUN_THRESHOLD: float = float(os.environ.get("RUN_THRESHOLD", "0.70"))
# Cap on children per run. With 3s child windows this caps run length at 6s.
# Without this, a clean 30s parent collapses into one giant run.
MAX_RUN_MEMBERS: int = int(os.environ.get("MAX_RUN_MEMBERS", "2"))

# Admin: shared secret guarding /admin/* destructive endpoints.
# Empty value disables the endpoint (returns 503).
ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "").strip()

# Phase 8: Observability
LOG_FORMAT: str = os.environ.get("LOG_FORMAT", "json").strip().lower()
SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "").strip()
SENTRY_ENVIRONMENT: str = os.environ.get("SENTRY_ENVIRONMENT", "").strip() or "production"

# Phase 9: Postgres migration (D-06, D-08, D-11, D-17)
# DATABASE_URL: Neon DIRECT endpoint connection string (NOT -pooler — RESEARCH Pitfall 1).
#   Stock Neon URL works as-is; asyncpg parses sslmode=require natively (RESEARCH D-18 resolution).
#   Empty when METADATA_BACKEND=postgres + OFFLINE_DEMO=false should fail-loud at pool init.
DATABASE_URL: str = os.environ.get("DATABASE_URL", "").strip()
# METADATA_BACKEND: 'sqlite' (default — v1.0 path) or 'postgres' (v1.1 cutover).
#   D-06 rollback flag. OFFLINE_DEMO=true hard-overrides to sqlite regardless of this value (D-11).
METADATA_BACKEND: str = os.environ.get("METADATA_BACKEND", "sqlite").strip().lower()
# KEEPALIVE_INTERVAL_S: Neon SELECT 1 ping interval (DEMO-03 / SC-5).
#   240s = 4min, well under Neon's 5min scale-to-zero idle threshold (RESEARCH Pattern 5).
KEEPALIVE_INTERVAL_S: int = int(os.environ.get("KEEPALIVE_INTERVAL_S", "240"))
# OFFLINE_DEMO: when true, all v1.1 external dependencies are bypassed (D-11).
#   Phase 9 effect: hard-overrides METADATA_BACKEND to sqlite, skips Neon pool init + keepalive.
#   Mirrors Phase 8 D-16 graceful-degrade pattern (empty SENTRY_DSN → skip Sentry).
OFFLINE_DEMO: bool = os.environ.get("OFFLINE_DEMO", "false").strip().lower() == "true"

# Phase 10: Vercel Blob migration (D-12, D-19, D-23; amendments 1-8 in 10-PLAN.md)
# STORAGE_BACKEND: 'local' (default — v1.0 path, kept indefinitely for OFFLINE_DEMO + rollback)
#   or 'blob' (v1.1 cutover — Vercel Blob via raw httpx wrapper, D-01).
#   OFFLINE_DEMO=true hard-overrides to local regardless of this value (D-18).
STORAGE_BACKEND: str = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
# BLOB_READ_WRITE_TOKEN: Vercel-issued read/write token for the Blob store.
#   Format: vercel_blob_rw_<store_id>_<random>. Loaded once at module import.
#   Never logged, never sent to browser (L-02). Empty when STORAGE_BACKEND=blob
#   AND OFFLINE_DEMO=false fails fast at lifespan startup (D-19).
BLOB_READ_WRITE_TOKEN: str = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()

# Phase 11: Moderation gate (post-reconciliation D-24 — classifier-only CSAM detection)
# GEMINI_MODERATION_MODEL: separate from GEMINI_MODEL (L18) so the moderation
#   classifier model can iterate independently of the caption pipeline model.
GEMINI_MODERATION_MODEL: str = os.environ.get("GEMINI_MODERATION_MODEL", "gemini-2.5-flash-lite")
# MODERATION_MAX_BUDGET_S: absolute upper-bound on the gate (D-03). Default 20s.
#   Cancel-when-embed-finishes is the typical primitive (Marengo's elapsed time
#   bounds Gemini); this is the safety floor when both tasks exceed Marengo p99.
MODERATION_MAX_BUDGET_S: float = float(os.environ.get("MODERATION_MAX_BUDGET_S", "20.0"))

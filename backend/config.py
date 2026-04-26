import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
OFFLINE_DEMO = os.environ.get("OFFLINE_DEMO", "false").lower() == "true"

# Phase 2: Marengo embedding
TWELVELABS_API_KEY: str = os.environ.get("TWELVELABS_API_KEY", "").strip()
USE_MOCK_EMBEDDINGS: bool = os.environ.get("USE_MOCK_EMBEDDINGS", "false").lower() == "true"
PRE_WARM_CLIP_PATH: str = os.environ.get(
    "PRE_WARM_CLIP_PATH", str(Path(__file__).parent / "seed" / "prewarm.mp4")
)

# Phase 4.7: Gemini captioning (replaces Anthropic Haiku/Sonnet caption synthesis)
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Phase 3: Clustering
CLUSTER_THRESHOLD: float = float(os.environ.get("CLUSTER_THRESHOLD", "0.55"))
VISUAL_FLOOR: float = float(os.environ.get("VISUAL_FLOOR", "0.80"))

# Phase 4.6: Run detection (compile-time grouping of contiguous similar children)
# Threshold lowered 0.85 → 0.70 to catch gentle scene shifts (lighting, pan,
# subject change) that wouldn't break a 0.85 floor. The hard MAX_RUN_MEMBERS
# cap below dominates run length even when adjacent cosines stay high.
RUN_THRESHOLD: float = float(os.environ.get("RUN_THRESHOLD", "0.70"))
# Cap on children per run. With 3s child windows this caps run length at 6s.
# Without this, a clean 30s parent collapses into one giant run.
MAX_RUN_MEMBERS: int = int(os.environ.get("MAX_RUN_MEMBERS", "2"))

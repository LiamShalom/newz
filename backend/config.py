import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
OFFLINE_DEMO = os.environ.get("OFFLINE_DEMO", "false").lower() == "true"

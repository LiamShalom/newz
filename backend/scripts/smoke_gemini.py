"""
backend/scripts/smoke_gemini.py — one-off Gemini Flash smoke test.

Usage:
    python -m backend.scripts.smoke_gemini [path/to/clip.mp4]

Validates: SDK install, Files API upload, video ACTIVE-state polling,
gemini-2.0-flash response_schema enforcement, AP-wire prompt style, latency.
"""

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import os

# Load backend/.env so GEMINI_API_KEY is available
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai
from google.genai import types

# Import the live prompt + schema so the smoke test stays in lockstep with prod
from backend.pipeline.caption_pipeline import SYSTEM_PROMPT, RESPONSE_SCHEMA


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set in environment or backend/.env")
        sys.exit(1)

    clip_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).resolve().parent.parent / "seed" / "demo" / "realworld-1.mp4"
    )
    if not clip_path.exists():
        print(f"ERROR: clip not found at {clip_path}")
        sys.exit(1)

    size_mb = clip_path.stat().st_size / (1024 * 1024)
    print(f"clip: {clip_path.name} ({size_mb:.2f} MB)")

    client = genai.Client(api_key=api_key)

    # 1) Upload via Files API
    t0 = time.time()
    print("uploading to Files API...")
    uploaded = client.files.upload(file=str(clip_path))
    upload_secs = time.time() - t0
    print(f"  -> uploaded in {upload_secs:.2f}s, name={uploaded.name}, state={uploaded.state.name}")

    # 2) Poll until file is ACTIVE (video needs processing)
    t1 = time.time()
    while uploaded.state.name == "PROCESSING":
        time.sleep(1)
        uploaded = client.files.get(name=uploaded.name)
    process_secs = time.time() - t1
    print(f"  -> processed in {process_secs:.2f}s, final state={uploaded.state.name}")

    if uploaded.state.name != "ACTIVE":
        print(f"ERROR: file did not reach ACTIVE state (got {uploaded.state.name})")
        sys.exit(1)

    # 3) Generate content with system prompt + JSON schema
    t2 = time.time()
    model_id = "gemini-2.5-flash"
    print(f"calling {model_id}...")
    response = client.models.generate_content(
        model=model_id,
        contents=[uploaded, "Write the title, caption, and location for this footage."],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    infer_secs = time.time() - t2
    print(f"  -> inference in {infer_secs:.2f}s")

    # 4) Parse + display
    print("\n--- raw response ---")
    print(response.text)

    print("\n--- parsed JSON ---")
    parsed = json.loads(response.text)
    for k, v in parsed.items():
        print(f"  {k}: {v}")

    total = upload_secs + process_secs + infer_secs
    print(f"\n--- TOTAL WALL-CLOCK: {total:.2f}s ---")
    print(f"  upload:  {upload_secs:.2f}s")
    print(f"  process: {process_secs:.2f}s")
    print(f"  infer:   {infer_secs:.2f}s")

    # Cleanup uploaded file
    try:
        client.files.delete(name=uploaded.name)
        print(f"\ncleanup: deleted {uploaded.name}")
    except Exception as e:
        print(f"\ncleanup warning: {e}")


if __name__ == "__main__":
    main()

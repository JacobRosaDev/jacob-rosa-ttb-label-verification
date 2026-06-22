"""Small script to run the VisionService against a local image for manual testing.

Usage: python -m app.run_vision_demo path/to/image.jpg
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .vision_service import OpenAIVisionService


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m app.run_vision_demo path/to/image.jpg")
        return 2
    img_path = Path(argv[1])
    if not img_path.exists():
        print("Image not found:", img_path)
        return 2

    with img_path.open("rb") as f:
        img_bytes = f.read()

    api_key = os.environ.get("OPENAI_API_KEY")
    svc = OpenAIVisionService(api_key=api_key)
    result = svc.extract(img_bytes)
    print(result.json(indent=2, exclude_none=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

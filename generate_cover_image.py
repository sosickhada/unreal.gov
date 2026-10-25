"""Optional story-specific cover image generation via Pollinations.

Requires POLLINATIONS_API_KEY in /opt/unreal.gov/.env. Never charges or
purchases credits automatically. If generation fails, the caller can
continue using the existing Figma background.
Usage: .venv/bin/python generate_cover_image.py "사건 제목" /tmp/cover.png
"""
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

ENV_FILE = Path("/opt/unreal.gov/.env")
API_URL = "https://gen.pollinations.ai/image/"


def env_value(key):
    if os.getenv(key):
        return os.environ[key]
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def generate(title, output):
    key = env_value("POLLINATIONS_API_KEY")
    if not key:
        raise RuntimeError("POLLINATIONS_API_KEY not configured. No API call made.")
    prompt = (
        "Photorealistic editorial photograph, realistic Korean contemporary "
        "office or public institution setting. Story context: " + title + ". "
        "Moody dark navy and subtle blue-gray cinematic color grade, "
        "natural light, restrained contrast, believable real-world details, "
        "no legible text, no letters, no logos, no watermarks, "
        "vertical 4:5 composition, subject in lower half, ample negative "
        "space in upper half for headline overlay. Not 3D, not illustration."
    )
    response = requests.get(
        API_URL + quote(prompt, safe=""),
        params={"model": "flux", "width": 1080, "height": 1350},
        headers={"Authorization": "Bearer " + key},
        timeout=150,
    )
    if response.status_code in (401, 402, 403, 429):
        raise RuntimeError(
            "Image API unavailable (authorization, quota, or rate limit); "
            "no paid fallback was attempted. HTTP " + str(response.status_code)
        )
    response.raise_for_status()
    if not response.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("Image API did not return an image.")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)
    print("Generated:", output)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python generate_cover_image.py "title" output.png')
    generate(sys.argv[1], sys.argv[2])

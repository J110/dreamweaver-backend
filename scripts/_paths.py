"""Shared output paths for content generation.

COVER_OUTPUT_DIR controls where generators write covers. Defaults to
``BASE_DIR/public/covers`` for dev parity; the production cron sets
``COVER_OUTPUT_DIR=/opt/cover-store`` so generators land files directly
in the nginx-aliased serving path — no public/covers/ involvement, no
git commits required.

Mirrors the ``TTS_ENGINE_EN`` env-var pattern used elsewhere.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

COVER_OUTPUT_DIR = Path(
    os.getenv("COVER_OUTPUT_DIR", str(BASE_DIR / "public" / "covers"))
)

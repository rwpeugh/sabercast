"""Sabercast app configuration and shared helpers.

Includes the OpenAI key loader used by every script that calls the API.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Demo mode toggles (used by Phase 3 + 4 polish) ───────────────────────────
DEMO_MODE = "live"  # "showcase" or "live" — sprint runs everything live
CACHED_TEAMS = ["SEA", "LAD", "OAK", "BAL", "TEX"]

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent          # sabercast/
PARENT_DIR   = PROJECT_ROOT.parent                              # ../ (course folder)
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_PROC    = PROJECT_ROOT / "data" / "processed"

# ── OpenAI key loader ────────────────────────────────────────────────────────
def get_openai_api_key() -> str:
    """Return the OpenAI API key from env or a local OpenAIKey.txt file.

    Search order: OPENAI_API_KEY env var, then OpenAIKey.txt in the project root,
    then OpenAIKey.txt one directory up (matches the existing notebook layout).
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key

    for candidate in (PROJECT_ROOT / "OpenAIKey.txt", PARENT_DIR / "OpenAIKey.txt"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()

    raise RuntimeError(
        "OpenAI API key not found. Set OPENAI_API_KEY or place the key in "
        "OpenAIKey.txt in the sabercast/ folder or its parent."
    )

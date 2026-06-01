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
    """Return the OpenAI API key from any supported location.

    Search order:
      1. ``OPENAI_API_KEY`` environment variable (local dev, most CI setups).
      2. ``st.secrets["OPENAI_API_KEY"]`` if running under Streamlit. Streamlit
         Cloud reads secrets from the dashboard's Secrets pane and exposes them
         here; it does NOT always propagate them as env vars.
      3. ``OpenAIKey.txt`` in the project root.
      4. ``OpenAIKey.txt`` one directory up (matches the existing notebook layout).
    """
    # 1. Env var
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key

    # 2. Streamlit secrets — Streamlit Cloud's documented secret mechanism.
    # Guarded so this module remains importable from non-Streamlit contexts
    # (pipelines, eval scripts, smoke tests).
    try:
        import streamlit as st  # noqa: PLC0415
        # ``st.secrets`` is a dict-like proxy; "in" check avoids a KeyError
        # when secrets aren't configured (local dev without secrets.toml).
        if "OPENAI_API_KEY" in st.secrets:
            secret_key = str(st.secrets["OPENAI_API_KEY"]).strip()
            if secret_key:
                return secret_key
    except Exception:
        # streamlit not installed, or no secrets configured — fall through
        pass

    # 3 + 4. Local files
    for candidate in (PROJECT_ROOT / "OpenAIKey.txt", PARENT_DIR / "OpenAIKey.txt"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()

    raise RuntimeError(
        "OpenAI API key not found. On Streamlit Cloud, set OPENAI_API_KEY in "
        "the app's Secrets pane (Manage app → Settings → Secrets). Locally, "
        "set the OPENAI_API_KEY environment variable or place the key in "
        "OpenAIKey.txt in the sabercast/ folder or its parent."
    )

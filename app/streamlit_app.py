"""Sabercast — Streamlit entry point.

Three-tab MLB front-office intelligence app. All three tabs are functional
across any of the 30 MLB clubs:
    1. Roster Builder    — day-to-day lineup construction vs. a chosen opponent
                            with optional probable-starter pick for platoon-
                            aware lineup ordering (one gpt-4o call)
    2. Opponent Scouting — narrative + top threats + exploitable weaknesses
                            (one gpt-4o call)
    3. Gap Filler        — top-3 roster gaps, incumbent-aware composite
                            improvement scoring, bargain / at-budget / premium
                            tier recommendations with explicit trade-off
                            rationales (1 gpt-4o + ~11 gpt-4o-mini calls
                            running in parallel, ~10s end-to-end)

See docs/final_report/SABERCAST_FINAL_REPORT.md for the full evaluation
(13 pre-registered tests, 4 significant findings) and BUILD_LOG.md for the
chronological build history (32 entries).
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make `core.*` and `app.*` importable regardless of how Streamlit was launched.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.tabs import gap_filler, opponent_scouting, roster_builder  # noqa: E402


st.set_page_config(
    page_title="Sabercast — MLB front-office intelligence",
    page_icon="⚾",
    layout="wide",
)

# ── Header ───────────────────────────────────────────────────────────────────
st.title("Sabercast")
st.caption(
    "LLM-powered MLB front-office intelligence. Build rosters, scout opponents, "
    "fill gaps — grounded in real 2024 player data and recent free-agent contracts."
)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "**Sabercast** combines LLM reasoning with cached MLB statistics and "
        "contract data to support roster construction, opponent scouting, and "
        "free-agent gap filling."
    )
    st.markdown("---")
    st.caption("MKTG 569 · Building Business Applications of LLMs and Generative Models")

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_rb, tab_os, tab_gf = st.tabs([
    "1. Roster Builder",
    "2. Opponent Scouting",
    "3. Gap Filler",
])

with tab_rb:
    roster_builder.render()
with tab_os:
    opponent_scouting.render()
with tab_gf:
    gap_filler.render()

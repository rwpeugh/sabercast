"""Tab 2: Opponent Scouting — functional implementation.

Aggregates an opponent's 2024 batting + pitching, identifies their top hitters
and pitchers, then makes one gpt-4o call returning a structured scouting report:
narrative, top threats, exploitable weaknesses, pitching strategy, hitting
approach.
"""
from __future__ import annotations

import streamlit as st

from core.orchestrator import TEAM_ABBR_TO_BREF, run_opponent_scouting_simple


def _get_cache() -> dict:
    """Session-scoped cache for scouting results so repeat queries are instant."""
    if "scouting_cache" not in st.session_state:
        st.session_state["scouting_cache"] = {}
    return st.session_state["scouting_cache"]


def _impact_chip(impact: str) -> str:
    color = {"high": "red", "medium": "orange", "low": "blue"}.get(
        str(impact).lower(), "gray"
    )
    return f":{color}[**{str(impact).upper()}**]"


def render() -> None:
    st.subheader("Opponent Scouting")
    st.caption(
        "Pick a team and get a scouting report: top threats on the roster, "
        "exploitable weaknesses, and concrete recommendations for pitching "
        "strategy and hitting approach. One gpt-4o call grounded in their full "
        "2024 line and per-position deltas vs. league average."
    )

    evaluation_year = 2024
    teams_sorted = sorted(TEAM_ABBR_TO_BREF.keys())

    col1, col2 = st.columns([1, 3])
    with col1:
        opponent = st.selectbox(
            "Opponent",
            teams_sorted,
            index=teams_sorted.index("HOU"),
            help="Pick any of the 30 MLB teams to scout.",
        )
    with col2:
        st.markdown("**Scouting as of**")
        st.markdown(f"end of **{evaluation_year}**")

    if st.button("Generate scouting report", type="primary"):
        cache = _get_cache()
        cache_key = (opponent, evaluation_year)
        if cache_key in cache:
            result = cache[cache_key]
            st.success(
                f"Loaded **{opponent}** from cache · 0s "
                f"(was {result['elapsed_seconds']}s on the first run)."
            )
        else:
            with st.status(f"Scouting {opponent}…", expanded=True) as status:
                def progress(label: str) -> None:
                    status.update(label=label)
                    st.write(f"• {label}")

                result = run_opponent_scouting_simple(
                    opponent_abbr=opponent,
                    evaluation_year=evaluation_year,
                    progress=progress,
                )
                status.update(
                    label=f"Done — {result['elapsed_seconds']}s, 1 gpt-4o call",
                    state="complete", expanded=False,
                )
            cache[cache_key] = result
        st.session_state["scouting_result"] = result

    result = st.session_state.get("scouting_result")
    if not result:
        st.info("Click *Generate scouting report* to run the analysis. "
                "Expect ~5–10 seconds for the live LLM call.")
        return

    # ── Narrative + top hitters/pitchers ─────────────────────────────────────
    st.markdown(f"### Scouting report — {result['opponent']} ({result['year']})")
    st.write(result["narrative"])

    col_h, col_p = st.columns(2)
    with col_h:
        st.markdown("**Top hitters (by 2024 OPS)**")
        rows = [
            {
                "Player":  h["name"],
                "PA":      h["PA"],
                "HR":      h["HR"],
                "Slash":   f".{int(h['AVG']*1000):03d}/.{int(h['OBP']*1000):03d}/.{int(h['SLG']*1000):03d}",
                "OPS":     f"{h['OPS']:.3f}",
            }
            for h in result["top_hitters"]
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)

    with col_p:
        st.markdown("**Top pitchers (by 2024 ERA)**")
        rows = [
            {
                "Player": p["name"],
                "Role":   p["role"],
                "IP":     f"{p['IP']:.1f}",
                "ERA":    f"{p['ERA']:.2f}",
                "WHIP":   f"{p['WHIP']:.3f}",
                "K/9":    f"{p['K9']:.1f}",
            }
            for p in result["top_pitchers"]
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Threats + weaknesses (cards) ─────────────────────────────────────────
    st.markdown("### Top threats")
    if result["threats"]:
        t_cols = st.columns(len(result["threats"]))
        for t, col in zip(result["threats"], t_cols):
            with col:
                role_tag = ":blue[hitter]" if t.get("role") == "hitter" else ":violet[pitcher]"
                with st.container(border=True):
                    st.markdown(f"**{t['player_name']}** &nbsp;{role_tag}",
                                unsafe_allow_html=True)
                    st.caption(t.get("why", ""))

    st.markdown("### Exploitable weaknesses")
    if result["weaknesses"]:
        w_cols = st.columns(len(result["weaknesses"]))
        for w, col in zip(result["weaknesses"], w_cols):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{w['area']}** &nbsp;{_impact_chip(w.get('win_impact','?'))}",
                                unsafe_allow_html=True)
                    st.caption(f"Stat evidence: {w.get('stat_evidence','')}")

    # ── Strategy recommendations ─────────────────────────────────────────────
    st.markdown("### How to attack")
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        with st.container(border=True):
            st.markdown("**Pitching strategy** (when they're at bat)")
            st.write(result["pitching_strategy"])
    with s_col2:
        with st.container(border=True):
            st.markdown("**Hitting approach** (when we're at bat vs their staff)")
            st.write(result["hitting_approach"])

"""Tab 1: Roster Builder — functional implementation.

Picks a team + opponent, aggregates the team's hitters and the opponent's
pitchers + defensive profile, and makes one gpt-4o call returning a
structured recommendation: lineup, matchup advantages, risks, narrative.
"""
from __future__ import annotations

import streamlit as st

from core.orchestrator import (
    TEAM_ABBR_TO_BREF,
    TEAM_DEFAULT_PAYROLL,
    run_roster_builder_simple,
)


def _get_cache() -> dict:
    """Session-scoped cache so repeat queries for the same (team, opponent) tuple
    return instantly."""
    if "roster_builder_cache" not in st.session_state:
        st.session_state["roster_builder_cache"] = {}
    return st.session_state["roster_builder_cache"]


def _leverage_chip(leverage: str) -> str:
    color = {"high": "red", "medium": "orange", "low": "blue"}.get(
        str(leverage).lower(), "gray"
    )
    return f":{color}[**{str(leverage).upper()}**]"


def _fmt_money(n: float | int | None) -> str:
    if n is None:
        return "—"
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    return f"${n:,.0f}"


def render() -> None:
    st.subheader("Roster Builder")
    st.caption(
        "Pick a team and an opponent. The orchestrator aggregates the team's "
        "qualified hitters and the opponent's top pitchers + per-position "
        "defensive deltas, then asks GPT-4o to construct a recommended 9-player "
        "lineup with matchup-specific reasoning."
    )

    evaluation_year = 2024
    teams_sorted = sorted(TEAM_ABBR_TO_BREF.keys())

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        team = st.selectbox(
            "Team",
            teams_sorted,
            index=teams_sorted.index("SEA"),
            key="roster_builder_team",
        )
    with col2:
        # Default opponent: HOU unless team IS HOU, then NYY
        default_opp = "HOU" if team != "HOU" else "NYY"
        opponent = st.selectbox(
            "Opponent",
            [t for t in teams_sorted if t != team],
            index=[t for t in teams_sorted if t != team].index(default_opp)
                  if default_opp in [t for t in teams_sorted if t != team] else 0,
            key="roster_builder_opponent",
        )
    with col3:
        default_budget = TEAM_DEFAULT_PAYROLL.get(team, 165_000_000)
        budget = st.number_input(
            f"Max payroll for {evaluation_year + 1} (USD)",
            min_value=50_000_000, max_value=500_000_000,
            value=default_budget, step=5_000_000,
            help="Pre-filled with the selected team's 2025 default payroll. "
                 "Budget context is currently displayed for reference only — "
                 "lineup recommendations use 2024 stats regardless.",
            key="roster_builder_budget",
        )

    if st.button("Build roster + matchup plan", type="primary"):
        cache = _get_cache()
        cache_key = (team, opponent, evaluation_year)
        if cache_key in cache:
            result = cache[cache_key]
            st.success(
                f"Loaded **{team} vs {opponent}** from cache · 0s "
                f"(was {result['elapsed_seconds']}s on the first run)."
            )
        else:
            with st.status(f"Building lineup for {team} vs {opponent}…",
                            expanded=True) as status:
                def progress(label: str) -> None:
                    status.update(label=label)
                    st.write(f"• {label}")

                result = run_roster_builder_simple(
                    team_abbr=team, opponent_abbr=opponent,
                    max_budget=int(budget),
                    evaluation_year=evaluation_year,
                    progress=progress,
                )
                status.update(
                    label=f"Done — {result['elapsed_seconds']}s, 1 gpt-4o call",
                    state="complete", expanded=False,
                )
            cache[cache_key] = result
        st.session_state["roster_builder_result"] = result

    result = st.session_state.get("roster_builder_result")
    if not result:
        st.info("Click *Build roster + matchup plan* to run the analysis. "
                "Expect ~5–10 seconds for the live LLM call.")
        return

    # ── Narrative ────────────────────────────────────────────────────────────
    st.markdown(
        f"### {result['team']} vs. {result['opponent']} — strategy ({result['year']})"
    )
    st.write(result["narrative"])

    # ── Lineup card ──────────────────────────────────────────────────────────
    st.markdown("### Recommended starting lineup")
    lineup = result.get("recommended_lineup") or []
    if lineup:
        rows = [
            {
                "Order":      slot.get("order", "?"),
                "Position":   slot.get("position", "?"),
                "Player":     slot.get("player_name", "?"),
                "Rationale":  slot.get("rationale", ""),
            }
            for slot in sorted(lineup, key=lambda s: s.get("order", 99))
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.warning("No lineup returned. Re-run, or check the orchestrator output.")

    # ── Advantages + risks side-by-side ─────────────────────────────────────
    st.markdown("### Matchup analysis")
    adv_col, risk_col = st.columns(2)
    with adv_col:
        st.markdown("**Advantages to lean into**")
        for a in (result.get("matchup_advantages") or []):
            with st.container(border=True):
                st.markdown(
                    f"**{a.get('area', '?')}** &nbsp;{_leverage_chip(a.get('leverage','?'))}",
                    unsafe_allow_html=True,
                )
                st.caption(f"Evidence: {a.get('evidence', '')}")
    with risk_col:
        st.markdown("**Risks to mitigate**")
        for r in (result.get("matchup_risks") or []):
            with st.container(border=True):
                st.markdown(f"**{r.get('area', '?')}**")
                st.caption(f"Mitigation: {r.get('mitigation', '')}")

    # ── Reference data tables ───────────────────────────────────────────────
    with st.expander("Reference data fed to the LLM"):
        ref_col1, ref_col2 = st.columns(2)
        with ref_col1:
            st.markdown(f"**{result['team']} top hitters (by 2024 OPS)**")
            hitter_rows = [
                {
                    "Player": h["name"],
                    "PA":     h["PA"],
                    "HR":     h["HR"],
                    "Slash":  f".{int(h['AVG']*1000):03d}/.{int(h['OBP']*1000):03d}/.{int(h['SLG']*1000):03d}",
                    "OPS":    f"{h['OPS']:.3f}",
                }
                for h in (result.get("team_hitters") or [])
            ]
            st.dataframe(hitter_rows, hide_index=True, use_container_width=True)
        with ref_col2:
            st.markdown(f"**{result['opponent']} top pitchers (by 2024 ERA)**")
            pit_rows = [
                {
                    "Player": p["name"],
                    "Role":   p["role"],
                    "IP":     f"{p['IP']:.1f}",
                    "ERA":    f"{p['ERA']:.2f}",
                    "WHIP":   f"{p['WHIP']:.3f}",
                    "K/9":    f"{p['K9']:.1f}",
                }
                for p in (result.get("opponent_pitchers") or [])
            ]
            st.dataframe(pit_rows, hide_index=True, use_container_width=True)

        opp_def = result.get("opponent_defense_deltas") or {}
        opp_pos = (opp_def.get("by_position") or {})
        if opp_pos:
            st.markdown(f"**{result['opponent']} per-position OAA deltas vs league**")
            def_rows = []
            for pos, d in opp_pos.items():
                def_rows.append({
                    "Position":          pos,
                    "Opponent OAA":      d.get("team_oaa_total"),
                    "League avg / team": d.get("league_avg_per_team"),
                    "Delta":             d.get("oaa_delta_vs_league_per_team"),
                })
            st.dataframe(def_rows, hide_index=True, use_container_width=True)

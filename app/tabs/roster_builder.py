"""Tab 1: Roster Builder — functional implementation.

Picks a team + opponent (and optionally the opponent's probable starting
pitcher), aggregates the team's hitters and the opponent's pitchers +
defensive profile, and makes one gpt-4o call returning a structured
recommendation: lineup, matchup advantages, risks, narrative.
"""
from __future__ import annotations

import streamlit as st

from core.orchestrator import (
    TEAM_ABBR_TO_BREF,
    list_team_starters,
    run_roster_builder_simple,
)


_NO_PITCHER_SENTINEL = "— Any starter / staff-level —"


@st.cache_data(show_spinner=False)
def _cached_team_starters(team_abbr: str, evaluation_year: int) -> list[dict]:
    """Cache the per-team starter list so flipping opponents doesn't re-read
    the pitching CSV every time."""
    try:
        return list_team_starters(team_abbr, evaluation_year=evaluation_year)
    except Exception:
        return []


def _format_starter_label(row: dict) -> str:
    return (f"{row['name']}  ·  {row['GS']} GS  ·  "
            f"{row['ERA']:.2f} ERA  ·  {row['WHIP']:.3f} WHIP")


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


def render() -> None:
    st.subheader("Roster Builder")
    st.caption(
        "Day-to-day lineup construction (scouting as of end of 2024 season). "
        "Pick the team you're managing, the opponent for an upcoming game, "
        "and — when available — the opponent's confirmed probable starter. "
        "When a probable starter is selected, the lineup ordering and matchup "
        "plan are tailored specifically to that pitcher's stat profile. "
        "No payroll input — this tab uses the existing roster as is."
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
        opp_options = [t for t in teams_sorted if t != team]
        opponent = st.selectbox(
            "Opponent",
            opp_options,
            index=opp_options.index(default_opp) if default_opp in opp_options else 0,
            key="roster_builder_opponent",
        )
    with col3:
        starters = _cached_team_starters(opponent, evaluation_year)
        if starters:
            options    = [_NO_PITCHER_SENTINEL] + [s["name"] for s in starters]
            label_map  = {_NO_PITCHER_SENTINEL: _NO_PITCHER_SENTINEL}
            label_map.update({s["name"]: _format_starter_label(s) for s in starters})
            pitcher_choice = st.selectbox(
                "Opponent probable starter (optional)",
                options=options,
                format_func=lambda v: label_map.get(v, v),
                key=f"roster_builder_pitcher_{opponent}",
                help=("When selected, the lineup is tailored specifically to "
                      "attacking this pitcher's stat profile. Leave on the "
                      "default for staff-level reasoning."),
            )
        else:
            pitcher_choice = _NO_PITCHER_SENTINEL
            st.caption(f"No {evaluation_year} starter data on file for {opponent}.")

    probable_pitcher = (None if pitcher_choice == _NO_PITCHER_SENTINEL
                        else pitcher_choice)

    if st.button("Build roster + matchup plan", type="primary"):
        cache = _get_cache()
        cache_key = (team, opponent, evaluation_year, probable_pitcher)
        if cache_key in cache:
            result = cache[cache_key]
            st.success(
                f"Loaded **{team} vs {opponent}** from cache · 0s "
                f"(was {result['elapsed_seconds']}s on the first run)."
            )
        else:
            status_label = (f"Building lineup for {team} vs {opponent}"
                            f"{' (vs ' + probable_pitcher + ')' if probable_pitcher else ''}…")
            with st.status(status_label, expanded=True) as status:
                def progress(label: str) -> None:
                    status.update(label=label)
                    st.write(f"• {label}")

                result = run_roster_builder_simple(
                    team_abbr=team, opponent_abbr=opponent,
                    evaluation_year=evaluation_year,
                    probable_pitcher=probable_pitcher,
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
    header = f"### {result['team']} vs. {result['opponent']} — strategy ({result['year']})"
    starter = result.get("probable_starter")
    if starter:
        header += f"  ·  facing **{starter['name']}**"
    st.markdown(header)
    if starter:
        with st.container(border=True):
            throws = starter.get("throws")
            hand_badge = {"R": "RHP", "L": "LHP", "S": "SHP"}.get(throws or "", "")
            hand_label = f"  ·  **{hand_badge}**" if hand_badge else ""
            st.markdown(
                f"**Facing tonight: {starter['name']}**{hand_label}  ·  "
                f"{starter['GS']} GS  ·  {starter['IP']:.1f} IP  ·  "
                f"**{starter['ERA']:.2f}** ERA  ·  {starter['WHIP']:.3f} WHIP  ·  "
                f"{starter['K9']:.1f} K/9  ·  {starter.get('BB9', 0):.1f} BB/9  ·  "
                f"{starter.get('HR9', 0):.2f} HR/9"
            )
            caption_extra = (" Platoon-aware lineup ordering is on." if hand_badge
                             else " (Handedness unknown — falling back to stat-profile reasoning.)")
            st.caption(
                "Lineup ordering and matchup plan below are tailored to this pitcher's profile."
                + caption_extra
            )
    st.write(result["narrative"])

    # ── Lineup card ──────────────────────────────────────────────────────────
    # NB: rendered as a hand-built HTML table instead of st.dataframe because
    # Streamlit's default dataframe widget uses Glide Data Grid (canvas-based)
    # which has known kerning quirks on certain capital + diacritic letter
    # combinations -- "Víctor Robles" rendered with a visible gap between V and
    # í while "Julio Rodríguez" rendered cleanly even though both use the same
    # precomposed U+00ED character. Switching to HTML lets the browser's native
    # text layout handle the kerning correctly.
    st.markdown("### Recommended starting lineup")
    lineup = result.get("recommended_lineup") or []
    if lineup:
        import html as _html
        slots_sorted = sorted(lineup, key=lambda s: s.get("order", 99))
        header_cells = "".join(
            f"<th style='text-align:left;padding:6px 12px;border-bottom:2px solid #ddd;"
            f"font-weight:600;color:#555;font-size:0.85em'>{label}</th>"
            for label in ("Order", "Position", "Player", "Rationale")
        )
        body_rows = []
        for slot in slots_sorted:
            order   = _html.escape(str(slot.get("order", "?")))
            pos     = _html.escape(str(slot.get("position", "?")))
            player  = _html.escape(str(slot.get("player_name", "?")))
            rat     = _html.escape(str(slot.get("rationale", "")))
            body_rows.append(
                f"<tr>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{order}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{pos}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{player}</td>"
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#555'>{rat}</td>"
                f"</tr>"
            )
        table_html = (
            f"<table style='width:100%;border-collapse:collapse;font-size:0.95em'>"
            f"<thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            f"</table>"
        )
        st.markdown(table_html, unsafe_allow_html=True)
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

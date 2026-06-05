"""Tab 3: Roster Gap Filler — the only functional tab for the sprint.

Hardcodes team='SEA' and max_budget=$165M per spec sprint scope. Calls the
simplified orchestrator and renders the result as Streamlit cards with a small
Plotly delta chart at the top.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from pathlib import Path

import pandas as pd

from core.orchestrator import (
    TEAM_ABBR_TO_BREF,
    TEAM_DEFAULT_PAYROLL,
    compute_committed_payroll,
    run_gap_filler_simple,
)


@st.cache_data(show_spinner=False)
def _load_combined_contracts() -> pd.DataFrame:
    """Loads contracts.csv + contracts_extended.csv once per session. Cheap
    enough to load eagerly so the UI can show the committed-payroll estimate
    before the user clicks Diagnose."""
    root = Path(__file__).resolve().parents[2] / "data" / "raw"
    main = pd.read_csv(root / "contracts.csv", encoding="utf-8")
    ext_path = root / "contracts_extended.csv"
    if ext_path.exists():
        ext = pd.read_csv(ext_path, encoding="utf-8")
        return pd.concat([main, ext], ignore_index=True)
    return main


@st.cache_data(show_spinner=False)
def _committed_estimate(team_abbr: str, evaluation_year: int) -> dict:
    """Cached wrapper around compute_committed_payroll for the UI."""
    contracts = _load_combined_contracts()
    return compute_committed_payroll(team_abbr, contracts, evaluation_year)


def _get_cache() -> dict:
    """Session-scoped result cache. Survives reruns within a single Streamlit
    session; cleared when the user reloads. Keyed by (team, budget, year).

    Uses session_state instead of @st.cache_data so we can still show the
    live progress callback on cache misses — st.cache_data hashes every
    argument including the callback, which would break the cache or force a
    re-run on every change.
    """
    if "gap_filler_cache" not in st.session_state:
        st.session_state["gap_filler_cache"] = {}
    return st.session_state["gap_filler_cache"]

# ──────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────
def _fmt_money(n: float | int | None) -> str:
    if n is None:
        return "—"
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    return f"${n:,.0f}"


def _md_money(n) -> str:
    """``_fmt_money`` with $ escaped so Streamlit's KaTeX doesn't treat a
    `$...$` pair as inline math (markdown context)."""
    return _fmt_money(n).replace("$", r"\$")


def _html_money(n) -> str:
    """``_fmt_money`` with $ replaced by its HTML entity so Streamlit's KaTeX
    pre-processor leaves it alone in ``unsafe_allow_html=True`` blocks."""
    return _fmt_money(n).replace("$", "&#36;")


def _delta_arrow(v: float | None) -> str:
    if v is None:
        return ""
    return "▲" if v > 0 else ("▼" if v < 0 else "—")


# Whether a positive delta means "team is better than league". For batting rate
# stats and K/9 this is True; for ERA/WHIP/SO_total a positive delta is bad.
_HIGHER_IS_BETTER = {
    "AVG_weighted": True,  "OBP_weighted": True,  "SLG_weighted": True, "OPS_weighted": True,
    "HR_total": True,  "R_total": True, "RBI_total": True, "SB_total": True, "BB_total": True,
    "SO_total": False,
    "ERA": False, "WHIP": False, "BB": False, "SO": True, "K9": True, "IP": True,
}

# Plain-English labels for the chart axis.
_LABELS = {
    "AVG_weighted": "AVG", "OBP_weighted": "OBP", "SLG_weighted": "SLG", "OPS_weighted": "OPS",
    "HR_total": "HR", "R_total": "Runs", "RBI_total": "RBI", "SB_total": "SB",
    "BB_total": "BB", "SO_total": "K",
    "ERA": "ERA", "WHIP": "WHIP", "K9": "K/9", "IP": "IP", "BB": "BB (pit)", "SO": "K (pit)",
}


def _delta_chart(result: dict) -> go.Figure:
    """Horizontal Plotly bar chart of normalized team-vs-league deltas.

    For each metric, we compute (team - league) and flip the sign so that
    positive bars always mean 'team is above the league'. Counting stats and
    rate stats are scaled independently so they're visible on the same axis.
    """
    rows: list[tuple[str, float, bool]] = []   # (label, normalized_delta, team_is_better)

    rate_keys = ["AVG_weighted", "OBP_weighted", "SLG_weighted", "OPS_weighted"]
    for k in rate_keys:
        v = result.get("deltas_batting", {}).get(k)
        if v is not None:
            rows.append((_LABELS[k], v * 1000, _HIGHER_IS_BETTER[k] == (v > 0)))

    # Pitching rate stats (flip ERA/WHIP so positive = better)
    pit = result.get("deltas_pitching", {})
    for k in ("ERA", "WHIP", "K9"):
        v = pit.get(k)
        if v is not None:
            sign = 1 if _HIGHER_IS_BETTER.get(k, True) else -1
            rows.append((_LABELS[k], v * sign * (50 if k == "K9" else 100),
                         (sign * v) > 0))

    # Bat counting stats (HR, SB) for visual interest — scaled
    for k in ("HR_total", "SB_total"):
        v = result.get("deltas_batting", {}).get(k)
        if v is not None:
            rows.append((_LABELS[k], v, v > 0))

    labels  = [r[0] for r in rows]
    values  = [r[1] for r in rows]
    colors  = ["#2BAA5E" if r[2] else "#C0382B" for r in rows]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=colors,
        hovertemplate="%{y}: %{x:+.2f}<extra></extra>",
    ))
    fig.update_layout(
        title="Team vs. league average (positive = team above league, normalized)",
        title_font_size=13,
        height=240, margin=dict(l=10, r=10, t=40, b=20),
        xaxis=dict(zeroline=True, zerolinecolor="#888", showgrid=False),
        yaxis=dict(autorange="reversed"),
        showlegend=False,
        font=dict(size=11),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _impact_chip(impact: str) -> str:
    """Return a colored markdown chip for HIGH/MEDIUM/LOW impact."""
    color = {"high": "red", "medium": "orange", "low": "blue"}.get(impact.lower(), "gray")
    return f":{color}[**{impact.upper()} IMPACT**]"


# ──────────────────────────────────────────────────────────────────────────────
# Page render
# ──────────────────────────────────────────────────────────────────────────────
def render() -> None:
    st.subheader("Roster Gap Filler")
    st.caption(
        "Diagnose where a team underperforms league average, suggest free-agent "
        "targets, and price comparable contracts. Pick any team and tune the "
        "payroll input; the diagnosis is anchored to the end of the 2024 season "
        "(a GM cannot see contracts signed after that)."
    )

    evaluation_year = 2024
    teams_sorted = sorted(TEAM_ABBR_TO_BREF.keys())

    # ── Inputs row: team selector + editable payroll fields ─────────────────
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        team = st.selectbox(
            "Team",
            teams_sorted,
            index=teams_sorted.index("SEA"),
            help="Pick any of the 30 MLB teams. The diagnosis pulls their 2024 roster aggregates.",
        )
    with col2:
        default_budget = TEAM_DEFAULT_PAYROLL.get(team, 165_000_000)
        budget = st.number_input(
            f"Total payroll budget for {evaluation_year + 1} (USD)",
            min_value=50_000_000, max_value=500_000_000,
            value=default_budget, step=5_000_000,
            help=(
                "Pre-filled with an approximate 2025 payroll for the selected "
                "team. This is your TOTAL budget — the tool subtracts existing "
                "committed contracts to compute room for new signings."
            ),
        )

    # Auto-computed committed estimate from contracts.csv (no-look-ahead).
    committed_info = _committed_estimate(team, evaluation_year)
    auto_committed = int(committed_info["committed_total"])
    n_known        = committed_info["n_contracts"]

    with col3:
        committed_override = st.number_input(
            f"Committed payroll for {evaluation_year + 1} (USD)",
            min_value=0, max_value=500_000_000,
            value=auto_committed, step=1_000_000,
            help=(
                "Pre-filled from our tracked-contracts dataset (no-look-ahead). "
                "Likely UNDER-COUNTS the team's actual commitments because the "
                "dataset excludes league-minimum and pre-arb players. Override "
                "with your own estimate for sharper recommendations — the "
                "single-signing ceiling is computed as 30% of "
                "(total budget - committed)."
            ),
        )

    available_preview = max(0, int(budget) - int(committed_override))
    ceiling_preview   = int(available_preview * 0.30)

    # NB: Streamlit markdown treats $...$ as LaTeX math delimiters which
    # breaks rendering for any dollar-prefixed text. Rendering via st.markdown
    # with unsafe_allow_html=True and an explicit HTML span bypasses the
    # markdown parser entirely, so dollar amounts display literally and the
    # rest of the line keeps its styling.
    committed_origin = (
        f"from Spotrac team payroll" if committed_info.get("committed_source") == "spotrac_team_payroll"
        else f"from {n_known} tracked contracts" if n_known
        else "no contracts on file"
    )
    if int(committed_override) > int(budget):
        st.markdown(
            f"<div style='background:#FFEEEE;border:1px solid #E0B0B0;"
            f"padding:8px 12px;border-radius:4px;margin-top:6px'>"
            f"<b>Committed payroll (${int(committed_override)/1e6:,.1f}M)"
            f" exceeds total budget (${int(budget)/1e6:,.1f}M).</b> "
            f"The tool will return zero affordable targets. Adjust either field."
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='color:#666;font-size:0.88em;margin-top:6px'>"
            f"<b>Committed:</b> ${auto_committed/1e6:,.1f}M ({committed_origin})  ·  "
            f"<b>Available:</b> ${available_preview/1e6:,.1f}M  ·  "
            f"<b>Single-signing ceiling:</b> ${ceiling_preview/1e6:,.1f}M "
            f"(30% of available)"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.caption(
        f"Comparable contracts are filtered to signings on or before "
        f"{evaluation_year} — a GM scouting at the end of the {evaluation_year} "
        f"season cannot see contracts signed later. No look-ahead bias."
    )

    # ── Run trigger with progressive status + session-scoped caching ────────
    if st.button("Diagnose roster gaps", type="primary"):
        cache = _get_cache()
        # Cache key includes the committed override so different
        # payroll-situation scenarios don't collide.
        cache_key = (team, int(budget), int(committed_override), evaluation_year)

        if cache_key in cache:
            result = cache[cache_key]
            cache_used = True
            st.success(
                f"Loaded **{team}** from cache · 0s "
                f"(was {result['elapsed_seconds']}s on the first run)."
            )
        else:
            with st.status(f"Running gap diagnosis for {team}…", expanded=True) as status:
                def progress(label: str) -> None:
                    status.update(label=label)
                    st.write(f"• {label}")

                result = run_gap_filler_simple(
                    team_abbr=team, max_budget=int(budget),
                    evaluation_year=evaluation_year,
                    committed_payroll=int(committed_override),
                    progress=progress,
                )
                n_target_calls = sum(len(g.get("targets") or []) for g in result["gaps_results"])
                status.update(
                    label=(f"Done — {result['elapsed_seconds']}s, 1 gpt-4o + "
                           f"{3 + n_target_calls} gpt-4o-mini calls"),
                    state="complete", expanded=False,
                )
            cache[cache_key] = result
            cache_used = False

        st.session_state["gap_filler_result"] = result
        st.session_state["gap_filler_cache_used"] = cache_used

    result = st.session_state.get("gap_filler_result")
    if not result:
        st.info("Click *Diagnose roster gaps* to run the analysis. "
                "Typical end-to-end: 8–15 seconds (LLM calls run in parallel).")
        return

    # ── Payroll situation panel ───────────────────────────────────────────────
    # Surfaces how the single-signing ceiling was actually computed:
    #   total_budget - committed = available; ceiling = 30% of available.
    # The user can see WHY a given AAV target is or isn't eligible.
    payroll_total      = result.get("max_budget", 0)
    payroll_committed  = result.get("committed_payroll", 0)
    payroll_available  = result.get("available_for_signings", 0)
    payroll_ceiling    = result.get("single_signing_ceiling", 0)
    payroll_source     = result.get("committed_source", "auto_estimate")
    payroll_caveat     = result.get("committed_caveat", "")
    payroll_breakdown  = result.get("committed_breakdown") or []
    over_committed     = result.get("over_committed", False)

    st.markdown("### Payroll situation")
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric("Total budget",   f"${payroll_total/1e6:,.1f}M")
    with p2:
        source_label = {
            "user_override":         "user override",
            "spotrac_team_payroll":  "Spotrac team payroll page (authoritative)",
            "contracts_sum":         f"sum of {len(payroll_breakdown)} tracked contracts (likely under-counts)",
        }.get(payroll_source, payroll_source or "unknown")
        st.metric("Committed",      f"${payroll_committed/1e6:,.1f}M",
                  help=f"Source: {source_label}")
    with p3:
        st.metric("Available room", f"${payroll_available/1e6:,.1f}M")
    with p4:
        st.metric("Single-signing ceiling", f"${payroll_ceiling/1e6:,.1f}M",
                  help="30% of available room. Targets above this AAV are filtered out.")
    if over_committed:
        st.error(
            "Committed payroll exceeds total budget — zero affordable targets "
            "returned. Increase the budget or lower the committed override."
        )
    if payroll_caveat and payroll_source != "user_override":
        st.caption(f"_{payroll_caveat}_")
    if payroll_breakdown:
        with st.expander(f"View the {len(payroll_breakdown)} tracked contracts that make up committed payroll"):
            rows = [
                {
                    "Player":      b.get("player_name"),
                    "Position":    b.get("position"),
                    "AAV":         _html_money(b.get("aav")),
                    "Signed":      b.get("signed_year"),
                    "Years":       b.get("years"),
                    "Expires after": (b.get("signed_year") or 0) + (b.get("years") or 0) - 1,
                }
                for b in payroll_breakdown
            ]
            st.dataframe(rows, hide_index=True, use_container_width=True)

    # ── Roster summary + delta chart side by side ────────────────────────────
    st.markdown("### Roster summary")
    summary_col, chart_col = st.columns([3, 4])
    with summary_col:
        st.write(result["roster_summary"])
        eval_yr = result.get("evaluation_year", 2024)
        mkt_yr  = result.get("market_year", eval_yr + 1)
        n_target_calls = sum(len(g.get("targets") or []) for g in result["gaps_results"])
        st.caption(
            f"Run took {result.get('elapsed_seconds')}s · "
            f"1 gpt-4o + {3 + n_target_calls} gpt-4o-mini calls (parallelized)\n\n"
            f"Comparables from contracts signed on or before {eval_yr}; "
            f"pricing anchored to the {mkt_yr} offseason."
        )
    with chart_col:
        st.plotly_chart(_delta_chart(result), use_container_width=True,
                        config={"displayModeBar": False})

    thin = result.get("thin_targets_positions") or []
    if thin:
        st.warning(
            "Thin target pool at: "
            + ", ".join(thin)
            + ". Fewer than 3 eligible acquisition targets in the contracts "
            "dataset at this position (signed on or before "
            + str(eval_yr)
            + ", AAV within the 30% single-signing ceiling). The estimate and "
            "leverage notes account for this."
        )

    with st.expander("Detailed batting and pitching deltas vs. league"):
        st.markdown("**Batting deltas** (team minus league/30 per-team average)")
        bat_rows = [
            {"metric": k, "team − league": v, "": _delta_arrow(v)}
            for k, v in result["deltas_batting"].items()
        ]
        st.dataframe(bat_rows, hide_index=True, use_container_width=True)

        st.markdown("**Pitching deltas** (lower is better for ERA/WHIP)")
        pit_rows = [
            {"metric": k, "team − league": v, "": _delta_arrow(v)}
            for k, v in result["deltas_pitching"].items()
        ]
        st.dataframe(pit_rows, hide_index=True, use_container_width=True)

    # ── Defensive snapshot (Statcast OAA + catcher pop time + sprint speed) ─
    if result.get("have_defense") and result.get("defense_deltas"):
        with st.expander("Team defense — Statcast OAA by position, catcher pop time, sprint speed"):
            st.caption(
                "Outs Above Average (OAA) per position from Baseball Savant. "
                "Positive delta = team above league. Catcher defense uses pop "
                "time to 2B (lower is better)."
            )
            dd = result["defense_deltas"]
            pos_rows = []
            for pos, d in (dd.get("by_position") or {}).items():
                pos_rows.append({
                    "Position":          pos,
                    "Team OAA":          d["team_oaa_total"],
                    "League avg / team": d["league_avg_per_team"],
                    "Delta":             d["oaa_delta_vs_league_per_team"],
                    "":                  _delta_arrow(d["oaa_delta_vs_league_per_team"]),
                })
            st.dataframe(pos_rows, hide_index=True, use_container_width=True)

            cat = dd.get("catcher")
            sprint = dd.get("sprint_delta")
            cat_col, sprint_col = st.columns(2)
            with cat_col:
                st.markdown("**Catcher pop time (to 2B)**")
                if cat and cat.get("team_pop_2b_mean"):
                    st.markdown(
                        f"Team mean **{cat['team_pop_2b_mean']:.3f}s** vs "
                        f"league **{cat['league_pop_2b_mean']:.3f}s** "
                        f"(delta {cat['pop_2b_delta']:+.3f}s — "
                        f"_{cat['delta_interpretation']}_)"
                    )
                else:
                    st.caption("No catcher pop-time data for this team.")
            with sprint_col:
                st.markdown("**Team sprint speed**")
                if sprint is not None:
                    st.markdown(f"Delta vs league: **{sprint:+.2f} ft/sec**")
                else:
                    st.caption("No sprint speed data.")

    # ── Three gap cards ──────────────────────────────────────────────────────
    st.markdown("### Top 3 gaps")
    for i, gr in enumerate(result["gaps_results"], start=1):
        _render_gap_card(i, gr, budget, evaluation_year=eval_yr)

    # ── Plain language wrap-up ───────────────────────────────────────────────
    if result["gaps_results"]:
        top = result["gaps_results"][0]
        pos = top["gap"].get("position")
        est = top["estimate"]
        aav = est.get("estimated_aav")
        targets = top.get("targets") or []
        top_target = targets[0]["player_name"] if targets else None
        if aav:
            pct = aav / budget * 100
            target_phrase = (
                f"Top recommended target: **{top_target}**."
                if top_target else
                "No statistically-ranked target available within budget."
            )
            st.success(
                f"**Highest priority:** {pos} signing at approximately "
                f"**{_md_money(aav)} AAV** ({pct:.0f}% of the team's "
                + r"\$165M"
                + f" payroll). {target_phrase}"
            )


def _format_player_stats(stats: dict | None) -> str:
    """Render a player's 2024 line as a one-line HTML snippet."""
    if not stats:
        return "<span style='color:#999;font-style:italic'>No 2024 stats on file</span>"
    if stats.get("role") == "hitter":
        avg = (stats.get("AVG") or 0)
        obp = (stats.get("OBP") or 0)
        slg = (stats.get("SLG") or 0)
        slash = f".{int(avg*1000):03d}/.{int(obp*1000):03d}/.{int(slg*1000):03d}"
        return (
            f"<span style='font-family:monospace'>{slash}</span>"
            f" &middot; <b>{stats.get('HR','?')}</b> HR &middot; "
            f"<b>{stats.get('RBI','?')}</b> RBI &middot; "
            f"<b>{stats.get('PA','?')}</b> PA"
        )
    if stats.get("role") == "pitcher":
        era  = stats.get("ERA")
        whip = stats.get("WHIP")
        k9   = stats.get("K9")
        ip   = stats.get("IP", 0.0)
        return (
            f"<b>{era:.2f}</b> ERA &middot; <b>{whip:.3f}</b> WHIP &middot; "
            f"<b>{k9:.1f}</b> K/9 &middot; <b>{ip:.0f}</b> IP"
            if era is not None and whip is not None and k9 is not None
            else "<span style='color:#999;font-style:italic'>partial 2024 stats</span>"
        )
    return ""


def _render_gap_card(idx: int, gr: dict, budget: float, evaluation_year: int) -> None:
    """Render one of the three gap cards. Pulled out for readability."""
    gap = gr["gap"]
    targets = gr.get("targets") or []
    pricing_comps = gr.get("pricing_comparables") or []
    est = gr["estimate"]
    incumbent = gr.get("incumbent")

    with st.container(border=True):
        # ── Header strip: position + impact + gap score ──────────────────────
        h1, h2, h3 = st.columns([1, 1, 2])
        with h1:
            st.markdown(f"#### #{idx} · {gap.get('position', '?')}")
            st.markdown(_impact_chip(gap.get("win_impact", "?")))
        with h2:
            score = gap.get("gap_score", 0)
            st.metric("Gap score", f"{score:.1f}/10")
            st.progress(min(max(score / 10, 0), 1.0))
            # Offense / defense split (defensive integration added 2026-05-29)
            comp = gap.get("gap_components") or {}
            off = comp.get("offense")
            dfn = comp.get("defense")
            if off is not None or dfn is not None:
                st.markdown(
                    f"<div style='font-size:0.82em;color:#555;margin-top:4px'>"
                    f"offense <b>{off if off is not None else '?'}</b>"
                    f" &nbsp;·&nbsp; defense <b>{dfn if dfn is not None else '?'}</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        with h3:
            st.markdown("**Why this is a gap**")
            st.caption(gap.get("reasoning", ""))

        st.divider()

        # ── Current incumbent at this position ──────────────────────────────
        # Shows the team's current player(s) at the gap position, so every
        # target recommendation below can be read as "vs this baseline."
        if incumbent and incumbent.get("primary_player"):
            inc_bits: list[str] = []
            if incumbent.get("offense"):
                o = incumbent["offense"]
                inc_bits.append(
                    f"OPS <b>{o['OPS']:.3f}</b> "
                    f"({o['PA']} PA, {o['HR']} HR)"
                )
            if incumbent.get("defense") and incumbent["defense"].get("oaa") is not None:
                d = incumbent["defense"]
                delta = d.get("delta_vs_league") or 0
                color = "#2E863E" if delta >= 0 else "#B33A3A"
                inc_bits.append(
                    f"OAA <b style='color:{color}'>{d['oaa']:+d}</b> "
                    f"({delta:+.1f} vs league/team)"
                )
            if incumbent.get("defense") and incumbent["defense"].get("pop_2b_sba"):
                inc_bits.append(
                    f"pop time <b>{incumbent['defense']['pop_2b_sba']:.2f}s</b>"
                )
            if incumbent.get("pitching"):
                p = incumbent["pitching"]
                inc_bits.append(
                    f"<b>{p['GS']} GS</b>, ERA <b>{p['ERA']:.2f}</b>, "
                    f"WHIP <b>{p['WHIP']:.3f}</b>, K/9 <b>{p['K9']:.1f}</b>"
                )
            secondary = incumbent.get("secondary_players") or []
            sec_hint = (f" &nbsp;<span style='color:#888;font-size:0.85em'>"
                         f"(+ {', '.join(secondary[:2])}"
                         f"{'…' if len(secondary) > 2 else ''})</span>"
                         if secondary else "")
            st.markdown(
                f"<div style='background:#F0F4F8;padding:8px 12px;"
                f"border-left:3px solid #3A82CD;border-radius:4px;margin-bottom:10px'>"
                f"<span style='color:#666;font-size:0.85em'>Current incumbent &middot; "
                f"</span><b>{incumbent['primary_player']}</b>{sec_hint}<br>"
                f"<span style='font-size:0.9em'>{' &middot; '.join(inc_bits)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── Contract estimate (left) | Recommended targets (right) ──────────
        est_col, targ_col = st.columns([2, 3])
        with est_col:
            st.markdown("**Estimated contract to fill**")
            if est.get("estimated_aav"):
                aav = _fmt_money(est["estimated_aav"])
                yrs = est.get("estimated_years", "?")
                total_low  = _html_money(est.get("total_range_low"))
                total_high = _html_money(est.get("total_range_high"))
                st.metric("AAV", aav, delta=f"{yrs} yr deal")
                st.markdown(f"<small>Total: {total_low} – {total_high}</small>",
                            unsafe_allow_html=True)
                if gr.get("affordable") is False:
                    st.warning("Exceeds 30% single-signing ceiling")
                else:
                    pct = est["estimated_aav"] / budget * 100
                    st.success(f"Within payroll · {pct:.0f}% of total")
            else:
                st.warning("No comparable contracts at this position.")

        with targ_col:
            n_tgt = gr.get("n_targets_available", len(targets))
            source = gr.get("targets_source", "stat_fit")
            base = ("retrieved by ChromaDB semantic match against the gap's "
                    "diagnostic reasoning, filtered to position-eligible "
                    "contracts within 5× the single-signing ceiling"
                    ) if source == "vectorstore" \
                   else "filtered by position, up to 5× the single-signing ceiling"
            tier_note = (
                ", then bucketed into bargain / at-budget / premium tiers "
                "with the top-1 by composite improvement picked per tier"
            )
            if incumbent and incumbent.get("primary_player"):
                source_label = (
                    f"{base}{tier_note} (improvement is measured against the "
                    f"current incumbent {incumbent['primary_player']})"
                )
            else:
                source_label = base + tier_note + " (no incumbent baseline)"
            st.markdown(
                f"**Recommended targets** &nbsp;<span style='color:#666;font-size:0.85em'>"
                f"({n_tgt} {'option' if n_tgt == 1 else 'options'}, {source_label})"
                f"</span>",
                unsafe_allow_html=True,
            )
            if not targets:
                st.write(
                    "_No statistically-ranked targets at this position within budget. "
                    "All eligible contracts at this position exceed the 30% single-signing ceiling._"
                )
            else:
                tgt_cols = st.columns(len(targets))
                for t, col in zip(targets, tgt_cols):
                    with col:
                        # Tier badge -- bargain (green) / medium (blue) / premium (orange).
                        # Sits above the player name so the buyer immediately knows
                        # whether this card is a cheap stretch or a budget-buster.
                        tier = t.get("tier")
                        if tier:
                            badge = {
                                "bargain": ("BARGAIN", "#2E863E", "#E8F4EA"),
                                "medium":  ("AT BUDGET", "#3A82CD", "#E6EFF8"),
                                "premium": ("PREMIUM",  "#C26B1F", "#FBEFE3"),
                            }.get(tier, ("?", "#666", "#EEE"))
                            label, fg, bg = badge
                            st.markdown(
                                f"<div style='display:inline-block;padding:2px 8px;"
                                f"font-size:0.72em;font-weight:700;letter-spacing:0.5px;"
                                f"background:{bg};color:{fg};border-radius:3px;"
                                f"margin-bottom:6px'>{label}</div>",
                                unsafe_allow_html=True,
                            )
                        name_line = f"**{t['player_name']}**"
                        if t.get("is_expensive_vs_estimate"):
                            pct = int((t.get("premium_vs_estimate") or 0) * 100)
                            name_line += f" &nbsp;:orange[**+{pct}% vs estimate**]"
                        st.markdown(name_line, unsafe_allow_html=True)
                        st.caption(
                            f"{t['position']} · {t['team']}"
                            + (f" · age {t['age_at_signing']}" if t.get("age_at_signing") else "")
                        )
                        st.markdown(
                            f"<div style='line-height:1.5;font-size:0.92em;margin-top:4px'>"
                            f"{_format_player_stats(t.get('stats_2024'))}"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                        # vs-incumbent delta row (task #62) -- the "trade-off"
                        # signal. Color-coded: green = improvement, amber = mild
                        # regression, red = clear regression.
                        comp_score = t.get("composite_score")
                        if comp_score is not None and incumbent and incumbent.get("primary_player"):
                            off_d = t.get("vs_incumbent_offense")
                            def_d = t.get("vs_incumbent_defense")
                            pit_d = t.get("vs_incumbent_pitching")
                            chips: list[str] = []
                            if off_d is not None:
                                col = ("#2E863E" if off_d >= 0.020
                                        else "#C08C00" if off_d >= -0.020
                                        else "#B33A3A")
                                chips.append(
                                    f"<span style='color:{col}'>"
                                    f"{off_d:+.3f} OPS</span>"
                                )
                            if def_d is not None and pit_d is None:
                                col = ("#2E863E" if def_d >= 2
                                        else "#C08C00" if def_d >= -2
                                        else "#B33A3A")
                                # Catcher: pop time delta is in seconds; others: OAA outs
                                if gap.get("position") == "C":
                                    chips.append(
                                        f"<span style='color:{col}'>"
                                        f"{def_d:+.3f}s pop</span>"
                                    )
                                else:
                                    chips.append(
                                        f"<span style='color:{col}'>"
                                        f"{def_d:+d} OAA</span>"
                                    )
                            if pit_d is not None:
                                era_d  = pit_d.get("ERA_delta", 0)
                                whip_d = pit_d.get("WHIP_delta", 0)
                                k9_d   = pit_d.get("K9_delta", 0)
                                col_era = ("#2E863E" if era_d >= 0.30
                                            else "#C08C00" if era_d >= -0.30
                                            else "#B33A3A")
                                col_whip = ("#2E863E" if whip_d >= 0.050
                                             else "#C08C00" if whip_d >= -0.050
                                             else "#B33A3A")
                                col_k9 = ("#2E863E" if k9_d >= 0.5
                                           else "#C08C00" if k9_d >= -0.5
                                           else "#B33A3A")
                                chips.append(
                                    f"<span style='color:{col_era}'>"
                                    f"{era_d:+.2f} ERA</span>"
                                )
                                chips.append(
                                    f"<span style='color:{col_whip}'>"
                                    f"{whip_d:+.3f} WHIP</span>"
                                )
                                chips.append(
                                    f"<span style='color:{col_k9}'>"
                                    f"{k9_d:+.1f} K/9</span>"
                                )
                            comp_col = ("#2E863E" if comp_score >= 1.0
                                         else "#C08C00" if comp_score >= 0
                                         else "#B33A3A")
                            st.markdown(
                                f"<div style='margin-top:8px;padding:6px 8px;"
                                f"background:#FAFBFC;border-radius:4px;"
                                f"font-size:0.85em'>"
                                f"<span style='color:#666'>vs {incumbent['primary_player']}: </span>"
                                f"{' &middot; '.join(chips)}"
                                f" &nbsp;|&nbsp; "
                                f"<span style='color:{comp_col}'>composite "
                                f"<b>{comp_score:+.2f}</b></span>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                        # Forecast AAV (what this player would command on a new deal)
                        f_aav = t.get("forecast_aav")
                        f_yrs = t.get("forecast_years")
                        if f_aav:
                            st.markdown(
                                f"<div style='margin-top:8px;font-size:0.92em'>"
                                f"<span style='color:#666'>Forecast next deal:</span> "
                                f"<b>{_html_money(f_aav)}</b> AAV "
                                f"&middot; <b>{f_yrs or '?'} yr</b>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                            if t.get("forecast_rationale"):
                                st.caption(f"_{t['forecast_rationale']}_")
                        else:
                            st.caption("_Forecast unavailable for this player._")

                        # Current contract context (existing deal, smaller, gray)
                        st.markdown(
                            f"<div style='color:#888;font-size:0.82em;margin-top:6px'>"
                            f"Currently signed for {_html_money(t.get('aav'))} AAV "
                            f"({t.get('years','?')} yr, signed {t.get('signed_year','?')})"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                        # Show archetype + trend (vectorstore) or fit score (stat_fit).
                        archetype = t.get("archetype")
                        trend     = t.get("trend")
                        sem       = t.get("semantic_score")
                        fit       = t.get("fit_score")
                        if archetype or sem is not None:
                            label = (f"<b>{archetype}</b>" if archetype else "")
                            if trend:
                                label += f" &middot; trend <b>{trend}</b>"
                            if sem is not None:
                                label += f" &middot; semantic <b>{sem:.2f}</b>"
                            st.markdown(
                                f"<div style='color:#666;font-size:0.82em;margin-top:6px'>"
                                f"{label}</div>",
                                unsafe_allow_html=True,
                            )
                        elif fit is not None:
                            st.markdown(
                                f"<div style='color:#666;font-size:0.82em;margin-top:6px'>"
                                f"Fit score <b>{fit:.2f}</b></div>",
                                unsafe_allow_html=True,
                            )
                        if t.get("is_expensive_vs_estimate") and est.get("estimated_aav") and f_aav:
                            st.caption(
                                f"Forecast cost {_md_money(f_aav)} AAV vs the "
                                f"{_md_money(est['estimated_aav'])} gap estimate — "
                                f"premium beyond what the role appears to be worth."
                            )

        # ── Pricing comparables section (below targets) ──────────────────────
        if pricing_comps:
            st.markdown("")  # spacer
            n_comp = gr.get("n_pricing_comparables_available", len(pricing_comps))
            st.markdown(
                f"**Pricing comparables** &nbsp;<span style='color:#666;font-size:0.85em'>"
                f"({n_comp} contract{'s' if n_comp != 1 else ''} the model used "
                f"to anchor the AAV estimate above)</span>",
                unsafe_allow_html=True,
            )
            comp_cols = st.columns(len(pricing_comps))
            for c, col in zip(pricing_comps, comp_cols):
                with col:
                    st.markdown(f"**{c['player_name']}**")
                    st.caption(
                        f"{c['position']} · {c['team']} · "
                        f"signed {c.get('signed_year', '?')}"
                        + (f" · age {c['age_at_signing']}"
                           if c.get("age_at_signing") else "")
                    )
                    st.markdown(
                        f"<div style='line-height:1.5;font-size:0.92em;margin-top:4px'>"
                        f"AAV <b>{_html_money(c.get('aav'))}</b> &middot; "
                        f"{c.get('years', '?')} yr<br>"
                        f"Total <b>{_html_money(c.get('total_value'))}</b>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    if c.get("is_also_target"):
                        st.caption(":blue[Same player as recommended target above.]")
                    elif c.get("rationale"):
                        st.caption(f"_{c['rationale']}_")

        st.caption(f"**Leverage:** {est.get('leverage_note', '')}")

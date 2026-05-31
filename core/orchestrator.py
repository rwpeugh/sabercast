"""Simplified gap-filler orchestrator (sprint version).

This is the sprint-scope implementation of `run_gap_filler` per SABERCAST_SPEC.md.
It deliberately inlines the data loading, league-average computation, and prompt
construction that the full build splits across core/data_loader, core/gap_diagnostic,
core/player_matcher, and core/contract_valuator. We will refactor into the spec's
modular structure post-Checkpoint 3.

Flow:
  1. Aggregate the team's 2024 batting + pitching stats.
  2. Aggregate the league 2024 averages over the same qualified-player filter.
  3. Compute deltas. One gpt-4o call interprets the deltas and returns top 3 gaps
     (each tagged with a position drawn from a constrained list).
  4. For each gap, filter contracts.csv by position -> up to 3 candidate FA-style
     comparables. One gpt-4o-mini call per gap produces an AAV/years estimate
     grounded in those comparables.
  5. Check affordability against max_budget.
"""
from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
from openai import OpenAI

ProgressCallback = Optional[Callable[[str], None]]


def _ascii_fold(s: str) -> str:
    """Strip accents so 'Julio Rodríguez' (bref) matches 'Julio Rodriguez' (Spotrac).

    Spotrac's contract feed often drops diacritics that Baseball Reference keeps,
    so an exact-string join on player name silently misses Latino players.
    Folding to NFKD-then-ASCII-ignore preserves the visual identity while letting
    the join succeed.
    """
    if not isinstance(s, str):
        return s
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

# ──────────────────────────────────────────────────────────────────────────────
# Paths and constants
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"

# Map MLB team abbreviation -> bref `Tm` column value.
# bref stores city names (and concatenates them with commas for traded players).
# This sprint only needs SEA, but the dict makes future expansion trivial.
TEAM_ABBR_TO_BREF: dict[str, str] = {
    "ARI": "Arizona",       "ATL": "Atlanta",       "BAL": "Baltimore",
    "BOS": "Boston",        "CHC": "Chicago",       "CWS": "Chicago",
    "CIN": "Cincinnati",    "CLE": "Cleveland",     "COL": "Colorado",
    "DET": "Detroit",       "HOU": "Houston",       "KC":  "Kansas City",
    "LAA": "Los Angeles",   "LAD": "Los Angeles",   "MIA": "Miami",
    "MIL": "Milwaukee",     "MIN": "Minnesota",     "NYM": "New York",
    "NYY": "New York",      "OAK": "Oakland",       "PHI": "Philadelphia",
    "PIT": "Pittsburgh",    "SD":  "San Diego",     "SEA": "Seattle",
    "SF":  "San Francisco", "STL": "St. Louis",     "TB":  "Tampa Bay",
    "TEX": "Texas",         "TOR": "Toronto",       "WSH": "Washington",
}

# Constrained list the gpt-4o call must choose its gap position from. Mirrors
# Spotrac's position values so downstream contract matching is direct.
GAP_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SP", "RP"]


# Rough 2025 payroll defaults per team (in USD). Used as the initial value for
# the editable payroll input on the Gap Filler tab. Sourced from public
# tracking (Spotrac, Cot's). These are approximate end-of-2024 payroll levels —
# users should override for their actual scenario. The full build will pull
# committed-payroll figures from the contracts CSV.
TEAM_DEFAULT_PAYROLL: dict[str, int] = {
    "LAD": 325_000_000, "NYM": 320_000_000, "NYY": 305_000_000,
    "PHI": 255_000_000, "TEX": 240_000_000, "HOU": 235_000_000,
    "ATL": 230_000_000, "TOR": 230_000_000, "BOS": 215_000_000,
    "SF":  205_000_000, "ARI": 195_000_000, "STL": 195_000_000,
    "CHC": 185_000_000, "SEA": 165_000_000, "MIN": 165_000_000,
    "MIL": 155_000_000, "SD":  220_000_000, "CIN": 130_000_000,
    "DET": 140_000_000, "CWS": 110_000_000, "KC":  130_000_000,
    "BAL": 155_000_000, "CLE": 105_000_000, "COL": 145_000_000,
    "MIA":  85_000_000, "WSH": 110_000_000, "PIT":  90_000_000,
    "OAK":  75_000_000, "LAA": 170_000_000, "TB":  100_000_000,
}

# Spec's positional scarcity weights — surfaced as context to the LLM, not used
# in the simplified sprint scoring math.
POSITION_SCARCITY_WEIGHTS = {
    "C": 1.4, "SS": 1.4, "CF": 1.3, "RP": 1.3,
    "2B": 1.1, "3B": 1.1,
    "LF": 0.9, "RF": 0.9, "1B": 0.9,
    "DH": 0.7, "SP": 1.0,
}

MIN_PA = 100   # PA threshold for "qualified" 2024 batter (full season ~ 500+)
MIN_IP = 20    # IP threshold for "qualified" 2024 pitcher

GPT4O      = "gpt-4o"
GPT4O_MINI = "gpt-4o-mini"


# ──────────────────────────────────────────────────────────────────────────────
# Data loading and aggregation
# ──────────────────────────────────────────────────────────────────────────────
def _filter_team(df: pd.DataFrame, bref_team: str) -> pd.DataFrame:
    """Rows where Tm column contains the team city (catches mid-season trades)."""
    if "Tm" not in df.columns:
        return df.iloc[0:0]
    return df[df["Tm"].astype(str).str.contains(bref_team, case=False, na=False)].copy()


def _safe_weighted_mean(values: pd.Series, weights: pd.Series) -> float | None:
    """Weighted mean ignoring NaN. Returns None if no valid rows."""
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return None
    v = values[mask].astype(float)
    w = weights[mask].astype(float)
    return float((v * w).sum() / w.sum())


def aggregate_batting(df: pd.DataFrame) -> dict[str, float | int | None]:
    """PA-weighted batting aggregate over qualified players."""
    q = df[df["PA"].fillna(0) >= MIN_PA].copy()
    if q.empty:
        return {"n_players": 0}
    return {
        "n_players":  int(len(q)),
        "PA_total":   int(q["PA"].sum()),
        "HR_total":   int(q["HR"].sum()) if "HR" in q else None,
        "R_total":    int(q["R"].sum())  if "R"  in q else None,
        "RBI_total":  int(q["RBI"].sum()) if "RBI" in q else None,
        "SB_total":   int(q["SB"].sum()) if "SB" in q else None,
        "BB_total":   int(q["BB"].sum()) if "BB" in q else None,
        "SO_total":   int(q["SO"].sum()) if "SO" in q else None,
        "AVG_weighted": _safe_weighted_mean(q["AVG"] if "AVG" in q else q["BA"], q["PA"]),
        "OBP_weighted": _safe_weighted_mean(q["OBP"], q["PA"]),
        "SLG_weighted": _safe_weighted_mean(q["SLG"], q["PA"]),
        "OPS_weighted": _safe_weighted_mean(q["OPS"], q["PA"]),
    }


def aggregate_pitching(df: pd.DataFrame) -> dict[str, float | int | None]:
    """IP-weighted pitching aggregate over qualified pitchers, with SP/RP split."""
    q = df[df["IP"].fillna(0) >= MIN_IP].copy()
    if q.empty:
        return {"n_pitchers": 0}

    starters = q[q["GS"].fillna(0) >= 5]
    relievers = q[q["GS"].fillna(0) < 5]

    def block(d: pd.DataFrame) -> dict[str, Any]:
        if d.empty:
            return {"n": 0}
        return {
            "n":      int(len(d)),
            "IP":     float(d["IP"].sum()),
            "ERA":    _safe_weighted_mean(d["ERA"], d["IP"]),
            "WHIP":   _safe_weighted_mean(d["WHIP"], d["IP"]),
            "K9":     _safe_weighted_mean(d["SO9"] if "SO9" in d else d.get("K/9"), d["IP"]),
            "BB":     int(d["BB"].sum()) if "BB" in d else None,
            "SO":     int(d["SO"].sum()) if "SO" in d else None,
        }

    return {
        "n_pitchers": int(len(q)),
        "starters":   block(starters),
        "relievers":  block(relievers),
        "overall":    block(q),
    }


def _compute_delta(team: dict, league: dict) -> dict[str, float | None]:
    """Per-stat delta = team - league for the comparable scalar fields."""
    delta: dict[str, float | None] = {}
    for k, v in team.items():
        lv = league.get(k)
        if isinstance(v, (int, float)) and isinstance(lv, (int, float)):
            delta[k] = round(v - lv, 4)
    return delta


# ──────────────────────────────────────────────────────────────────────────────
# Defensive aggregation (added 2026-05-29)
# ──────────────────────────────────────────────────────────────────────────────
# Statcast's OAA leaderboard uses team nicknames in display_team_name. This map
# normalizes them to the 3-letter abbreviations we use throughout.
OAA_NICKNAME_TO_ABBR: dict[str, str] = {
    "Angels": "LAA", "Astros": "HOU", "Athletics": "OAK", "Blue Jays": "TOR",
    "Braves": "ATL", "Brewers": "MIL", "Cardinals": "STL", "Cubs": "CHC",
    "D-backs": "ARI", "Dodgers": "LAD", "Giants": "SF",  "Guardians": "CLE",
    "Mariners": "SEA", "Marlins": "MIA", "Mets": "NYM", "Nationals": "WSH",
    "Orioles": "BAL", "Padres": "SD",  "Phillies": "PHI", "Pirates": "PIT",
    "Rangers": "TEX", "Rays": "TB",  "Red Sox": "BOS", "Reds": "CIN",
    "Rockies": "COL", "Royals": "KC",  "Tigers": "DET", "Twins": "MIN",
    "White Sox": "CWS","Yankees": "NYY",
}


def aggregate_team_defense(team_abbr: str,
                           oaa_df: pd.DataFrame,
                           catcher_df: pd.DataFrame,
                           sprint_df: pd.DataFrame) -> dict:
    """Per-position defensive aggregate for one team. Returns:
      {
        "by_position": {"SS": {"oaa_total": 1, "frp_total": 0, "n_players": 1},
                        "1B": {"oaa_total": -11, ...}, ...},
        "catcher":     {"n": 1, "pop_2b_mean": 1.95, ...} | None,
        "sprint_team_mean": 27.4,
      }
    """
    by_position: dict[str, dict[str, float | int]] = {}
    if oaa_df is not None and not oaa_df.empty:
        # Statcast OAA uses team nicknames (e.g. "Mariners") in display_team_name.
        # Normalize to the 3-letter abbr and filter to this team.
        oaa_with_abbr = oaa_df.copy()
        oaa_with_abbr["team_abbr"] = oaa_with_abbr["display_team_name"].astype(str).map(
            OAA_NICKNAME_TO_ABBR
        )
        team_oaa = oaa_with_abbr[oaa_with_abbr["team_abbr"] == team_abbr]
        for pos, grp in team_oaa.groupby("primary_pos_formatted"):
            oaa_vals = pd.to_numeric(grp["outs_above_average"], errors="coerce")
            frp_vals = pd.to_numeric(grp["fielding_runs_prevented"], errors="coerce")
            by_position[str(pos)] = {
                "n_players":  int(len(grp)),
                "oaa_total":  int(oaa_vals.sum(skipna=True)),
                "frp_total":  int(frp_vals.sum(skipna=True)),
            }

    # Catcher pop-time aggregate (lower pop = better)
    catcher_block: dict | None = None
    if catcher_df is not None and not catcher_df.empty:
        # catcher_defense uses team_id (numeric) — match via batting (where mlbID -> team).
        # Simplest sprint-scope approach: use entity_name and look up the team
        # from the sprint_speed file (which has team abbr).
        cat_with_team = catcher_df.merge(
            sprint_df[["player_id", "team"]],
            left_on="entity_id", right_on="player_id", how="left",
        )
        team_cat = cat_with_team[cat_with_team["team"].astype(str) == team_abbr]
        if not team_cat.empty:
            pop_vals = pd.to_numeric(team_cat["pop_2b_sba"], errors="coerce").dropna()
            arm_vals = pd.to_numeric(team_cat["maxeff_arm_2b_3b_sba"], errors="coerce").dropna()
            catcher_block = {
                "n": int(len(team_cat)),
                "pop_2b_mean": round(float(pop_vals.mean()), 3) if not pop_vals.empty else None,
                "arm_strength_mean": round(float(arm_vals.mean()), 1) if not arm_vals.empty else None,
            }

    # Team-level sprint speed (mean over players on this team)
    sprint_team_mean: float | None = None
    if sprint_df is not None and not sprint_df.empty:
        sprint_team = sprint_df[sprint_df["team"].astype(str) == team_abbr]
        if not sprint_team.empty:
            sprint_vals = pd.to_numeric(sprint_team["sprint_speed"], errors="coerce").dropna()
            if not sprint_vals.empty:
                sprint_team_mean = round(float(sprint_vals.mean()), 2)

    return {
        "by_position":      by_position,
        "catcher":          catcher_block,
        "sprint_team_mean": sprint_team_mean,
    }


def aggregate_league_defense_per_team(oaa_df: pd.DataFrame,
                                      catcher_df: pd.DataFrame,
                                      sprint_df: pd.DataFrame,
                                      n_teams: int = 30) -> dict:
    """League-wide defensive aggregate divided per team — comparable scale to a single team."""
    by_position: dict[str, dict[str, float | int]] = {}
    if oaa_df is not None and not oaa_df.empty:
        for pos, grp in oaa_df.groupby("primary_pos_formatted"):
            oaa_vals = pd.to_numeric(grp["outs_above_average"], errors="coerce")
            frp_vals = pd.to_numeric(grp["fielding_runs_prevented"], errors="coerce")
            by_position[str(pos)] = {
                "n_players_total":  int(len(grp)),
                "oaa_per_team_avg": round(float(oaa_vals.sum(skipna=True)) / n_teams, 2),
                "frp_per_team_avg": round(float(frp_vals.sum(skipna=True)) / n_teams, 2),
            }

    catcher_block: dict | None = None
    if catcher_df is not None and not catcher_df.empty:
        pop_vals = pd.to_numeric(catcher_df["pop_2b_sba"], errors="coerce").dropna()
        arm_vals = pd.to_numeric(catcher_df["maxeff_arm_2b_3b_sba"], errors="coerce").dropna()
        catcher_block = {
            "n_catchers": int(len(catcher_df)),
            "league_pop_2b_mean": round(float(pop_vals.mean()), 3) if not pop_vals.empty else None,
            "league_arm_strength_mean": round(float(arm_vals.mean()), 1) if not arm_vals.empty else None,
        }

    sprint_league_mean: float | None = None
    if sprint_df is not None and not sprint_df.empty:
        sprint_vals = pd.to_numeric(sprint_df["sprint_speed"], errors="coerce").dropna()
        if not sprint_vals.empty:
            sprint_league_mean = round(float(sprint_vals.mean()), 2)

    return {
        "by_position":         by_position,
        "catcher":             catcher_block,
        "sprint_league_mean":  sprint_league_mean,
    }


def compute_defense_deltas(team_defense: dict, league_defense: dict) -> dict:
    """Per-position OAA delta + sprint speed delta. Positive = team above league."""
    deltas: dict[str, dict] = {}
    team_by_pos   = team_defense.get("by_position", {})
    league_by_pos = league_defense.get("by_position", {})
    for pos in sorted(set(team_by_pos) | set(league_by_pos)):
        t = team_by_pos.get(pos, {})
        l = league_by_pos.get(pos, {})
        team_oaa = t.get("oaa_total", 0) or 0
        lge_oaa  = l.get("oaa_per_team_avg", 0) or 0
        deltas[pos] = {
            "oaa_delta_vs_league_per_team": round(team_oaa - lge_oaa, 2),
            "team_oaa_total":              team_oaa,
            "league_avg_per_team":         lge_oaa,
        }

    # Catcher delta (lower pop time is better, so flip the sign for "above league")
    cat_delta: dict | None = None
    t_cat = team_defense.get("catcher")
    l_cat = league_defense.get("catcher")
    if t_cat and l_cat and t_cat.get("pop_2b_mean") and l_cat.get("league_pop_2b_mean"):
        # Negative delta means team pop is FASTER than league (better)
        cat_delta = {
            "team_pop_2b_mean":   t_cat["pop_2b_mean"],
            "league_pop_2b_mean": l_cat["league_pop_2b_mean"],
            "pop_2b_delta":       round(t_cat["pop_2b_mean"] - l_cat["league_pop_2b_mean"], 3),
            "delta_interpretation": "negative = team is faster (better)",
        }

    # Sprint speed delta
    sprint_delta = None
    if team_defense.get("sprint_team_mean") and league_defense.get("sprint_league_mean"):
        sprint_delta = round(
            team_defense["sprint_team_mean"] - league_defense["sprint_league_mean"], 2
        )

    return {
        "by_position":  deltas,
        "catcher":      cat_delta,
        "sprint_delta": sprint_delta,
    }


# ──────────────────────────────────────────────────────────────────────────────
# LLM calls
# ──────────────────────────────────────────────────────────────────────────────
GAP_DIAGNOSTIC_SYSTEM = """You are an MLB front-office analyst evaluating where a team has the largest
performance gaps versus league average. You will be given the team's 2024
season aggregates (offense + pitching + defense), the league's 2024 averages,
and the per-stat deltas including per-position defensive metrics:
  * outs_above_average (OAA) per fielding position — positive = team above league
  * catcher pop time to 2B — negative delta = team's catcher is faster (better)
  * team-mean sprint speed — positive = team is faster than league

A "gap" can be driven by offensive underperformance, pitching underperformance,
defensive underperformance at a specific position, or a combination. When a
position has both poor offense AND poor defense the gap is more severe.

Return STRICT JSON only, no prose, with this exact schema:

{
  "team": "<3-letter abbr>",
  "year": 2024,
  "roster_summary": "<2-3 sentence plain-English summary of the team's profile, including any standout defensive findings>",
  "gaps": [
    {
      "position": "<one of C, 1B, 2B, 3B, SS, LF, CF, RF, DH, SP, RP>",
      "gap_score": <float 0-10, higher = bigger gap>,
      "win_impact": "<one of: high, medium, low>",
      "gap_components": {"offense": <float 0-10>, "defense": <float 0-10>},
      "reasoning": "<one sentence: why this is a gap, citing one or two specific stat deltas including OAA where relevant>"
    }
  ]
}

Return EXACTLY 3 gaps. Choose positions where filling the gap is most likely to
improve next year's wins. You may consider positional scarcity (C and SS scarce,
DH abundant). Do not include any position not in the allowed list. The defense
component should be 0 for SP/RP/DH (no fielding) and proportional to the
position's OAA deficit otherwise."""


CONTRACT_ESTIMATE_SYSTEM = """You are an MLB contract valuation analyst. Given a target position with a
described gap, plus 1-3 recent comparable contracts at that position, produce a
realistic AAV (average annual value) and years estimate for a free-agent
acquisition who would fill that gap.

Return STRICT JSON only, no prose, with this exact schema:

{
  "position": "<position>",
  "estimated_aav": <integer USD>,
  "estimated_years": <integer>,
  "total_range_low":  <integer USD, total contract>,
  "total_range_high": <integer USD, total contract>,
  "comparable_contracts": [
    {
      "player_name": "<name>",
      "aav": <integer>,
      "years": <integer>,
      "signed_year": <year>,
      "rationale": "<one short phrase, max 12 words, explaining why this contract is a useful price reference for the gap — e.g. 'recent free-agent benchmark at peak production', 'top-of-market ceiling for the position', 'comparable age and offensive profile'>"
    }
  ],
  "leverage_note": "<one sentence: who has leverage in this signing and why>"
}

Ground your numbers in the comparables provided. If only 1-2 comparables exist,
still produce an estimate and reflect the limited sample in the leverage_note.

CRITICAL: Echo back EVERY comparable contract that was provided to you in the
input, in the same order — do not drop outliers, do not skip any. If a contract
is an extreme outlier (e.g. a ten-year deal that distorts the market) say so in
its rationale ('outlier ceiling, not representative', etc.). The rationale field
is required for every comparable; keep each one specific and non-repetitive."""


TARGET_FORECAST_SYSTEM = """You are an MLB contract valuation analyst. Given a specific named player's
recent statistical line, age, and position-matched comparable contracts,
forecast the AAV and years that player would command on a NEW free-agent deal
in the upcoming offseason.

This is NOT the player's current contract — it is your forecast of what a new
deal would look like if they hit the open market in the {market_year} offseason
following their {prior_year} regular season.

Return STRICT JSON only, no prose, with this exact schema:

{
  "player_name": "<name as provided>",
  "forecast_aav":   <integer USD>,
  "forecast_years": <integer>,
  "rationale": "<one short phrase, max 15 words, citing the specific stats and comparables driving this forecast>"
}

Ground your forecast in the comparables provided. Factor in:
  * Recent production (a player coming off a career-best year commands more)
  * Age (younger players get longer terms; older players get shorter terms at lower AAV)
  * Positional scarcity (catchers and middle infielders earn premiums)
  * The current state of the comparable market at this position

Do NOT reference market events after {market_year}."""


def _client() -> OpenAI:
    """Lazy-import key loader so this module can be imported without OPENAI_API_KEY."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.config import get_openai_api_key
    return OpenAI(api_key=get_openai_api_key())


def diagnose_gaps_llm(team_abbr: str, team_bat: dict, team_pit: dict,
                      league_bat: dict, league_pit: dict,
                      delta_bat: dict, delta_pit: dict,
                      team_defense: dict | None = None,
                      league_defense: dict | None = None,
                      defense_deltas: dict | None = None) -> dict:
    """One gpt-4o call interpreting deltas and returning top 3 gaps as JSON."""
    oai = _client()
    user_payload = {
        "team": team_abbr,
        "year": 2024,
        "team_batting":   team_bat,
        "team_pitching":  team_pit,
        "league_batting": league_bat,
        "league_pitching": league_pit,
        "batting_deltas_vs_league":  delta_bat,
        "pitching_deltas_vs_league": delta_pit,
        "position_scarcity_weights": POSITION_SCARCITY_WEIGHTS,
        "allowed_positions": GAP_POSITIONS,
    }
    if team_defense is not None and defense_deltas is not None:
        user_payload["team_defense"]              = team_defense
        user_payload["league_defense_per_team"]   = league_defense
        user_payload["defense_deltas_vs_league"]  = defense_deltas
    resp = oai.chat.completions.create(
        model=GPT4O,
        response_format={"type": "json_object"},
        temperature=0,
        seed=42,
        messages=[
            {"role": "system", "content": GAP_DIAGNOSTIC_SYSTEM},
            {"role": "user",   "content": json.dumps(user_payload)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def estimate_contract_llm(position: str, gap_reasoning: str,
                          comparables: list[dict], market_year: int) -> dict:
    """One gpt-4o-mini call per gap. Comparables are 1-3 contract rows.

    ``market_year`` is the offseason in which the hypothetical signing would
    happen — i.e., evaluation_year + 1. The LLM is instructed not to extrapolate
    beyond this year (avoids leaking forward-curve assumptions from training data).
    """
    oai = _client()
    user_payload = {
        "position": position,
        "gap_description": gap_reasoning,
        "comparable_contracts": comparables,
        "market_year": market_year,
        "instruction": (
            f"You are pricing this contract as if it were signed in the offseason "
            f"following the {market_year - 1} regular season. Do not reference or "
            f"assume any market events after {market_year}."
        ),
    }
    resp = oai.chat.completions.create(
        model=GPT4O_MINI,
        response_format={"type": "json_object"},
        temperature=0,
        seed=42,
        messages=[
            {"role": "system", "content": CONTRACT_ESTIMATE_SYSTEM},
            {"role": "user",   "content": json.dumps(user_payload)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


OPPONENT_SCOUTING_SYSTEM = """You are an MLB advance scout preparing a report on an opponent. You receive
the opponent's full 2024 season aggregates (offense + pitching), the per-team
league averages, and per-stat deltas, plus the names and 2024 lines of their
top hitters and pitchers.

Return STRICT JSON only, no prose, with this exact schema:

{
  "opponent": "<3-letter abbr>",
  "year": 2024,
  "narrative": "<2-3 sentence plain-English summary of how this team plays — strengths, weaknesses, and tendencies>",
  "top_threats": [
    {"player_name": "<name>", "role": "hitter" | "pitcher", "why": "<one short phrase, why this player is a threat>"}
  ],
  "exploitable_weaknesses": [
    {"area": "<short label, e.g. 'middle-infield power', 'left-handed pitching', 'bullpen middle innings'>",
     "stat_evidence": "<one short phrase citing the relevant delta>",
     "win_impact": "high" | "medium" | "low"}
  ],
  "pitching_strategy": "<2-3 sentence recommendation: how to pitch against this lineup, where to attack, which hitters to neutralize>",
  "hitting_approach":  "<2-3 sentence recommendation: how to approach their starters and bullpen, what pitch types/zones to target>"
}

Return EXACTLY 3 top_threats (mix of hitters and pitchers as appropriate) and
EXACTLY 3 exploitable_weaknesses. Ground every recommendation in the provided
data; do not reference market events or signings."""


def scout_opponent_llm(opponent_abbr: str,
                       team_bat: dict, team_pit: dict,
                       league_bat: dict, league_pit: dict,
                       delta_bat: dict, delta_pit: dict,
                       top_hitters: list[dict],
                       top_pitchers: list[dict]) -> dict:
    """One gpt-4o call producing the opponent scouting report as structured JSON."""
    oai = _client()
    user_payload = {
        "opponent": opponent_abbr,
        "year": 2024,
        "opponent_batting":   team_bat,
        "opponent_pitching":  team_pit,
        "league_batting":     league_bat,
        "league_pitching":    league_pit,
        "batting_deltas_vs_league":  delta_bat,
        "pitching_deltas_vs_league": delta_pit,
        "top_hitters":  top_hitters,
        "top_pitchers": top_pitchers,
    }
    resp = oai.chat.completions.create(
        model=GPT4O,
        response_format={"type": "json_object"},
        temperature=0,
        seed=42,
        messages=[
            {"role": "system", "content": OPPONENT_SCOUTING_SYSTEM},
            {"role": "user",   "content": json.dumps(user_payload)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def forecast_target_contract_llm(player: dict, position: str,
                                 comparables: list[dict],
                                 market_year: int) -> dict:
    """One gpt-4o-mini call per recommended target.

    Produces a forward-looking forecast of what THIS SPECIFIC PLAYER would
    command on a new free-agent deal in the ``market_year`` offseason — distinct
    from their current contract AAV. The premium flag compares this forecast
    (what it would actually cost to sign them) against the gap-fill estimate
    (what the role appears to be worth at market).
    """
    oai = _client()
    # Use .replace() instead of .format() — the JSON example inside the prompt
    # contains literal {} characters that would collide with str.format().
    sys_prompt = (
        TARGET_FORECAST_SYSTEM
        .replace("{market_year}", str(market_year))
        .replace("{prior_year}",  str(market_year - 1))
    )
    user_payload = {
        "player_name": player["player_name"],
        "position":    position,
        "age_now":     player.get("age_at_signing"),  # rough proxy; refined post-sprint
        "stats_2024":  player.get("stats_2024"),
        "current_contract": {
            "aav":          player.get("aav"),
            "years":        player.get("years"),
            "signed_year":  player.get("signed_year"),
        },
        "position_comparables": comparables,
        "market_year":   market_year,
    }
    resp = oai.chat.completions.create(
        model=GPT4O_MINI,
        response_format={"type": "json_object"},
        temperature=0,
        seed=42,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user",   "content": json.dumps(user_payload)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


# ──────────────────────────────────────────────────────────────────────────────
# Candidate selection helpers
# ──────────────────────────────────────────────────────────────────────────────
_HITTER_POSITIONS  = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF"}
_PITCHER_POSITIONS = {"SP", "RP"}


def _filter_eligible_pool(contracts: pd.DataFrame, position: str,
                          evaluation_year: int) -> pd.DataFrame:
    """Players at the gap position whose contracts existed by evaluation_year."""
    pool = contracts[
        (contracts["position"] == position)
        & (contracts["signed_year"].fillna(9999) <= evaluation_year)
    ].copy()
    if pool.empty and position == "RP":
        # Spotrac labels relievers sparingly; broaden to any reliever-coded rows.
        pool = contracts[
            contracts["position"].str.contains("P", na=False)
            & ~contracts["position"].eq("SP")
            & (contracts["signed_year"].fillna(9999) <= evaluation_year)
        ].copy()
    if pool.empty and position == "OF":
        # Generic OF — broaden to all three outfield positions.
        pool = contracts[
            contracts["position"].isin(["LF", "CF", "RF", "OF"])
            & (contracts["signed_year"].fillna(9999) <= evaluation_year)
        ].copy()
    return pool


def _lookup_player_stats(name: str, batting: pd.DataFrame, pitching: pd.DataFrame,
                         position: str) -> dict | None:
    """Pull a player's 2024 stats from the appropriate CSV by accent-folded name match.

    Returns None only when the player truly has no 2024 stats at the expected
    role (injured, on the IL all year, etc.). Name encoding mismatches between
    Spotrac (ASCII) and bref (UTF-8 with diacritics) are bridged via accent
    folding on both sides of the comparison.
    """
    folded_name = _ascii_fold(name)
    if position in _HITTER_POSITIONS:
        rows = batting[batting["Name"].apply(_ascii_fold) == folded_name]
        if rows.empty:
            return None
        row = rows.iloc[0]
        return {
            "role": "hitter",
            "PA":   int(row.get("PA"))  if pd.notna(row.get("PA"))  else 0,
            "G":    int(row.get("G"))   if pd.notna(row.get("G"))   else 0,
            "HR":   int(row.get("HR"))  if pd.notna(row.get("HR"))  else 0,
            "RBI":  int(row.get("RBI")) if pd.notna(row.get("RBI")) else 0,
            "SB":   int(row.get("SB"))  if pd.notna(row.get("SB"))  else 0,
            "AVG":  float(row["AVG"])   if pd.notna(row.get("AVG")) else None,
            "OBP":  float(row["OBP"])   if pd.notna(row.get("OBP")) else None,
            "SLG":  float(row["SLG"])   if pd.notna(row.get("SLG")) else None,
            "OPS":  float(row["OPS"])   if pd.notna(row.get("OPS")) else None,
        }
    if position in _PITCHER_POSITIONS:
        rows = pitching[pitching["Name"].apply(_ascii_fold) == folded_name]
        if rows.empty:
            return None
        row = rows.iloc[0]
        return {
            "role": "pitcher",
            "IP":   float(row["IP"])    if pd.notna(row.get("IP"))   else 0.0,
            "G":    int(row.get("G"))   if pd.notna(row.get("G"))    else 0,
            "GS":   int(row.get("GS"))  if pd.notna(row.get("GS"))   else 0,
            "ERA":  float(row["ERA"])   if pd.notna(row.get("ERA"))  else None,
            "WHIP": float(row["WHIP"])  if pd.notna(row.get("WHIP")) else None,
            "K9":   float(row["SO9"])   if pd.notna(row.get("SO9"))  else None,
            "W":    int(row.get("W"))   if pd.notna(row.get("W"))    else 0,
            "L":    int(row.get("L"))   if pd.notna(row.get("L"))    else 0,
        }
    return None


def _compute_fit_score(stats: dict | None) -> float:
    """How much would acquiring this player improve the team at this gap?

    Heuristic for the sprint:
      * Hitter fit  = (OPS − 0.700) × min(PA, 600) / 100
        Higher OPS, more playing time → higher score. 0.700 is roughly league-
        average OPS; PA is capped at a full season to avoid rewarding outliers.
      * Pitcher fit = (4.00 − ERA) × min(IP, 200) / 50
        Lower ERA, more innings → higher score. 4.00 is roughly league-average
        ERA; IP capped at a full starter season.
      * Missing stats → 0. Player ranks at the bottom (and the UI flags it).

    Not a sabermetric WAR — but a defensible one-line proxy for "how much would
    adding this player at this position lift the team."
    """
    if not stats:
        return 0.0
    if stats["role"] == "hitter":
        ops = stats.get("OPS") or 0
        pa  = stats.get("PA",  0)
        return round((ops - 0.700) * min(pa, 600) / 100.0, 2)
    if stats["role"] == "pitcher":
        era = stats.get("ERA")
        if era is None:
            return 0.0
        ip = stats.get("IP", 0.0)
        return round((4.00 - era) * min(ip, 200) / 50.0, 2)
    return 0.0


def _build_target_row(row: pd.Series, stats: dict | None, fit: float) -> dict:
    """Common dict shape for both target and pricing-comparable rows."""
    return {
        "player_name":   row["player_name"],
        "team":          row["team"],
        "position":      row["position"],
        "aav":           int(row["aav"])            if pd.notna(row["aav"])            else None,
        "years":         int(row["years"])          if pd.notna(row["years"])          else None,
        "total_value":   int(row["contract_value"]) if pd.notna(row["contract_value"]) else None,
        "signed_year":   int(row["signed_year"])    if pd.notna(row["signed_year"])    else None,
        "age_at_signing":int(row["age"])            if pd.notna(row["age"])            else None,
        "stats_2024":    stats,
        "fit_score":     fit,
    }


def _pick_targets(contracts: pd.DataFrame, batting: pd.DataFrame,
                  pitching: pd.DataFrame, position: str, evaluation_year: int,
                  single_signing_ceiling: float, k: int = 3) -> list[dict]:
    """Top-k acquisition targets at this position, ranked by 2024 statistical fit.

    A *target* differs from a *pricing comparable*: targets are players whose
    on-field production would most improve the team at this gap, subject to a
    single-signing budget ceiling. Pricing comparables (see
    ``_pick_pricing_comparables``) are top-AAV contracts at the position and
    are the LLM's reference points for what such a player would cost.

    The two lists can and often will overlap — the best statistical fit at a
    scarce position is usually also the highest-paid contract.
    """
    pool = _filter_eligible_pool(contracts, position, evaluation_year)
    if pool.empty:
        return []
    # Budget filter: a single signing taking >X% of total payroll is unrealistic.
    pool = pool[pool["aav"].fillna(float("inf")) <= single_signing_ceiling].copy()
    if pool.empty:
        return []

    enriched = []
    for _, row in pool.iterrows():
        stats = _lookup_player_stats(row["player_name"], batting, pitching, row["position"])
        fit = _compute_fit_score(stats)
        enriched.append(_build_target_row(row, stats, fit))

    # Sort by fit_score desc; tiebreak by AAV desc (better contract = more proven).
    enriched.sort(key=lambda r: (r["fit_score"], r["aav"] or 0), reverse=True)
    return enriched[:k]


def _pick_pricing_comparables(contracts: pd.DataFrame, batting: pd.DataFrame,
                              pitching: pd.DataFrame, position: str,
                              evaluation_year: int, k: int = 3) -> list[dict]:
    """Top-k contracts at the position by AAV. These are the LLM's pricing anchors.

    Same eligibility filter as ``_pick_targets`` (no look-ahead), but no budget
    ceiling — the very biggest comparable signings are valuable pricing context
    even if they would themselves be unaffordable for a small/mid-market team.
    """
    pool = _filter_eligible_pool(contracts, position, evaluation_year)
    if pool.empty:
        return []
    pool = pool.sort_values("aav", ascending=False).head(k)
    rows = []
    for _, row in pool.iterrows():
        stats = _lookup_player_stats(row["player_name"], batting, pitching, row["position"])
        fit = _compute_fit_score(stats)
        rows.append(_build_target_row(row, stats, fit))
    return rows


def run_gap_filler_simple(team_abbr: str = "SEA",
                          max_budget: float = 165_000_000,
                          evaluation_year: int = 2024,
                          progress: ProgressCallback = None) -> dict:
    """Sprint orchestrator. Returns the full structured output for the Gap Filler tab.

    ``evaluation_year`` is the season whose stats inform the diagnosis. The GM is
    assumed to be making decisions in the offseason that follows. To avoid
    look-ahead bias, comparable contracts are filtered to those signed on or
    before ``evaluation_year``; future signings are excluded even if they are
    present in the raw CSV.

    ``progress`` is an optional callback that receives a string label at each
    major step. The Streamlit tab uses this to drive an ``st.status`` widget so
    the user sees what's happening during the live LLM calls.
    """
    def _tick(label: str) -> None:
        if progress is not None:
            progress(label)

    if team_abbr not in TEAM_ABBR_TO_BREF:
        raise ValueError(f"Unknown team abbreviation: {team_abbr}")
    bref_team = TEAM_ABBR_TO_BREF[team_abbr]
    market_year = evaluation_year + 1
    t0 = time.time()

    # 1. Load
    _tick("Loading 2024 batting, pitching, contract, and defensive CSVs")
    batting   = pd.read_csv(DATA_RAW / "batting_2024.csv",  encoding="utf-8")
    pitching  = pd.read_csv(DATA_RAW / "pitching_2024.csv", encoding="utf-8")
    contracts = pd.read_csv(DATA_RAW / "contracts.csv",     encoding="utf-8")

    # Defensive CSVs are optional — Day 1 sprint runs without them. Treat as best-effort.
    def _try_read(name: str) -> pd.DataFrame | None:
        p = DATA_RAW / name
        return pd.read_csv(p, encoding="utf-8") if p.exists() else None

    oaa_df     = _try_read("oaa_2024.csv")
    sprint_df  = _try_read("sprint_speed_2024.csv")
    catcher_df = _try_read("catcher_defense_2024.csv")
    have_defense = oaa_df is not None and sprint_df is not None

    # 2. Aggregate team and league
    _tick(f"Aggregating {team_abbr}'s qualified-player stats vs the rest of MLB")
    team_bat_df = _filter_team(batting,  bref_team)
    team_pit_df = _filter_team(pitching, bref_team)

    team_bat   = aggregate_batting(team_bat_df)
    team_pit   = aggregate_pitching(team_pit_df)
    league_bat = aggregate_batting(batting)
    league_pit = aggregate_pitching(pitching)

    # Per-team scaling: league totals are 30-team sums, team totals are one team's
    # contribution. Compare team to league/30 for total-counting stats so they
    # are on the same scale; rate stats (AVG/OBP/SLG/OPS/ERA/WHIP/K9) compare directly.
    league_bat_per_team = {
        k: (v / 30 if isinstance(v, (int, float)) and k.endswith("_total") else v)
        for k, v in league_bat.items()
    }
    league_pit_per_team_overall = {
        k: (v / 30 if isinstance(v, (int, float)) and k in {"IP", "n"} else v)
        for k, v in league_pit.get("overall", {}).items()
    }

    delta_bat = _compute_delta(team_bat, league_bat_per_team)
    delta_pit = _compute_delta(team_pit.get("overall", {}), league_pit_per_team_overall)

    # 2b. Defensive aggregates (if defensive CSVs are present)
    team_defense:    dict | None = None
    league_defense:  dict | None = None
    defense_deltas:  dict | None = None
    if have_defense:
        _tick(f"Aggregating {team_abbr}'s defensive metrics vs league (OAA, pop time, sprint speed)")
        team_defense   = aggregate_team_defense(team_abbr, oaa_df, catcher_df, sprint_df)
        league_defense = aggregate_league_defense_per_team(oaa_df, catcher_df, sprint_df)
        defense_deltas = compute_defense_deltas(team_defense, league_defense)

    # 3. Diagnose gaps via gpt-4o
    _tick("Asking GPT-4o to interpret deltas and identify the top 3 gap positions")
    diag = diagnose_gaps_llm(
        team_abbr,
        team_bat, team_pit.get("overall", {}),
        league_bat_per_team, league_pit_per_team_overall,
        delta_bat, delta_pit,
        team_defense=team_defense,
        league_defense=league_defense,
        defense_deltas=defense_deltas,
    )

    # 4 + 5. For each gap:
    #          (a) pick recommended targets (vectorstore-based semantic match
    #              when available; stat-fit fallback otherwise)
    #          (b) pick pricing comparables (top-AAV contracts at the position)
    #          (c) gpt-4o-mini contract estimate, anchored to the comparables
    #
    # Single-signing ceiling: assume one acquisition can claim at most 30% of the
    # total payroll. This is a heuristic — see core/budget_manager.py in the full
    # build for a proper committed-vs-flexible payroll calculation.
    single_signing_ceiling = max_budget * 0.30

    # Try the embedding-based player matcher (Pipeline 04 → runtime). It uses
    # the ChromaDB vectorstore of player profiles to find semantically similar
    # candidates, then filters to those within position + budget + no-look-ahead.
    # Falls back to the stat-fit picker if the vectorstore isn't available.
    try:
        from core.player_matcher import find_matches, vectorstore_available
        vs_ready = vectorstore_available()
    except Exception:
        vs_ready = False
        find_matches = None

    results = []
    for idx, gap in enumerate(diag.get("gaps", [])[:3], start=1):
        pos = gap.get("position")
        _tick(f"Ranking targets and pricing gap {idx}/3 ({pos}) with GPT-4o-mini")

        targets: list[dict] = []
        targets_source = "stat_fit"   # default
        if vs_ready and find_matches is not None:
            try:
                targets = find_matches(
                    gap, contracts, batting, pitching,
                    evaluation_year=evaluation_year,
                    single_signing_ceiling=single_signing_ceiling,
                    k=3,
                )
                if targets:
                    targets_source = "vectorstore"
            except Exception:
                targets = []

        if not targets:
            targets = _pick_targets(contracts, batting, pitching, pos,
                                    evaluation_year,
                                    single_signing_ceiling, k=3)
        pricing_comparables = _pick_pricing_comparables(contracts, batting, pitching,
                                                        pos, evaluation_year, k=3)

        if pricing_comparables:
            estimate = estimate_contract_llm(
                pos, gap.get("reasoning", ""), pricing_comparables,
                market_year=market_year,
            )
        else:
            estimate = {
                "position": pos,
                "estimated_aav": None,
                "estimated_years": None,
                "total_range_low": None,
                "total_range_high": None,
                "comparable_contracts": [],
                "leverage_note": (
                    f"No comparable contracts in dataset for position {pos} "
                    f"with signed_year <= {evaluation_year}."
                ),
            }
        affordable = (
            estimate.get("estimated_aav") is not None
            and estimate["estimated_aav"] <= single_signing_ceiling
        )

        # Cross-link LLM rationales onto the structured pricing-comparable rows
        # (the LLM only sees the comparables list — its output carries the
        # rationale string but lacks the full contract metadata we want to show
        # in the UI), and flag comparables that are also recommended targets.
        llm_rationales = {
            c.get("player_name"): c.get("rationale", "")
            for c in estimate.get("comparable_contracts", [])
        }
        target_name_set = {t["player_name"] for t in targets}
        for pc in pricing_comparables:
            pc["rationale"]      = llm_rationales.get(pc["player_name"], "")
            pc["is_also_target"] = pc["player_name"] in target_name_set

        # Per-target forecast: predict what each recommended target would
        # actually command on a NEW free-agent deal in the upcoming offseason.
        # This is distinct from the player's existing contract AAV, which only
        # reflects a deal signed at a prior point in their career. The premium
        # flag then compares the forecast (cost to acquire) vs the estimate
        # (what the role merits).
        est_aav = estimate.get("estimated_aav")
        for ti, t in enumerate(targets, start=1):
            _tick(f"Forecasting target {ti}/{len(targets)} ({t['player_name']}) for the {pos} gap")
            try:
                forecast = forecast_target_contract_llm(
                    t, pos, pricing_comparables, market_year=market_year,
                )
                t["forecast_aav"]       = forecast.get("forecast_aav")
                t["forecast_years"]     = forecast.get("forecast_years")
                t["forecast_rationale"] = forecast.get("rationale", "")
            except Exception as e:                              # noqa: BLE001
                t["forecast_aav"]       = None
                t["forecast_years"]     = None
                t["forecast_rationale"] = f"forecast unavailable ({type(e).__name__})"

            # Premium flag now uses the FORECAST (what we'd pay to sign them)
            # vs the gap-fill ESTIMATE (what the role appears to be worth).
            f_aav = t.get("forecast_aav")
            if est_aav and f_aav:
                t["premium_vs_estimate"] = round(f_aav / est_aav - 1.0, 2)
                t["is_expensive_vs_estimate"] = f_aav > est_aav * 1.5
            else:
                t["premium_vs_estimate"] = None
                t["is_expensive_vs_estimate"] = False

        results.append({
            "gap": gap,
            "targets": targets,
            "targets_source": targets_source,
            "pricing_comparables": pricing_comparables,
            "estimate": estimate,
            "affordable": affordable,
            "n_targets_available": len(targets),
            "n_pricing_comparables_available": len(pricing_comparables),
        })

    # Positions where we had fewer than 3 affordable, stat-rich targets:
    thin_targets_positions = [
        r["gap"].get("position") for r in results if r["n_targets_available"] < 3
    ]

    return {
        "team": team_abbr,
        "year": evaluation_year,
        "evaluation_year": evaluation_year,
        "market_year": market_year,
        "max_budget": max_budget,
        "elapsed_seconds": round(time.time() - t0, 2),
        "team_batting":  team_bat,
        "team_pitching": team_pit,
        "league_batting_per_team":  league_bat_per_team,
        "league_pitching_per_team": league_pit_per_team_overall,
        "deltas_batting":  delta_bat,
        "deltas_pitching": delta_pit,
        "team_defense":    team_defense,
        "league_defense":  league_defense,
        "defense_deltas":  defense_deltas,
        "have_defense":    have_defense,
        "roster_summary": diag.get("roster_summary", ""),
        "gaps_results": results,
        "comparables_policy": (
            f"Only contracts with signed_year <= {evaluation_year} are eligible as "
            f"targets or pricing comparables. Pricing is anchored to the "
            f"{market_year} offseason. Targets additionally must have an AAV "
            f"within 30% of total payroll (the single-signing ceiling)."
        ),
        "thin_targets_positions": thin_targets_positions,
    }


def _top_hitters(team_bat_df: pd.DataFrame, n: int = 5) -> list[dict]:
    """Top-n batters by OPS for the team (min 200 PA to filter call-ups)."""
    q = team_bat_df[team_bat_df["PA"].fillna(0) >= 200].copy()
    if q.empty:
        return []
    q = q.sort_values("OPS", ascending=False).head(n)
    return [
        {
            "name": row["Name"],
            "PA":   int(row["PA"]) if pd.notna(row.get("PA")) else 0,
            "HR":   int(row["HR"]) if pd.notna(row.get("HR")) else 0,
            "AVG":  round(float(row.get("AVG", row.get("BA", 0)) or 0), 3),
            "OBP":  round(float(row.get("OBP", 0) or 0), 3),
            "SLG":  round(float(row.get("SLG", 0) or 0), 3),
            "OPS":  round(float(row.get("OPS", 0) or 0), 3),
        }
        for _, row in q.iterrows()
    ]


def _top_pitchers(team_pit_df: pd.DataFrame, n: int = 5) -> list[dict]:
    """Top-n pitchers by ERA (min 30 IP) — mix of starters and relievers."""
    q = team_pit_df[team_pit_df["IP"].fillna(0) >= 30].copy()
    if q.empty:
        return []
    q = q.sort_values("ERA", ascending=True).head(n)
    return [
        {
            "name":  row["Name"],
            "IP":    float(row["IP"]) if pd.notna(row.get("IP")) else 0.0,
            "GS":    int(row["GS"]) if pd.notna(row.get("GS")) else 0,
            "ERA":   round(float(row["ERA"]) if pd.notna(row.get("ERA")) else 0, 2),
            "WHIP":  round(float(row["WHIP"]) if pd.notna(row.get("WHIP")) else 0, 3),
            "K9":    round(float(row.get("SO9", 0) or 0), 1),
            "role":  "starter" if (row.get("GS", 0) or 0) >= 5 else "reliever",
        }
        for _, row in q.iterrows()
    ]


def run_opponent_scouting_simple(opponent_abbr: str = "HOU",
                                 evaluation_year: int = 2024,
                                 progress: ProgressCallback = None) -> dict:
    """Sprint orchestrator for Opponent Scouting.

    Aggregates the opponent's 2024 stats, identifies their top hitters and
    pitchers, and makes ONE gpt-4o call that returns a structured scouting
    report (threats, exploitable weaknesses, pitching strategy, hitting approach).
    No contract data involved — this tab is purely about on-field profile.
    """
    def _tick(label: str) -> None:
        if progress is not None:
            progress(label)

    if opponent_abbr not in TEAM_ABBR_TO_BREF:
        raise ValueError(f"Unknown team abbreviation: {opponent_abbr}")
    bref_team = TEAM_ABBR_TO_BREF[opponent_abbr]
    t0 = time.time()

    _tick(f"Loading {evaluation_year} batting and pitching CSVs")
    batting  = pd.read_csv(DATA_RAW / f"batting_{evaluation_year}.csv",  encoding="utf-8")
    pitching = pd.read_csv(DATA_RAW / f"pitching_{evaluation_year}.csv", encoding="utf-8")

    _tick(f"Aggregating {opponent_abbr}'s offense + pitching vs the rest of MLB")
    team_bat_df = _filter_team(batting,  bref_team)
    team_pit_df = _filter_team(pitching, bref_team)

    team_bat   = aggregate_batting(team_bat_df)
    team_pit   = aggregate_pitching(team_pit_df)
    league_bat = aggregate_batting(batting)
    league_pit = aggregate_pitching(pitching)
    league_bat_per_team = {
        k: (v / 30 if isinstance(v, (int, float)) and k.endswith("_total") else v)
        for k, v in league_bat.items()
    }
    league_pit_per_team_overall = {
        k: (v / 30 if isinstance(v, (int, float)) and k in {"IP", "n"} else v)
        for k, v in league_pit.get("overall", {}).items()
    }
    delta_bat = _compute_delta(team_bat, league_bat_per_team)
    delta_pit = _compute_delta(team_pit.get("overall", {}), league_pit_per_team_overall)

    top_hitters  = _top_hitters(team_bat_df, n=5)
    top_pitchers = _top_pitchers(team_pit_df, n=5)

    _tick(f"Asking GPT-4o to scout {opponent_abbr}'s strengths, weaknesses, and how to attack them")
    report = scout_opponent_llm(
        opponent_abbr,
        team_bat, team_pit.get("overall", {}),
        league_bat_per_team, league_pit_per_team_overall,
        delta_bat, delta_pit,
        top_hitters, top_pitchers,
    )

    return {
        "opponent": opponent_abbr,
        "year": evaluation_year,
        "elapsed_seconds": round(time.time() - t0, 2),
        "team_batting":  team_bat,
        "team_pitching": team_pit,
        "league_batting_per_team":  league_bat_per_team,
        "league_pitching_per_team": league_pit_per_team_overall,
        "deltas_batting":  delta_bat,
        "deltas_pitching": delta_pit,
        "top_hitters":  top_hitters,
        "top_pitchers": top_pitchers,
        "narrative": report.get("narrative", ""),
        "threats":    report.get("top_threats", []),
        "weaknesses": report.get("exploitable_weaknesses", []),
        "pitching_strategy": report.get("pitching_strategy", ""),
        "hitting_approach":  report.get("hitting_approach", ""),
    }


if __name__ == "__main__":
    # Quick smoke test from the CLI
    import sys
    out = run_gap_filler_simple("SEA", 165_000_000)
    json.dump(out, sys.stdout, indent=2, default=str)
    print()

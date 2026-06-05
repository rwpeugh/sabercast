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
import re
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
# Pitcher handedness lookup — Roster Builder uses this for platoon-aware lineup
# ordering when a probable starter is selected. Data sourced from MLB Stats API
# via pipelines/01d_pull_handedness.py and stored at data/raw/player_handedness.csv.
# ──────────────────────────────────────────────────────────────────────────────
_HANDEDNESS_CACHE: dict[str, str] | None = None


def _load_handedness() -> dict[str, str]:
    """Return a {ascii-folded-lowered-name: throws-code} lookup. Cached.

    ``throws-code`` is one of "R", "L", "S" (Pat Venditte, the lone switch
    pitcher in the dataset). Missing handedness data is silently ignored —
    callers fall back to None and let the LLM reason from the stat line alone.
    """
    global _HANDEDNESS_CACHE
    if _HANDEDNESS_CACHE is not None:
        return _HANDEDNESS_CACHE
    p = Path(__file__).resolve().parent.parent / "data" / "raw" / "player_handedness.csv"
    if not p.exists():
        _HANDEDNESS_CACHE = {}
        return _HANDEDNESS_CACHE
    df = pd.read_csv(p, encoding="utf-8")
    lookup: dict[str, str] = {}
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        throws = str(row.get("throws", "")).strip()
        if not name or not throws:
            continue
        key = _ascii_fold(name).lower()
        lookup[key] = throws
    _HANDEDNESS_CACHE = lookup
    return lookup


def _lookup_pitcher_hand(name: str) -> str | None:
    """Look up a pitcher's throwing hand. Returns "R" / "L" / "S" or None."""
    if not name:
        return None
    key = _ascii_fold(str(name)).lower()
    return _load_handedness().get(key)

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


# Tier thresholds for the bargain / medium / premium recommendation slots.
# Defined as multiples of the single-signing ceiling.
#   bargain: 0 < AAV <= TIER_BARGAIN_RATIO * ceiling        ("well under budget")
#   medium:  TIER_BARGAIN_RATIO * ceiling < AAV <= ceiling  ("at budget")
#   premium: ceiling < AAV <= TIER_PREMIUM_RATIO * ceiling  ("above budget")
#
# Premium also has an absolute cap (max of the multiplicative cap or
# TIER_PREMIUM_MIN_CAP) so we still surface premium candidates when the
# single-signing ceiling is near zero (over-committed teams). Without this
# floor, over-committed teams would see no premium tier at all.
TIER_BARGAIN_RATIO     = 0.50         # bargain = at most half the ceiling
TIER_PREMIUM_RATIO     = 5.0          # premium upper bound = 5x ceiling
TIER_PREMIUM_MIN_CAP   = 30_000_000   # ...but always cover up to $30M
TIER_ORDER             = ("bargain", "medium", "premium")


def _classify_target_tier(aav: float | None,
                            single_signing_ceiling: float) -> str:
    """Bucket a candidate's AAV into ``bargain`` / ``medium`` / ``premium``.

    The ceiling is the GM's already-computed single-signing ceiling
    (30% of available room after committed payroll). For over-committed
    teams (ceiling <= 0), every candidate is considered "premium" since
    nothing fits under-budget.
    """
    if aav is None or aav <= 0:
        return "premium"
    if single_signing_ceiling <= 0:
        return "premium"
    if aav <= TIER_BARGAIN_RATIO * single_signing_ceiling:
        return "bargain"
    if aav <= single_signing_ceiling:
        return "medium"
    return "premium"


def _pick_top_per_tier(targets: list[dict],
                        single_signing_ceiling: float,
                        max_per_tier: int = 1) -> list[dict]:
    """Pick the best ``max_per_tier`` candidates from each AAV tier by
    composite improvement score. Returns them in bargain→medium→premium order.

    Over-committed special case: when the ceiling is zero, bargain and medium
    are empty by construction. In that case we fall back to returning the
    top-3 premium candidates so the user still gets recommendations (with the
    "over-committed" warning surfaced via ``over_committed`` upstream).
    """
    for t in targets:
        t["tier"] = _classify_target_tier(t.get("aav"), single_signing_ceiling)

    def _rank_key(t: dict) -> tuple[float, float]:
        comp = t.get("composite_score")
        comp = -1e9 if comp is None else float(comp)
        tiebreak = t.get("semantic_score") or t.get("fit_score") or 0.0
        return (comp, float(tiebreak))

    ordered: list[dict] = []
    for tier in TIER_ORDER:
        tier_pool = [t for t in targets if t.get("tier") == tier]
        tier_pool.sort(key=_rank_key, reverse=True)
        ordered.extend(tier_pool[:max_per_tier])

    # Over-committed: ceiling is 0 -> bargain/medium are empty -> top up to 3
    # from premium so the user sees something actionable.
    if single_signing_ceiling <= 0 and len(ordered) < 3:
        premium_pool = [t for t in targets if t.get("tier") == "premium"]
        premium_pool.sort(key=_rank_key, reverse=True)
        seen_names = {t.get("player_name") for t in ordered}
        for t in premium_pool:
            if t.get("player_name") in seen_names:
                continue
            ordered.append(t)
            if len(ordered) >= 3:
                break
    return ordered


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
def _filter_team(df: pd.DataFrame, bref_team: str,
                  league: str | None = None) -> pd.DataFrame:
    """Rows where Tm column contains the team city (catches mid-season trades).

    Three MLB cities host two teams each — Chicago (CHC/CWS), Los Angeles
    (LAD/LAA), New York (NYM/NYY). Filtering on city alone returns BOTH
    teams' players (e.g., a CHC query would incorrectly include Andrew
    Vaughn from CWS). When `league` is provided ("AL" or "NL"), we also
    filter on the `Lev` column to disambiguate. For non-ambiguous cities
    the league filter is a no-op but harmless.

    Inter-league mid-season trades (Lev='Maj-AL,Maj-NL') are matched for
    BOTH leagues since the player did genuinely appear in both. Their
    stats are split across the original team rows; downstream aggregates
    may slightly over-count these players when summing across both
    leagues. There were 6 such players in 2024; we accept this as a small
    edge-case caveat rather than complicating the schema further.
    """
    if "Tm" not in df.columns:
        return df.iloc[0:0]
    rows = df[df["Tm"].astype(str).str.contains(bref_team, case=False, na=False)]
    if league and "Lev" in df.columns:
        wanted = f"Maj-{league.upper()}"
        rows = rows[rows["Lev"].astype(str).str.contains(wanted, case=False, na=False)]
    return rows.copy()


# Each MLB team's league. Used by _filter_team to disambiguate shared-city
# franchise pairs (Chicago, Los Angeles, New York).
TEAM_ABBR_TO_LEAGUE: dict[str, str] = {
    "ARI": "NL", "ATL": "NL", "BAL": "AL", "BOS": "AL",
    "CHC": "NL", "CWS": "AL", "CIN": "NL", "CLE": "AL",
    "COL": "NL", "DET": "AL", "HOU": "AL", "KC":  "AL",
    "LAA": "AL", "LAD": "NL", "MIA": "NL", "MIL": "NL",
    "MIN": "AL", "NYM": "NL", "NYY": "AL", "OAK": "AL",
    "PHI": "NL", "PIT": "NL", "SD":  "NL", "SEA": "AL",
    "SF":  "NL", "STL": "NL", "TB":  "AL", "TEX": "AL",
    "TOR": "AL", "WSH": "NL",
}


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
# Position-incumbent identification
#
# For each gap position the Gap Filler flags, we want to compare candidate FAs
# against the team's CURRENT incumbent at that position — not against league
# average in the abstract. This gives the LLM the material to surface explicit
# trade-offs ("Player X is +0.080 OPS but -5 OAA vs your current 2B Polanco").
#
# Identification rules per position type:
#   * Fielders (1B/2B/3B/SS/LF/CF/RF) — Statcast OAA's primary_pos_formatted.
#     If multiple players are listed at the position for one team, pick the one
#     with the highest absolute fielding_runs_prevented (proxy for playing time).
#   * Catcher (C) — catcher_defense rows joined to the team via sprint_speed.
#   * Starting Pitcher (SP) — top of the team's pitching slice by GS.
#   * Relief Pitcher (RP) — most appearances (G) with GS<3 in the team's slice.
#   * DH — no clean primary-position assignment in the source data. We skip it
#     and let the matcher fall back to league-baseline scoring.
# ──────────────────────────────────────────────────────────────────────────────

def _lookup_candidate_oaa(name: str, position: str,
                          oaa_df: pd.DataFrame | None) -> int | None:
    """Look up a hitter's 2024 OAA at the gap position. Returns None if the
    player isn't in the OAA file at that position (didn't play it enough)."""
    if oaa_df is None or oaa_df.empty or not name:
        return None
    folded = _ascii_fold(name).lower()
    rows = oaa_df[
        oaa_df["last_name, first_name"].astype(str).map(
            lambda n: _ascii_fold(_oaa_name_to_human(str(n))).lower()
        ) == folded
    ]
    rows = rows[rows["primary_pos_formatted"].astype(str) == position]
    if rows.empty:
        return None
    val = pd.to_numeric(rows["outs_above_average"], errors="coerce").iloc[0]
    return int(val) if pd.notna(val) else None


def _lookup_candidate_catcher_pop(name: str,
                                   catcher_df: pd.DataFrame | None) -> float | None:
    """Look up a catcher's 2024 pop time to 2B. Lower = better (faster arm)."""
    if catcher_df is None or catcher_df.empty or not name:
        return None
    folded = _ascii_fold(name).lower()
    rows = catcher_df[
        catcher_df["entity_name"].astype(str).map(
            lambda n: _ascii_fold(_oaa_name_to_human(str(n))).lower()
        ) == folded
    ]
    if rows.empty:
        return None
    val = pd.to_numeric(rows["pop_2b_sba"], errors="coerce").iloc[0]
    return round(float(val), 3) if pd.notna(val) else None


def compute_committed_payroll(team_abbr: str, contracts: pd.DataFrame,
                              evaluation_year: int) -> dict:
    """Estimate the team's committed payroll for the upcoming season
    (``market_year = evaluation_year + 1``).

    Source preference (best -> worst):
      1. ``data/raw/team_payrolls_<market_year>.csv`` -- Spotrac's authoritative
         per-team total, pulled by ``pipelines/02d_pull_team_payrolls.py``.
         Includes every player on the active roster + retained payroll. This
         is the correct number to use whenever it's available.
      2. Sum of contracts.csv rows for the team where the contract was signed
         on or before ``evaluation_year`` AND is still active in ``market_year``.
         Used as a fallback when the team_payrolls CSV is missing. Skews to
         high-AAV signings and under-counts reality by ~50-60% because the
         contracts dataset misses league-minimum / pre-arb players.

    Returns a dict carrying:
      * ``committed_total``    -- USD total
      * ``committed_source``   -- "spotrac_team_payroll" | "contracts_sum"
      * ``n_contracts``        -- (only set for contracts_sum) count that qualified
      * ``breakdown``          -- (only set for contracts_sum) per-contract list
                                  for UI transparency
      * ``market_year``        -- the year being projected INTO
      * ``coverage_caveat``    -- one-line note appropriate to the source

    No-look-ahead. The contracts-sum path filters ``signed_year <= evaluation_year``
    so historical backtests don't leak future signings into the committed payroll.
    The team_payrolls path is by definition current-year; for historical
    evaluation_years (running a 2022 backtest in 2026), prefer the contracts-sum
    path or pull a vintage team_payrolls_<year>.csv via the pipeline.
    """
    market_year = evaluation_year + 1

    # ── Source 1: Spotrac team-payroll total (preferred) ─────────────────
    team_payrolls_path = DATA_RAW / f"team_payrolls_{market_year}.csv"
    if team_payrolls_path.exists():
        try:
            tp_df = pd.read_csv(team_payrolls_path, encoding="utf-8")
            row = tp_df[tp_df["team_abbr"].astype(str) == team_abbr]
            if not row.empty:
                committed = float(row.iloc[0]["committed_total"])
                if committed > 0:
                    snap_date = str(row.iloc[0].get("snapshot_date", ""))
                    return {
                        "committed_total":   committed,
                        "committed_source":  "spotrac_team_payroll",
                        "n_contracts":       None,
                        "breakdown":         [],
                        "market_year":       market_year,
                        "coverage_caveat":   (
                            f"Sourced from Spotrac's {team_abbr} team payroll page "
                            f"({snap_date}). Includes the full active roster plus "
                            f"retained payroll. This is the authoritative committed "
                            f"figure -- no estimation required."
                        ),
                    }
        except Exception:                                       # noqa: BLE001
            pass  # fall through to contracts-sum

    # ── Source 2: sum contracts.csv (fallback) ──────────────────────────
    if contracts is None or contracts.empty:
        return {
            "committed_total":  0.0,
            "committed_source": "contracts_sum",
            "n_contracts":      0,
            "breakdown":        [],
            "market_year":      market_year,
            "coverage_caveat":  "No contracts dataset available.",
        }
    team_rows = contracts[contracts["team"].astype(str) == team_abbr].copy()
    if team_rows.empty:
        return {
            "committed_total":  0.0,
            "committed_source": "contracts_sum",
            "n_contracts":      0,
            "breakdown":        [],
            "market_year":      market_year,
            "coverage_caveat":  ("No contracts on file for this team in our "
                                  "dataset. Real committed payroll is non-zero. "
                                  "Run pipelines/02d_pull_team_payrolls.py for "
                                  "the authoritative Spotrac figure."),
        }

    team_rows["signed_year"] = pd.to_numeric(team_rows["signed_year"], errors="coerce")
    team_rows["years"]       = pd.to_numeric(team_rows["years"],       errors="coerce")
    team_rows["aav"]         = pd.to_numeric(team_rows["aav"],         errors="coerce")

    # No-look-ahead: contract must have been signed on or before evaluation_year.
    # Active-in-market_year: contract's final year (signed_year + years - 1) >=
    # market_year, equivalently signed_year + years > market_year.
    mask = (
        (team_rows["signed_year"].fillna(9999) <= evaluation_year)
        & ((team_rows["signed_year"].fillna(0) + team_rows["years"].fillna(0))
            > market_year)
        & team_rows["aav"].notna()
    )
    active = team_rows[mask].copy()
    if active.empty:
        return {
            "committed_total":  0.0,
            "committed_source": "contracts_sum",
            "n_contracts":      0,
            "breakdown":        [],
            "market_year":      market_year,
            "coverage_caveat":  (f"No no-look-ahead contracts on file for "
                                  f"{team_abbr} that extend into {market_year}. "
                                  f"Real committed payroll is non-zero. Run "
                                  f"pipelines/02d_pull_team_payrolls.py for the "
                                  f"authoritative Spotrac figure."),
        }

    active = active.sort_values("aav", ascending=False)
    committed_total = float(active["aav"].sum())
    breakdown = [
        {
            "player_name": str(r["player_name"]),
            "position":    str(r.get("position", "")),
            "aav":         int(r["aav"]) if pd.notna(r["aav"]) else None,
            "signed_year": int(r["signed_year"]) if pd.notna(r["signed_year"]) else None,
            "years":       int(r["years"])       if pd.notna(r["years"])       else None,
        }
        for _, r in active.iterrows()
    ]
    return {
        "committed_total":  committed_total,
        "committed_source": "contracts_sum",
        "n_contracts":      len(active),
        "breakdown":        breakdown,
        "market_year":      market_year,
        "coverage_caveat":  (
            f"Estimate from {len(active)} tracked contracts. Likely UNDER-COUNTS "
            f"the team's true commitments — our contracts dataset excludes "
            f"league-minimum, pre-arb, and many arb-eligible players. Run "
            f"pipelines/02d_pull_team_payrolls.py for the authoritative figure."
        ),
    }


def _compute_improvement_deltas(target: dict, incumbent: dict | None,
                                 gap: dict,
                                 oaa_df: pd.DataFrame | None = None,
                                 catcher_df: pd.DataFrame | None = None) -> dict:
    """Compute how much this target improves on the team's current incumbent
    at the gap position.

    Returns dict carrying:
      * vs_incumbent_offense  : OPS delta (positive = better) | None
      * vs_incumbent_defense  : OAA delta (or -pop delta for C) | None
      * vs_incumbent_pitching : dict of ERA/WHIP/K9 deltas for SP/RP | None
      * composite_score       : normalized + gap-weighted scalar | None
      * breakdown             : 1-line human-readable summary
      * incumbent_name        : for cross-reference in UI

    Normalization (so offense and defense are roughly comparable):
      * OPS delta divided by 0.100  (a 100-pt OPS jump = 1.0 unit)
      * OAA delta divided by 5      (a 5-OAA jump = 1.0 unit)
      * Pop-time delta divided by 0.05 seconds (50 ms = 1.0 unit, *negated*)
      * ERA delta divided by 1.00   (1.00 ERA improvement = 1.0 unit)
      * WHIP delta divided by 0.100 (100-pt WHIP improvement = 1.0 unit)
      * K9 delta divided by 2.0     (2.0 K/9 improvement = 1.0 unit)

    Weighting:
      * Hitter+fielder gaps  -> use gap_components.offense / defense ratio
      * Catcher              -> use gap_components.offense / defense ratio,
                                where defense is pop-time
      * SP / RP gaps         -> ERA 0.50 + WHIP 0.30 + K9 0.20 (fixed mix)
      * DH (incumbent=None)  -> composite=None, fall back to absolute fit
    """
    if not incumbent:
        return {
            "vs_incumbent_offense":  None,
            "vs_incumbent_defense":  None,
            "vs_incumbent_pitching": None,
            "composite_score":       None,
            "breakdown":             ("Incumbent not identifiable for this "
                                       "position — ranking falls back to "
                                       "absolute stat fit."),
            "incumbent_name":        None,
        }

    position = gap.get("position", "")
    inc_name = incumbent.get("primary_player", "")

    gap_components = gap.get("gap_components") or {}
    off_raw = float(gap_components.get("offense", 50) or 0)
    def_raw = float(gap_components.get("defense", 50) or 0)
    total   = off_raw + def_raw
    off_w   = off_raw / total if total > 0 else 0.5
    def_w   = def_raw / total if total > 0 else 0.5

    cand_stats = target.get("stats_2024") or {}
    cand_name  = target.get("player_name", "")

    # ── Pitcher gap ─────────────────────────────────────────────────────────
    if position in {"SP", "RP"} and incumbent.get("pitching"):
        if cand_stats.get("role") != "pitcher":
            return {
                "vs_incumbent_offense": None, "vs_incumbent_defense": None,
                "vs_incumbent_pitching": None, "composite_score": None,
                "breakdown": "Candidate has no pitcher stats — cannot compare.",
                "incumbent_name": inc_name,
            }
        inc_pit = incumbent["pitching"]
        era_d  = round(inc_pit.get("ERA", 0) - (cand_stats.get("ERA") or 0), 2)
        whip_d = round(inc_pit.get("WHIP", 0) - (cand_stats.get("WHIP") or 0), 3)
        k9_d   = round((cand_stats.get("K9") or 0) - inc_pit.get("K9", 0), 1)
        composite = (0.50 * (era_d / 1.00)
                      + 0.30 * (whip_d / 0.100)
                      + 0.20 * (k9_d / 2.0))
        pitch_deltas = {"ERA_delta": era_d, "WHIP_delta": whip_d, "K9_delta": k9_d}
        verb_era  = "better" if era_d  > 0 else "worse" if era_d  < 0 else "same"
        verb_whip = "better" if whip_d > 0 else "worse" if whip_d < 0 else "same"
        breakdown = (f"vs {inc_name}: {abs(era_d):.2f} ERA {verb_era}, "
                     f"{abs(whip_d):.3f} WHIP {verb_whip}, "
                     f"{k9_d:+.1f} K/9")
        return {
            "vs_incumbent_offense":  None,
            "vs_incumbent_defense":  None,
            "vs_incumbent_pitching": pitch_deltas,
            "composite_score":       round(composite, 2),
            "breakdown":             breakdown,
            "incumbent_name":        inc_name,
        }

    # ── Catcher gap ─────────────────────────────────────────────────────────
    if position == "C":
        # Offense delta (against incumbent catcher's OPS)
        offense_delta = None
        offense_norm  = 0.0
        if (incumbent.get("offense") and cand_stats.get("role") == "hitter"):
            inc_ops  = incumbent["offense"].get("OPS", 0)
            cand_ops = cand_stats.get("OPS", 0) or 0
            offense_delta = round(cand_ops - inc_ops, 3)
            offense_norm  = offense_delta / 0.100
        # Defense delta — pop time (lower = better; flip sign)
        defense_delta = None
        defense_norm  = 0.0
        if incumbent.get("defense") and incumbent["defense"].get("pop_2b_sba"):
            inc_pop  = incumbent["defense"]["pop_2b_sba"]
            cand_pop = _lookup_candidate_catcher_pop(cand_name, catcher_df)
            if cand_pop is not None:
                defense_delta = round(inc_pop - cand_pop, 3)   # positive = candidate is faster
                defense_norm  = defense_delta / 0.05
        composite = off_w * offense_norm + def_w * defense_norm
        bits = []
        if offense_delta is not None:
            bits.append(f"{offense_delta:+.3f} OPS")
        if defense_delta is not None:
            bits.append(f"{defense_delta:+.3f}s pop time")
        breakdown = (f"vs {inc_name}: " + ", ".join(bits)) if bits else (
            f"vs {inc_name}: limited stat overlap to compare.")
        return {
            "vs_incumbent_offense":  offense_delta,
            "vs_incumbent_defense":  defense_delta,
            "vs_incumbent_pitching": None,
            "composite_score":       round(composite, 2),
            "breakdown":             breakdown,
            "incumbent_name":        inc_name,
        }

    # ── Hitter + fielder gap (1B/2B/3B/SS/LF/CF/RF) ─────────────────────────
    if position in _FIELDER_POSITIONS:
        offense_delta = None
        offense_norm  = 0.0
        if (incumbent.get("offense") and cand_stats.get("role") == "hitter"):
            inc_ops  = incumbent["offense"].get("OPS", 0)
            cand_ops = cand_stats.get("OPS", 0) or 0
            offense_delta = round(cand_ops - inc_ops, 3)
            offense_norm  = offense_delta / 0.100
        defense_delta = None
        defense_norm  = 0.0
        if incumbent.get("defense"):
            inc_oaa  = incumbent["defense"].get("oaa", 0) or 0
            cand_oaa = _lookup_candidate_oaa(cand_name, position, oaa_df)
            if cand_oaa is not None:
                defense_delta = int(cand_oaa - inc_oaa)
                defense_norm  = defense_delta / 5.0
        composite = off_w * offense_norm + def_w * defense_norm
        bits = []
        if offense_delta is not None:
            bits.append(f"{offense_delta:+.3f} OPS")
        if defense_delta is not None:
            bits.append(f"{defense_delta:+d} OAA")
        breakdown = (f"vs {inc_name}: " + ", ".join(bits)) if bits else (
            f"vs {inc_name}: limited stat overlap to compare.")
        return {
            "vs_incumbent_offense":  offense_delta,
            "vs_incumbent_defense":  defense_delta,
            "vs_incumbent_pitching": None,
            "composite_score":       round(composite, 2),
            "breakdown":             breakdown,
            "incumbent_name":        inc_name,
        }

    # Position not handled (shouldn't happen — DH already exited above)
    return {
        "vs_incumbent_offense":  None,
        "vs_incumbent_defense":  None,
        "vs_incumbent_pitching": None,
        "composite_score":       None,
        "breakdown":             f"No comparison logic for position {position}.",
        "incumbent_name":        inc_name,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Hallucination defense for the forecast LLM rationale (task #63)
#
# Three layered defenses against the model inventing delta numbers:
#
#   1. ``_sanitize_incumbent_for_payload(incumbent, improvement_deltas)`` —
#      strips dimensions of the incumbent profile that don't have a
#      corresponding delta. Removes the raw material the LLM uses to "compute"
#      deltas from its training-data priors for famous players.
#
#   2. ``_rationale_hallucinations(rationale, improvement_deltas)`` — regex
#      scan for number+unit pairs ("X OAA", "X.XXX OPS", "X.XX ERA") that
#      reference dimensions absent from the deltas dict, OR whose numeric
#      values disagree with the known delta values by more than rounding
#      tolerance. Returns a list of offending phrases (empty = clean).
#
#   3. ``_programmatic_rationale(target, incumbent, improvement_deltas,
#      gap)`` — deterministic, hallucination-free rationale built from the
#      known deltas via template substitution. Used as a hard fallback when
#      the LLM rationale fails validation.
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_incumbent_for_payload(incumbent: dict | None,
                                     improvement_deltas: dict | None) -> dict | None:
    """Strip incumbent dimensions whose corresponding deltas aren't in the
    deltas dict. The LLM can't compute a fake defense delta if it can't see
    the incumbent's defensive stats in the first place.
    """
    if not incumbent or not improvement_deltas:
        return incumbent
    sanitized = {k: v for k, v in incumbent.items()
                  if k not in {"offense", "defense", "pitching"}}
    if "offense" in improvement_deltas:
        sanitized["offense"] = incumbent.get("offense")
    if "defense" in improvement_deltas:
        sanitized["defense"] = incumbent.get("defense")
    if "pitching" in improvement_deltas:
        sanitized["pitching"] = incumbent.get("pitching")
    return sanitized


# Regex patterns -- match common forms the model uses to cite deltas.
# Examples covered:
#   "+0.080 OPS"  ".080 OPS"  "0.080 OPS"  "loses 5 OAA"  "+30 OAA"
#   "0.85 ERA"    ".850 WHIP"  "8.5 K/9"   "1.95s pop"
_NUM = r"[+\-]?\d+(?:\.\d+)?"
_UNIT_PATTERNS = {
    "offense":  re.compile(rf"({_NUM})\s*OPS\b", re.IGNORECASE),
    "defense_oaa": re.compile(rf"({_NUM})\s*OAA\b", re.IGNORECASE),
    "defense_pop": re.compile(rf"({_NUM})\s*s\s*pop\b", re.IGNORECASE),
    "era":      re.compile(rf"({_NUM})\s*ERA\b", re.IGNORECASE),
    "whip":     re.compile(rf"({_NUM})\s*WHIP\b", re.IGNORECASE),
    "k9":       re.compile(rf"({_NUM})\s*K/9\b", re.IGNORECASE),
}


def _rationale_hallucinations(rationale: str,
                                improvement_deltas: dict | None) -> list[str]:
    """Return a list of hallucinated phrases in the rationale (empty = clean).

    A phrase is considered hallucinated if it cites a stat dimension not
    present in the deltas dict, OR if it cites a numeric value that doesn't
    match the known delta within rounding tolerance.
    """
    if not rationale:
        return []
    if not improvement_deltas:
        # No deltas at all -> any "X OAA" / "X OPS" / etc reference is a hallucination
        improvement_deltas = {}

    has_offense  = "offense"  in improvement_deltas
    has_defense  = "defense"  in improvement_deltas
    has_pitching = "pitching" in improvement_deltas

    pitching = improvement_deltas.get("pitching") or {}
    known: dict[str, float | None] = {
        "offense":     improvement_deltas.get("offense") if has_offense else None,
        "defense_oaa": improvement_deltas.get("defense") if has_defense else None,
        "defense_pop": improvement_deltas.get("defense") if has_defense else None,
        "era":         pitching.get("ERA_delta")  if has_pitching else None,
        "whip":        pitching.get("WHIP_delta") if has_pitching else None,
        "k9":          pitching.get("K9_delta")   if has_pitching else None,
    }

    issues: list[str] = []
    for key, pattern in _UNIT_PATTERNS.items():
        for m in pattern.finditer(rationale):
            num_str  = m.group(1)
            try:
                cited = float(num_str)
            except ValueError:
                continue
            phrase = m.group(0)
            if known.get(key) is None:
                # This dimension simply isn't in the deltas -> hallucination
                issues.append(phrase)
                continue
            # Both present. We accept if either the signed value OR the
            # unsigned magnitude matches the actual delta within tolerance.
            # That charitable rule lets the LLM write "loses 0.089 OPS" when
            # actual=-0.089 without being flagged for a missing sign. Real
            # number-fabrications (the cited magnitude doesn't match at all)
            # are still caught.
            actual = float(known[key])
            tol = 0.01 if key in {"offense", "whip"} else (
                  0.02 if key in {"era", "defense_pop"} else 1.0)
            signed_match    = abs(cited - actual) <= tol
            magnitude_match = abs(abs(cited) - abs(actual)) <= tol
            if not (signed_match or magnitude_match):
                issues.append(f"{phrase} (actual {actual:+.3f})")
    return issues


def _programmatic_rationale(target: dict, incumbent: dict | None,
                             improvement_deltas: dict | None,
                             gap: dict | None) -> str:
    """Build a deterministic hallucination-free rationale from the deltas.

    Used as a hard fallback when the LLM's rationale fails validation, and
    also as the rationale the LLM is shown as a "ground-truth" template.
    """
    if not incumbent or not improvement_deltas:
        return ("Recommendation based on stat-fit ranking — no incumbent "
                "baseline available for explicit trade-off comparison.")
    inc_name = incumbent.get("primary_player", "the incumbent")
    bits: list[str] = []
    off = improvement_deltas.get("offense")
    if off is not None:
        verb = "Adds" if off >= 0 else "Gives back"
        bits.append(f"{verb} {abs(off):.3f} OPS")
    defense = improvement_deltas.get("defense")
    if defense is not None and (gap or {}).get("position") == "C":
        # Catcher pop time: positive delta = faster (better)
        verb = "improves" if defense >= 0 else "gives back"
        bits.append(f"{verb} pop time by {abs(defense):.3f}s")
    elif defense is not None:
        verb = "gains" if defense >= 0 else "loses"
        bits.append(f"{verb} {abs(int(defense))} OAA")
    pitching = improvement_deltas.get("pitching") or {}
    if "ERA_delta" in pitching:
        era_d = pitching["ERA_delta"]
        verb = "drops" if era_d >= 0 else "adds"
        bits.append(f"{verb} {abs(era_d):.2f} ERA")
    if "WHIP_delta" in pitching:
        whip_d = pitching["WHIP_delta"]
        verb = "drops" if whip_d >= 0 else "adds"
        bits.append(f"{verb} {abs(whip_d):.3f} WHIP")
    if "K9_delta" in pitching:
        k9_d = pitching["K9_delta"]
        bits.append(f"{k9_d:+.1f} K/9")

    base = f"vs {inc_name}: " + ", ".join(bits) if bits else f"vs {inc_name}."
    # Append a one-clause gap-priority interpretation
    off_w = (gap or {}).get("gap_components", {}).get("offense") if gap else None
    def_w = (gap or {}).get("gap_components", {}).get("defense") if gap else None
    comp  = improvement_deltas.get("composite")
    tail = ""
    if comp is not None and off_w is not None and def_w is not None:
        if off_w > def_w:
            priority = "offense-first"
        elif def_w > off_w:
            priority = "defense-first"
        else:
            priority = "balanced"
        verdict = "net upgrade" if comp >= 0 else "net downgrade"
        tail = f" — {verdict} given the team's {priority} gap."
    return base + tail


def _lookup_hitter_offense_row(name: str, batting: pd.DataFrame) -> dict | None:
    """Look up one hitter's offensive line by name (accent-tolerant)."""
    if batting is None or batting.empty or not name:
        return None
    folded = _ascii_fold(name).lower()
    match = batting[
        batting["Name"].astype(str).map(lambda n: _ascii_fold(str(n)).lower()) == folded
    ]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "PA":  int(row.get("PA",  0)) if pd.notna(row.get("PA"))  else 0,
        "HR":  int(row.get("HR",  0)) if pd.notna(row.get("HR"))  else 0,
        "AVG": round(float(row.get("AVG", row.get("BA", 0)) or 0), 3),
        "OBP": round(float(row.get("OBP", 0) or 0), 3),
        "SLG": round(float(row.get("SLG", 0) or 0), 3),
        "OPS": round(float(row.get("OPS", 0) or 0), 3),
    }


def _oaa_name_to_human(oaa_name: str) -> str:
    """Statcast OAA uses 'Last, First'. Flip to 'First Last' for join keys."""
    if not isinstance(oaa_name, str) or "," not in oaa_name:
        return str(oaa_name).strip()
    last, first = [p.strip() for p in oaa_name.split(",", 1)]
    return f"{first} {last}"


_FIELDER_POSITIONS = {"1B", "2B", "3B", "SS", "LF", "CF", "RF"}
_NICKNAME_BY_ABBR = {abbr: nick for nick, abbr in OAA_NICKNAME_TO_ABBR.items()}


def get_position_incumbent(team_abbr: str, position: str,
                            batting: pd.DataFrame, pitching: pd.DataFrame,
                            oaa_df: pd.DataFrame | None = None,
                            catcher_df: pd.DataFrame | None = None,
                            sprint_df: pd.DataFrame | None = None) -> dict | None:
    """Identify the team's current incumbent(s) at one gap position with their
    offensive + defensive line. Returns ``None`` if the position has no clean
    primary assignment in the source data (notably DH).

    Output schema (only the keys relevant to the position type are populated):
      {
        "position":         "2B",
        "primary_player":   "Jorge Polanco",
        "secondary_players": ["Dylan Moore"],          # may be empty
        "offense": {"PA": int, "OPS": float, "OBP": float,
                    "SLG": float, "AVG": float, "HR": int} | None,
        "defense": {"oaa": int, "frp": int, "league_avg_oaa": float,
                    "delta_vs_league": float,
                    "pop_2b_sba": float | None}        | None,
        "pitching": {"IP": float, "GS": int, "ERA": float, "WHIP": float,
                     "K9": float, "BB9": float, "HR9": float} | None,
      }
    """
    if position == "DH":
        return None

    # ── Fielders ─────────────────────────────────────────────────────────────
    if position in _FIELDER_POSITIONS:
        if oaa_df is None or oaa_df.empty:
            return None
        nickname = _NICKNAME_BY_ABBR.get(team_abbr)
        if not nickname:
            return None
        rows = oaa_df[
            (oaa_df["display_team_name"].astype(str) == nickname)
            & (oaa_df["primary_pos_formatted"].astype(str) == position)
        ].copy()
        if rows.empty:
            return None
        # Use |fielding_runs_prevented| as a proxy for playing time -- the
        # regular starter usually has the largest-magnitude FRP.
        rows["_abs_frp"] = pd.to_numeric(
            rows["fielding_runs_prevented"], errors="coerce"
        ).fillna(0).abs()
        rows = rows.sort_values("_abs_frp", ascending=False)
        primary_oaa_name = str(rows.iloc[0]["last_name, first_name"])
        primary_player   = _oaa_name_to_human(primary_oaa_name)
        secondary        = [_oaa_name_to_human(str(n))
                            for n in rows.iloc[1:]["last_name, first_name"].tolist()]

        # Aggregate team OAA at this position (all incumbents combined)
        oaa_sum = int(pd.to_numeric(rows["outs_above_average"], errors="coerce").fillna(0).sum())
        frp_sum = int(pd.to_numeric(rows["fielding_runs_prevented"], errors="coerce").fillna(0).sum())
        # League-average OAA per team at this position
        league_avg_oaa = 0.0
        if oaa_df is not None:
            pos_league = oaa_df[oaa_df["primary_pos_formatted"].astype(str) == position]
            if not pos_league.empty:
                league_avg_oaa = round(
                    float(pd.to_numeric(pos_league["outs_above_average"], errors="coerce")
                          .fillna(0).sum()) / 30.0, 2
                )

        offense = _lookup_hitter_offense_row(primary_player, batting)
        return {
            "position":          position,
            "primary_player":    primary_player,
            "secondary_players": secondary,
            "offense":           offense,
            "defense": {
                "oaa":             oaa_sum,
                "frp":             frp_sum,
                "league_avg_oaa":  league_avg_oaa,
                "delta_vs_league": round(oaa_sum - league_avg_oaa, 2),
                "pop_2b_sba":      None,
            },
            "pitching":          None,
        }

    # ── Catcher ──────────────────────────────────────────────────────────────
    if position == "C":
        if catcher_df is None or catcher_df.empty or sprint_df is None:
            return None
        cat_join = catcher_df.merge(
            sprint_df[["player_id", "team"]],
            left_on="entity_id", right_on="player_id", how="left",
        )
        team_cat = cat_join[cat_join["team"].astype(str) == team_abbr]
        if team_cat.empty:
            return None
        # Pick the catcher with the largest pop_2b_sba_count (most chances → primary)
        team_cat = team_cat.copy()
        team_cat["_chances"] = pd.to_numeric(
            team_cat["pop_2b_sba_count"], errors="coerce"
        ).fillna(0)
        team_cat = team_cat.sort_values("_chances", ascending=False)
        # entity_name in catcher_defense.csv uses "Last, First" — flip to
        # "First Last" so the batting CSV join works.
        primary_player = _oaa_name_to_human(str(team_cat.iloc[0]["entity_name"]))
        secondary = [_oaa_name_to_human(str(n))
                     for n in team_cat.iloc[1:]["entity_name"].tolist()]
        pop_2b = pd.to_numeric(team_cat["pop_2b_sba"], errors="coerce").dropna()
        offense = _lookup_hitter_offense_row(primary_player, batting)
        return {
            "position":          position,
            "primary_player":    primary_player,
            "secondary_players": secondary,
            "offense":           offense,
            "defense": {
                "oaa":            None,
                "frp":            None,
                "league_avg_oaa": None,
                "delta_vs_league": None,
                "pop_2b_sba":     round(float(pop_2b.mean()), 3) if not pop_2b.empty else None,
            },
            "pitching":          None,
        }

    # ── Starting pitcher ─────────────────────────────────────────────────────
    if position == "SP":
        if pitching is None or pitching.empty:
            return None
        bref_team = TEAM_ABBR_TO_BREF.get(team_abbr)
        team_pit = _filter_team(pitching, bref_team,
                                 league=TEAM_ABBR_TO_LEAGUE.get(team_abbr))
        starters = team_pit[team_pit["GS"].fillna(0) >= 5].copy()
        if starters.empty:
            return None
        starters = starters.sort_values("GS", ascending=False)
        primary_row    = starters.iloc[0]
        primary_player = str(primary_row["Name"]).strip()
        secondary      = [str(n).strip()
                          for n in starters.iloc[1:5]["Name"].tolist()]
        ip = float(primary_row.get("IP", 0) or 0)
        bb = float(primary_row.get("BB", 0) or 0)
        hr = float(primary_row.get("HR", 0) or 0)
        return {
            "position":          position,
            "primary_player":    primary_player,
            "secondary_players": secondary,
            "offense":           None,
            "defense":           None,
            "pitching": {
                "IP":   round(ip, 1),
                "GS":   int(primary_row.get("GS", 0) or 0),
                "ERA":  round(float(primary_row.get("ERA", 0) or 0), 2),
                "WHIP": round(float(primary_row.get("WHIP", 0) or 0), 3),
                "K9":   round(float(primary_row.get("SO9", 0) or 0), 1),
                "BB9":  round((9.0 * bb / ip) if ip > 0 else 0.0, 1),
                "HR9":  round((9.0 * hr / ip) if ip > 0 else 0.0, 2),
            },
        }

    # ── Relief pitcher ───────────────────────────────────────────────────────
    if position == "RP":
        if pitching is None or pitching.empty:
            return None
        bref_team = TEAM_ABBR_TO_BREF.get(team_abbr)
        team_pit = _filter_team(pitching, bref_team,
                                 league=TEAM_ABBR_TO_LEAGUE.get(team_abbr))
        relievers = team_pit[
            (team_pit["GS"].fillna(0) < 3) & (team_pit["G"].fillna(0) >= 20)
        ].copy()
        if relievers.empty:
            return None
        relievers = relievers.sort_values("G", ascending=False)
        primary_row    = relievers.iloc[0]
        primary_player = str(primary_row["Name"]).strip()
        secondary      = [str(n).strip()
                          for n in relievers.iloc[1:5]["Name"].tolist()]
        ip = float(primary_row.get("IP", 0) or 0)
        bb = float(primary_row.get("BB", 0) or 0)
        hr = float(primary_row.get("HR", 0) or 0)
        return {
            "position":          position,
            "primary_player":    primary_player,
            "secondary_players": secondary,
            "offense":           None,
            "defense":           None,
            "pitching": {
                "IP":   round(ip, 1),
                "GS":   int(primary_row.get("GS", 0) or 0),
                "ERA":  round(float(primary_row.get("ERA", 0) or 0), 2),
                "WHIP": round(float(primary_row.get("WHIP", 0) or 0), 3),
                "K9":   round(float(primary_row.get("SO9", 0) or 0), 1),
                "BB9":  round((9.0 * bb / ip) if ip > 0 else 0.0, 1),
                "HR9":  round((9.0 * hr / ip) if ip > 0 else 0.0, 2),
            },
        }

    return None


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
recent statistical line, age, position-matched comparable contracts, AND
(when available) the team's CURRENT incumbent at the gap position along
with this candidate's improvement deltas against that incumbent, forecast
the AAV and years that player would command on a NEW free-agent deal AND
articulate the trade-off in plain English.

This is NOT the player's current contract — it is your forecast of what a new
deal would look like if they hit the open market in the {market_year} offseason
following their {prior_year} regular season.

Return STRICT JSON only, no prose, with this exact schema:

{
  "player_name": "<name as provided>",
  "forecast_aav":   <integer USD>,
  "forecast_years": <integer>,
  "rationale": "<one short phrase, max 25 words, EXPLICITLY citing the trade-off vs the incumbent if incumbent_profile is provided -- e.g. 'Adds 0.080 OPS over Polanco but loses 5 OAA -- net upgrade given the team's offense-first 2B gap.' If incumbent_profile is null, fall back to citing the candidate's stats vs comparables.>"
}

Ground your forecast in the comparables provided. Factor in:
  * Recent production (a player coming off a career-best year commands more)
  * Age (younger players get longer terms; older players get shorter terms at lower AAV)
  * Positional scarcity (catchers and middle infielders earn premiums)
  * The current state of the comparable market at this position
  * The improvement (or regression) over the incumbent across offense and defense

SIGN CONVENTIONS for ``improvement_deltas`` -- READ CAREFULLY:
  * ``offense`` (OPS delta)  -- POSITIVE means candidate is BETTER, NEGATIVE means WORSE
  * ``defense`` (OAA delta)  -- POSITIVE means candidate is BETTER, NEGATIVE means WORSE
  * ``defense`` for catchers (pop-time delta) -- POSITIVE means candidate has a FASTER (better) arm
  * ``pitching.ERA_delta``   -- POSITIVE means candidate is BETTER (lower ERA)
  * ``pitching.WHIP_delta``  -- POSITIVE means candidate is BETTER (lower WHIP)
  * ``pitching.K9_delta``    -- POSITIVE means candidate is BETTER (higher K/9)
  * ``composite``            -- POSITIVE means net upgrade over the incumbent
  * Use the candidate's name with verbs like "gains" / "adds" for POSITIVE deltas,
    and "gives back" / "loses" / "regresses" for NEGATIVE deltas.

CRITICAL RULE -- DO NOT INVENT DELTAS:
  * Only cite a dimension (offense / defense / pitching) that is EXPLICITLY
    present in the ``improvement_deltas`` dict. If a field is absent, do NOT
    mention it -- not even as "loses 1 OAA" or "no change in defense".
  * Do NOT compute deltas yourself from ``incumbent_profile`` stats. The
    ``incumbent_profile`` is shown for context only. If ``improvement_deltas``
    doesn't carry a defense delta, the candidate's defense data simply isn't
    available -- say nothing about defense in that case.

NUMERIC FORMATTING -- ALWAYS write a delta with EITHER an explicit verb that
encodes the sign OR an explicit "+" / "-" prefix. Never write a bare unsigned
number when citing a delta:
  * If ``offense`` = +0.080  -> "Adds 0.080 OPS" or "+0.080 OPS" -- both fine
  * If ``offense`` = -0.089  -> "Loses 0.089 OPS" or "-0.089 OPS" -- never
    write "0.089 OPS" alone, that's ambiguous about direction.
  * Same rule for OAA / pop / ERA / WHIP / K/9. The user must be able to tell
    from your rationale alone whether the candidate is better or worse on
    each cited dimension.

GAP WEIGHTING -- ``gap_components`` (in the position_comparables block, if shown):
  * ``offense`` vs ``defense`` -- whichever is LARGER is the team's bigger
    problem at this position. So an "offense=5, defense=9" gap is DEFENSE-FIRST,
    not offense-first. Reflect that priority in the rationale.

If ``improvement_deltas`` indicates the candidate is worse than the incumbent
in some dimension, SAY SO honestly in the rationale rather than hiding it.
A defensible recommendation acknowledges trade-offs.

Do NOT reference market events after {market_year}."""


def _client() -> OpenAI:
    """Lazy-import key loader so this module can be imported without OPENAI_API_KEY."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.config import get_openai_api_key
    return OpenAI(api_key=get_openai_api_key())


# ──────────────────────────────────────────────────────────────────────────────
# Together AI fine-tuned forecaster routing (added Entry 15 — OpenAI deprecated
# self-serve fine-tuning, so we trained a Llama 3.1 8B Instruct model on Together
# and route the contract forecaster to it when use_finetuned=True. The default
# OpenAI gpt-4o-mini path remains unchanged.)
# ──────────────────────────────────────────────────────────────────────────────
def _get_finetuned_together_model() -> str | None:
    """Return the Together model identifier to use for inference.

    Together's dedicated-endpoint routing is keyed on ``endpoint.name`` (set
    when the endpoint is created), NOT on the raw fine-tuned model id from
    ``model_output_name``. When pipelines/05e is running a deployed-endpoint
    eval it writes the endpoint name to the meta JSON; we prefer that. If no
    endpoint name is present we fall back to the model id (which only works
    for serverless tiers — see BUILD_LOG Entry 15 for the routing story).
    Returns None if the fine-tune did not complete.
    """
    meta_path = PROJECT_ROOT / "data" / "processed" / "finetune_together_meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if meta.get("status") != "completed":
        return None
    return meta.get("endpoint_name") or meta.get("fine_tuned_model")


def _together_client():
    """Lazy import of the together SDK + key loader. Mirrors _client()."""
    import os
    from together import Together
    key = os.environ.get("TOGETHER_API_KEY", "").strip()
    if not key:
        for candidate in (PROJECT_ROOT / "TogetherKey.txt",
                          PROJECT_ROOT.parent / "TogetherKey.txt"):
            if candidate.exists():
                key = candidate.read_text(encoding="utf-8").strip()
                break
    if not key:
        raise RuntimeError(
            "Together API key not found. Set TOGETHER_API_KEY env var or place "
            "the key in TogetherKey.txt in the sabercast/ folder or its parent."
        )
    return Together(api_key=key)


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
                                 market_year: int,
                                 use_finetuned: bool = False,
                                 incumbent: dict | None = None,
                                 improvement_deltas: dict | None = None) -> dict:
    """One forecast call per recommended target.

    Produces a forward-looking forecast of what THIS SPECIFIC PLAYER would
    command on a new free-agent deal in the ``market_year`` offseason — distinct
    from their current contract AAV. The premium flag compares this forecast
    (what it would actually cost to sign them) against the gap-fill estimate
    (what the role appears to be worth at market).

    ``incumbent`` and ``improvement_deltas`` (when provided) let the model
    articulate the trade-off in the rationale -- e.g. "0.080 OPS over Polanco
    but -5 OAA, net upgrade given the team's offense-first 2B gap". This is
    the explicit-trade-off behavior added by task #62.

    When ``use_finetuned=True`` and pipelines/05c_finetune_together.py has
    completed, the call is routed to the Together AI Llama-3.1-8B model
    fine-tuned on Sabercast's 29 contract examples. Otherwise the default
    OpenAI gpt-4o-mini path is used. The user payload structure is identical
    in both cases so the fine-tuned model sees inputs in the exact shape it
    was trained on.
    """
    # Use .replace() instead of .format() — the JSON example inside the prompt
    # contains literal {} characters that would collide with str.format().
    sys_prompt = (
        TARGET_FORECAST_SYSTEM
        .replace("{market_year}", str(market_year))
        .replace("{prior_year}",  str(market_year - 1))
    )
    # Match the user payload built by pipelines/05a_finetune_submit.py so the
    # fine-tuned model sees inputs in the same shape it learned from.
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
        "position_comparables":  comparables,
        "market_year":           market_year,
        # Trade-off framing (task #62): the incumbent profile + per-stat deltas
        # let the model say "+0.080 OPS, -5 OAA vs Polanco" in the rationale.
        # When None, the model falls back to comparables-only reasoning.
        "incumbent_profile":     incumbent,
        "improvement_deltas":    improvement_deltas,
    }

    if use_finetuned:
        ft_model = _get_finetuned_together_model()
        if not ft_model:
            raise RuntimeError(
                "use_finetuned=True but no completed Together fine-tune found. "
                "Run pipelines/05c_finetune_together.py first."
            )
        # Together's chat.completions endpoint is OpenAI-compatible. We drop
        # response_format/seed because not all Together-hosted models support
        # them; the fine-tuned model emits JSON natively from training.
        tg = _together_client()
        resp = tg.chat.completions.create(
            model=ft_model,
            temperature=0,
            max_tokens=512,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": json.dumps(user_payload)},
            ],
        )
        raw = resp.choices[0].message.content or ""
        # Be tolerant of fine-tuned models that occasionally wrap JSON in
        # ```json fences or add a trailing newline.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Salvage the JSON object substring if the model added prose
            start = raw.find("{")
            end   = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start:end + 1])
            raise

    oai = _client()
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
    """Top-k acquisition targets at this position, ranked by statistical fit.

    A *target* differs from a *pricing comparable*: targets are players whose
    on-field production would most improve the team at this gap, subject to a
    single-signing budget ceiling. Pricing comparables (see
    ``_pick_pricing_comparables``) are top-AAV contracts at the position and
    are the LLM's reference points for what such a player would cost.

    The caller dedupes the comparables against the targets so the user always
    sees ``k`` distinct targets + ``k`` distinct comparables per gap.
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
    # Some stars appear multiple times in the contracts data (different signings
    # of the same player). Collapse to one row per distinct player_name, keeping
    # the highest-ranked instance.
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in enriched:
        name = r.get("player_name")
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(r)
        if len(deduped) >= k:
            break
    return deduped


def _pick_pricing_comparables(contracts: pd.DataFrame, batting: pd.DataFrame,
                              pitching: pd.DataFrame, position: str,
                              evaluation_year: int, k: int = 3,
                              exclude_names: set[str] | None = None) -> list[dict]:
    """Top-k contracts at the position by AAV. These are the LLM's pricing anchors.

    Same eligibility filter as ``_pick_targets`` (no look-ahead), but no budget
    ceiling — the very biggest comparable signings are valuable pricing context
    even if they would themselves be unaffordable for a small/mid-market team.

    ``exclude_names`` (typically the names of recommended targets) lets the
    caller suppress overlap with the targets list. With the orchestrator's
    default flow, comparables are picked AFTER targets and exclude them by
    name — so the user sees 3 distinct targets + 3 distinct market benchmarks
    rather than overlapping cards labeled "also target".
    """
    pool = _filter_eligible_pool(contracts, position, evaluation_year)
    if pool.empty:
        return []
    if exclude_names:
        pool = pool[~pool["player_name"].astype(str).isin(exclude_names)]
        if pool.empty:
            return []
    # Sort by AAV desc, then collapse to one row per player (keep highest AAV).
    # Some stars appear in the contracts dataset with multiple separate signings
    # (e.g., Carlos Correa's rescinded SF deal + his eventual MIN deal). For
    # pricing-anchor purposes we want one row per distinct player.
    pool = pool.sort_values("aav", ascending=False)
    pool = pool.drop_duplicates(subset=["player_name"], keep="first").head(k)
    rows = []
    for _, row in pool.iterrows():
        stats = _lookup_player_stats(row["player_name"], batting, pitching, row["position"])
        fit = _compute_fit_score(stats)
        rows.append(_build_target_row(row, stats, fit))
    return rows


def run_gap_filler_simple(team_abbr: str = "SEA",
                          max_budget: float = 165_000_000,
                          evaluation_year: int = 2024,
                          committed_payroll: float | None = None,
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
    bref_team    = TEAM_ABBR_TO_BREF[team_abbr]
    team_league  = TEAM_ABBR_TO_LEAGUE.get(team_abbr)
    market_year  = evaluation_year + 1
    t0 = time.time()

    # 1. Load
    _tick("Loading 2024 batting, pitching, contract, and defensive CSVs")
    batting   = pd.read_csv(DATA_RAW / "batting_2024.csv",  encoding="utf-8")
    pitching  = pd.read_csv(DATA_RAW / "pitching_2024.csv", encoding="utf-8")

    # Use the combined contract pool — original top-100/manual list (115 rows)
    # PLUS the Spotrac yearly FA tracker scrape (~1,139 mid-tier signings).
    # Total ~1,254. Matches the pool the precision@10 test validated against;
    # gives the live app the broader candidate set its evaluation justifies.
    # No-look-ahead is enforced inside player_matcher.find_matches and the
    # _pick_targets / _pick_pricing_comparables helpers regardless of pool size.
    contracts_main = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    ext_path = DATA_RAW / "contracts_extended.csv"
    if ext_path.exists():
        contracts_ext = pd.read_csv(ext_path, encoding="utf-8")
        # Align columns; pd.concat fills missing with NaN
        contracts = pd.concat([contracts_main, contracts_ext], ignore_index=True)
    else:
        contracts = contracts_main

    # Defensive CSVs are optional — Day 1 sprint runs without them. Treat as best-effort.
    def _try_read(name: str) -> pd.DataFrame | None:
        p = DATA_RAW / name
        return pd.read_csv(p, encoding="utf-8") if p.exists() else None

    oaa_df     = _try_read("oaa_2024.csv")
    sprint_df  = _try_read("sprint_speed_2024.csv")
    catcher_df = _try_read("catcher_defense_2024.csv")
    have_defense = oaa_df is not None and sprint_df is not None

    # 2. Aggregate team and league — pass team_league so shared-city pairs
    # (CHC/CWS, LAD/LAA, NYM/NYY) don't bleed into each other's filters.
    _tick(f"Aggregating {team_abbr}'s qualified-player stats vs the rest of MLB")
    team_bat_df = _filter_team(batting,  bref_team, league=team_league)
    team_pit_df = _filter_team(pitching, bref_team, league=team_league)

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
    #          (d) gpt-4o-mini per-target forecast — what the player would
    #              actually command on a new FA deal in the upcoming offseason
    #
    # Optimization (post-Checkpoint-3 polish pass): the local-data steps (a, b)
    # are fast and run sequentially. Steps (c) and (d) are pure LLM calls and
    # are completely independent across gaps and targets — we run all ~12 LLM
    # calls in a thread pool so total wall time becomes single-call latency
    # instead of 12 × single-call latency. Brings the Gap Filler from ~12s
    # sequential to ~4-5s in practice.
    #
    # Committed-vs-available payroll calculation. Previously this code took a
    # shortcut: ``single_signing_ceiling = max_budget * 0.30``, treating the
    # user's total-payroll input as if it were freely available. That's wrong
    # for any real GM — most of the budget is already spoken for by existing
    # contracts. We now compute the team's no-look-ahead committed payroll
    # (from contracts.csv, with the same signed_year filter we use everywhere
    # else), subtract from the total budget to get the available room, and
    # set the single-signing ceiling = 30% of THAT.
    #
    # ``committed_payroll`` is a user override. Pass None (default) to use the
    # auto-computed estimate from our contracts dataset. Pass a number to
    # override — real GMs know their actual committed payroll better than our
    # dataset does, since contracts.csv excludes league-min / pre-arb players.
    _tick(f"Computing {team_abbr}'s committed-payroll baseline for {evaluation_year + 1}")
    committed_info = compute_committed_payroll(team_abbr, contracts, evaluation_year)
    if committed_payroll is None:
        committed_payroll = float(committed_info["committed_total"])
        # Source is now resolved inside compute_committed_payroll: it's either
        # "spotrac_team_payroll" (authoritative) or "contracts_sum" (estimate
        # from the partial contracts dataset). The UI tile labels itself
        # accordingly.
        committed_source  = committed_info["committed_source"]
    else:
        committed_payroll = float(committed_payroll)
        committed_source  = "user_override"

    available_for_signings = max(0.0, max_budget - committed_payroll)
    single_signing_ceiling = available_for_signings * 0.30
    over_committed         = committed_payroll > max_budget

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

    # ── Step A+B: sequential local prep per gap (no LLM) ─────────────────────
    # Task #62: incumbent-aware composite improvement scoring.
    #   1. For each gap, identify the team's current incumbent at that position
    #      and compute their offensive + defensive line.
    #   2. Ask the matcher for a wider candidate pool (k=10) than we'll show, so
    #      composite re-ranking has options.
    #   3. Compute (offense, defense, pitching) deltas per candidate vs the
    #      incumbent. The composite_score combines them weighted by the gap's
    #      own offense/defense ratio from gap_components.
    #   4. Re-sort by composite_score and take the top-3 to surface to the user.
    #   5. Attach incumbent + deltas to the result so the UI can render the
    #      "vs your current 2B Polanco" row and the LLM can articulate the
    #      trade-off in each forecast rationale.
    _tick("Picking candidate targets + pricing comparables for the top-3 gaps")
    prepared_gaps: list[dict] = []
    # Candidate pool ceiling = the premium-tier upper bound. We retrieve all
    # candidates up to ``5 * single_signing_ceiling`` (floored at $30M for
    # over-committed teams) so the bargain / medium / premium bucketing has
    # genuine candidates in every tier rather than only at-budget players.
    tier_pool_ceiling = max(
        single_signing_ceiling * TIER_PREMIUM_RATIO,
        TIER_PREMIUM_MIN_CAP,
    )
    for idx, gap in enumerate(diag.get("gaps", [])[:3], start=1):
        pos = gap.get("position")
        targets: list[dict] = []
        targets_source = "stat_fit"
        # Pull a deeper pool so each tier has real options to pick from.
        candidate_pool_k = 20
        if vs_ready and find_matches is not None:
            try:
                targets = find_matches(
                    gap, contracts, batting, pitching,
                    evaluation_year=evaluation_year,
                    single_signing_ceiling=tier_pool_ceiling,
                    k=candidate_pool_k,
                )
                if targets:
                    targets_source = "vectorstore"
            except Exception:
                targets = []
        if not targets:
            targets = _pick_targets(contracts, batting, pitching, pos,
                                    evaluation_year,
                                    tier_pool_ceiling, k=candidate_pool_k)

        # Compute the team's current incumbent at this position
        incumbent = get_position_incumbent(
            team_abbr, pos, batting, pitching,
            oaa_df=oaa_df, catcher_df=catcher_df, sprint_df=sprint_df,
        )

        # Compute per-target improvement deltas vs incumbent + composite score
        for t in targets:
            deltas = _compute_improvement_deltas(
                t, incumbent, gap, oaa_df=oaa_df, catcher_df=catcher_df,
            )
            t["vs_incumbent_offense"]  = deltas["vs_incumbent_offense"]
            t["vs_incumbent_defense"]  = deltas["vs_incumbent_defense"]
            t["vs_incumbent_pitching"] = deltas["vs_incumbent_pitching"]
            t["composite_score"]       = deltas["composite_score"]
            t["delta_breakdown"]       = deltas["breakdown"]

        # Bucket by AAV tier (bargain / medium / premium) and pick top-1 per
        # tier by composite improvement score. Result is ordered bargain ->
        # medium -> premium so the UI reads cheap-to-expensive. The classifier
        # tags each target with a ``tier`` field for downstream UI badges.
        targets = _pick_top_per_tier(targets, single_signing_ceiling,
                                       max_per_tier=1)

        target_names = {t.get("player_name") for t in targets if t.get("player_name")}
        pricing_comparables = _pick_pricing_comparables(
            contracts, batting, pitching, pos, evaluation_year, k=3,
            exclude_names=target_names,
        )
        prepared_gaps.append({
            "idx":                 idx,
            "gap":                 gap,
            "pos":                 pos,
            "targets":             targets,
            "targets_source":      targets_source,
            "incumbent":           incumbent,
            "pricing_comparables": pricing_comparables,
        })

    # ── Step C: parallel pricing estimates + per-target forecasts ───────────
    from concurrent.futures import ThreadPoolExecutor

    def _safe_estimate(pg: dict) -> tuple[int, dict]:
        if not pg["pricing_comparables"]:
            return pg["idx"], {
                "position": pg["pos"], "estimated_aav": None, "estimated_years": None,
                "total_range_low": None, "total_range_high": None,
                "comparable_contracts": [],
                "leverage_note": (f"No comparable contracts in dataset for position "
                                  f"{pg['pos']} with signed_year <= {evaluation_year}."),
            }
        try:
            est = estimate_contract_llm(
                pg["pos"], pg["gap"].get("reasoning", ""),
                pg["pricing_comparables"], market_year=market_year,
            )
        except Exception as e:                                  # noqa: BLE001
            est = {"position": pg["pos"], "estimated_aav": None, "estimated_years": None,
                   "leverage_note": f"estimate unavailable ({type(e).__name__}: {e})"}
        return pg["idx"], est

    def _safe_forecast(idx: int, target: dict, pos: str,
                       pricing_comparables: list[dict],
                       incumbent: dict | None,
                       gap: dict | None = None) -> tuple[int, str, dict]:
        # Re-package the per-target deltas in the shape the LLM payload expects.
        # IMPORTANT: only include fields whose deltas are actually known. If we
        # send {"defense": null} the LLM tends to hallucinate a defense delta
        # anyway ("gives back 5 OAA"). Omitting the key forces the LLM to leave
        # that dimension out of the rationale.
        improvement_deltas = None
        if target.get("composite_score") is not None:
            gc = (gap or {}).get("gap_components") or {}
            improvement_deltas = {
                "composite": target.get("composite_score"),
                "breakdown": target.get("delta_breakdown", ""),
            }
            if target.get("vs_incumbent_offense") is not None:
                improvement_deltas["offense"]  = target.get("vs_incumbent_offense")
            if target.get("vs_incumbent_defense") is not None:
                improvement_deltas["defense"]  = target.get("vs_incumbent_defense")
            if target.get("vs_incumbent_pitching") is not None:
                improvement_deltas["pitching"] = target.get("vs_incumbent_pitching")
            if gc.get("offense") is not None:
                improvement_deltas["gap_offense_weight"] = gc.get("offense")
            if gc.get("defense") is not None:
                improvement_deltas["gap_defense_weight"] = gc.get("defense")

        # ── Layer 1: sanitize the incumbent so the LLM can't see incumbent
        # stats it shouldn't be doing arithmetic on. If we don't carry a
        # defense delta, strip the incumbent's defense block too.
        clean_incumbent = _sanitize_incumbent_for_payload(incumbent, improvement_deltas)

        try:
            forecast = forecast_target_contract_llm(
                target, pos, pricing_comparables, market_year=market_year,
                incumbent=clean_incumbent, improvement_deltas=improvement_deltas,
            )
            rationale = forecast.get("rationale", "")

            # ── Layer 2: validate the LLM rationale against the deltas. If
            # any number+unit phrase references a dimension the deltas don't
            # carry (or disagrees with the known value beyond rounding
            # tolerance), the rationale is hallucinating. Replace it with
            # the programmatic version.
            hallucinations = _rationale_hallucinations(rationale, improvement_deltas)
            if hallucinations:
                rationale = _programmatic_rationale(
                    target, incumbent, improvement_deltas, gap
                )
                rationale_source = "programmatic_fallback"
            else:
                rationale_source = "llm"

            return idx, target["player_name"], {
                "forecast_aav":            forecast.get("forecast_aav"),
                "forecast_years":          forecast.get("forecast_years"),
                "forecast_rationale":      rationale,
                "rationale_source":        rationale_source,
                "rationale_hallucinations": hallucinations,
            }
        except Exception as e:                                  # noqa: BLE001
            # ── Layer 3 (also covers total LLM failure): even with no LLM
            # output, we can still give the user a deterministic rationale
            # from the deltas.
            fallback_rat = _programmatic_rationale(
                target, incumbent, improvement_deltas, gap
            ) if improvement_deltas else f"forecast unavailable ({type(e).__name__})"
            return idx, target["player_name"], {
                "forecast_aav":            None,
                "forecast_years":          None,
                "forecast_rationale":      fallback_rat,
                "rationale_source":        "programmatic_fallback",
                "rationale_hallucinations": [],
            }

    total_targets = sum(len(pg["targets"]) for pg in prepared_gaps)
    _tick(f"Running 3 contract estimates + {total_targets} per-target forecasts in parallel")

    estimates_by_idx: dict[int, dict] = {}
    forecasts_by_key: dict[tuple[int, str], dict] = {}

    # max_workers sized to the total parallelizable calls; thread pool handles
    # OpenAI rate limits gracefully via httpx's connection pooling.
    n_calls = len(prepared_gaps) + total_targets
    with ThreadPoolExecutor(max_workers=max(4, min(n_calls, 12))) as ex:
        # Submit all estimate calls
        est_futures = [ex.submit(_safe_estimate, pg) for pg in prepared_gaps]
        # Submit all forecast calls
        fc_futures = []
        for pg in prepared_gaps:
            for target in pg["targets"]:
                fc_futures.append(ex.submit(_safe_forecast, pg["idx"], target,
                                            pg["pos"], pg["pricing_comparables"],
                                            pg.get("incumbent"), pg["gap"]))
        # Collect estimates
        for fut in est_futures:
            idx, est = fut.result()
            estimates_by_idx[idx] = est
        # Collect forecasts
        for fut in fc_futures:
            idx, name, fc = fut.result()
            forecasts_by_key[(idx, name)] = fc

    # ── Step D: sequential post-processing (rationale linking, premium flags) ─
    results = []
    for pg in prepared_gaps:
        pos       = pg["pos"]
        gap       = pg["gap"]
        targets   = pg["targets"]
        pricing_comparables = pg["pricing_comparables"]
        estimate  = estimates_by_idx[pg["idx"]]

        affordable = (
            estimate.get("estimated_aav") is not None
            and estimate["estimated_aav"] <= single_signing_ceiling
        )

        # Cross-link LLM rationales onto the structured pricing-comparable rows
        # and flag comparables that are also recommended targets.
        llm_rationales = {
            c.get("player_name"): c.get("rationale", "")
            for c in estimate.get("comparable_contracts", [])
        }
        target_name_set = {t["player_name"] for t in targets}
        for pc in pricing_comparables:
            pc["rationale"]      = llm_rationales.get(pc["player_name"], "")
            pc["is_also_target"] = pc["player_name"] in target_name_set

        # Attach forecasts to targets + compute premium flags
        est_aav = estimate.get("estimated_aav")
        for t in targets:
            fc = forecasts_by_key.get((pg["idx"], t["player_name"]), {})
            t["forecast_aav"]              = fc.get("forecast_aav")
            t["forecast_years"]            = fc.get("forecast_years")
            t["forecast_rationale"]        = fc.get("forecast_rationale", "")
            t["rationale_source"]          = fc.get("rationale_source")
            t["rationale_hallucinations"]  = fc.get("rationale_hallucinations", [])
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
            "targets_source": pg["targets_source"],
            "incumbent": pg.get("incumbent"),
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
        # Payroll situation (committed vs available, plus the data caveat)
        "committed_payroll":      committed_payroll,
        "committed_source":       committed_source,
        "committed_breakdown":    committed_info["breakdown"],
        "committed_caveat":       committed_info["coverage_caveat"],
        "available_for_signings": available_for_signings,
        "single_signing_ceiling": single_signing_ceiling,
        "over_committed":         over_committed,
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


def list_team_starters(team_abbr: str, evaluation_year: int = 2024,
                       min_gs: int = 5) -> list[dict]:
    """List a team's starting-pitcher options for the Roster Builder's
    probable-pitcher dropdown. Returns rows sorted by GS descending so the
    workhorse starter (ace) is at the top.

    Each row: {"name": str, "GS": int, "IP": float, "ERA": float, "WHIP": float, "K9": float}.

    ``min_gs`` filters out long relievers / spot starters. Default 5 matches
    the threshold ``_top_pitchers`` uses to classify pitchers as starters.
    """
    if team_abbr not in TEAM_ABBR_TO_BREF:
        raise ValueError(f"Unknown team abbreviation: {team_abbr}")
    bref_team = TEAM_ABBR_TO_BREF[team_abbr]
    league    = TEAM_ABBR_TO_LEAGUE.get(team_abbr)
    pit_path  = DATA_RAW / f"pitching_{evaluation_year}.csv"
    if not pit_path.exists():
        return []
    pitching = pd.read_csv(pit_path, encoding="utf-8")
    team_pit = _filter_team(pitching, bref_team, league=league)
    starters = team_pit[team_pit["GS"].fillna(0) >= min_gs].copy()
    if starters.empty:
        return []
    starters = starters.sort_values("GS", ascending=False)
    rows: list[dict] = []
    seen: set[str] = set()
    for _, row in starters.iterrows():
        name = str(row.get("Name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append({
            "name": name,
            "GS":   int(row.get("GS", 0) or 0),
            "IP":   round(float(row.get("IP", 0) or 0), 1),
            "ERA":  round(float(row.get("ERA", 0) or 0), 2),
            "WHIP": round(float(row.get("WHIP", 0) or 0), 3),
            "K9":   round(float(row.get("SO9", 0) or 0), 1),
        })
    return rows


def _lookup_pitcher_row(pitcher_name: str, team_pit_df: pd.DataFrame) -> dict | None:
    """Look up one pitcher's full stat line by name, within a team's pitching slice.

    Returns the formatted stat dict the LLM consumes, or ``None`` if the
    pitcher isn't found. Falls back to ascii-folded name matching so accent
    differences (José vs Jose) don't cause misses.
    """
    if not pitcher_name:
        return None
    needle      = str(pitcher_name).strip()
    needle_fold = _ascii_fold(needle).lower()
    match = team_pit_df[team_pit_df["Name"].astype(str).str.strip() == needle]
    if match.empty:
        match = team_pit_df[
            team_pit_df["Name"].astype(str).map(lambda n: _ascii_fold(str(n)).lower())
            == needle_fold
        ]
    if match.empty:
        return None
    row = match.iloc[0]
    name_clean = str(row["Name"]).strip()
    ip = float(row.get("IP", 0) or 0)
    # Bref's CSV carries SO9 directly but not BB9 / HR9. Compute those from
    # raw counts (BB, HR) and innings. Guards against IP=0 division.
    bb = float(row.get("BB", 0) or 0)
    hr = float(row.get("HR", 0) or 0)
    bb9 = (9.0 * bb / ip) if ip > 0 else 0.0
    hr9 = (9.0 * hr / ip) if ip > 0 else 0.0
    return {
        "name":   name_clean,
        "throws": _lookup_pitcher_hand(name_clean),       # "R" / "L" / "S" / None
        "IP":     round(ip, 1),
        "GS":     int(row.get("GS", 0) or 0),
        "ERA":    round(float(row.get("ERA", 0) or 0), 2),
        "WHIP":   round(float(row.get("WHIP", 0) or 0), 3),
        "K9":     round(float(row.get("SO9", 0) or 0), 1),
        "BB9":    round(bb9, 1),
        "HR9":    round(hr9, 2),
    }


ROSTER_BUILDER_SYSTEM = """You are an MLB game-strategy analyst helping a front office build the
best starting lineup against a specific opponent. You receive:
  * The team's qualified hitters (2024 stat lines, top 12 by OPS)
  * The opponent's qualified pitchers (top 5 by ERA — a mix of starters and
    relievers, useful for thinking about the staff overall and bullpen leverage)
  * The opponent's per-position defensive deltas vs. league (where positive
    OAA means the opponent's defense is above average and offense is harder
    to find against them)
  * OPTIONAL: ``probable_starter`` — when present, this is the opponent's
    confirmed probable starter for tonight, with their season stat line:
    ``throws`` ("R" | "L" | "S" | null), ERA, WHIP, K/9, BB/9, HR/9, IP, GS.
    When this field is provided, the lineup ordering and the narrative MUST
    be specifically tailored to attacking THIS pitcher's profile, not the
    staff in general. Cite the starter by name in the narrative.

    When ``throws`` is non-null, the lineup MUST be PLATOON-AWARE: stack
    opposite-handed hitters (right-handed batters against a left-handed
    pitcher, and vice versa) into the high-leverage spots (1-5). Switch
    hitters are neutral and can slot anywhere. Note the platoon advantage
    in at least one lineup rationale and one matchup_advantages entry.
    When ``throws`` is null, do not invent handedness — reason from the
    stat line alone.

    When ``probable_starter`` is null entirely, reason about the staff as a
    whole.

Return STRICT JSON only, no prose, with this exact schema:

{
  "team": "<3-letter abbr>",
  "opponent": "<3-letter abbr>",
  "year": 2024,
  "narrative": "<2-3 sentence strategic summary of how this team should attack this opponent — name the probable starter if one is provided>",
  "recommended_lineup": [
    {"order": <1-9>, "player_name": "<name>", "position": "<C|1B|2B|3B|SS|LF|CF|RF|DH>", "rationale": "<one short phrase, why this slot/order — reference the probable starter's specific weaknesses when applicable>"}
  ],
  "matchup_advantages": [
    {"area": "<short label, e.g. 'attack high WHIP early innings'>", "evidence": "<one short phrase citing stats from the probable starter or the staff>", "leverage": "high" | "medium" | "low"}
  ],
  "matchup_risks": [
    {"area": "<short label>", "mitigation": "<one sentence on how to neutralize it>"}
  ]
}

The lineup MUST be exactly 9 players covering 9 distinct positions:
C, 1B, 2B, 3B, SS, LF, CF, RF, DH. Pick the best hitters available who can
plausibly play each position; if the team's hitter list is thin at a position,
note this in the rationale rather than inventing a player. Return EXACTLY 3
matchup_advantages and EXACTLY 2 matchup_risks. Ground every recommendation
in the data provided; do not reference 2025+ events or trades."""


def build_roster_llm(team_abbr: str, opponent_abbr: str,
                    team_hitters: list[dict],
                    opponent_pitchers: list[dict],
                    opponent_defense_deltas: dict | None,
                    probable_starter: dict | None = None) -> dict:
    """One gpt-4o call producing the roster-builder report as structured JSON.

    When ``probable_starter`` is provided, the prompt instructs the model to
    tailor lineup ordering and narrative specifically to that pitcher's stat
    profile. When None, the model reasons about the staff as a whole.
    """
    oai = _client()
    user_payload = {
        "team":     team_abbr,
        "opponent": opponent_abbr,
        "year":     2024,
        "team_top_hitters":         team_hitters,
        "opponent_top_pitchers":    opponent_pitchers,
        "opponent_defense_deltas":  opponent_defense_deltas,
        "probable_starter":         probable_starter,
    }
    resp = oai.chat.completions.create(
        model=GPT4O,
        response_format={"type": "json_object"},
        temperature=0,
        seed=42,
        messages=[
            {"role": "system", "content": ROSTER_BUILDER_SYSTEM},
            {"role": "user",   "content": json.dumps(user_payload, default=str)},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def run_roster_builder_simple(team_abbr: str = "SEA",
                              opponent_abbr: str = "HOU",
                              evaluation_year: int = 2024,
                              probable_pitcher: str | None = None,
                              progress: ProgressCallback = None) -> dict:
    """Day-to-day lineup construction for one game against one specific opponent.

    Uses the team's existing 2024 roster — no payroll or free-agency input.
    Aggregates the team's top hitters (PA >= 200) and the opponent's top
    pitchers (IP >= 30), plus the opponent's per-position defensive deltas
    if Statcast data is available. One ``gpt-4o`` call returns a structured
    recommendation: lineup, advantages, risks, narrative.

    ``probable_pitcher`` (optional): the opponent's confirmed probable starter
    for this game, by player name. When provided, the LLM gets that pitcher's
    full stat line and is instructed to tailor lineup ordering specifically
    to attacking THIS pitcher rather than the staff as a whole. When None,
    the orchestrator behaves exactly as it did before this feature was added.
    """
    def _tick(label: str) -> None:
        if progress is not None:
            progress(label)

    if team_abbr not in TEAM_ABBR_TO_BREF:
        raise ValueError(f"Unknown team abbreviation: {team_abbr}")
    if opponent_abbr not in TEAM_ABBR_TO_BREF:
        raise ValueError(f"Unknown opponent abbreviation: {opponent_abbr}")
    bref_team       = TEAM_ABBR_TO_BREF[team_abbr]
    bref_opponent   = TEAM_ABBR_TO_BREF[opponent_abbr]
    team_league     = TEAM_ABBR_TO_LEAGUE.get(team_abbr)
    opponent_league = TEAM_ABBR_TO_LEAGUE.get(opponent_abbr)
    t0 = time.time()

    _tick(f"Loading {evaluation_year} batting and pitching CSVs")
    batting  = pd.read_csv(DATA_RAW / f"batting_{evaluation_year}.csv",  encoding="utf-8")
    pitching = pd.read_csv(DATA_RAW / f"pitching_{evaluation_year}.csv", encoding="utf-8")

    def _try_read(name: str) -> pd.DataFrame | None:
        p = DATA_RAW / name
        return pd.read_csv(p, encoding="utf-8") if p.exists() else None

    oaa_df     = _try_read(f"oaa_{evaluation_year}.csv")
    sprint_df  = _try_read(f"sprint_speed_{evaluation_year}.csv")
    catcher_df = _try_read(f"catcher_defense_{evaluation_year}.csv")

    _tick(f"Aggregating {team_abbr}'s top hitters and {opponent_abbr}'s top pitchers")
    team_bat_df = _filter_team(batting,  bref_team,     league=team_league)
    opp_pit_df  = _filter_team(pitching, bref_opponent, league=opponent_league)
    team_hitters     = _top_hitters(team_bat_df,  n=12)
    opponent_pitchers = _top_pitchers(opp_pit_df, n=5)

    probable_starter: dict | None = None
    if probable_pitcher:
        probable_starter = _lookup_pitcher_row(probable_pitcher, opp_pit_df)
        if probable_starter is None:
            _tick(f"Warning: probable starter '{probable_pitcher}' not found on "
                  f"{opponent_abbr}'s {evaluation_year} pitching roster — falling "
                  f"back to staff-level reasoning")

    opponent_defense_deltas: dict | None = None
    if oaa_df is not None and sprint_df is not None:
        _tick(f"Aggregating {opponent_abbr}'s defensive profile (per-position OAA, sprint, catcher pop time)")
        opp_def    = aggregate_team_defense(opponent_abbr, oaa_df, catcher_df, sprint_df)
        league_def = aggregate_league_defense_per_team(oaa_df, catcher_df, sprint_df)
        opponent_defense_deltas = compute_defense_deltas(opp_def, league_def)

    if probable_starter:
        _tick(f"Asking GPT-4o to build a lineup tailored to attacking "
              f"{probable_starter['name']} ({probable_starter['ERA']:.2f} ERA, "
              f"{probable_starter['WHIP']:.3f} WHIP)")
    else:
        _tick(f"Asking GPT-4o to build a lineup and matchup plan for {team_abbr} vs {opponent_abbr}")
    report = build_roster_llm(team_abbr, opponent_abbr, team_hitters,
                              opponent_pitchers, opponent_defense_deltas,
                              probable_starter=probable_starter)

    return {
        "team":     team_abbr,
        "opponent": opponent_abbr,
        "year":     evaluation_year,
        "elapsed_seconds":  round(time.time() - t0, 2),
        "team_hitters":       team_hitters,
        "opponent_pitchers":  opponent_pitchers,
        "opponent_defense_deltas": opponent_defense_deltas,
        "probable_starter":   probable_starter,
        "narrative":          report.get("narrative", ""),
        "recommended_lineup": report.get("recommended_lineup", []),
        "matchup_advantages": report.get("matchup_advantages", []),
        "matchup_risks":      report.get("matchup_risks", []),
    }


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
    bref_team       = TEAM_ABBR_TO_BREF[opponent_abbr]
    opponent_league = TEAM_ABBR_TO_LEAGUE.get(opponent_abbr)
    t0 = time.time()

    _tick(f"Loading {evaluation_year} batting and pitching CSVs")
    batting  = pd.read_csv(DATA_RAW / f"batting_{evaluation_year}.csv",  encoding="utf-8")
    pitching = pd.read_csv(DATA_RAW / f"pitching_{evaluation_year}.csv", encoding="utf-8")

    _tick(f"Aggregating {opponent_abbr}'s offense + pitching vs the rest of MLB")
    team_bat_df = _filter_team(batting,  bref_team, league=opponent_league)
    team_pit_df = _filter_team(pitching, bref_team, league=opponent_league)

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

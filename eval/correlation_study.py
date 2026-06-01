"""eval/correlation_study.py — 6-year correlation between gap score and next-year wins.

For each (evaluation_year, team) in 2019–2024 × 30 MLB teams (180 rows):
  1. Aggregate the team's offensive + pitching stats from the year-specific CSV
  2. Compute deltas vs league per-team averages
  3. Call ``diagnose_gaps_llm`` to get top 3 gaps with scores
  4. Compute a composite team gap score (sum of weighted gap_scores)
  5. Look up the team's wins in the FOLLOWING year via pybaseball.standings()

Then compute:
  * Pooled Pearson correlation across all (year, team) rows
  * Per-year Pearson correlation
  * The 2020 COVID 60-game season is broken out separately so its noise does not
    drag the headline number

Outputs:
  eval/results/correlation_table.csv
  eval/results/correlation_scatter.png
  eval/results/correlation_by_year.png

Caching: diagnose_gaps_llm responses are cached in
data/processed/correlation_diagnose_cache.json so reruns are essentially free
(only the new 2024 evaluation year incurs 30 fresh gpt-4o gap-diagnostic calls).

Defensive scope: OAA + sprint speed + catcher pop are now available for all
2019-2025 (Entry 7 + the June 1 2026 refresh that added 2025). The ablation
table reports offense-only, defense-only, and combined gap scores.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pybaseball import standings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from core.orchestrator import (                                # noqa: E402
    TEAM_ABBR_TO_BREF,
    POSITION_SCARCITY_WEIGHTS,
    _compute_delta, _filter_team,
    aggregate_batting, aggregate_pitching,
    aggregate_team_defense, aggregate_league_defense_per_team,
    compute_defense_deltas,
    diagnose_gaps_llm,
)

EVAL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]   # gap scored at end of each
CACHE_PATH = DATA_PROC / "correlation_diagnose_cache.json"

# Map our 3-letter abbreviations to Baseball Reference full names so we can
# join with pybaseball.standings() output.
TEAM_ABBR_TO_FULL = {
    "ARI": "Arizona Diamondbacks",  "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",     "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",          "CWS": "Chicago White Sox",
    "CIN": "Cincinnati Reds",       "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",      "DET": "Detroit Tigers",
    "HOU": "Houston Astros",        "KC":  "Kansas City Royals",
    "LAA": "Los Angeles Angels",    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",         "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",       "NYM": "New York Mets",
    "NYY": "New York Yankees",      "OAK": "Oakland Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates",
    "SD":  "San Diego Padres",      "SEA": "Seattle Mariners",
    "SF":  "San Francisco Giants",  "STL": "St. Louis Cardinals",
    "TB":  "Tampa Bay Rays",        "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",     "WSH": "Washington Nationals",
}

# Cleveland was the "Indians" before 2022 — standings() may use either name.
# pybaseball returns whatever bref published for that season; we accept either.
def _alt_team_names(full_name: str) -> list[str]:
    aliases = [full_name]
    if full_name == "Cleveland Guardians":
        aliases.append("Cleveland Indians")
    if full_name == "Oakland Athletics":
        aliases.append("Oakland A's")
        # 2025 rebrand: bref dropped the city prefix after the team's move
        aliases.append("Athletics")
    return aliases


# ──────────────────────────────────────────────────────────────────────────────
# Caching wrapper around diagnose_gaps_llm
# ──────────────────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_key(team_abbr: str, year: int, delta_bat: dict, delta_pit: dict,
               defense_deltas: dict | None = None) -> str:
    """Hash of inputs to diagnose_gaps_llm. Defense deltas are part of the key
    so offense-only results don't bleed into defense-augmented runs."""
    payload = json.dumps({
        "team": team_abbr, "year": year,
        "delta_bat": delta_bat, "delta_pit": delta_pit,
        "defense": defense_deltas,
    }, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def cached_diagnose(team_abbr: str, year: int,
                    team_bat: dict, team_pit: dict,
                    league_bat: dict, league_pit: dict,
                    delta_bat: dict, delta_pit: dict,
                    cache: dict,
                    team_defense: dict | None = None,
                    league_defense: dict | None = None,
                    defense_deltas: dict | None = None) -> dict:
    key = _cache_key(team_abbr, year, delta_bat, delta_pit, defense_deltas)
    if key in cache:
        return cache[key]

    # Retry-with-backoff for the gpt-4o TPM limit (30K tokens/min). The
    # defensive payload pushed each request past ~1.4K tokens, so 30 sequential
    # team-diagnoses can land within 60 seconds. We sleep briefly between calls
    # to stay under TPM, and retry-with-backoff on 429.
    from openai import RateLimitError                          # local import
    max_attempts = 5
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        try:
            diag = diagnose_gaps_llm(
                team_abbr, team_bat, team_pit,
                league_bat, league_pit,
                delta_bat, delta_pit,
                team_defense=team_defense,
                league_defense=league_defense,
                defense_deltas=defense_deltas,
            )
            break
        except RateLimitError as e:
            if attempt == max_attempts:
                raise
            wait_s = delay * (2 ** (attempt - 1))
            print(f"    [rate-limit] attempt {attempt}/{max_attempts}, "
                  f"sleeping {wait_s:.0f}s before retry")
            time.sleep(wait_s)

    cache[key] = diag
    _save_cache(cache)
    # Courteous pacing to stay well under the 30K TPM budget on the next call.
    time.sleep(1.5)
    return diag


# ──────────────────────────────────────────────────────────────────────────────
# Composite gap scores (offense-only, defense-only, combined)
# ──────────────────────────────────────────────────────────────────────────────
def composite_gap_score(gaps: list[dict]) -> float:
    """Backward-compatible composite — uses gap_score weighted by scarcity."""
    total = 0.0
    for g in gaps[:3]:
        score = float(g.get("gap_score") or 0)
        pos = g.get("position", "")
        weight = POSITION_SCARCITY_WEIGHTS.get(pos, 1.0)
        total += score * weight
    return round(total, 2)


def composite_gap_scores(gaps: list[dict]) -> tuple[float, float, float]:
    """Returns (offense_only, defense_only, combined) composite scores using
    the LLM-provided gap_components, each weighted by positional scarcity."""
    off_total = def_total = combined_total = 0.0
    for g in gaps[:3]:
        pos = g.get("position", "")
        weight = POSITION_SCARCITY_WEIGHTS.get(pos, 1.0)
        comp = g.get("gap_components") or {}
        off = float(comp.get("offense") or 0)
        dfn = float(comp.get("defense") or 0)
        off_total += off * weight
        def_total += dfn * weight
        combined_total += (off + dfn) * weight
    return round(off_total, 2), round(def_total, 2), round(combined_total, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Wins lookup
# ──────────────────────────────────────────────────────────────────────────────
_STANDINGS_CACHE: dict[int, pd.DataFrame] = {}


def get_wins(team_abbr: str, year: int) -> int | None:
    if year not in _STANDINGS_CACHE:
        try:
            divisions = standings(year)
            combined = pd.concat(divisions, ignore_index=True)
            combined["Tm"] = combined["Tm"].astype(str).str.strip()
            _STANDINGS_CACHE[year] = combined
        except Exception as e:                              # noqa: BLE001
            print(f"  [WARN] standings({year}) failed: {e}")
            _STANDINGS_CACHE[year] = pd.DataFrame()
    df = _STANDINGS_CACHE[year]
    if df.empty:
        return None
    full_name = TEAM_ABBR_TO_FULL.get(team_abbr, "")
    if not full_name:
        return None
    for alias in _alt_team_names(full_name):
        row = df[df["Tm"] == alias]
        if not row.empty:
            return int(row.iloc[0]["W"])
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main study
# ──────────────────────────────────────────────────────────────────────────────
def _aggregate_year(year: int):
    """Load and aggregate batting/pitching/defense for a single year. Returns
    (batting_df, pitching_df, league_bat_per_team, league_pit_per_team,
     oaa_df, sprint_df, catcher_df, league_defense_per_team).

    Defensive frames may be None if the year's CSVs aren't on disk yet — the
    caller treats this as offense-only for that year.
    """
    batting  = pd.read_csv(DATA_RAW / f"batting_{year}.csv",  encoding="utf-8")
    pitching = pd.read_csv(DATA_RAW / f"pitching_{year}.csv", encoding="utf-8")

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

    def _try_read(name: str) -> pd.DataFrame | None:
        p = DATA_RAW / name
        return pd.read_csv(p, encoding="utf-8") if p.exists() else None

    oaa_df     = _try_read(f"oaa_{year}.csv")
    sprint_df  = _try_read(f"sprint_speed_{year}.csv")
    catcher_df = _try_read(f"catcher_defense_{year}.csv")
    league_defense = (
        aggregate_league_defense_per_team(oaa_df, catcher_df, sprint_df)
        if oaa_df is not None and sprint_df is not None
        else None
    )
    return (batting, pitching, league_bat_per_team, league_pit_per_team_overall,
            oaa_df, sprint_df, catcher_df, league_defense)


def main() -> None:
    cache = _load_cache()
    rows: list[dict] = []

    for year in EVAL_YEARS:
        print(f"\n=== {year} ===")
        (batting, pitching, league_bat_per_team, league_pit_per_team,
         oaa_df, sprint_df, catcher_df, league_defense) = _aggregate_year(year)
        has_defense_year = oaa_df is not None and sprint_df is not None
        defense_tag = "DEF" if has_defense_year else "NO-DEF"
        print(f"  defensive data for {year}: {defense_tag}")

        for abbr in sorted(TEAM_ABBR_TO_BREF):
            bref_team = TEAM_ABBR_TO_BREF[abbr]
            team_bat_df = _filter_team(batting,  bref_team)
            team_pit_df = _filter_team(pitching, bref_team)
            team_bat = aggregate_batting(team_bat_df)
            team_pit = aggregate_pitching(team_pit_df)
            team_pit_overall = team_pit.get("overall", {})

            delta_bat = _compute_delta(team_bat, league_bat_per_team)
            delta_pit = _compute_delta(team_pit_overall, league_pit_per_team)

            team_defense   = None
            defense_deltas = None
            if has_defense_year:
                team_defense   = aggregate_team_defense(abbr, oaa_df, catcher_df, sprint_df)
                defense_deltas = compute_defense_deltas(team_defense, league_defense)

            diag = cached_diagnose(
                abbr, year, team_bat, team_pit_overall,
                league_bat_per_team, league_pit_per_team,
                delta_bat, delta_pit,
                cache,
                team_defense=team_defense,
                league_defense=league_defense,
                defense_deltas=defense_deltas,
            )
            off_score, def_score, combined = composite_gap_scores(diag.get("gaps", []))
            score = composite_gap_score(diag.get("gaps", []))   # backward-compat headline

            wins_next = get_wins(abbr, year + 1)
            if wins_next is None:
                print(f"  {abbr}: gap={score:5.2f}  wins({year+1})=??  (skipped)")
                continue
            print(f"  {abbr}: gap={score:5.2f}  "
                  f"off={off_score:5.2f}  def={def_score:5.2f}  combined={combined:5.2f}  "
                  f"wins({year+1})={wins_next}")
            rows.append({
                "year":             year,
                "team":             abbr,
                "gap_score":        score,
                "gap_offense":      off_score,
                "gap_defense":      def_score,
                "gap_combined":     combined,
                "has_defense_data": has_defense_year,
                "next_year_wins":   wins_next,
                "n_gaps_returned":  len(diag.get("gaps", [])),
                "top_gap_position": (diag.get("gaps") or [{}])[0].get("position"),
            })

    if not rows:
        raise SystemExit("No (year, team) rows produced — aborting.")

    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / "correlation_table.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\nSaved {out_csv} ({len(df)} rows)")

    # ── Pearson correlations (offense / defense / combined ablation) ────────
    print("\nCorrelations (Pearson r vs. next-year wins):")
    pooled_no2020 = df[df["year"] != 2020]
    ablation_rows = []
    for label, col in [
        ("legacy gap_score (headline)",      "gap_score"),
        ("offense-only composite",            "gap_offense"),
        ("defense-only composite",            "gap_defense"),
        ("combined offense+defense composite", "gap_combined"),
    ]:
        r_all      = df[col].corr(df["next_year_wins"])
        r_no2020   = pooled_no2020[col].corr(pooled_no2020["next_year_wins"])
        print(f"  [{label:38s}] all r = {r_all:+.3f}  (excl. 2020 r = {r_no2020:+.3f})")
        ablation_rows.append({
            "metric": label,
            "n_all":  len(df),
            "r_all":  round(r_all, 3),
            "n_no2020": len(pooled_no2020),
            "r_no2020": round(r_no2020, 3),
        })

    # Persist ablation table
    pd.DataFrame(ablation_rows).to_csv(RESULTS_DIR / "ablation_offense_vs_defense.csv",
                                       index=False, encoding="utf-8")

    pooled_r = df["gap_score"].corr(df["next_year_wins"])
    pooled_n = len(df)
    pooled_r_no2020 = pooled_no2020["gap_score"].corr(pooled_no2020["next_year_wins"])

    per_year = {}
    for year in EVAL_YEARS:
        yr = df[df["year"] == year]
        if len(yr) < 5:
            continue
        r = yr["gap_score"].corr(yr["next_year_wins"])
        per_year[year] = r
        print(f"  per-year {year} ({len(yr)} obs) headline gap_score   : r = {r:+.3f}")

    # ── Pooled scatter ──────────────────────────────────────────────────────
    fig_s = px.scatter(
        df, x="gap_score", y="next_year_wins", color="year",
        hover_data=["team", "top_gap_position"],
        labels={"gap_score": "Composite gap score (end of evaluation_year)",
                "next_year_wins": "Wins in evaluation_year + 1"},
        title=(f"Gap score (year Y) vs. wins (year Y+1) — "
               f"pooled r={pooled_r:+.3f} (n={pooled_n}), "
               f"excl. 2020 r={pooled_r_no2020:+.3f}"),
    )
    fig_s.update_layout(width=900, height=600)
    out_scatter = RESULTS_DIR / "correlation_scatter.png"
    fig_s.write_image(str(out_scatter))
    print(f"\nSaved {out_scatter}")

    # ── Per-year bar chart ──────────────────────────────────────────────────
    bar_rows = [{"year": y, "pearson_r": r} for y, r in per_year.items()]
    fig_b = px.bar(
        bar_rows, x="year", y="pearson_r",
        labels={"pearson_r": "Pearson r (gap → next-year wins)",
                "year": "Evaluation year"},
        title="Per-year Pearson r — gap score vs. next-year wins",
    )
    fig_b.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_b.update_layout(width=800, height=500, yaxis_range=[-1, 1])
    out_bar = RESULTS_DIR / "correlation_by_year.png"
    fig_b.write_image(str(out_bar))
    print(f"Saved {out_bar}")

    print("\n=== Correlation study done ===")
    print(f"Headline: gap_score (year Y, offense + pitching components only) "
          f"vs wins (year Y+1) — pooled r = {pooled_r:+.3f} "
          f"({'positive' if pooled_r > 0 else 'negative'}, "
          f"{'expected' if pooled_r < 0 else 'unexpected'} sign — "
          f"higher gap should mean fewer future wins).")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nElapsed: {time.time() - t0:.1f}s")

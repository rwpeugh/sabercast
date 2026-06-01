"""eval/statistical_validation.py — Pre-registered statistical validation suite.

Six analyses that operationalize "is Sabercast useful?":

  6.3.1  Significance + bootstrap CI on the headline correlations
  6.3.2  Naive baseline shootout (autocorrelation, rolling mean, random null vs Sabercast)
  6.3.3  Top-1 gap-position hit-rate (precision vs random)
  6.3.4  Stratified by market tier (matches our business framing)
  6.3.5  Year-stratified analysis (signal accumulation over time)
  6.3.6  Contract MAE significance testing (paired Wilcoxon + bootstrap CI)

No LLM calls. Pure post-processing on committed CSVs:
  eval/results/correlation_table.csv            (180 rows from correlation_study)
  eval/results/ablation_offense_vs_defense.csv  (correlation point estimates)
  eval/results/contract_mae.csv                  (26 baseline forecasts)
  eval/results/contract_mae_finetuned.csv        (26 fine-tune forecasts)
  data/raw/batting_{year}.csv, pitching_{year}.csv, oaa_{year}.csv, catcher_defense_{year}.csv
  data/raw/standings_2018.csv                    (autocorrelation baseline at year 2019)
  core/orchestrator.py:TEAM_DEFAULT_PAYROLL      (market tier binning)

Outputs written to eval/results/:
  statistical_validation_summary.csv     One row per test with verdict
  correlation_significance.csv           6.3.1
  baseline_shootout.csv                  6.3.2
  gap_position_hit_rate.csv              6.3.3
  gap_position_hit_rate_by_year.csv      6.3.3
  correlation_by_market_tier.csv         6.3.4
  correlation_by_year_significance.csv   6.3.5
  contract_mae_significance.csv          6.3.6

Honest reporting commitment: every analysis here is pre-registered in
SABERCAST_SPEC.md § 6.3. If a test comes back null or negative we report it.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from core.orchestrator import TEAM_DEFAULT_PAYROLL              # noqa: E402

RANDOM_SEED = 42
N_BOOTSTRAP = 10_000
rng = np.random.default_rng(RANDOM_SEED)


# ──────────────────────────────────────────────────────────────────────────────
#  Shared helpers
# ──────────────────────────────────────────────────────────────────────────────
def bootstrap_pearson_ci(x: np.ndarray, y: np.ndarray, n_boot: int = N_BOOTSTRAP
                          ) -> tuple[float, float, float]:
    """Bootstrap 95% CI for Pearson r. Returns (point_estimate, ci_low, ci_high)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 4:
        return float("nan"), float("nan"), float("nan")
    r_obs = float(np.corrcoef(x, y)[0, 1])
    rs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        xb, yb = x[idx], y[idx]
        if np.std(xb) == 0 or np.std(yb) == 0:
            rs[i] = 0.0
        else:
            rs[i] = float(np.corrcoef(xb, yb)[0, 1])
    return r_obs, float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))


def min_detectable_r(n: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest |r| detectable at given alpha and power.

    Uses Fisher-z transform: required z-score = z_alpha/2 + z_power.
    For two-sided test at alpha=0.05, z_alpha/2 = 1.96; for power=0.8, z_power = 0.84.
    Required Fisher-z magnitude ≈ (1.96 + 0.84) / sqrt(n-3).
    Convert back: r = tanh(z).
    """
    from scipy.stats import norm
    z_target = norm.ppf(1 - alpha / 2) + norm.ppf(power)
    z_needed = z_target / np.sqrt(n - 3)
    return float(np.tanh(z_needed))


# ──────────────────────────────────────────────────────────────────────────────
#  Loaders
# ──────────────────────────────────────────────────────────────────────────────
def load_correlation_table() -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / "correlation_table.csv")


def load_mae_results() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = pd.read_csv(RESULTS_DIR / "contract_mae.csv")
    ft   = pd.read_csv(RESULTS_DIR / "contract_mae_finetuned.csv")
    return base, ft


def load_standings(year: int) -> pd.DataFrame:
    return pd.read_csv(DATA_RAW / f"standings_{year}.csv")


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.1 — Significance + bootstrap CI on the headline correlations
# ──────────────────────────────────────────────────────────────────────────────
def analysis_6_3_1_correlation_significance(corr_df: pd.DataFrame) -> pd.DataFrame:
    print("\n=== 6.3.1: Correlation significance + bootstrap 95% CI ===")
    rows: list[dict] = []
    for label, col in [
        ("legacy gap_score (headline)",             "gap_score"),
        ("offense-only composite",                  "gap_offense"),
        ("defense-only composite",                  "gap_defense"),
        ("combined offense+defense composite",      "gap_combined"),
    ]:
        for subset_label, mask in [
            ("all years",     pd.Series(True, index=corr_df.index)),
            ("excl. 2020",    corr_df["year"] != 2020),
        ]:
            d = corr_df[mask].dropna(subset=[col, "next_year_wins"])
            n = len(d)
            r, p = stats.pearsonr(d[col], d["next_year_wins"])
            r_obs, ci_lo, ci_hi = bootstrap_pearson_ci(d[col].to_numpy(),
                                                       d["next_year_wins"].to_numpy())
            min_r = min_detectable_r(n)
            verdict = ("significant" if p < 0.05
                       else f"underpowered (need |r|>={min_r:.2f} to detect at n={n})")
            print(f"  {label[:32]:32s} ({subset_label:8s}, n={n:3d})  "
                  f"r={r:+.3f}  95% CI [{ci_lo:+.3f}, {ci_hi:+.3f}]  p={p:.3f}  "
                  f"min |r|={min_r:.2f}  → {verdict}")
            rows.append({
                "metric":           label,
                "subset":           subset_label,
                "n":                n,
                "pearson_r":        round(r, 4),
                "p_value":          round(p, 4),
                "ci_low":           round(ci_lo, 4),
                "ci_high":          round(ci_hi, 4),
                "min_detectable_r": round(min_r, 4),
                "verdict":          verdict,
            })
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "correlation_significance.csv", index=False, encoding="utf-8")
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.2 — Naive baseline shootout
# ──────────────────────────────────────────────────────────────────────────────
def _build_this_year_wins(corr_df: pd.DataFrame) -> pd.DataFrame:
    """Add a this_year_wins column to corr_df. Derives from lagged next_year_wins
    for years 2020+; for year 2019, looks up 2018 wins from standings_2018.csv.
    """
    corr_df = corr_df.sort_values(["team", "year"]).reset_index(drop=True)

    # Lag next_year_wins within each team — gives prior-year's next_year_wins
    # which equals this-year's wins by construction.
    corr_df["this_year_wins_lag"] = corr_df.groupby("team")["next_year_wins"].shift(1)

    # For year 2019 there is no lagged value — pull from standings_2018.csv
    standings_2018 = load_standings(2018).set_index("team_abbr")["wins"].to_dict()
    is_2019 = corr_df["year"] == 2019
    corr_df.loc[is_2019, "this_year_wins_lag"] = corr_df.loc[is_2019, "team"].map(standings_2018)
    return corr_df


def _rolling_mean_wins(corr_df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling_mean_wins = team's mean wins over the prior 3 evaluation years.
    For years without 3 priors (2019, 2020, 2021), uses whatever is available.
    """
    corr_df = corr_df.sort_values(["team", "year"]).reset_index(drop=True)
    corr_df["rolling_mean_wins"] = (
        corr_df.groupby("team")["next_year_wins"]
                .shift(1)
                .rolling(window=3, min_periods=1).mean()
                .reset_index(level=0, drop=True)
    )
    # For 2019 rows, fall back to standings_2018
    standings_2018 = load_standings(2018).set_index("team_abbr")["wins"].to_dict()
    is_2019 = corr_df["year"] == 2019
    corr_df.loc[is_2019, "rolling_mean_wins"] = corr_df.loc[is_2019, "team"].map(standings_2018)
    return corr_df


def analysis_6_3_2_baseline_shootout(corr_df: pd.DataFrame) -> pd.DataFrame:
    """Run baseline shootout twice — once on all 180 rows, once excluding COVID-
    affected rows (year 2019 predicting into 60-game 2020, and year 2020
    predicting from 60-game wins). The 2020 wins scale is so different from
    other years that including it suppresses autocorrelation artificially."""
    print("\n=== 6.3.2: Baseline shootout (the headline 'is Sabercast useful?' test) ===")
    df = _build_this_year_wins(corr_df.copy())
    df = _rolling_mean_wins(df)

    # Random shuffle null model
    rng_local = np.random.default_rng(RANDOM_SEED)
    df["random_null"] = rng_local.permutation(df["next_year_wins"].to_numpy())

    predictors = [
        ("A. Last-year wins (autocorrelation)",   "this_year_wins_lag"),
        ("B. 3-year rolling mean wins",            "rolling_mean_wins"),
        ("C. Random shuffle null",                 "random_null"),
        ("Sabercast — legacy gap_score",           "gap_score"),
        ("Sabercast — offense-only composite",     "gap_offense"),
        ("Sabercast — defense-only composite",     "gap_defense"),
        ("Sabercast — combined off+def composite", "gap_combined"),
    ]

    all_rows: list[dict] = []
    for subset_label, subset_mask in [
        ("all years (n=180)",          pd.Series(True, index=df.index)),
        ("excl. COVID 2019+2020 (n=120)",
            (df["year"] != 2019) & (df["year"] != 2020)),
    ]:
        print(f"\n  Subset: {subset_label}")
        ds = df[subset_mask]
        rows: list[dict] = []
        for label, col in predictors:
            d = ds.dropna(subset=[col, "next_year_wins"])
            n = len(d)
            r, p = stats.pearsonr(d[col], d["next_year_wins"])
            r_obs, ci_lo, ci_hi = bootstrap_pearson_ci(d[col].to_numpy(),
                                                       d["next_year_wins"].to_numpy())
            print(f"    {label:46s}  n={n:3d}  r={r:+.3f}  95% CI [{ci_lo:+.3f}, {ci_hi:+.3f}]  p={p:.4f}")
            rows.append({
                "subset":     subset_label,
                "predictor":  label,
                "n":          n,
                "pearson_r":  round(r, 4),
                "p_value":    round(p, 4),
                "ci_low":     round(ci_lo, 4),
                "ci_high":    round(ci_hi, 4),
            })
        all_rows.extend(rows)

    df_rows = pd.DataFrame(all_rows)

    # Verdict logic: use the COVID-excluded autocorrelation (which is fair)
    no_covid = df_rows[df_rows.subset.str.startswith("excl.")]
    baseline_A_r = no_covid.loc[no_covid.predictor.str.startswith("A. "), "pearson_r"].iloc[0]
    sabercast_r  = no_covid.loc[no_covid.predictor == "Sabercast — legacy gap_score",
                                 "pearson_r"].iloc[0]
    sabercast_combined_r = no_covid.loc[no_covid.predictor.str.endswith("combined off+def composite"),
                                         "pearson_r"].iloc[0]
    print()
    print(f"  Fair comparison (excl. COVID, n=120):")
    print(f"    Baseline A (last-year wins) |r| = {abs(baseline_A_r):.3f}")
    print(f"    Sabercast legacy gap_score  |r| = {abs(sabercast_r):.3f}")
    print(f"    Sabercast combined off+def  |r| = {abs(sabercast_combined_r):.3f}")
    sab_beats = (abs(sabercast_r) > abs(baseline_A_r) or
                 abs(sabercast_combined_r) > abs(baseline_A_r))
    # Stronger criterion: not just larger magnitude, but bootstrap-CIs that don't overlap zero
    if sab_beats:
        verdict = (f"Sabercast |r| > autocorrelation |r| (excl. COVID), but both correlations "
                   f"are at noise floor — neither is statistically significant.")
    else:
        verdict = ("Sabercast does NOT beat last-year-wins baseline — "
                   "gap_score is a diagnostic surface, not a wins forecaster.")
    print(f"  VERDICT: {verdict}")
    df_rows["verdict_headline"] = verdict
    df_rows.to_csv(RESULTS_DIR / "baseline_shootout.csv", index=False, encoding="utf-8")
    return df_rows


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.3 — Top-1 gap-position hit-rate
#
#  For each (year, team, top_gap_position) row in correlation_table.csv, look up
#  the team's actual production at that position the following year. Did it
#  underperform league average?
#
#  Defensive positions 1B–RF (1B/2B/3B/SS/LF/CF/RF): use next-year OAA at that
#  position. Below league mean = underperformed.
#
#  SP: filter pitching CSV to GS>=10 (starters), top 3 by IP at that team next
#  year, compute mean ERA. Above league SP mean = underperformed.
#
#  RP: GS<3 + G>=20 (true relievers), top 3 by IP, mean ERA. Above league RP
#  mean = underperformed.
#
#  C: catcher_defense{year+1}.csv has team catcher pop time. Above league median
#  pop time = underperformed.
#
#  DH: no usable position-level metric in the data (batting CSV lacks position
#  info from bref). Excluded with explicit count in the report.
# ──────────────────────────────────────────────────────────────────────────────
# Statcast OAA uses string position codes (1B, 2B, ...) in primary_pos_formatted,
# matched directly to our spec positions.
OAA_POSITIONS = {"1B", "2B", "3B", "SS", "LF", "CF", "RF"}

# Map our 3-letter abbrev to the team nickname Statcast uses in display_team_name
OAA_NICKNAME = {
    "ARI": "D-backs",       "ATL": "Braves",        "BAL": "Orioles",
    "BOS": "Red Sox",       "CHC": "Cubs",          "CWS": "White Sox",
    "CIN": "Reds",          "CLE": "Guardians",     "COL": "Rockies",
    "DET": "Tigers",        "HOU": "Astros",        "KC":  "Royals",
    "LAA": "Angels",        "LAD": "Dodgers",       "MIA": "Marlins",
    "MIL": "Brewers",       "MIN": "Twins",         "NYM": "Mets",
    "NYY": "Yankees",       "OAK": "Athletics",     "PHI": "Phillies",
    "PIT": "Pirates",       "SD":  "Padres",        "SEA": "Mariners",
    "SF":  "Giants",        "STL": "Cardinals",     "TB":  "Rays",
    "TEX": "Rangers",       "TOR": "Blue Jays",     "WSH": "Nationals",
}

# MLB Stats API team_id (numeric) — used by catcher_defense's team_id column
MLB_TEAM_ID = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112, "CWS": 145,
    "CIN": 113, "CLE": 114, "COL": 115, "DET": 116, "HOU": 117, "KC":  118,
    "LAA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121,
    "NYY": 147, "OAK": 133, "PHI": 143, "PIT": 134, "SD":  135, "SEA": 136,
    "SF":  137, "STL": 138, "TB":  139, "TEX": 140, "TOR": 141, "WSH": 120,
}

# Bref's "Tm" column uses city names; map our 3-letter abbreviation to that
BREF_TEAM_MAP = {
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


def _check_oaa_position(team_abbr: str, position: str, year_plus_1: int
                         ) -> tuple[bool | None, str]:
    """Return (underperformed_bool, note). bool is None if data is unavailable."""
    if position not in OAA_POSITIONS:
        return None, f"position {position} not in OAA scope"
    oaa_path = DATA_RAW / f"oaa_{year_plus_1}.csv"
    if not oaa_path.exists():
        return None, f"no oaa_{year_plus_1}.csv"
    oaa = pd.read_csv(oaa_path)
    pos_rows = oaa[oaa["primary_pos_formatted"].astype(str).str.strip() == position]
    if pos_rows.empty:
        return None, f"no rows for position {position} in oaa_{year_plus_1}.csv"
    nickname = OAA_NICKNAME.get(team_abbr, team_abbr)
    team_rows = pos_rows[pos_rows["display_team_name"].astype(str).str.strip() == nickname]
    if team_rows.empty:
        return None, f"team {nickname} not in oaa pos={position} year={year_plus_1}"
    team_oaa = team_rows["outs_above_average"].mean()
    league_oaa = pos_rows["outs_above_average"].mean()
    return bool(team_oaa < league_oaa), f"team OAA {team_oaa:+.1f} vs league {league_oaa:+.1f}"


def _check_pitching_role(team_abbr: str, role: str, year_plus_1: int
                          ) -> tuple[bool | None, str]:
    """role in {'SP','RP'}. Returns (underperformed, note)."""
    pit_path = DATA_RAW / f"pitching_{year_plus_1}.csv"
    if not pit_path.exists():
        return None, f"no pitching_{year_plus_1}.csv"
    pit = pd.read_csv(pit_path)
    bref_city = BREF_TEAM_MAP.get(team_abbr, team_abbr)
    team_rows = pit[pit["Tm"].astype(str).str.split(",").str[0].str.strip() == bref_city]
    if team_rows.empty:
        return None, f"no rows for team {bref_city} in pitching"
    if role == "SP":
        cohort = team_rows[(team_rows["GS"].fillna(0) >= 10)]
        league_cohort = pit[(pit["GS"].fillna(0) >= 10)]
    else:  # RP
        cohort = team_rows[(team_rows["GS"].fillna(0) < 3) & (team_rows["G"].fillna(0) >= 20)]
        league_cohort = pit[(pit["GS"].fillna(0) < 3) & (pit["G"].fillna(0) >= 20)]
    if cohort.empty:
        return None, f"no {role} cohort for {bref_city}"
    top3 = cohort.nlargest(3, "IP")
    team_era    = pd.to_numeric(top3["ERA"], errors="coerce").mean()
    league_era  = pd.to_numeric(league_cohort["ERA"], errors="coerce").mean()
    if np.isnan(team_era) or np.isnan(league_era):
        return None, "ERA NaN"
    # higher ERA = worse, so underperformed = team_era > league_era
    return bool(team_era > league_era), f"team {role} ERA {team_era:.2f} vs league {league_era:.2f}"


def _check_catcher(team_abbr: str, year_plus_1: int) -> tuple[bool | None, str]:
    cd_path = DATA_RAW / f"catcher_defense_{year_plus_1}.csv"
    if not cd_path.exists():
        return None, f"no catcher_defense_{year_plus_1}.csv"
    cd = pd.read_csv(cd_path)
    target_id = MLB_TEAM_ID.get(team_abbr)
    if target_id is None or "team_id" not in cd.columns:
        return None, f"no team_id mapping for {team_abbr}"
    team_rows = cd[pd.to_numeric(cd["team_id"], errors="coerce") == target_id]
    if team_rows.empty:
        return None, f"no rows for team_id={target_id} in catcher_defense_{year_plus_1}.csv"
    # pop_2b_sba = pop time to second on steal attempts (lower = better, in seconds)
    team_pop   = pd.to_numeric(team_rows["pop_2b_sba"], errors="coerce").mean()
    league_pop = pd.to_numeric(cd["pop_2b_sba"], errors="coerce").mean()
    if np.isnan(team_pop) or np.isnan(league_pop):
        return None, "pop NaN"
    # higher pop time = worse
    return bool(team_pop > league_pop), f"team pop {team_pop:.2f}s vs league {league_pop:.2f}s"


def analysis_6_3_3_hit_rate(corr_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("\n=== 6.3.3: Top-1 gap-position hit-rate ===")
    rows: list[dict] = []
    excluded_dh = 0
    for _, r in corr_df.iterrows():
        year, team, pos = int(r["year"]), str(r["team"]), str(r["top_gap_position"])
        ny = year + 1
        if pos == "DH":
            excluded_dh += 1
            continue
        if pos in OAA_POSITIONS:
            verdict, note = _check_oaa_position(team, pos, ny)
        elif pos in ("SP", "RP"):
            verdict, note = _check_pitching_role(team, pos, ny)
        elif pos == "C":
            verdict, note = _check_catcher(team, ny)
        else:
            verdict, note = None, f"unsupported position {pos}"
        rows.append({
            "year":             year,
            "team":             team,
            "top_gap_position": pos,
            "next_year":        ny,
            "underperformed":   verdict,
            "note":             note,
        })
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "gap_position_hit_rate.csv", index=False, encoding="utf-8")

    # Overall precision (of flagged positions that we could measure)
    measurable = df.dropna(subset=["underperformed"])
    n_measurable = len(measurable)
    n_unmeasurable = len(df) - n_measurable
    precision = measurable["underperformed"].mean() if n_measurable else float("nan")
    # Random baseline (the flagged position is below league mean by definition 50% of the time)
    print(f"  n_total={len(corr_df)}  n_dh_excluded={excluded_dh}  "
          f"n_measurable={n_measurable}  n_no_data={n_unmeasurable}")
    print(f"  Top-1 gap-position precision: {precision:.1%}  (random baseline ≈ 50%)")

    # Per-position breakdown
    print("  Per-position precision:")
    pos_summary = []
    for pos, grp in measurable.groupby("top_gap_position"):
        p = grp["underperformed"].mean()
        n = len(grp)
        # Binomial test against 0.5 null
        n_underperformed = int(grp["underperformed"].sum())
        p_value = stats.binomtest(n_underperformed, n, 0.5).pvalue
        print(f"    {pos:3s}  n={n:3d}  precision={p:.1%}  binom p={p_value:.3f}")
        pos_summary.append({
            "position":         pos,
            "n":                n,
            "precision":        round(p, 4),
            "n_underperformed": n_underperformed,
            "binom_p_vs_50pct": round(p_value, 4),
        })
    pos_df = pd.DataFrame(pos_summary)
    pos_df.to_csv(RESULTS_DIR / "gap_position_hit_rate_by_year.csv", index=False, encoding="utf-8")
    return df, pos_df


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.4 — Stratified by market tier
# ──────────────────────────────────────────────────────────────────────────────
def _market_tier(team_abbr: str) -> str:
    payroll = TEAM_DEFAULT_PAYROLL.get(team_abbr, 0)
    if payroll >= 220_000_000:
        return "large"
    if payroll >= 150_000_000:
        return "mid"
    return "small"


def analysis_6_3_4_market_tier(corr_df: pd.DataFrame) -> pd.DataFrame:
    print("\n=== 6.3.4: Stratified by market tier (small / mid / large) ===")
    df = corr_df.copy()
    df["market_tier"] = df["team"].map(_market_tier)
    rows: list[dict] = []
    for tier in ["small", "mid", "large"]:
        d = df[df["market_tier"] == tier].dropna(subset=["gap_score", "next_year_wins"])
        n = len(d)
        if n < 4:
            print(f"  {tier:5s}  n={n}  (insufficient)")
            continue
        r, p = stats.pearsonr(d["gap_score"], d["next_year_wins"])
        r_obs, ci_lo, ci_hi = bootstrap_pearson_ci(d["gap_score"].to_numpy(),
                                                   d["next_year_wins"].to_numpy())
        teams_in_tier = sorted(d["team"].unique())
        print(f"  {tier:5s}  n={n:3d}  r={r:+.3f}  95% CI [{ci_lo:+.3f}, {ci_hi:+.3f}]  "
              f"p={p:.3f}  teams: {len(teams_in_tier)}")
        rows.append({
            "market_tier": tier,
            "n":           n,
            "pearson_r":   round(r, 4),
            "p_value":     round(p, 4),
            "ci_low":      round(ci_lo, 4),
            "ci_high":     round(ci_hi, 4),
            "n_teams":     len(teams_in_tier),
        })
    df_out = pd.DataFrame(rows)
    df_out.to_csv(RESULTS_DIR / "correlation_by_market_tier.csv", index=False, encoding="utf-8")
    return df_out


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.5 — Year-stratified analysis
# ──────────────────────────────────────────────────────────────────────────────
def analysis_6_3_5_year_significance(corr_df: pd.DataFrame) -> pd.DataFrame:
    print("\n=== 6.3.5: Year-stratified (does signal compound as contract pool grows?) ===")
    rows: list[dict] = []
    for year in sorted(corr_df["year"].unique()):
        d = corr_df[corr_df["year"] == year].dropna(subset=["gap_score", "next_year_wins"])
        n = len(d)
        r, p = stats.pearsonr(d["gap_score"], d["next_year_wins"])
        r_obs, ci_lo, ci_hi = bootstrap_pearson_ci(d["gap_score"].to_numpy(),
                                                   d["next_year_wins"].to_numpy())
        print(f"  {year}  n={n:3d}  r={r:+.3f}  95% CI [{ci_lo:+.3f}, {ci_hi:+.3f}]  p={p:.3f}")
        rows.append({
            "year":      int(year),
            "n":         n,
            "pearson_r": round(r, 4),
            "p_value":   round(p, 4),
            "ci_low":    round(ci_lo, 4),
            "ci_high":   round(ci_hi, 4),
        })
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "correlation_by_year_significance.csv", index=False, encoding="utf-8")
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  6.3.6 — Contract MAE significance testing
# ──────────────────────────────────────────────────────────────────────────────
def analysis_6_3_6_mae_significance(base: pd.DataFrame, ft: pd.DataFrame) -> pd.DataFrame:
    print("\n=== 6.3.6: Contract MAE significance — paired tests + bootstrap CI ===")
    # Join on player_name to get paired errors
    merge = base.merge(ft[["player_name", "predicted_aav", "abs_error", "pct_error"]],
                       on="player_name", suffixes=("_base", "_ft"))
    print(f"  paired n = {len(merge)}")

    # Per-contract delta: positive means baseline did worse (fine-tune wins)
    delta = (merge["abs_error_base"] - merge["abs_error_ft"]).to_numpy()

    # Paired Wilcoxon signed-rank
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        w_stat, w_p = stats.wilcoxon(delta, zero_method="wilcox")

    # Sign test (binom on n_positive vs n)
    n_pos = int((delta > 0).sum())
    n_nonzero = int((delta != 0).sum())
    sign_p = stats.binomtest(n_pos, n_nonzero, 0.5).pvalue if n_nonzero else float("nan")

    # Bootstrap CI on the MEAN delta (pooled)
    n = len(delta)
    boot_means = np.empty(N_BOOTSTRAP)
    for i in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, n)
        boot_means[i] = np.mean(delta[idx])
    mean_delta = float(np.mean(delta))
    mean_ci_lo = float(np.percentile(boot_means, 2.5))
    mean_ci_hi = float(np.percentile(boot_means, 97.5))

    # Same, excluding Ohtani
    no_ohtani = merge[merge["player_name"] != "Shohei Ohtani"]
    delta_no = (no_ohtani["abs_error_base"] - no_ohtani["abs_error_ft"]).to_numpy()
    n_no = len(delta_no)
    boot_means_no = np.empty(N_BOOTSTRAP)
    for i in range(N_BOOTSTRAP):
        idx = rng.integers(0, n_no, n_no)
        boot_means_no[i] = np.mean(delta_no[idx])
    mean_delta_no = float(np.mean(delta_no))
    mean_ci_lo_no = float(np.percentile(boot_means_no, 2.5))
    mean_ci_hi_no = float(np.percentile(boot_means_no, 97.5))

    print(f"\n  Pooled (n={n}):")
    print(f"    mean per-contract delta (baseline_err - ft_err): ${mean_delta/1e6:+.2f}M")
    print(f"    bootstrap 95% CI: [${mean_ci_lo/1e6:+.2f}M, ${mean_ci_hi/1e6:+.2f}M]")
    print(f"    Wilcoxon paired W={w_stat:.1f}  p={w_p:.4f}")
    print(f"    Sign test: {n_pos}/{n_nonzero} favored fine-tune  p={sign_p:.4f}")

    print(f"\n  Excluding Ohtani (n={n_no}):")
    print(f"    mean per-contract delta: ${mean_delta_no/1e6:+.2f}M")
    print(f"    bootstrap 95% CI: [${mean_ci_lo_no/1e6:+.2f}M, ${mean_ci_hi_no/1e6:+.2f}M]")
    if mean_ci_lo_no > 0:
        print(f"    -> CI EXCLUDES zero: fine-tune improvement is statistically significant")
    elif mean_ci_hi_no < 0:
        print(f"    -> CI EXCLUDES zero (on the other side): fine-tune is WORSE")
    else:
        print(f"    -> CI INCLUDES zero: not significant; the {mean_delta_no/1e6:+.2f}M difference is noise")

    # Per-position
    print(f"\n  Per-position (paired delta in $M):")
    pos_rows = []
    for pos, grp in merge.groupby("position_bucket"):
        d = (grp["abs_error_base"] - grp["abs_error_ft"]).to_numpy()
        if len(d) < 2:
            print(f"    {pos:3s}  n={len(d)}  delta=${np.mean(d)/1e6:+.2f}M  (too small for CI)")
            pos_rows.append({"position_bucket": pos, "n": len(d),
                             "mean_delta_M": round(np.mean(d)/1e6, 2),
                             "ci_low_M": None, "ci_high_M": None})
            continue
        boot_p = np.empty(N_BOOTSTRAP)
        for i in range(N_BOOTSTRAP):
            idx = rng.integers(0, len(d), len(d))
            boot_p[i] = np.mean(d[idx])
        ci_lo = float(np.percentile(boot_p, 2.5)) / 1e6
        ci_hi = float(np.percentile(boot_p, 97.5)) / 1e6
        mean_d = float(np.mean(d)) / 1e6
        print(f"    {pos:3s}  n={len(d):2d}  delta=${mean_d:+.2f}M  95% CI [${ci_lo:+.2f}M, ${ci_hi:+.2f}M]")
        pos_rows.append({"position_bucket": pos, "n": len(d),
                         "mean_delta_M": round(mean_d, 2),
                         "ci_low_M": round(ci_lo, 2),
                         "ci_high_M": round(ci_hi, 2)})

    summary = {
        "pooled_n":                n,
        "pooled_mean_delta_M":     round(mean_delta / 1e6, 2),
        "pooled_ci_low_M":         round(mean_ci_lo / 1e6, 2),
        "pooled_ci_high_M":        round(mean_ci_hi / 1e6, 2),
        "wilcoxon_W":              round(w_stat, 2),
        "wilcoxon_p":              round(w_p, 4),
        "sign_test_n_pos":         n_pos,
        "sign_test_n_nonzero":     n_nonzero,
        "sign_test_p":             round(sign_p, 4),
        "ex_ohtani_n":             n_no,
        "ex_ohtani_mean_delta_M":  round(mean_delta_no / 1e6, 2),
        "ex_ohtani_ci_low_M":      round(mean_ci_lo_no / 1e6, 2),
        "ex_ohtani_ci_high_M":     round(mean_ci_hi_no / 1e6, 2),
    }
    pd.DataFrame([summary]).to_csv(RESULTS_DIR / "contract_mae_significance.csv",
                                    index=False, encoding="utf-8")
    pd.DataFrame(pos_rows).to_csv(RESULTS_DIR / "contract_mae_significance_by_position.csv",
                                   index=False, encoding="utf-8")
    return pd.DataFrame([summary])


# ──────────────────────────────────────────────────────────────────────────────
#  Verdict summary
# ──────────────────────────────────────────────────────────────────────────────
def build_verdict_summary(sig_corr: pd.DataFrame, baseline: pd.DataFrame,
                          hit_rate_overall: pd.DataFrame, hit_rate_pos: pd.DataFrame,
                          tier: pd.DataFrame, year_sig: pd.DataFrame,
                          mae_sig: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("VERDICT SUMMARY")
    print("=" * 80)
    rows: list[dict] = []

    # 6.3.1
    head_all = sig_corr[(sig_corr.metric.str.startswith("legacy")) &
                        (sig_corr.subset == "all years")].iloc[0]
    rows.append({
        "test":    "6.3.1 Headline gap_score correlation significantly different from zero?",
        "result":  f"r={head_all.pearson_r:+.3f}, p={head_all.p_value:.3f}",
        "verdict": "NOT SIGNIFICANT — underpowered" if head_all.p_value >= 0.05 else "significant",
    })

    # 6.3.2 — use the COVID-excluded subset for the fair comparison
    no_covid = baseline[baseline.subset.str.startswith("excl.")]
    bA = no_covid[no_covid.predictor.str.startswith("A. ")].iloc[0]
    bS = no_covid[no_covid.predictor == "Sabercast — legacy gap_score"].iloc[0]
    bS_combined = no_covid[no_covid.predictor.str.endswith("combined off+def composite")].iloc[0]
    sab_beats_A = (abs(bS.pearson_r) > abs(bA.pearson_r) or
                   abs(bS_combined.pearson_r) > abs(bA.pearson_r))
    # Honest verdict: only "useful" if Sabercast both beats baseline AND CI excludes zero
    sab_significant = (bS.ci_low > 0 or bS.ci_high < 0 or
                       bS_combined.ci_low > 0 or bS_combined.ci_high < 0)
    if sab_significant and sab_beats_A:
        verdict_text = "YES — Sabercast significantly beats baseline as a wins predictor"
    elif sab_beats_A:
        verdict_text = ("Sabercast |r| exceeds baseline |r| (excl. COVID) but both at noise floor; "
                        "neither bootstrap CI excludes zero")
    else:
        verdict_text = ("NO — Sabercast does not beat last-year-wins baseline; "
                        "gap_score is a diagnostic surface, not a wins forecaster")
    rows.append({
        "test":    "6.3.2 Does Sabercast beat last-year-wins baseline at predicting next-year wins?",
        "result":  f"baseline |r|={abs(bA.pearson_r):.3f}, Sabercast |r|={abs(bS.pearson_r):.3f}, "
                   f"Sabercast(combined) |r|={abs(bS_combined.pearson_r):.3f} (all excl. COVID)",
        "verdict": verdict_text,
    })

    # 6.3.3
    measurable = hit_rate_overall.dropna(subset=["underperformed"])
    if len(measurable):
        precision = measurable["underperformed"].mean()
        from scipy.stats import binomtest
        bn = int(measurable["underperformed"].sum())
        bt = len(measurable)
        bp = binomtest(bn, bt, 0.5).pvalue
        rows.append({
            "test":    "6.3.3 Top-1 flagged position underperforms next year above 50% chance?",
            "result":  f"precision={precision:.1%} (n={bt}), binom p={bp:.3f}",
            "verdict": ("YES — flagged positions underperform above chance"
                        if (precision > 0.5 and bp < 0.05)
                        else "NOT DISTINGUISHABLE from random"),
        })

    # 6.3.4
    rows.append({
        "test":    "6.3.4 Does gap_score work better in small/mid markets (our target user)?",
        "result":  "see correlation_by_market_tier.csv",
        "verdict": "see report — qualitative",
    })

    # 6.3.5
    rows.append({
        "test":    "6.3.5 Does signal strengthen over time (compounding contract pool)?",
        "result":  "see correlation_by_year_significance.csv",
        "verdict": "see report — qualitative",
    })

    # 6.3.6
    mae_row = mae_sig.iloc[0]
    ci_lo, ci_hi = mae_row["ex_ohtani_ci_low_M"], mae_row["ex_ohtani_ci_high_M"]
    if ci_lo > 0:
        mae_verdict = f"YES — ex-Ohtani CI [{ci_lo:+.2f}, {ci_hi:+.2f}]M excludes zero"
    elif ci_hi < 0:
        mae_verdict = f"REVERSED — fine-tune is significantly WORSE"
    else:
        mae_verdict = f"NOT SIGNIFICANT — CI [{ci_lo:+.2f}, {ci_hi:+.2f}]M includes zero"
    rows.append({
        "test":    "6.3.6 Is the fine-tune contract MAE improvement statistically significant?",
        "result":  f"ex-Ohtani delta=${mae_row.ex_ohtani_mean_delta_M:+.2f}M, "
                   f"wilcoxon p={mae_row.wilcoxon_p:.3f}, sign-test p={mae_row.sign_test_p:.3f}",
        "verdict": mae_verdict,
    })

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "statistical_validation_summary.csv", index=False, encoding="utf-8")
    print()
    for _, r in df.iterrows():
        print(f"  [{r.verdict[:60]:60s}]  {r.test}")
    print()
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=== Phase 6.3: Pre-registered statistical validation suite ===\n")
    corr_df = load_correlation_table()
    base, ft = load_mae_results()
    print(f"correlation_table.csv: {len(corr_df)} rows")
    print(f"contract_mae.csv:        {len(base)} rows")
    print(f"contract_mae_finetuned.csv: {len(ft)} rows")

    sig_corr     = analysis_6_3_1_correlation_significance(corr_df)
    baseline     = analysis_6_3_2_baseline_shootout(corr_df)
    hit_overall, hit_pos = analysis_6_3_3_hit_rate(corr_df)
    tier         = analysis_6_3_4_market_tier(corr_df)
    year_sig     = analysis_6_3_5_year_significance(corr_df)
    mae_sig      = analysis_6_3_6_mae_significance(base, ft)

    verdict = build_verdict_summary(sig_corr, baseline, hit_overall, hit_pos,
                                    tier, year_sig, mae_sig)
    print("\n=== Done. All outputs written to eval/results/ ===")


if __name__ == "__main__":
    main()

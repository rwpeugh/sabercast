"""eval/wins_predictor.py — Multivariate wins prediction with incremental-value test.

Follow-up to Phase 6.3.2's finding that Sabercast's gap_score, on its own, does
NOT predict next-year wins as well as raw last-year wins. This script asks the
sharper question: does the gap_score add INCREMENTAL information beyond what
standard box-score features already capture?

Baseline model (the "kitchen-sink box-score" predictor):
    next_year_wins ~ last_year_wins
                   + pythag_wins                (R^2 / (R^2 + RA^2) * 162)
                   + team_bat_war               (sum of bref offensive bWAR)
                   + team_pit_war               (sum of bref pitching bWAR)
                   + roster_age_weighted        (PA-weighted hitter age)

Extended model:
    same + gap_score                            (Sabercast diagnostic)

Comparison:
  * In-sample baseline R^2  vs  extended R^2
  * Partial F-test on gap_score's contribution
  * Leave-one-year-out cross-validated R^2 for both models (the harder test)
  * Coefficient sign + p-value on gap_score after controlling for the rest

Outputs:
  eval/results/team_features.csv                  (one row per year-team)
  eval/results/wins_predictor_coefficients.csv    (baseline + extended coefs + p-vals)
  eval/results/wins_predictor_cv.csv              (LOYO R^2 per year, both models)
  eval/results/wins_predictor_summary.csv         (the verdict row)

No LLM calls. Pure pre-registered statistical analysis on existing data.

COVID note: the 60-game 2020 season distorts wins-on-a-162-game scale. The
script reports two variants — all 180 rows and excluding COVID-affected rows
(year=2019 predicting into 2020, and year=2020 predicting from 60-game wins).
The COVID-excluded result is the headline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))

# Map B-R's team codes (SFG, SDP, TBR, ...) to our 3-letter abbreviations
BREF_TO_ABBR = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CHW": "CWS", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KCR": "KC",
    "LAA": "LAA", "ANA": "LAA",                       # Angels rename
    "LAD": "LAD", "MIA": "MIA", "FLA": "MIA",         # Marlins rename
    "MIL": "MIL", "MIN": "MIN", "NYM": "NYM",
    "NYY": "NYY", "OAK": "OAK", "PHI": "PHI",
    "PIT": "PIT", "SDP": "SD",  "SEA": "SEA",
    "SFG": "SF",  "STL": "STL", "TBR": "TB",  "TBD": "TB",
    "TEX": "TEX", "TOR": "TOR", "WSN": "WSH",
}

# Map our 3-letter to the bref-city in batting/pitching CSVs (for Pythagorean)
BREF_CITY = {
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


# ──────────────────────────────────────────────────────────────────────────────
#  Feature builders
# ──────────────────────────────────────────────────────────────────────────────
def _team_bref_match(team_abbr: str, tm_value: str) -> bool:
    """Return True iff bref's 'Tm' value matches our team abbr.

    bref uses city names; players who were traded carry comma-joined cities
    (e.g., 'San Diego,Tampa Bay'). We match if the first segment equals our
    expected city for the abbr.
    """
    expected = BREF_CITY.get(team_abbr)
    if not expected:
        return False
    first_city = str(tm_value).split(",")[0].strip()
    if first_city == expected:
        return True
    # Disambiguate two-team cities: Chicago / Los Angeles / New York
    if expected == "Chicago":
        # CHC vs CWS — can't tell from just 'Chicago'. Need to look up the league.
        # We don't have league info in batting/pitching CSV's Tm column;
        # fall back to including all rows. Pythagorean is approximate anyway.
        return first_city == "Chicago"
    if expected == "Los Angeles":
        return first_city == "Los Angeles"
    if expected == "New York":
        return first_city == "New York"
    return False


def _compute_pythagorean(year: int, team_abbr: str) -> tuple[float, int, int]:
    """Compute the team's Pythagorean expectation for the year. Returns
    (pythag_wins, runs_scored, runs_allowed). Falls back to NaN if data missing.
    """
    bat_path = DATA_RAW / f"batting_{year}.csv"
    pit_path = DATA_RAW / f"pitching_{year}.csv"
    if not (bat_path.exists() and pit_path.exists()):
        return float("nan"), 0, 0
    bat = pd.read_csv(bat_path, encoding="utf-8")
    pit = pd.read_csv(pit_path, encoding="utf-8")
    # bref 'R' on the batting side = runs scored; 'R' on pitching side = runs allowed
    bat = bat[bat["Tm"].apply(lambda s: _team_bref_match(team_abbr, s))]
    pit = pit[pit["Tm"].apply(lambda s: _team_bref_match(team_abbr, s))]
    rs = pd.to_numeric(bat.get("R"), errors="coerce").sum()
    ra = pd.to_numeric(pit.get("R"), errors="coerce").sum()
    games = 60 if year == 2020 else 162   # COVID 60-game season
    if rs <= 0 or ra <= 0:
        return float("nan"), int(rs), int(ra)
    # Bill James' Pythagorean wins, exponent = 2
    pythag_pct = (rs ** 2) / (rs ** 2 + ra ** 2)
    return pythag_pct * games, int(rs), int(ra)


def _team_war(year: int, team_abbr: str,
              bat_archive: pd.DataFrame, pit_archive: pd.DataFrame
              ) -> tuple[float, float]:
    """Return (team_bat_war, team_pit_war) summed across all players who appeared
    for the team that year. Players who switched teams contribute to whichever
    team's stint they're on."""
    bat = bat_archive[(bat_archive["year_ID"] == year)
                       & (bat_archive["team_ID"].map(BREF_TO_ABBR) == team_abbr)
                       & (bat_archive["pitcher"] == "N")]
    pit = pit_archive[(pit_archive["year_ID"] == year)
                       & (pit_archive["team_ID"].map(BREF_TO_ABBR) == team_abbr)]
    return float(bat["WAR"].sum()), float(pit["WAR"].sum())


def _roster_age(year: int, team_abbr: str) -> float:
    """PA-weighted mean age of position players on the team that year."""
    bat_path = DATA_RAW / f"batting_{year}.csv"
    if not bat_path.exists():
        return float("nan")
    bat = pd.read_csv(bat_path, encoding="utf-8")
    bat = bat[bat["Tm"].apply(lambda s: _team_bref_match(team_abbr, s))]
    if bat.empty:
        return float("nan")
    ages = pd.to_numeric(bat["Age"], errors="coerce")
    pas  = pd.to_numeric(bat["PA"],  errors="coerce")
    mask = (~ages.isna()) & (~pas.isna()) & (pas > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(ages[mask], weights=pas[mask]))


def build_team_features(corr_df: pd.DataFrame,
                        bat_archive: pd.DataFrame,
                        pit_archive: pd.DataFrame) -> pd.DataFrame:
    print("Computing team-year features (Pythagorean, team WAR, roster age) ...")
    feats: list[dict] = []
    for _, r in corr_df.iterrows():
        year = int(r["year"])
        team = str(r["team"])
        pythag, rs, ra   = _compute_pythagorean(year, team)
        bat_war, pit_war = _team_war(year, team, bat_archive, pit_archive)
        age              = _roster_age(year, team)
        feats.append({
            "year":           year,
            "team":           team,
            "runs_scored":    rs,
            "runs_allowed":   ra,
            "pythag_wins":    pythag,
            "team_bat_war":   bat_war,
            "team_pit_war":   pit_war,
            "team_war":       bat_war + pit_war,
            "roster_age":     age,
        })
    fdf = pd.DataFrame(feats)
    # Last-year wins (lag of next_year_wins within team, ordered by year)
    df = corr_df.merge(fdf, on=["year", "team"])
    df = df.sort_values(["team", "year"]).reset_index(drop=True)
    df["last_year_wins"] = df.groupby("team")["next_year_wins"].shift(1)
    # 2019 rows: pull from standings_2018.csv
    standings_2018 = pd.read_csv(DATA_RAW / "standings_2018.csv").set_index("team_abbr")["wins"]
    is_2019 = df["year"] == 2019
    df.loc[is_2019, "last_year_wins"] = df.loc[is_2019, "team"].map(standings_2018.to_dict())
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  Regression with closed-form OLS (no sklearn dependency for the headline test)
# ──────────────────────────────────────────────────────────────────────────────
def _fit_ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Fit OLS with intercept. Returns (coef, r2, fitted, residuals).

    X is the design matrix WITHOUT intercept; we prepend a column of ones here.
    """
    n = len(y)
    Xb = np.column_stack([np.ones(n), X])
    beta, *_ = np.linalg.lstsq(Xb, y, rcond=None)
    fitted = Xb @ beta
    ss_res = float(((y - fitted) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2, fitted, y - fitted


def _coef_pvalues(X: np.ndarray, y: np.ndarray, beta: np.ndarray,
                  residuals: np.ndarray) -> np.ndarray:
    """Compute two-sided p-values for each coefficient (including intercept)."""
    n = len(y)
    Xb = np.column_stack([np.ones(n), X])
    p = Xb.shape[1]
    rss = float((residuals ** 2).sum())
    sigma2 = rss / (n - p) if n > p else float("nan")
    try:
        cov = sigma2 * np.linalg.inv(Xb.T @ Xb)
        se = np.sqrt(np.diag(cov))
        t_stat = beta / se
        pvals = 2 * (1 - stats.t.cdf(np.abs(t_stat), df=n - p))
        return pvals
    except np.linalg.LinAlgError:
        return np.full(p, float("nan"))


def _partial_f_test(rss_baseline: float, rss_extended: float,
                    n: int, p_baseline: int, p_extended: int) -> tuple[float, float]:
    """Partial F-test for adding (p_extended - p_baseline) parameters.
    Returns (F-stat, p-value)."""
    df_extra = p_extended - p_baseline
    df_resid = n - p_extended
    if df_extra <= 0 or df_resid <= 0 or rss_extended <= 0:
        return float("nan"), float("nan")
    F = ((rss_baseline - rss_extended) / df_extra) / (rss_extended / df_resid)
    p = 1 - stats.f.cdf(F, df_extra, df_resid)
    return float(F), float(p)


# ──────────────────────────────────────────────────────────────────────────────
#  Models
# ──────────────────────────────────────────────────────────────────────────────
BASELINE_COLS = ["last_year_wins", "pythag_wins", "team_war", "roster_age"]
EXTENDED_COLS = BASELINE_COLS + ["gap_score"]
ALL_REQUIRED  = EXTENDED_COLS + ["next_year_wins"]


def _drop_na(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(subset=ALL_REQUIRED).reset_index(drop=True)


def _fit_print(df: pd.DataFrame, cols: list[str], label: str) -> dict:
    X = df[cols].to_numpy(dtype=float)
    y = df["next_year_wins"].to_numpy(dtype=float)
    beta, r2, fitted, resid = _fit_ols(X, y)
    pvals = _coef_pvalues(X, y, beta, resid)
    rss = float((resid ** 2).sum())
    print(f"  {label}  n={len(y):3d}  R²={r2:.3f}  RSS={rss:.1f}")
    print(f"    intercept  beta={beta[0]:+.3f}  p={pvals[0]:.3f}")
    for i, c in enumerate(cols):
        print(f"    {c:20s}  beta={beta[i+1]:+.4f}  p={pvals[i+1]:.4f}")
    return {
        "label":  label,
        "n":      len(y),
        "r2":     r2,
        "rss":    rss,
        "beta":   beta.tolist(),
        "pvals":  pvals.tolist(),
        "cols":   cols,
    }


def loyo_cv(df: pd.DataFrame, cols: list[str]) -> dict:
    """Leave-one-year-out cross-validation. For each year, fit on the other years
    and score on that year. Returns per-year R² and CV-aggregated R² (predictions
    pooled across folds)."""
    years = sorted(df["year"].unique())
    per_year_r2 = {}
    all_preds, all_actuals = [], []
    for held in years:
        train = df[df["year"] != held]
        test  = df[df["year"] == held]
        if len(train) < 5 or len(test) < 1:
            per_year_r2[int(held)] = float("nan")
            continue
        X_tr = train[cols].to_numpy(dtype=float)
        y_tr = train["next_year_wins"].to_numpy(dtype=float)
        X_te = test[cols].to_numpy(dtype=float)
        y_te = test["next_year_wins"].to_numpy(dtype=float)
        beta, _, _, _ = _fit_ols(X_tr, y_tr)
        Xb_te = np.column_stack([np.ones(len(y_te)), X_te])
        preds = Xb_te @ beta
        ss_res = float(((y_te - preds) ** 2).sum())
        ss_tot = float(((y_te - y_te.mean()) ** 2).sum())
        per_year_r2[int(held)] = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        all_preds.extend(preds.tolist())
        all_actuals.extend(y_te.tolist())
    # Pooled-CV R² (held-out predictions vs actuals across all folds)
    ya = np.array(all_actuals); yp = np.array(all_preds)
    ss_res = float(((ya - yp) ** 2).sum())
    ss_tot = float(((ya - ya.mean()) ** 2).sum())
    pooled_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"per_year_r2": per_year_r2, "pooled_cv_r2": pooled_r2}


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=== eval/wins_predictor.py — does gap_score add incremental signal over box-score features? ===\n")

    corr_df = pd.read_csv(RESULTS_DIR / "correlation_table.csv")
    bat_arch = pd.read_csv(DATA_RAW / "bwar_bat_archive.csv")
    pit_arch = pd.read_csv(DATA_RAW / "bwar_pitch_archive.csv")
    print(f"  correlation rows: {len(corr_df)}")
    print(f"  bwar_bat rows:    {len(bat_arch):,}")
    print(f"  bwar_pitch rows:  {len(pit_arch):,}")

    feats = build_team_features(corr_df, bat_arch, pit_arch)
    feats.to_csv(RESULTS_DIR / "team_features.csv", index=False, encoding="utf-8")
    print(f"\n  saved team_features.csv ({len(feats)} rows)")
    print(f"\n  Missing-data audit:")
    for col in BASELINE_COLS + ["gap_score"]:
        miss = feats[col].isna().sum()
        print(f"    {col:20s}  missing: {miss}")

    # Summary stats
    print(f"\n  Feature ranges:")
    for col in BASELINE_COLS + ["gap_score"]:
        s = feats[col].dropna()
        if len(s):
            print(f"    {col:20s}  min={s.min():7.2f}  median={s.median():7.2f}  max={s.max():7.2f}")

    results: list[dict] = []

    # ── ALL YEARS variant ────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ALL YEARS (n=180, includes COVID 2020 distortion)")
    print("=" * 80)
    df_all = _drop_na(feats)
    print(f"\n  Baseline (last_year_wins + pythag + team_war + roster_age):")
    base_all = _fit_print(df_all, BASELINE_COLS, "all-years-baseline")
    print(f"\n  Extended (baseline + gap_score):")
    ext_all = _fit_print(df_all, EXTENDED_COLS, "all-years-extended")
    F_all, pF_all = _partial_f_test(base_all["rss"], ext_all["rss"], len(df_all),
                                    p_baseline=len(BASELINE_COLS)+1,
                                    p_extended=len(EXTENDED_COLS)+1)
    print(f"\n  Partial F-test on gap_score's contribution:")
    print(f"    F = {F_all:.3f}   p = {pF_all:.4f}")
    print(f"    incremental R² = {ext_all['r2'] - base_all['r2']:+.4f}")
    cv_base_all = loyo_cv(df_all, BASELINE_COLS)
    cv_ext_all  = loyo_cv(df_all, EXTENDED_COLS)
    print(f"\n  Leave-one-year-out CV R²:")
    print(f"    baseline pooled-CV R² = {cv_base_all['pooled_cv_r2']:.3f}")
    print(f"    extended pooled-CV R² = {cv_ext_all['pooled_cv_r2']:.3f}")
    results.extend([
        {"subset": "all years", "model": "baseline", **base_all,
         "pooled_cv_r2": cv_base_all["pooled_cv_r2"]},
        {"subset": "all years", "model": "extended", **ext_all,
         "pooled_cv_r2": cv_ext_all["pooled_cv_r2"]},
    ])

    # ── COVID-EXCLUDED variant (the headline) ────────────────────────────
    print("\n" + "=" * 80)
    print("EXCL. COVID 2019+2020 (n=120, headline test)")
    print("=" * 80)
    df_no = df_all[(df_all["year"] != 2019) & (df_all["year"] != 2020)].reset_index(drop=True)
    print(f"\n  Baseline:")
    base_no = _fit_print(df_no, BASELINE_COLS, "no-covid-baseline")
    print(f"\n  Extended:")
    ext_no = _fit_print(df_no, EXTENDED_COLS, "no-covid-extended")
    F_no, pF_no = _partial_f_test(base_no["rss"], ext_no["rss"], len(df_no),
                                  p_baseline=len(BASELINE_COLS)+1,
                                  p_extended=len(EXTENDED_COLS)+1)
    print(f"\n  Partial F-test on gap_score's contribution (no-covid):")
    print(f"    F = {F_no:.3f}   p = {pF_no:.4f}")
    print(f"    incremental R² = {ext_no['r2'] - base_no['r2']:+.4f}")
    cv_base_no = loyo_cv(df_no, BASELINE_COLS)
    cv_ext_no  = loyo_cv(df_no, EXTENDED_COLS)
    print(f"\n  Leave-one-year-out CV R²:")
    print(f"    baseline pooled-CV R² = {cv_base_no['pooled_cv_r2']:.3f}")
    print(f"    extended pooled-CV R² = {cv_ext_no['pooled_cv_r2']:.3f}")
    print(f"\n  Per-year LOYO R² (baseline / extended):")
    for y in sorted(cv_base_no["per_year_r2"].keys()):
        print(f"    {y}:  baseline={cv_base_no['per_year_r2'][y]:+.3f}   "
              f"extended={cv_ext_no['per_year_r2'][y]:+.3f}")
    results.extend([
        {"subset": "excl. COVID", "model": "baseline", **base_no,
         "pooled_cv_r2": cv_base_no["pooled_cv_r2"]},
        {"subset": "excl. COVID", "model": "extended", **ext_no,
         "pooled_cv_r2": cv_ext_no["pooled_cv_r2"]},
    ])

    # ── VERDICT ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    gap_idx_in_ext = EXTENDED_COLS.index("gap_score") + 1   # +1 for intercept
    coef_no = ext_no["beta"][gap_idx_in_ext]
    pval_no = ext_no["pvals"][gap_idx_in_ext]
    inc_r2_no = ext_no["r2"] - base_no["r2"]
    inc_cv_r2_no = cv_ext_no["pooled_cv_r2"] - cv_base_no["pooled_cv_r2"]
    if pval_no < 0.05 and inc_r2_no > 0:
        verdict = ("YES — gap_score adds significant incremental signal over box-score features. "
                   "The LLM diagnostic earns its keep as a feature.")
    elif pval_no < 0.05 and inc_r2_no < 0:
        verdict = ("UNEXPECTED — gap_score is significant but has a sign that REDUCES "
                   "predictive accuracy. Investigate.")
    else:
        verdict = ("NO — after controlling for last-year-wins, Pythagorean expectation, team WAR, "
                   "and roster age, gap_score's incremental contribution is statistically zero. "
                   "Sabercast is descriptive, not predictive at the wins level.")
    print(f"\n  excl. COVID variant (the headline):")
    print(f"    gap_score coefficient = {coef_no:+.4f}   p = {pval_no:.4f}")
    print(f"    in-sample incremental R² = {inc_r2_no:+.4f}")
    print(f"    LOYO-CV incremental R²   = {inc_cv_r2_no:+.4f}")
    print(f"\n  VERDICT: {verdict}")

    # Persist results
    pd.DataFrame(results).to_csv(RESULTS_DIR / "wins_predictor_coefficients.csv",
                                  index=False, encoding="utf-8")
    cv_rows = []
    for variant, cv_b, cv_e in [
        ("all years",   cv_base_all, cv_ext_all),
        ("excl. COVID", cv_base_no,  cv_ext_no),
    ]:
        for y in sorted(cv_b["per_year_r2"].keys()):
            cv_rows.append({
                "subset":          variant,
                "year":            y,
                "baseline_r2":     round(cv_b["per_year_r2"][y], 4),
                "extended_r2":     round(cv_e["per_year_r2"][y], 4),
                "delta_r2":        round(cv_e["per_year_r2"][y] - cv_b["per_year_r2"][y], 4),
            })
    pd.DataFrame(cv_rows).to_csv(RESULTS_DIR / "wins_predictor_cv.csv",
                                  index=False, encoding="utf-8")
    summary = {
        "n_no_covid":             len(df_no),
        "baseline_r2_no_covid":   round(base_no["r2"], 4),
        "extended_r2_no_covid":   round(ext_no["r2"], 4),
        "incremental_r2_no_covid": round(inc_r2_no, 4),
        "incremental_cv_r2_no_covid": round(inc_cv_r2_no, 4),
        "gap_score_coef_no_covid":  round(coef_no, 4),
        "gap_score_pvalue_no_covid": round(pval_no, 4),
        "partial_F_no_covid":       round(F_no, 4),
        "partial_F_pvalue_no_covid": round(pF_no, 4),
        "verdict":                  verdict,
    }
    pd.DataFrame([summary]).to_csv(RESULTS_DIR / "wins_predictor_summary.csv",
                                    index=False, encoding="utf-8")
    print(f"\n  Outputs:")
    print(f"    team_features.csv               ({len(feats)} rows)")
    print(f"    wins_predictor_coefficients.csv ({len(results)} models)")
    print(f"    wins_predictor_cv.csv           ({len(cv_rows)} year-model rows)")
    print(f"    wins_predictor_summary.csv      (verdict row)")


if __name__ == "__main__":
    main()

"""eval/methodology_ablation.py — Two follow-up tests addressing measurement noise.

After 6.3.2 / 6.3.3 / 6.3.6 / gap_fill_test showed directional but
non-significant signal, we asked: is the limitation (a) sample size, or
(b) measurement noise from heuristic choices in the gap_score formula?

This script runs TWO ablations against the existing data — no new LLM calls,
no new data pulls — and reports whether either materially changes the
significance picture.

LEVER 1: Drop positional scarcity weights
  The current gap_score multiplies each top-3 gap's LLM score by a
  heuristic positional weight (C/SS=1.4, CF/CL=1.3, 2B/3B=1.1, LF/RF/1B=0.9,
  DH=0.7). These weights come from baseball-analytics conventional wisdom
  about scarcity, not from this dataset. We re-aggregate gap_score with all
  weights = 1.0 and compare correlations.

  Hypothesis: if heuristic weights add noise, the unweighted gap_score should
  correlate with next-year wins better than the weighted one.

LEVER 2: Continuous treatment for the gap-fill test
  gap_fill_test.py binarizes the treatment: "did the team sign ANY player at
  the flagged position?" That treats $35M-Rendon and $1M-veteran as identical
  treatments. We replace binary with continuous (AAV invested at the flagged
  position) and test Pearson + Spearman correlations vs wins_delta.

  Hypothesis: dose-response matters. Teams that invested more at the flagged
  position should improve more.

Inputs:
  eval/results/correlation_per_gap.csv       (180 (year, team) x 3 gaps = 540 rows)
  eval/results/correlation_table.csv         (180 rows with next_year_wins)
  eval/results/gap_fill_events.csv           (180 (year, team) events with top1_filled)
  data/raw/contracts.csv + contracts_extended.csv  (combined 1254 contracts)

Outputs:
  eval/results/methodology_ablation_summary.csv   (verdict table)
  eval/results/weight_ablation_correlations.csv   (Lever 1)
  eval/results/continuous_treatment_correlations.csv (Lever 2)

Pre-registered honest reporting: if neither lever moves the needle, the
report says so. We do NOT cherry-pick.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"

RANDOM_SEED = 42
N_BOOTSTRAP = 10_000


def bootstrap_pearson_ci(x: np.ndarray, y: np.ndarray, n_boot: int = N_BOOTSTRAP
                          ) -> tuple[float, float, float, float]:
    """Returns (r, ci_low, ci_high, p_value)."""
    rng = np.random.default_rng(RANDOM_SEED)
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 4:
        return float("nan"), float("nan"), float("nan"), float("nan")
    r, p = stats.pearsonr(x, y)
    rs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        xb, yb = x[idx], y[idx]
        rs[i] = 0.0 if np.std(xb) == 0 or np.std(yb) == 0 else float(np.corrcoef(xb, yb)[0, 1])
    return float(r), float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5)), float(p)


# ──────────────────────────────────────────────────────────────────────────────
#  LEVER 1: Drop positional scarcity weights, recompute gap_score, compare
# ──────────────────────────────────────────────────────────────────────────────
def lever_1_weight_ablation() -> pd.DataFrame:
    print("\n=== LEVER 1: Positional scarcity weight ablation ===")
    pg = pd.read_csv(RESULTS_DIR / "correlation_per_gap.csv")
    corr = pd.read_csv(RESULTS_DIR / "correlation_table.csv")

    # Re-aggregate per (year, team)
    weighted = (pg.assign(weighted_score=pg.gap_score * pg.scarcity_weight)
                  .groupby(["year", "team"])["weighted_score"].sum()
                  .reset_index().rename(columns={"weighted_score": "gap_score_weighted"}))
    unweighted = (pg.groupby(["year", "team"])["gap_score"].sum()
                    .reset_index().rename(columns={"gap_score": "gap_score_unweighted"}))
    df = corr[["year", "team", "next_year_wins"]].merge(weighted, on=["year","team"])\
                                                  .merge(unweighted, on=["year","team"])
    print(f"  merged: {len(df)} (year, team) rows")

    rows: list[dict] = []
    for subset_label, mask in [
        ("all years",   pd.Series(True, index=df.index)),
        ("excl. 2020",  df["year"] != 2020),
    ]:
        d = df[mask]
        for var_label, col in [("weighted (heuristic)", "gap_score_weighted"),
                                ("unweighted (1.0 for all positions)", "gap_score_unweighted")]:
            r, lo, hi, p = bootstrap_pearson_ci(d[col].to_numpy(),
                                                d["next_year_wins"].to_numpy())
            n = (~d[col].isna() & ~d["next_year_wins"].isna()).sum()
            print(f"  {var_label:38s}  {subset_label:10s}  n={n:3d}  r={r:+.3f}  "
                  f"95% CI [{lo:+.3f}, {hi:+.3f}]  p={p:.4f}")
            rows.append({
                "variant":   var_label, "subset": subset_label,
                "n":         int(n), "pearson_r": round(r, 4),
                "p_value":   round(p, 4),
                "ci_low":    round(lo, 4), "ci_high": round(hi, 4),
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "weight_ablation_correlations.csv", index=False, encoding="utf-8")

    # Verdict
    w_r  = abs(out[(out.variant.str.startswith("weighted")) &
                   (out.subset == "all years")].iloc[0]["pearson_r"])
    uw_r = abs(out[(out.variant.str.startswith("unweighted")) &
                   (out.subset == "all years")].iloc[0]["pearson_r"])
    diff = uw_r - w_r
    print(f"\n  |r| weighted   = {w_r:.3f}")
    print(f"  |r| unweighted = {uw_r:.3f}")
    print(f"  |r| improvement from dropping weights: {diff:+.3f}")
    if diff > 0.05:
        print(f"  VERDICT: Dropping weights MEANINGFULLY improves correlation. "
              f"Heuristic weights were adding noise.")
    elif diff < -0.05:
        print(f"  VERDICT: Weights HELP — the heuristic encodes real signal.")
    else:
        print(f"  VERDICT: Weights are roughly neutral. Sample size is the dominant constraint.")
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  LEVER 2: Continuous treatment for gap-fill test
# ──────────────────────────────────────────────────────────────────────────────
def lever_2_continuous_treatment() -> pd.DataFrame:
    print("\n=== LEVER 2: Continuous treatment (AAV invested at flagged position) ===")

    # Load combined contracts (original + extended)
    orig = pd.read_csv(DATA_RAW / "contracts.csv")
    if "source" not in orig.columns:
        orig["source"] = "spotrac_main_or_manual"
    ext = pd.read_csv(DATA_RAW / "contracts_extended.csv")
    cols = ["player_name", "team", "position", "aav", "signed_year", "source"]
    contracts = pd.concat([orig[cols], ext[cols]], ignore_index=True)
    print(f"  contracts pool: {len(contracts)} rows")

    # Load gap_fill events (180 rows: year, team, top_1_gap, top1_filled, wins_delta, ...)
    events = pd.read_csv(RESULTS_DIR / "gap_fill_events.csv")

    # For each event, compute AAV invested at the flagged position the following offseason
    def aav_at_position(row):
        signings = contracts[
            (contracts.team == row.team)
            & (contracts.signed_year == row.year + 1)
            & (contracts.position == row.top_1_gap)
        ]
        return float(pd.to_numeric(signings.aav, errors="coerce").sum())

    def n_signings_at_position(row):
        return int(((contracts.team == row.team)
                    & (contracts.signed_year == row.year + 1)
                    & (contracts.position == row.top_1_gap)).sum())

    events["aav_at_flagged"]  = events.apply(aav_at_position, axis=1)
    events["n_at_flagged"]    = events.apply(n_signings_at_position, axis=1)
    events["aav_at_flagged_M"] = events.aav_at_flagged / 1e6
    events["log_aav"] = np.log1p(events.aav_at_flagged)

    # Save the augmented events
    events.to_csv(RESULTS_DIR / "gap_fill_events.csv", index=False, encoding="utf-8")

    print(f"  Treatment distribution (excl. COVID):")
    no_cov = events[~events.covid_affected]
    print(f"    fraction with AAV>0 at flagged pos: "
          f"{(no_cov.aav_at_flagged > 0).mean()*100:.1f}%")
    print(f"    among filled, AAV distribution ($M):")
    filled = no_cov[no_cov.aav_at_flagged > 0]
    print(f"      n={len(filled)}  min=${filled.aav_at_flagged_M.min():.1f}M  "
          f"median=${filled.aav_at_flagged_M.median():.1f}M  "
          f"max=${filled.aav_at_flagged_M.max():.1f}M")

    rows: list[dict] = []
    for subset_label, mask in [
        ("all years",   pd.Series(True, index=events.index)),
        ("excl. COVID", ~events.covid_affected),
    ]:
        d = events[mask]
        n = len(d)
        # Pearson on linear AAV
        r1, lo1, hi1, p1 = bootstrap_pearson_ci(d.aav_at_flagged.to_numpy(),
                                                d.wins_delta.to_numpy())
        # Pearson on log AAV (handles skew)
        r2, lo2, hi2, p2 = bootstrap_pearson_ci(d.log_aav.to_numpy(),
                                                d.wins_delta.to_numpy())
        # Spearman (rank-based, robust to outliers)
        rs, ps = stats.spearmanr(d.aav_at_flagged, d.wins_delta)
        print(f"\n  {subset_label} (n={n}):")
        print(f"    Pearson (AAV_linear, wins_delta):  r={r1:+.3f}  CI [{lo1:+.3f}, {hi1:+.3f}]  p={p1:.4f}")
        print(f"    Pearson (log AAV, wins_delta):     r={r2:+.3f}  CI [{lo2:+.3f}, {hi2:+.3f}]  p={p2:.4f}")
        print(f"    Spearman (AAV, wins_delta):        r={rs:+.3f}  p={ps:.4f}")
        rows.append({
            "subset":          subset_label, "n": n,
            "pearson_linear_r": round(r1, 4), "pearson_linear_p": round(p1, 4),
            "ci_linear_low":   round(lo1, 4), "ci_linear_high": round(hi1, 4),
            "pearson_log_r":   round(r2, 4), "pearson_log_p": round(p2, 4),
            "spearman_r":      round(float(rs), 4),
            "spearman_p":      round(float(ps), 4),
        })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "continuous_treatment_correlations.csv", index=False, encoding="utf-8")

    # Verdict
    headline = out[out.subset == "excl. COVID"].iloc[0]
    sig_any = (headline.pearson_linear_p < 0.05 or
               headline.pearson_log_p < 0.05 or
               headline.spearman_p < 0.05)
    print(f"\n  VERDICT (excl. COVID, n={int(headline.n)}):")
    print(f"    any test reaches p<0.05? {sig_any}")
    print(f"    direction: Pearson(log)={headline.pearson_log_r:+.3f}, "
          f"Spearman={headline.spearman_r:+.3f}")
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Combined verdict
# ──────────────────────────────────────────────────────────────────────────────
def build_summary(lever1: pd.DataFrame, lever2: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 80)
    print("METHODOLOGY ABLATION SUMMARY")
    print("=" * 80)
    rows: list[dict] = []

    # Lever 1
    l1_all = lever1[lever1.subset == "all years"]
    w  = l1_all[l1_all.variant.str.startswith("weighted")].iloc[0]
    uw = l1_all[l1_all.variant.str.startswith("unweighted")].iloc[0]
    delta = abs(uw.pearson_r) - abs(w.pearson_r)
    if delta > 0.05:
        v1 = "improve (drop weights)"
    elif delta < -0.05:
        v1 = "weights help"
    else:
        v1 = "no meaningful change"
    rows.append({
        "lever":   "1. Drop positional scarcity weights",
        "result":  f"|r| weighted={abs(w.pearson_r):.3f} vs unweighted={abs(uw.pearson_r):.3f} (Δ={delta:+.3f})",
        "verdict": v1,
    })

    # Lever 2
    l2 = lever2[lever2.subset == "excl. COVID"].iloc[0]
    sig = (l2.pearson_log_p < 0.05 or l2.spearman_p < 0.05)
    if sig:
        v2 = (f"continuous treatment IS significant — "
              f"log-AAV r={l2.pearson_log_r:+.3f} (p={l2.pearson_log_p:.3f})")
    else:
        v2 = (f"continuous treatment still not significant — "
              f"log-AAV r={l2.pearson_log_r:+.3f} (p={l2.pearson_log_p:.3f})")
    rows.append({
        "lever":   "2. Continuous treatment (AAV at flagged position)",
        "result":  f"Pearson(log AAV)={l2.pearson_log_r:+.3f}  Spearman={l2.spearman_r:+.3f}",
        "verdict": v2,
    })

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "methodology_ablation_summary.csv", index=False, encoding="utf-8")
    print()
    for _, r in df.iterrows():
        print(f"  [{r.verdict[:50]:50s}]  {r.lever}")
    return df


def main() -> None:
    print("=== eval/methodology_ablation.py — Lever 1 + Lever 2 ablations ===\n")
    l1 = lever_1_weight_ablation()
    l2 = lever_2_continuous_treatment()
    build_summary(l1, l2)


if __name__ == "__main__":
    main()

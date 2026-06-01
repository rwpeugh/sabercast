"""eval/gap_fill_test.py — Does filling Sabercast's top-1 flagged gap correlate with wins improvement?

Pre-registered observational test (no causal claims). For each (year, team)
row in our 180-row correlation table:

  1. Read the team's TOP-1 flagged gap position from
     eval/results/correlation_table.csv (the existing `top_gap_position`
     column, set during the original correlation study).
  2. Find every contract signed during the Y -> Y+1 offseason at this team.
     We use both contracts.csv (115 top-tier deals) AND
     contracts_extended.csv (~1139 mid-tier deals scraped from Spotrac's FA
     tracker) — combined ~1250 contracts.
  3. Was the top-1 flagged gap filled by any Y+1 signing? (binary)
  4. Compute wins_delta = next_year_wins - this_year_wins.

We use top-1 (not top-3) because (a) it mirrors how Sabercast surfaces its
"highest priority gap" to the user, (b) all 180 team-years have top-1
data committed (the top-3 cache only has year=2024 due to a stale-cache
issue from data refreshes), and (c) the top-1 framing tests the strongest
prediction the system makes per (year, team).

Two statistical tests:

  TEST A (overall):  does "top-1 flagged gap filled" correlate with wins_delta?
    Mann-Whitney U on filled vs unfilled subsets of wins_delta.

  TEST B (by position): stratify by top-1 position. For each position P,
    compare wins_delta when teams with P-flagged filled at P vs didn't.
    These tests will be especially relevant for 2B and LF where Phase 6.3.3's
    next-year-defensive-OAA hit-rate test surfaced real signal.

Outputs:
  eval/results/gap_fill_events.csv         (one row per (year, team) event)
  eval/results/gap_fill_test_summary.csv   (verdict row)
  eval/results/gap_fill_by_position.csv    (Test B per-position breakdown)

LIMITATIONS we acknowledge openly:
  * Observational, not experimental. Teams that sign expensive FAs are richer /
    more competitive / more ambitious. We cannot isolate Sabercast's "recommendation"
    effect from those confounders.
  * Trades not captured. A big trade at the flagged position would fill the gap
    but isn't in our FA-only contract data.
  * Departures not tracked. A team that signs at 1B but loses its 2B has a muddied
    net effect that we can't measure.
  * Standings_2019.csv needed for the 2019 wins_delta (this_year_wins lookup);
    pulled via pipelines/01b_pull_standings.py.
  * Honest reporting commitment: even if the result is null or against us,
    we report it. Pre-registered in this docstring.
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
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
#  Loaders
# ──────────────────────────────────────────────────────────────────────────────
def load_combined_contracts() -> pd.DataFrame:
    """Combine contracts.csv (original 115) + contracts_extended.csv (~1139)."""
    original  = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    if "source" not in original.columns:
        original["source"] = "spotrac_main_or_manual"
    extended = pd.read_csv(DATA_RAW / "contracts_extended.csv", encoding="utf-8")
    # Align columns
    cols = ["player_name", "team", "position", "age", "contract_value", "aav",
            "years", "signed_year", "source"]
    for df in (original, extended):
        for c in cols:
            if c not in df.columns:
                df[c] = None
    combined = pd.concat([original[cols], extended[cols]], ignore_index=True)
    print(f"  combined contracts: {len(original)} original + {len(extended)} extended = {len(combined)}")
    return combined


def load_top1_gap_index(corr_df: pd.DataFrame) -> dict:
    """Build (year, team) -> top-1 flagged position from correlation_table.csv.
    This is the column the original correlation study persisted for all 180 rows.
    """
    by_key: dict[tuple[int, str], str] = {}
    for _, r in corr_df.iterrows():
        year = int(r["year"])
        team = str(r["team"])
        pos  = str(r.get("top_gap_position") or "").strip()
        if pos:
            by_key[(year, team)] = pos
    print(f"  top-1 gap index: {len(by_key)} (year, team) entries")
    return by_key


def load_this_year_wins(corr_df: pd.DataFrame) -> pd.DataFrame:
    """Add this_year_wins column to corr_df.

    For years 2020-2024, derive from the prior-year row's next_year_wins.
    For 2019, look up from standings_2019.csv.
    """
    df = corr_df.sort_values(["team", "year"]).reset_index(drop=True)
    df["this_year_wins_derived"] = df.groupby("team")["next_year_wins"].shift(1)

    standings_files = {
        2019: DATA_RAW / "standings_2019.csv",
    }
    standings_2019 = pd.read_csv(standings_files[2019]).set_index("team_abbr")["wins"].to_dict()
    is_2019 = df["year"] == 2019
    df.loc[is_2019, "this_year_wins_derived"] = df.loc[is_2019, "team"].map(standings_2019)
    df = df.rename(columns={"this_year_wins_derived": "this_year_wins"})
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  Core analysis
# ──────────────────────────────────────────────────────────────────────────────
def build_gap_fill_events(corr_df: pd.DataFrame,
                           top1_by_key: dict,
                           contracts: pd.DataFrame) -> pd.DataFrame:
    """For each (year, team), record whether the top-1 flagged gap was filled
    by a Y+1 offseason signing."""
    rows: list[dict] = []
    for _, r in corr_df.iterrows():
        year = int(r["year"])
        team = str(r["team"])
        top1 = top1_by_key.get((year, team))
        if not top1:
            continue
        this_wins = r.get("this_year_wins")
        next_wins = r.get("next_year_wins")
        if pd.isna(this_wins) or pd.isna(next_wins):
            continue
        wins_delta = int(next_wins) - int(this_wins)

        # Find offseason signings at this team that take effect for year Y+1
        signings = contracts[
            (contracts["team"].astype(str) == team)
            & (contracts["signed_year"] == year + 1)
        ]
        signed_positions = signings["position"].astype(str).tolist()
        top1_filled = top1 in signed_positions
        rows.append({
            "year":              year,
            "team":              team,
            "top_1_gap":         top1,
            "this_year_wins":    int(this_wins),
            "next_year_wins":    int(next_wins),
            "wins_delta":        wins_delta,
            "n_signings":        len(signings),
            "signing_positions": ",".join(sorted(set(signed_positions))),
            "top1_filled":       top1_filled,
            "covid_affected":    year in (2019, 2020),
        })
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "gap_fill_events.csv", index=False, encoding="utf-8")
    print(f"  built {len(df)} (year, team) event rows")
    return df


def test_a_overall(events: pd.DataFrame, exclude_covid: bool = True) -> dict:
    """TEST A: does top-1 gap filled correlate with wins_delta?"""
    df = events[~events.covid_affected] if exclude_covid else events
    label = "excl. COVID 2019+2020" if exclude_covid else "all years"
    print(f"\n  Subset: {label} (n={len(df)})")

    filled = df[df.top1_filled]["wins_delta"].to_numpy()
    unfilled = df[~df.top1_filled]["wins_delta"].to_numpy()
    print(f"    top-1 filled:   n={len(filled):3d}  mean wins_delta = {filled.mean():+.2f}  "
          f"median = {np.median(filled):+.2f}")
    print(f"    top-1 unfilled: n={len(unfilled):3d}  mean wins_delta = {unfilled.mean():+.2f}  "
          f"median = {np.median(unfilled):+.2f}")
    if len(filled) < 3 or len(unfilled) < 3:
        return {"label": label, "n_filled": len(filled), "n_unfilled": len(unfilled),
                "verdict": "insufficient sample sizes"}
    u_stat, u_p = stats.mannwhitneyu(filled, unfilled, alternative="two-sided")
    diff = float(filled.mean()) - float(unfilled.mean())
    print(f"    Mann-Whitney U={u_stat:.1f}  p={u_p:.4f}")
    print(f"    mean diff (filled - unfilled) = {diff:+.2f} wins")

    if u_p < 0.05 and diff > 0:
        verdict = ("filling the top-1 flagged gap correlates with HIGHER wins next year (p<0.05). "
                   "Causation NOT claimed — selection bias remains a confound.")
    elif u_p < 0.05 and diff < 0:
        verdict = ("filling the top-1 flagged gap correlates with LOWER wins next year (p<0.05). "
                   "Unexpected.")
    else:
        verdict = ("no significant difference in wins_delta between teams that filled vs. did not "
                   "fill the top-1 flagged gap.")
    return {
        "label":           label,
        "n_filled":        len(filled), "filled_mean_delta": round(float(filled.mean()), 2),
        "n_unfilled":      len(unfilled), "unfilled_mean_delta": round(float(unfilled.mean()), 2),
        "diff_wins":       round(diff, 2),
        "u_stat":          round(float(u_stat), 1),
        "u_p":             round(float(u_p), 4),
        "verdict":         verdict,
    }


def test_b_by_position(events: pd.DataFrame, exclude_covid: bool = True) -> pd.DataFrame:
    """TEST B: stratify by top-1 gap position. For each position P with sufficient
    sample, compare wins_delta between teams that filled at P vs didn't.
    """
    print("\n  Per-position breakdown (excl. COVID):")
    df = events[~events.covid_affected] if exclude_covid else events

    rows: list[dict] = []
    for pos, grp in df.groupby("top_1_gap"):
        filled = grp[grp.top1_filled]["wins_delta"].to_numpy()
        unfilled = grp[~grp.top1_filled]["wins_delta"].to_numpy()
        if len(filled) < 3 or len(unfilled) < 3:
            print(f"    {pos:3s}  n_filled={len(filled):2d}  n_unfilled={len(unfilled):2d}  "
                  f"(too small for Mann-Whitney)")
            rows.append({
                "position":    pos,
                "n_filled":    len(filled),
                "n_unfilled":  len(unfilled),
                "filled_mean_delta":   round(filled.mean(), 2) if len(filled) else None,
                "unfilled_mean_delta": round(unfilled.mean(), 2) if len(unfilled) else None,
                "diff_wins":   None,
                "u_p":         None,
            })
            continue
        u_stat, u_p = stats.mannwhitneyu(filled, unfilled, alternative="two-sided")
        diff = float(filled.mean()) - float(unfilled.mean())
        print(f"    {pos:3s}  n_filled={len(filled):2d}  n_unfilled={len(unfilled):2d}  "
              f"diff = {diff:+5.2f} wins  Mann-Whitney p={u_p:.3f}")
        rows.append({
            "position":            pos,
            "n_filled":            len(filled),
            "n_unfilled":          len(unfilled),
            "filled_mean_delta":   round(float(filled.mean()), 2),
            "unfilled_mean_delta": round(float(unfilled.mean()), 2),
            "diff_wins":           round(diff, 2),
            "u_p":                 round(float(u_p), 4),
        })
    pos_summary = pd.DataFrame(rows)
    pos_summary.to_csv(RESULTS_DIR / "gap_fill_by_position.csv", index=False, encoding="utf-8")
    return pos_summary


# ──────────────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=== eval/gap_fill_test.py — does filling the top-1 flagged gap correlate with wins improvement? ===\n")
    contracts = load_combined_contracts()
    corr_df = pd.read_csv(RESULTS_DIR / "correlation_table.csv")
    corr_df = load_this_year_wins(corr_df)
    print(f"  correlation rows: {len(corr_df)}")
    top1_idx = load_top1_gap_index(corr_df)

    events = build_gap_fill_events(corr_df, top1_idx, contracts)

    print(f"\n  Event distribution (excl. COVID):")
    no_covid = events[~events.covid_affected]
    print(f"    top-1 filled rate: {no_covid.top1_filled.mean() * 100:.1f}% "
          f"({no_covid.top1_filled.sum()}/{len(no_covid)})")

    test_a_results = test_a_overall(events, exclude_covid=True)
    pos_summary = test_b_by_position(events, exclude_covid=True)

    # Headline verdict
    print("\n" + "=" * 80)
    print("VERDICT (Test A, COVID-excluded headline)")
    print("=" * 80)
    print(f"  {test_a_results['verdict']}")
    print()
    print(f"  Significant per-position findings (p < 0.05):")
    sig = pos_summary[(pos_summary.u_p.notna()) & (pos_summary.u_p < 0.05)]
    if sig.empty:
        print(f"    None — no individual position shows a significant filled-vs-unfilled wins delta")
    else:
        for _, r in sig.iterrows():
            print(f"    {r.position}  diff={r.diff_wins:+.2f} wins  p={r.u_p:.3f}  "
                  f"(n_filled={r.n_filled}, n_unfilled={r.n_unfilled})")

    pd.DataFrame([test_a_results]).to_csv(
        RESULTS_DIR / "gap_fill_test_summary.csv", index=False, encoding="utf-8",
    )
    print(f"\nOutputs:")
    print(f"  eval/results/gap_fill_events.csv")
    print(f"  eval/results/gap_fill_by_position.csv")
    print(f"  eval/results/gap_fill_test_summary.csv")


if __name__ == "__main__":
    main()

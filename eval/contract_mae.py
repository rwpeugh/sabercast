"""eval/contract_mae.py — Held-out contract valuation accuracy.

Methodology:
  1. Sample N test contracts from contracts.csv, signed in 2019–2024 (so the
     player's signing-year stats are on disk).
  2. For each test contract:
     a. Look up the player's stats from the signing year (their "platform year").
        Skip the contract if no qualifying stats exist for that name/year.
     b. Build the comparable pool: contracts at the same position with
        signed_year STRICTLY LESS than the test contract's signed_year. This
        prevents leakage — the LLM cannot see the test contract or later
        contracts at the same position.
     c. Call ``forecast_target_contract_llm`` with the player profile, the
        comparables, and market_year = test contract's signed_year.
     d. Compare the forecasted AAV to the actual contract AAV.
  3. Compute MAE pooled and by position group.

CLI flags:
  --use-finetuned   Route the forecaster to the Together AI Llama-3.1-8B model
                    fine-tuned by pipelines/05c. Results are written to
                    contract_mae_finetuned.csv so the baseline file is preserved.

Outputs (baseline run):
  eval/results/contract_mae.csv             — one row per held-out contract
  eval/results/contract_mae_scatter.png     — predicted vs actual AAV
  eval/results/contract_mae_by_position.csv — MAE broken down by position bucket

Outputs (--use-finetuned run):
  eval/results/contract_mae_finetuned.csv
  eval/results/contract_mae_finetuned_scatter.png
  eval/results/contract_mae_finetuned_by_position.csv
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from core.orchestrator import (                                # noqa: E402
    forecast_target_contract_llm, _lookup_player_stats, _ascii_fold,
)

TEST_N      = 30
RANDOM_SEED = 42
SIGNED_YEAR_RANGE = range(2019, 2025)   # 2019–2024 inclusive
N_COMPARABLES     = 5                   # comparables shown to the LLM

POSITION_BUCKETS = {
    "C":  "C",
    "1B": "IF", "2B": "IF", "3B": "IF", "SS": "IF",
    "LF": "OF", "CF": "OF", "RF": "OF", "OF": "OF",
    "DH": "DH",
    "SP": "SP", "RP": "RP",
}


def _load_batting_pitching_for_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    bat = pd.read_csv(DATA_RAW / f"batting_{year}.csv",  encoding="utf-8")
    pit = pd.read_csv(DATA_RAW / f"pitching_{year}.csv", encoding="utf-8")
    return bat, pit


def _pick_comparables(contracts: pd.DataFrame, test_position: str,
                      test_signed_year: int, test_player_name: str,
                      bat_year: pd.DataFrame, pit_year: pd.DataFrame,
                      k: int = N_COMPARABLES) -> list[dict]:
    """Comparable contracts at the same position, signed strictly before the
    test contract's signed_year, excluding the test player themselves.
    Stats for each comparable use the test contract's signing-year stats (so
    the LLM sees the comparable's recent profile as of the time of the test).
    """
    pool = contracts[
        (contracts["position"] == test_position)
        & (contracts["signed_year"].fillna(9999) < test_signed_year)
        & (contracts["player_name"] != test_player_name)
    ].copy()
    if pool.empty:
        return []
    pool = pool.sort_values("aav", ascending=False).head(k)
    rows: list[dict] = []
    for _, r in pool.iterrows():
        stats = _lookup_player_stats(r["player_name"], bat_year, pit_year, test_position)
        rows.append({
            "player_name": r["player_name"],
            "team":        r["team"],
            "position":    r["position"],
            "aav":         int(r["aav"]) if pd.notna(r.get("aav")) else None,
            "years":       int(r["years"]) if pd.notna(r.get("years")) else None,
            "total_value": int(r["contract_value"]) if pd.notna(r.get("contract_value")) else None,
            "signed_year": int(r["signed_year"]) if pd.notna(r.get("signed_year")) else None,
            "age_at_signing": int(r["age"]) if pd.notna(r.get("age")) else None,
            "stats_2024":  stats,    # legacy key — forecaster reads this field
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--use-finetuned", action="store_true",
        help="Route the forecaster to the Together AI fine-tuned model.",
    )
    args = parser.parse_args()

    suffix = "_finetuned" if args.use_finetuned else ""
    if args.use_finetuned:
        print("=== Running with Together AI fine-tuned forecaster ===")
    else:
        print("=== Running with OpenAI gpt-4o-mini baseline forecaster ===")

    contracts = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    print(f"Loaded {len(contracts)} contracts.")

    # Filter to contracts signed in 2019–2024 (stats available)
    eligible = contracts[contracts["signed_year"].isin(list(SIGNED_YEAR_RANGE))].copy()
    print(f"Eligible (signed 2019-2024): {len(eligible)}")

    random.seed(RANDOM_SEED)
    test_idx = random.sample(range(len(eligible)), min(TEST_N, len(eligible)))
    test_contracts = eligible.iloc[test_idx].reset_index(drop=True)
    print(f"Sampled {len(test_contracts)} test contracts (seed={RANDOM_SEED}).")

    rows: list[dict] = []
    skipped = 0
    for i, c in test_contracts.iterrows():
        name        = c["player_name"]
        position    = c["position"]
        signed_year = int(c["signed_year"]) if pd.notna(c["signed_year"]) else None
        actual_aav  = float(c["aav"])      if pd.notna(c["aav"])         else None
        if signed_year is None or actual_aav is None:
            skipped += 1
            continue

        # Stats from the signing year
        bat_year, pit_year = _load_batting_pitching_for_year(signed_year)
        stats = _lookup_player_stats(name, bat_year, pit_year, position)
        if stats is None:
            skipped += 1
            print(f"  [SKIP] {name} ({position}, {signed_year}) — no stats row")
            continue

        # Comparables: same position, signed strictly before this contract
        comparables = _pick_comparables(
            contracts, position, signed_year, name, bat_year, pit_year,
            k=N_COMPARABLES,
        )
        if not comparables:
            skipped += 1
            print(f"  [SKIP] {name} ({position}, {signed_year}) — no prior comparables")
            continue

        player_dict = {
            "player_name":  name,
            "team":         c["team"],
            "position":     position,
            "aav":          int(actual_aav),
            "years":        int(c["years"]) if pd.notna(c["years"]) else None,
            "signed_year":  signed_year,
            "age_at_signing": int(c["age"]) if pd.notna(c["age"]) else None,
            "stats_2024":   stats,    # legacy key — forecaster reads this
        }

        try:
            forecast = forecast_target_contract_llm(
                player=player_dict, position=position,
                comparables=comparables, market_year=signed_year,
                use_finetuned=args.use_finetuned,
            )
        except Exception as e:                              # noqa: BLE001
            print(f"  [FAIL] {name} ({position}, {signed_year}): {type(e).__name__}: {e}")
            skipped += 1
            continue

        predicted_aav = forecast.get("forecast_aav")
        if predicted_aav is None:
            skipped += 1
            continue

        abs_err = abs(int(predicted_aav) - int(actual_aav))
        print(f"  {name:25s} ({position:3s}, {signed_year})  "
              f"actual=${actual_aav/1e6:5.1f}M  predicted=${predicted_aav/1e6:5.1f}M  "
              f"abs_err=${abs_err/1e6:5.1f}M")

        rows.append({
            "player_name":      name,
            "position":         position,
            "position_bucket":  POSITION_BUCKETS.get(position, position),
            "signed_year":      signed_year,
            "actual_aav":       int(actual_aav),
            "predicted_aav":    int(predicted_aav),
            "abs_error":        abs_err,
            "pct_error":        round(abs_err / actual_aav * 100, 1) if actual_aav else None,
            "forecast_rationale": forecast.get("rationale", ""),
            "n_comparables":    len(comparables),
        })
        time.sleep(1.0)   # courteous pacing under TPM limits

    if not rows:
        raise SystemExit("No predictions produced — aborting.")

    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / f"contract_mae{suffix}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\nSaved {out_csv} ({len(df)} predictions, {skipped} skipped)")

    # ── MAE pooled and by position bucket ──────────────────────────────────
    mae = df["abs_error"].mean()
    median_err = df["abs_error"].median()
    print(f"\nPooled MAE      : ${mae/1e6:.2f}M   (n={len(df)})")
    print(f"Pooled median   : ${median_err/1e6:.2f}M")
    print(f"Pooled MAPE     : {df['pct_error'].mean():.1f}%")

    by_pos = df.groupby("position_bucket").agg(
        n=("abs_error", "size"),
        mae=("abs_error", "mean"),
        median_abs_err=("abs_error", "median"),
        mape=("pct_error", "mean"),
    ).reset_index()
    print("\nMAE by position bucket:")
    print(by_pos.to_string(index=False))
    out_pos = RESULTS_DIR / f"contract_mae{suffix}_by_position.csv"
    by_pos.to_csv(out_pos, index=False, encoding="utf-8")
    print(f"Saved {out_pos}")

    # ── Scatter plot ───────────────────────────────────────────────────────
    df_plot = df.copy()
    df_plot["actual_aav_M"]    = df_plot["actual_aav"]    / 1e6
    df_plot["predicted_aav_M"] = df_plot["predicted_aav"] / 1e6
    title_prefix = ("Fine-tuned forecaster" if args.use_finetuned
                    else "Baseline gpt-4o-mini")
    fig = px.scatter(
        df_plot, x="actual_aav_M", y="predicted_aav_M",
        color="position_bucket",
        hover_data=["player_name", "signed_year", "pct_error"],
        labels={"actual_aav_M": "Actual AAV ($M)",
                "predicted_aav_M": "Forecast AAV ($M)",
                "position_bucket": "Position group"},
        title=(f"{title_prefix} — pooled MAE ${mae/1e6:.2f}M "
               f"(n={len(df)} contracts signed 2019–2024)"),
    )
    # 45-degree perfect-prediction line
    max_aav = max(df_plot["actual_aav_M"].max(), df_plot["predicted_aav_M"].max()) * 1.05
    fig.add_shape(type="line", x0=0, y0=0, x1=max_aav, y1=max_aav,
                  line=dict(color="gray", dash="dash"))
    fig.update_layout(width=900, height=650)
    out_png = RESULTS_DIR / f"contract_mae{suffix}_scatter.png"
    fig.write_image(str(out_png))
    print(f"Saved {out_png}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nElapsed: {time.time() - t0:.1f}s")

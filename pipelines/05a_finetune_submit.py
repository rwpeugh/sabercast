"""Pipeline 05a — Submit a fine-tuning job for the contract valuator.

Methodology:
  1. Load contracts.csv (115 contracts).
  2. Filter to contracts signed 2019-2024 (so signing-year stats are on disk).
  3. Use the SAME random.seed(42) test indices as eval/contract_mae.py to hold
     out the test set. The fine-tuning training data is everything else.
  4. For each training contract, build one OpenAI chat-format example:
       system    = TARGET_FORECAST_SYSTEM (same prompt as the runtime forecaster)
       user      = player profile + position-matched prior comparables
       assistant = the actual contract terms as the labeled JSON output
  5. Upload the JSONL file, submit a fine-tuning job against the
     ``gpt-4o-mini-2024-07-18`` base model, write meta JSON for the harvest step.

No leakage: each training example's comparables are contracts with
signed_year strictly less than the target contract's signed_year. The 30
contracts held out for the contract_mae evaluation are NEVER used as
training inputs.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import pandas as pd
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
DATA_PROC.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from app.config import get_openai_api_key                       # noqa: E402
from core.orchestrator import (                                # noqa: E402
    TARGET_FORECAST_SYSTEM, _lookup_player_stats,
)

# Must match eval/contract_mae.py exactly so the held-out set is identical
TEST_N            = 30
RANDOM_SEED       = 42
SIGNED_YEAR_RANGE = range(2019, 2025)
N_COMPARABLES     = 5

BASE_MODEL        = "gpt-4o-mini-2024-07-18"


def _load_year_csvs(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    bat = pd.read_csv(DATA_RAW / f"batting_{year}.csv",  encoding="utf-8")
    pit = pd.read_csv(DATA_RAW / f"pitching_{year}.csv", encoding="utf-8")
    return bat, pit


def _pick_comparables(contracts: pd.DataFrame, test_position: str,
                      test_signed_year: int, test_player_name: str,
                      bat_year: pd.DataFrame, pit_year: pd.DataFrame,
                      k: int = N_COMPARABLES) -> list[dict]:
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
            "aav":         int(r["aav"])            if pd.notna(r.get("aav"))            else None,
            "years":       int(r["years"])          if pd.notna(r.get("years"))          else None,
            "total_value": int(r["contract_value"]) if pd.notna(r.get("contract_value")) else None,
            "signed_year": int(r["signed_year"])    if pd.notna(r.get("signed_year"))    else None,
            "age_at_signing": int(r["age"])          if pd.notna(r.get("age"))            else None,
            "stats_2024":  stats,
        })
    return rows


def _format_user_payload(name: str, position: str, age: int | None,
                         stats: dict, comparables: list[dict],
                         market_year: int) -> str:
    return json.dumps({
        "player_name":  name,
        "position":     position,
        "age_now":      age,
        "stats_2024":   stats,
        "current_contract": None,        # withheld at training time
        "position_comparables": comparables,
        "market_year":  market_year,
        "instruction": (
            f"You are pricing this contract as if it were signed in the offseason "
            f"following the {market_year - 1} regular season. Do not reference or "
            f"assume any market events after {market_year}."
        ),
    }, default=str)


def _format_assistant_target(name: str, actual_aav: int, actual_years: int,
                              top_comparable: dict | None) -> str:
    """Construct the labeled assistant output. The rationale is a generic
    comparable-anchored phrase; the model will learn its own rationale style
    during fine-tuning."""
    if top_comparable:
        rationale = (
            f"Forecast anchored to {top_comparable['player_name']} "
            f"(${(top_comparable.get('aav') or 0)/1e6:.1f}M AAV at the same position)"
        )
    else:
        rationale = "Forecast based on player profile and position scarcity"
    return json.dumps({
        "player_name":     name,
        "forecast_aav":    int(actual_aav),
        "forecast_years":  int(actual_years),
        "rationale":       rationale,
    })


def build_training_jsonl(test_indices: set[int]) -> Path:
    contracts = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    eligible = contracts[contracts["signed_year"].isin(list(SIGNED_YEAR_RANGE))].reset_index(drop=True)

    out_path = DATA_PROC / "finetune_train_2019_2024.jsonl"
    examples = 0
    skipped = 0
    with out_path.open("w", encoding="utf-8") as f:
        for idx, c in eligible.iterrows():
            if idx in test_indices:
                continue   # never train on held-out test contracts

            name        = c["player_name"]
            position    = c["position"]
            signed_year = int(c["signed_year"])  if pd.notna(c.get("signed_year")) else None
            actual_aav  = int(c["aav"])           if pd.notna(c.get("aav"))         else None
            actual_yrs  = int(c["years"])         if pd.notna(c.get("years"))       else None
            age         = int(c["age"])           if pd.notna(c.get("age"))         else None
            if not (signed_year and actual_aav and actual_yrs):
                skipped += 1
                continue

            bat_year, pit_year = _load_year_csvs(signed_year)
            stats = _lookup_player_stats(name, bat_year, pit_year, position)
            if stats is None:
                skipped += 1
                continue

            comparables = _pick_comparables(contracts, position, signed_year,
                                            name, bat_year, pit_year)
            if not comparables:
                skipped += 1
                continue

            user_str = _format_user_payload(name, position, age, stats,
                                            comparables, signed_year)
            asst_str = _format_assistant_target(name, actual_aav, actual_yrs,
                                                top_comparable=comparables[0])

            f.write(json.dumps({
                "messages": [
                    {"role": "system",    "content": TARGET_FORECAST_SYSTEM
                        .replace("{market_year}", str(signed_year))
                        .replace("{prior_year}",  str(signed_year - 1))},
                    {"role": "user",      "content": user_str},
                    {"role": "assistant", "content": asst_str},
                ]
            }) + "\n")
            examples += 1

    print(f"Built {examples} training examples → {out_path.name}  ({skipped} skipped)")
    return out_path


def _held_out_indices() -> set[int]:
    """Same logic eval/contract_mae.py uses to pick its 30 held-out contracts.
    Returns indices into the ``eligible`` frame (contracts signed 2019-2024).
    """
    contracts = pd.read_csv(DATA_RAW / "contracts.csv", encoding="utf-8")
    eligible = contracts[contracts["signed_year"].isin(list(SIGNED_YEAR_RANGE))]
    random.seed(RANDOM_SEED)
    test_idx = random.sample(range(len(eligible)), min(TEST_N, len(eligible)))
    return set(test_idx)


def main() -> None:
    print("=== Pipeline 05a: Submit contract-valuator fine-tuning job ===")
    test_indices = _held_out_indices()
    print(f"Held-out indices for eval (will NOT be in training): {len(test_indices)}")

    jsonl_path = build_training_jsonl(test_indices)

    # Cost estimate (gpt-4o-mini training is $3.00 per 1M tokens)
    size_kb = jsonl_path.stat().st_size / 1024
    # Rough token estimate: 4 chars per token
    rough_tokens = jsonl_path.stat().st_size / 4
    cost_est = rough_tokens * 3.0 / 1_000_000
    print(f"\nTraining file size: {size_kb:.1f} KB  (~{rough_tokens/1000:.0f}K tokens)")
    print(f"Estimated fine-tuning cost (1 epoch, gpt-4o-mini): ${cost_est:.2f}")

    oai = OpenAI(api_key=get_openai_api_key())

    print(f"\nUploading {jsonl_path.name} ...")
    upload = oai.files.create(file=jsonl_path.open("rb"), purpose="fine-tune")
    print(f"  uploaded file id: {upload.id}")

    print(f"Submitting fine-tuning job (base model: {BASE_MODEL}) ...")
    job = oai.fine_tuning.jobs.create(
        training_file=upload.id,
        model=BASE_MODEL,
        suffix="sabercast-contract",
    )
    print(f"  job id: {job.id}")
    print(f"  status: {job.status}")

    meta = {
        "job_id":         job.id,
        "input_file_id":  upload.id,
        "base_model":     BASE_MODEL,
        "submitted_at":   int(time.time()),
        "status_at_submit": job.status,
    }
    meta_path = DATA_PROC / "finetune_job_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nMeta written to {meta_path}")
    print("Fine-tuning typically takes 10-30 minutes. Run pipelines/05b_finetune_harvest.py "
          "periodically to check status and capture the resulting model id.")


if __name__ == "__main__":
    main()

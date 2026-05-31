"""Pipeline 03a — Submit player archetype classification to the OpenAI Batch API.

Reads qualifying 2024 batters (PA >= 100) and pitchers (IP >= 20), joins with
prior-year stats where available, and builds a JSONL of three classification
requests per player:

  1. Zero-shot archetype (one of 13 options spanning hitter + pitcher roles)
  2. Few-shot pitcher role (pitchers only) with confidence
  3. Chain-of-thought trend signal (improving / declining / stable) with reason

Submits via openai.batches.create() with gpt-4o-mini. Total expected cost: well
under $1 at batch pricing. Returns a batch ID written to
data/processed/batch_03_meta.json so the harvest script (03b) knows what to
pick up.
"""
from __future__ import annotations

import json
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
from app.config import get_openai_api_key  # noqa: E402

YEAR        = 2024
PRIOR_YEAR  = 2023
MIN_PA      = 100
MIN_IP      = 20

GPT4O_MINI  = "gpt-4o-mini"


# ──────────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────────
ARCHETYPE_SYSTEM = """You are an MLB analyst classifying a player's primary archetype.

Given the player's recent stat profile, return STRICT JSON only with this schema:
{
  "archetype": "<one of the values below>",
  "confidence": <float 0-1>,
  "rationale": "<one short phrase citing the stats that drove the choice>"
}

Archetype values (choose exactly one):
- power_hitter         — high HR + SLG, lower contact
- contact_hitter       — high AVG/OBP, low strikeout rate
- speed_threat         — high SB, lower power
- defensive_specialist — light bat, primary value is fielding (no stats given here, infer from low offense + position scarcity)
- elite_defender       — strong defensive metrics expected (above-average fielder at scarce position)
- framing_specialist   — catchers known for pitch framing or arm
- ace_starter          — top-of-rotation starter (low ERA, high K/9, high IP)
- mid_rotation_starter — solid starter (ERA 3.50-4.25, 120+ IP)
- back_end_starter     — fifth-starter type
- closer               — high-leverage reliever (SV)
- setup_reliever       — late-inning reliever, low ERA
- middle_reliever      — middle innings, higher ERA
- lefty_specialist     — LHP focused on left-handed batters

Return ONLY the JSON object."""

ROLE_SYSTEM = """You are an MLB analyst classifying a pitcher's specific role.

You will see a few labeled examples first, then a new pitcher to classify.

Return STRICT JSON only with this schema:
{
  "role": "<starter | swingman | setup | closer | middle_relief | long_relief>",
  "confidence": <float 0-1>
}

Few-shot examples (for calibration only):

Example 1 — Pitcher: "Tarik Skubal | 2024 | 33 GS, 192.1 IP, 2.39 ERA, 11.4 K/9"
{"role": "starter", "confidence": 0.99}

Example 2 — Pitcher: "Emmanuel Clase | 2024 | 0 GS, 74.1 IP, 0.61 ERA, 47 SV"
{"role": "closer", "confidence": 0.99}

Example 3 — Pitcher: "Aaron Bummer | 2024 | 0 GS, 58.0 IP, 3.41 ERA, 0 SV, 11 holds"
{"role": "setup", "confidence": 0.85}

Example 4 — Pitcher: "Garrett Crochet | 2024 | 32 GS, 146.0 IP, 3.58 ERA, 12.9 K/9"
{"role": "starter", "confidence": 0.97}

Example 5 — Pitcher: "Phil Maton | 2024 | 0 GS, 64.0 IP, 3.66 ERA, 0 SV, 9 holds, 9.3 K/9"
{"role": "middle_relief", "confidence": 0.80}

Now classify the new pitcher. Return ONLY the JSON object."""

TREND_SYSTEM = """You are an MLB analyst evaluating a player's year-over-year trend.

You will see the player's current-year line and prior-year line side by side.
Use chain-of-thought reasoning: first reflect briefly on the deltas, then
output the final trend label and a one-sentence reason.

Return STRICT JSON only with this schema:
{
  "trend": "<improving | declining | stable>",
  "trend_reason": "<one sentence citing the specific deltas>",
  "confidence": <float 0-1>
}

Rules:
- "improving" if key rate stats (OPS for hitters, ERA/WHIP for pitchers) moved meaningfully in a favorable direction
- "declining" if they moved unfavorably
- "stable" if changes are within noise (e.g. < 30 points of OPS, < 0.30 ERA)
- If only the current year is available, return "stable" with low confidence

Return ONLY the JSON object."""


# ──────────────────────────────────────────────────────────────────────────────
# Stat summary builders
# ──────────────────────────────────────────────────────────────────────────────
def _safe_int(v) -> int:
    try:
        return int(v) if pd.notna(v) else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(v) -> float:
    try:
        return float(v) if pd.notna(v) else 0.0
    except (ValueError, TypeError):
        return 0.0


def batter_line(row: pd.Series, year: int) -> str:
    name = row.get("Name", "Unknown")
    team = row.get("Tm", "?")
    pa   = _safe_int(row.get("PA"))
    hr   = _safe_int(row.get("HR"))
    sb   = _safe_int(row.get("SB"))
    bb   = _safe_int(row.get("BB"))
    so   = _safe_int(row.get("SO"))
    avg  = _safe_float(row.get("AVG", row.get("BA", 0)))
    obp  = _safe_float(row.get("OBP"))
    slg  = _safe_float(row.get("SLG"))
    ops  = _safe_float(row.get("OPS"))
    return (f"{name} | {team} | {year} batter | {pa} PA, {hr} HR, {sb} SB, "
            f"{bb} BB, {so} K, slash {avg:.3f}/{obp:.3f}/{slg:.3f}, OPS {ops:.3f}")


def pitcher_line(row: pd.Series, year: int) -> str:
    name = row.get("Name", "Unknown")
    team = row.get("Tm", "?")
    ip   = _safe_float(row.get("IP"))
    gs   = _safe_int(row.get("GS"))
    sv   = _safe_int(row.get("SV"))
    era  = _safe_float(row.get("ERA"))
    whip = _safe_float(row.get("WHIP"))
    k9   = _safe_float(row.get("SO9"))
    bb   = _safe_int(row.get("BB"))
    return (f"{name} | {team} | {year} pitcher | {ip:.1f} IP, {gs} GS, {sv} SV, "
            f"{era:.2f} ERA, {whip:.3f} WHIP, {k9:.1f} K/9")


def _make_request(custom_id: str, system_prompt: str, user_content: str) -> dict:
    return {
        "custom_id": custom_id,
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":         GPT4O_MINI,
            "temperature":   0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Build JSONL
# ──────────────────────────────────────────────────────────────────────────────
def build_jsonl() -> Path:
    bat_cur   = pd.read_csv(DATA_RAW / f"batting_{YEAR}.csv",       encoding="utf-8")
    bat_prior = pd.read_csv(DATA_RAW / f"batting_{PRIOR_YEAR}.csv", encoding="utf-8")
    pit_cur   = pd.read_csv(DATA_RAW / f"pitching_{YEAR}.csv",      encoding="utf-8")
    pit_prior = pd.read_csv(DATA_RAW / f"pitching_{PRIOR_YEAR}.csv", encoding="utf-8")

    bat_q = bat_cur[bat_cur["PA"].fillna(0) >= MIN_PA].copy()
    pit_q = pit_cur[pit_cur["IP"].fillna(0) >= MIN_IP].copy()
    print(f"Qualifying batters ({YEAR}, PA>={MIN_PA}): {len(bat_q)}")
    print(f"Qualifying pitchers ({YEAR}, IP>={MIN_IP}): {len(pit_q)}")

    # Index prior-year rows by name for trend lookup
    bat_prior_idx = bat_prior.set_index("Name")
    pit_prior_idx = pit_prior.set_index("Name")

    out_path = DATA_PROC / f"batch_03_requests_{YEAR}.jsonl"
    n_lines = 0
    with out_path.open("w", encoding="utf-8") as f:
        # Batters: archetype + trend
        for _, row in bat_q.iterrows():
            name = row["Name"]
            cur_line = batter_line(row, YEAR)
            pid = str(row.get("mlbID", name)).replace(" ", "_")

            # Archetype call
            arch_req = _make_request(
                custom_id=f"bat_archetype_{pid}",
                system_prompt=ARCHETYPE_SYSTEM,
                user_content=cur_line,
            )
            f.write(json.dumps(arch_req) + "\n")
            n_lines += 1

            # Trend call — include prior-year line if available
            if name in bat_prior_idx.index:
                prior_row = bat_prior_idx.loc[name]
                if isinstance(prior_row, pd.DataFrame):
                    prior_row = prior_row.iloc[0]
                prior_line = batter_line(prior_row, PRIOR_YEAR)
                trend_content = f"Current: {cur_line}\nPrior:   {prior_line}"
            else:
                trend_content = f"Current: {cur_line}\nPrior:   (no qualifying {PRIOR_YEAR} season)"
            trend_req = _make_request(
                custom_id=f"bat_trend_{pid}",
                system_prompt=TREND_SYSTEM,
                user_content=trend_content,
            )
            f.write(json.dumps(trend_req) + "\n")
            n_lines += 1

        # Pitchers: archetype + role + trend
        for _, row in pit_q.iterrows():
            name = row["Name"]
            cur_line = pitcher_line(row, YEAR)
            pid = str(row.get("mlbID", name)).replace(" ", "_")

            arch_req = _make_request(
                custom_id=f"pit_archetype_{pid}",
                system_prompt=ARCHETYPE_SYSTEM,
                user_content=cur_line,
            )
            f.write(json.dumps(arch_req) + "\n")
            n_lines += 1

            role_req = _make_request(
                custom_id=f"pit_role_{pid}",
                system_prompt=ROLE_SYSTEM,
                user_content=cur_line,
            )
            f.write(json.dumps(role_req) + "\n")
            n_lines += 1

            if name in pit_prior_idx.index:
                prior_row = pit_prior_idx.loc[name]
                if isinstance(prior_row, pd.DataFrame):
                    prior_row = prior_row.iloc[0]
                prior_line = pitcher_line(prior_row, PRIOR_YEAR)
                trend_content = f"Current: {cur_line}\nPrior:   {prior_line}"
            else:
                trend_content = f"Current: {cur_line}\nPrior:   (no qualifying {PRIOR_YEAR} season)"
            trend_req = _make_request(
                custom_id=f"pit_trend_{pid}",
                system_prompt=TREND_SYSTEM,
                user_content=trend_content,
            )
            f.write(json.dumps(trend_req) + "\n")
            n_lines += 1

    print(f"Wrote {n_lines:,} requests to {out_path.name}")
    return out_path


# ──────────────────────────────────────────────────────────────────────────────
# Cost estimate (batch API discount: ~50% of real-time price)
# ──────────────────────────────────────────────────────────────────────────────
def estimate_cost(jsonl_path: Path) -> float:
    n_lines = sum(1 for _ in jsonl_path.open("r", encoding="utf-8"))
    avg_input_tokens  = 600   # system + user
    avg_output_tokens = 150   # JSON response
    # gpt-4o-mini batch pricing per OpenAI (as of 2026-05):
    #   input:  $0.075 / 1M tokens (50% off $0.15 real-time)
    #   output: $0.30  / 1M tokens (50% off $0.60 real-time)
    in_cost  = n_lines * avg_input_tokens  * 0.075 / 1_000_000
    out_cost = n_lines * avg_output_tokens * 0.30  / 1_000_000
    total = in_cost + out_cost
    print(f"\nEstimated cost: {n_lines:,} calls × ~{avg_input_tokens}+{avg_output_tokens} tokens")
    print(f"  Input  : ${in_cost:.3f}")
    print(f"  Output : ${out_cost:.3f}")
    print(f"  Total  : ${total:.3f}")
    return total


# ──────────────────────────────────────────────────────────────────────────────
# Submit batch
# ──────────────────────────────────────────────────────────────────────────────
def submit_batch(jsonl_path: Path) -> dict:
    oai = OpenAI(api_key=get_openai_api_key())

    print(f"\nUploading {jsonl_path.name} ({jsonl_path.stat().st_size / 1024:.1f} KB) ...")
    upload = oai.files.create(file=jsonl_path.open("rb"), purpose="batch")
    print(f"  uploaded file id: {upload.id}")

    print("Creating batch ...")
    batch = oai.batches.create(
        input_file_id=upload.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={"project": "sabercast", "stage": "pipeline_03_archetypes",
                  "year": str(YEAR)},
    )
    print(f"  batch id: {batch.id}")
    print(f"  status:   {batch.status}")

    meta = {
        "batch_id":        batch.id,
        "input_file_id":   upload.id,
        "endpoint":        batch.endpoint,
        "submitted_at":    int(time.time()),
        "year":            YEAR,
        "prior_year":      PRIOR_YEAR,
        "n_requests":      sum(1 for _ in jsonl_path.open("r", encoding="utf-8")),
        "status_at_submit": batch.status,
    }
    meta_path = DATA_PROC / "batch_03_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nMeta written to {meta_path}")
    return meta


def main() -> None:
    print("=== Pipeline 03a: Submit player archetype batch ===")
    jsonl_path = build_jsonl()
    estimate_cost(jsonl_path)

    print("\nProceed with submission? (y/N)", flush=True)
    # In a non-interactive run, auto-submit. Manual runs can be interrupted before this.
    print("[auto-yes for non-interactive runs]")
    meta = submit_batch(jsonl_path)
    print(f"\nBatch submitted. ID: {meta['batch_id']}")
    print("Run pipelines/03b_harvest_archetypes.py periodically to check status and pull results.")


if __name__ == "__main__":
    main()

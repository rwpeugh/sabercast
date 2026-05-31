"""Pipeline 03b — Harvest the archetype batch results.

Polls the batch from 03a until it reports completed/failed, downloads the output
file, parses the JSON-per-line responses, and writes
data/archetypes/player_archetypes.csv with columns:
  player_name, position_role (batter|pitcher), archetype, archetype_confidence,
  archetype_rationale, role, role_confidence, trend, trend_reason, trend_confidence

Run any number of times. If the batch is still in progress, the script prints
status and exits. Once completed, it writes the CSV and exits.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
ARCHETYPES   = PROJECT_ROOT / "data" / "archetypes"
ARCHETYPES.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))
from app.config import get_openai_api_key  # noqa: E402

META_PATH = DATA_PROC / "batch_03_meta.json"
OUT_CSV   = ARCHETYPES / "player_archetypes.csv"


def _load_meta() -> dict:
    if not META_PATH.exists():
        raise SystemExit(f"No batch metadata at {META_PATH}. Run 03a first.")
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def main() -> None:
    meta = _load_meta()
    batch_id = meta["batch_id"]
    print(f"=== Pipeline 03b: Harvest batch {batch_id} ===")

    oai = OpenAI(api_key=get_openai_api_key())
    batch = oai.batches.retrieve(batch_id)
    print(f"Status: {batch.status}")
    counts = getattr(batch, "request_counts", None)
    if counts:
        print(f"Requests — total: {counts.total}, completed: {counts.completed}, failed: {counts.failed}")

    if batch.status not in {"completed", "failed", "cancelled", "expired"}:
        print("Batch not done yet — exit. Re-run later.")
        return

    if batch.status != "completed":
        print(f"Batch ended in non-success state: {batch.status}")
        if batch.errors:
            print(f"Errors: {batch.errors}")
        return

    # ── Download output file ────────────────────────────────────────────────
    output_id = batch.output_file_id
    if not output_id:
        raise SystemExit("Batch completed but no output_file_id present.")
    print(f"Downloading output file {output_id} ...")
    content = oai.files.content(output_id)
    raw_path = DATA_PROC / "batch_03_output.jsonl"
    raw_path.write_bytes(content.read())
    print(f"  saved {raw_path.name} ({raw_path.stat().st_size / 1024:.1f} KB)")

    # ── Parse responses ─────────────────────────────────────────────────────
    # Group by player: custom_id format is "<role>_<task>_<player_id>"
    # e.g., "bat_archetype_592450", "pit_trend_675911"
    players: dict[str, dict[str, Any]] = {}
    n_lines = 0
    for line in raw_path.open("r", encoding="utf-8"):
        n_lines += 1
        rec = json.loads(line)
        custom_id = rec.get("custom_id", "")
        parts = custom_id.split("_", 2)
        if len(parts) != 3:
            continue
        role_tag, task, pid = parts
        if pid not in players:
            players[pid] = {"player_id": pid, "position_role": "batter" if role_tag == "bat" else "pitcher"}

        body = rec.get("response", {}).get("body", {})
        choices = body.get("choices") or []
        if not choices:
            continue
        content_str = choices[0].get("message", {}).get("content", "")
        try:
            parsed = json.loads(content_str)
        except json.JSONDecodeError:
            continue

        if task == "archetype":
            players[pid]["archetype"]           = parsed.get("archetype")
            players[pid]["archetype_confidence"]= parsed.get("confidence")
            players[pid]["archetype_rationale"] = parsed.get("rationale")
        elif task == "role":
            players[pid]["role"]            = parsed.get("role")
            players[pid]["role_confidence"] = parsed.get("confidence")
        elif task == "trend":
            players[pid]["trend"]            = parsed.get("trend")
            players[pid]["trend_reason"]     = parsed.get("trend_reason")
            players[pid]["trend_confidence"] = parsed.get("confidence")

    print(f"Parsed {n_lines:,} response lines into {len(players)} players")

    # ── Join player names via the original batting/pitching CSVs ────────────
    import pandas as pd
    bat = pd.read_csv(PROJECT_ROOT / "data" / "raw" / "batting_2024.csv",  encoding="utf-8")
    pit = pd.read_csv(PROJECT_ROOT / "data" / "raw" / "pitching_2024.csv", encoding="utf-8")
    id_to_name = {}
    for df in (bat, pit):
        if "mlbID" in df.columns and "Name" in df.columns:
            for _, row in df.iterrows():
                if pd.notna(row.get("mlbID")):
                    id_to_name[str(int(row["mlbID"]))] = row["Name"]

    rows = []
    for pid, p in players.items():
        rows.append({
            "player_id":         pid,
            "player_name":       id_to_name.get(pid, pid),
            "position_role":     p.get("position_role"),
            "archetype":         p.get("archetype"),
            "archetype_confidence": p.get("archetype_confidence"),
            "archetype_rationale": p.get("archetype_rationale"),
            "role":              p.get("role"),
            "role_confidence":   p.get("role_confidence"),
            "trend":             p.get("trend"),
            "trend_reason":      p.get("trend_reason"),
            "trend_confidence":  p.get("trend_confidence"),
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\nWrote {OUT_CSV} ({len(out)} players, {len(out.columns)} cols)")

    # Summary
    print("\nArchetype distribution:")
    print(out["archetype"].value_counts().head(15).to_string())
    print("\nTrend distribution:")
    print(out["trend"].value_counts().to_string())


if __name__ == "__main__":
    main()

"""Verify the new defensive CSVs join cleanly with the batting CSV.

Three joins to confirm:
  1. batting (mlbID) <-> sprint_speed (player_id)
  2. batting (mlbID) <-> oaa (player_id)
  3. batting (mlbID) <-> catcher_defense (entity_id)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

bat   = pd.read_csv(ROOT / "data/raw/batting_2024.csv",        encoding="utf-8")
oaa   = pd.read_csv(ROOT / "data/raw/oaa_2024.csv",            encoding="utf-8")
sprint = pd.read_csv(ROOT / "data/raw/sprint_speed_2024.csv",   encoding="utf-8")
catch = pd.read_csv(ROOT / "data/raw/catcher_defense_2024.csv", encoding="utf-8")

print(f"batting           : {len(bat):>5} rows, mlbID present: {('mlbID' in bat.columns)}")
print(f"oaa               : {len(oaa):>5} rows, player_id present: {('player_id' in oaa.columns)}")
print(f"sprint_speed      : {len(sprint):>5} rows, player_id present: {('player_id' in sprint.columns)}")
print(f"catcher_defense   : {len(catch):>5} rows, entity_id present: {('entity_id' in catch.columns)}")
print()

# Coerce IDs to int for clean comparison
bat["mlbID"]   = pd.to_numeric(bat["mlbID"], errors="coerce").astype("Int64")
oaa["player_id"]    = pd.to_numeric(oaa["player_id"], errors="coerce").astype("Int64")
sprint["player_id"] = pd.to_numeric(sprint["player_id"], errors="coerce").astype("Int64")
catch["entity_id"]  = pd.to_numeric(catch["entity_id"], errors="coerce").astype("Int64")

batting_ids = set(bat["mlbID"].dropna().astype(int))
print(f"batting unique IDs               : {len(batting_ids)}")

oaa_ids = set(oaa["player_id"].dropna().astype(int))
sprint_ids = set(sprint["player_id"].dropna().astype(int))
catch_ids = set(catch["entity_id"].dropna().astype(int))

print(f"OAA IDs in batting               : {len(oaa_ids & batting_ids):>3} / {len(oaa_ids):>3} ({100*len(oaa_ids & batting_ids)/max(1,len(oaa_ids)):.0f}%)")
print(f"Sprint IDs in batting            : {len(sprint_ids & batting_ids):>3} / {len(sprint_ids):>3} ({100*len(sprint_ids & batting_ids)/max(1,len(sprint_ids)):.0f}%)")
print(f"Catcher IDs in batting           : {len(catch_ids & batting_ids):>3} / {len(catch_ids):>3} ({100*len(catch_ids & batting_ids)/max(1,len(catch_ids)):.0f}%)")

# Sample join to surface a few players with full defensive profile
print("\nSample SEA players with OAA, sprint speed, and catcher defense joined:")
sea = bat[bat["Tm"].astype(str).str.contains("Seattle", na=False)].copy()
joined = sea.merge(sprint[["player_id","position","sprint_speed"]],
                    left_on="mlbID", right_on="player_id", how="left")
joined = joined.merge(oaa[["player_id","primary_pos_formatted","outs_above_average","fielding_runs_prevented"]],
                       left_on="mlbID", right_on="player_id", how="left", suffixes=("","_oaa"))
joined = joined.merge(catch[["entity_id","pop_2b_sba","maxeff_arm_2b_3b_sba"]],
                       left_on="mlbID", right_on="entity_id", how="left")
cols = ["Name","Tm","HR","OPS","position","sprint_speed",
        "primary_pos_formatted","outs_above_average","pop_2b_sba"]
print(joined[joined["PA"] >= 200][cols].head(10).to_string(index=False))

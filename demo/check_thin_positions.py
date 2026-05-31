"""Inspect what's already in contracts.csv at thin positions."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

c = pd.read_csv(ROOT / "data/raw/contracts.csv", encoding="utf-8")
print("Existing C / RP / 2B / CF entries (any signed_year):")
for pos in ["C", "RP", "2B", "CF"]:
    rows = c[c["position"] == pos]
    print(f"\n  {pos}: {len(rows)} contracts")
    for _, r in rows.iterrows():
        aav_m = (r["aav"] or 0) / 1e6
        print(f"    - {r['player_name']:25s} ({r['team']})  "
              f"{r['years']}y / ${aav_m:.1f}M AAV  signed {r['signed_year']}")

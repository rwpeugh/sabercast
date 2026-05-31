"""Verify the accent-folded name lookup recovers Latino players like Julio
Rodriguez (ASCII in Spotrac, with diacritics in bref)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from core.orchestrator import _ascii_fold, _lookup_player_stats  # noqa: E402

batting  = pd.read_csv(ROOT / "data/raw/batting_2024.csv", encoding="utf-8")
pitching = pd.read_csv(ROOT / "data/raw/pitching_2024.csv", encoding="utf-8")

print("Fold checks:")
print("  Julio Rodriguez ->", repr(_ascii_fold("Julio Rodriguez")))
print("  Julio Rodriguez ->", repr(_ascii_fold("Julio Rodríguez")))
print()

cases = [
    ("Julio Rodriguez",  "CF"),
    ("Jose Ramirez",     "3B"),
    ("Eugenio Suarez",   "3B"),
    ("Yordan Alvarez",   "DH"),
    ("Cal Raleigh",      "C"),     # ASCII control
    ("Aaron Judge",      "RF"),    # ASCII control
]
for name, pos in cases:
    s = _lookup_player_stats(name, batting, pitching, pos)
    if s:
        print(f"  {name:20s} ({pos}) -> FOUND: {s.get('PA','?')} PA, "
              f"OPS={s.get('OPS') or 0:.3f}")
    else:
        print(f"  {name:20s} ({pos}) -> NOT FOUND")

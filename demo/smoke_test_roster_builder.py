"""Smoke test the roster builder: SEA vs HOU."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import run_roster_builder_simple  # noqa: E402

out = run_roster_builder_simple("SEA", "HOU", evaluation_year=2024)
print(f"Team: {out['team']}  vs.  Opponent: {out['opponent']}  ·  ran in {out['elapsed_seconds']}s")
print()
print("NARRATIVE:")
print(f"  {out['narrative']}")
print()
print("RECOMMENDED LINEUP:")
for slot in out["recommended_lineup"]:
    order = slot.get("order", "?")
    pos = slot.get("position", "?")
    name = slot.get("player_name", "?")
    rationale = slot.get("rationale", "")
    print(f"  {order}. {pos:3s} {name:25s}  — {rationale}")
print()
print("MATCHUP ADVANTAGES:")
for a in out["matchup_advantages"]:
    leverage = a.get("leverage", "?").upper()
    print(f"  [{leverage:6s}] {a.get('area')}")
    print(f"           evidence: {a.get('evidence')}")
print()
print("MATCHUP RISKS:")
for r in out["matchup_risks"]:
    print(f"  - {r.get('area')}")
    print(f"    mitigation: {r.get('mitigation')}")

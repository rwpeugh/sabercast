"""Smoke test: run the opponent scouting orchestrator on Houston and dump the result."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import run_opponent_scouting_simple  # noqa: E402

out = run_opponent_scouting_simple("HOU", evaluation_year=2024)
print(f"Opponent: {out['opponent']}  ·  ran in {out['elapsed_seconds']}s")
print()
print("NARRATIVE:")
print(f"  {out['narrative']}")
print()
print("TOP HITTERS (raw, top 5 by OPS):")
for h in out["top_hitters"]:
    print(f"  {h['name']:25s}  {h['PA']} PA  {h['HR']} HR  OPS {h['OPS']:.3f}")
print()
print("TOP PITCHERS (raw, top 5 by ERA):")
for p in out["top_pitchers"]:
    print(f"  {p['name']:25s}  {p['role']:8s}  {p['IP']:.1f} IP  ERA {p['ERA']:.2f}  WHIP {p['WHIP']:.3f}")
print()
print("LLM TOP THREATS:")
for t in out["threats"]:
    print(f"  [{t.get('role','?'):7s}] {t['player_name']:25s} — {t['why']}")
print()
print("EXPLOITABLE WEAKNESSES:")
for w in out["weaknesses"]:
    print(f"  [{w['win_impact'].upper():6s}] {w['area']}")
    print(f"           evidence: {w['stat_evidence']}")
print()
print("PITCHING STRATEGY:")
print(f"  {out['pitching_strategy']}")
print()
print("HITTING APPROACH:")
print(f"  {out['hitting_approach']}")

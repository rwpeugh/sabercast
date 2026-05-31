"""Smoke test: confirm defensive aggregates flow through and the LLM uses them."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import run_gap_filler_simple  # noqa: E402

out = run_gap_filler_simple("SEA", 165_000_000, evaluation_year=2024)

print("Team defense by position:")
print(json.dumps(out.get("team_defense", {}).get("by_position", {}), indent=2))

print("\nCatcher block:")
print(json.dumps(out.get("team_defense", {}).get("catcher", {}), indent=2))

print("\nDefense deltas:")
for pos, d in out.get("defense_deltas", {}).get("by_position", {}).items():
    team = d["team_oaa_total"]
    league = d["league_avg_per_team"]
    delta = d["oaa_delta_vs_league_per_team"]
    flag = " ←" if abs(delta) >= 5 else ""
    print(f"  {pos:3s}: team_oaa={team:>4d}  league_avg/team={league:>6.2f}  "
          f"delta={delta:+6.2f}{flag}")

cd = out.get("defense_deltas", {}).get("catcher")
if cd:
    print(f"\nCatcher pop time delta: team {cd['team_pop_2b_mean']} vs "
          f"league {cd['league_pop_2b_mean']} ({cd['pop_2b_delta']:+.3f}, "
          f"{cd['delta_interpretation']})")

sd = out.get("defense_deltas", {}).get("sprint_delta")
if sd is not None:
    print(f"Sprint speed delta: {sd:+.2f} ft/sec vs league")

print("\nLLM's roster summary:")
print(f"  {out['roster_summary']}")

print("\nGaps with components:")
for g in out["gaps_results"]:
    gap = g["gap"]
    pos = gap["position"]
    components = gap.get("gap_components", {})
    score = gap["gap_score"]
    print(f"  #{gap.get('win_impact','?').upper():6s} {pos:3s} score={score:.1f}/10")
    print(f"    components: offense={components.get('offense','?')}, defense={components.get('defense','?')}")
    print(f"    reasoning : {gap['reasoning'][:140]}")

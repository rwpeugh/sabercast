"""Smoke test: confirm vectorstore-based player matching surfaces sensible
candidates for SEA's diagnosed gaps."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import run_gap_filler_simple  # noqa: E402

out = run_gap_filler_simple("SEA", 165_000_000, evaluation_year=2024)
print(f"evaluation_year: {out['evaluation_year']}")
print()
for g in out["gaps_results"]:
    pos = g["gap"]["position"]
    src = g.get("targets_source", "?")
    targets = g.get("targets") or []
    print(f"=== Gap {pos}  (targets_source={src}) ===")
    print(f"  Reasoning: {g['gap']['reasoning'][:120]}")
    for t in targets:
        cur_aav = (t.get("aav") or 0) / 1e6
        fc_aav  = (t.get("forecast_aav") or 0) / 1e6
        arch = t.get("archetype") or "?"
        trend = t.get("trend") or "?"
        sem = t.get("semantic_score")
        fit = t.get("fit_score")
        print(f"  - {t['player_name']:25s}  "
              f"current=${cur_aav:.1f}M  forecast=${fc_aav:.1f}M  "
              f"archetype={arch:18s}  trend={trend:10s}  "
              + (f"semantic={sem}" if sem is not None else f"fit={fit}"))
    print()

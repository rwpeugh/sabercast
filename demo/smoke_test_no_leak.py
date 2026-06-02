"""Smoke test: verify no contracts with signed_year > evaluation_year leak through
either the recommended targets or the pricing comparables. Also prints fit
scores so we can sanity-check the target ranking."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.orchestrator import run_gap_filler_simple  # noqa: E402

out = run_gap_filler_simple("SEA", 165_000_000, evaluation_year=2024)
print(f"evaluation_year   : {out['evaluation_year']}")
print(f"market_year       : {out['market_year']}")
print(f"comparables_policy: {out['comparables_policy']}")
print(f"thin_targets      : {out['thin_targets_positions']}")
print()

leak_count = 0
for g in out["gaps_results"]:
    pos = g["gap"]["position"]
    targets = g.get("targets", [])
    comps   = g.get("pricing_comparables", [])
    est_aav = g["estimate"].get("estimated_aav") or 0

    print(f"=== Gap {pos}  (estimated fill: ${est_aav/1e6:.1f}M AAV) ===")
    print(f"  Recommended targets ({len(targets)}, ranked by 2024 fit_score):")
    for t in targets:
        sy = t.get("signed_year")
        flag = "  ***LEAK***" if sy and sy > out["evaluation_year"] else ""
        if flag:
            leak_count += 1
        s = t.get("stats_2024") or {}
        if s.get("role") == "hitter":
            stat_str = (f"{s.get('PA','?')} PA, {s.get('HR','?')} HR, "
                        f".{int((s.get('AVG') or 0)*1000):03d}/"
                        f".{int((s.get('OBP') or 0)*1000):03d}/"
                        f".{int((s.get('SLG') or 0)*1000):03d}")
        elif s.get("role") == "pitcher":
            stat_str = (f"{s.get('IP','?'):.0f} IP, "
                        f"{s.get('ERA','?'):.2f} ERA, "
                        f"{s.get('WHIP','?'):.3f} WHIP")
        else:
            stat_str = "no 2024 stats"
        cur_aav = (t.get("aav") or 0) / 1e6
        fc_aav  = (t.get("forecast_aav") or 0) / 1e6
        premium = ""
        if t.get("is_expensive_vs_estimate"):
            premium = f"  [PREMIUM +{int((t['premium_vs_estimate'] or 0)*100)}% vs estimate]"
        # Targets carry either fit_score (stat-fit path) or semantic_score
        # (vectorstore path). Print whichever is available.
        score_lbl = ""
        if t.get("fit_score") is not None:
            score_lbl = f"fit={t['fit_score']:5.2f}"
        elif t.get("semantic_score") is not None:
            score_lbl = f"sem={t['semantic_score']:5.2f}"
        else:
            score_lbl = "score=   ? "
        print(f"    {t['player_name']:28s} {score_lbl}  "
              f"current=${cur_aav:.1f}M  forecast=${fc_aav:.1f}M{premium}")
        print(f"      stats: {stat_str}")
        if t.get("forecast_rationale"):
            print(f"      forecast rationale: {t['forecast_rationale']}")

    print(f"  Pricing comparables ({len(comps)}, ranked by AAV):")
    for c in comps:
        sy = c.get("signed_year")
        flag = "  ***LEAK***" if sy and sy > out["evaluation_year"] else ""
        if flag:
            leak_count += 1
        aav = (c.get("aav") or 0) / 1e6
        also_tgt = "  [also target]" if c.get("is_also_target") else ""
        rat = c.get("rationale") or ""
        print(f"    {c['player_name']:28s}                 "
              f"signed={sy} AAV=${aav:.1f}M{flag}{also_tgt}")
        if rat:
            print(f"      → {rat}")
    print()

print(f"LEAKS DETECTED: {leak_count}")
sys.exit(0 if leak_count == 0 else 1)

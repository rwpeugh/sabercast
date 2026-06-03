"""eval/precision_at_k.py — direct test of player_matcher recommendation quality.

The question this test answers: when a team had a flagged top-3 gap at position
P in year Y, and that team subsequently signed player X at position P during the
Y -> Y+1 offseason, does Sabercast's player_matcher.find_matches() retrieve
player X in its top-K recommended candidates?

Methodology
-----------
1. Combined contract pool: contracts.csv (115) + contracts_extended.csv (~1,139).
2. Restrict to signings with signed_year == 2025. These map to the 2024-25
   offseason for which we have a cached gap diagnostic at evaluation_year=2024.
3. For each (player, team, position) signing:
     a. Look up team's 2024 gap diagnostic. Skip if position wasn't in the top-3.
     b. Run find_matches(gap, combined_contracts, batting, pitching,
                         evaluation_year=2025, single_signing_ceiling=1e9, k=10).
        eval_year=2025 (not 2024) so the player's just-signed 2025 contract is
        eligible. ceiling=$1B disables budget filtering for the eval. This tests
        the pure retrieval + position-filter pipeline.
     c. Check player's rank in the top-K list (case-insensitive, accent-folded).

4. Compute precision@3, @5, @10. Significance via binomial-mixture test against
   a per-event random baseline (each event has its own pool size N_i, so the
   random precision@K varies per event; expected hits under null = sum(K/N_i)).

Outputs:
  eval/results/precision_at_k.csv          one row per (year, team, pos, player) event
  eval/results/precision_at_k_summary.csv  aggregate stats + significance verdict
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))

# Restrict to the offseason for which we have a cached diagnostic (eval_year=2024)
SIGNED_YEAR = 2025
EVAL_YEAR_FOR_DIAG  = 2024
EVAL_YEAR_FOR_MATCH = 2025   # so the signed player's new contract is eligible
NO_BUDGET_CEILING   = 1_000_000_000.0
K_VALUES            = (3, 5, 10)


def _ascii_fold(s: str) -> str:
    import unicodedata
    if not isinstance(s, str):
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def _load_combined_contracts() -> pd.DataFrame:
    orig = pd.read_csv(DATA_RAW / "contracts.csv")
    if "source" not in orig.columns:
        orig["source"] = "spotrac_main_or_manual"
    ext = pd.read_csv(DATA_RAW / "contracts_extended.csv")
    cols = ["player_name", "team", "position", "age", "contract_value", "aav",
            "years", "signed_year", "source"]
    for df in (orig, ext):
        for c in cols:
            if c not in df.columns:
                df[c] = None
    combined = pd.concat([orig[cols], ext[cols]], ignore_index=True)
    return combined


def _index_diagnose_cache() -> dict:
    """Return {(year, team): [gap_dicts]} from correlation_diagnose_cache.json."""
    raw = json.loads((DATA_PROC / "correlation_diagnose_cache.json").read_text(encoding="utf-8"))
    by_key: dict[tuple[int, str], list[dict]] = {}
    for entry in raw.values():
        year = int(entry.get("year"))
        team = str(entry.get("team"))
        gaps = entry.get("gaps", []) or []
        by_key[(year, team)] = gaps
    return by_key


def main() -> None:
    print(f"=== eval/precision_at_k.py — RAG retrieval vs actual {SIGNED_YEAR} signings ===\n")

    contracts = _load_combined_contracts()
    print(f"  combined contracts pool: {len(contracts)}")
    batting   = pd.read_csv(DATA_RAW / f"batting_{EVAL_YEAR_FOR_MATCH - 1}.csv")
    pitching  = pd.read_csv(DATA_RAW / f"pitching_{EVAL_YEAR_FOR_MATCH - 1}.csv")
    print(f"  batting_{EVAL_YEAR_FOR_MATCH - 1}.csv: {len(batting)} rows")
    print(f"  pitching_{EVAL_YEAR_FOR_MATCH - 1}.csv: {len(pitching)} rows")

    diag_idx = _index_diagnose_cache()
    diag_2024_keys = [k for k in diag_idx if k[0] == EVAL_YEAR_FOR_DIAG]
    print(f"  diagnostic cache: {len(diag_2024_keys)} team-year entries at {EVAL_YEAR_FOR_DIAG}")

    # ── Build the event list ───────────────────────────────────────────────
    signings_2025 = contracts[contracts["signed_year"] == SIGNED_YEAR].copy()
    print(f"  signings in {SIGNED_YEAR}: {len(signings_2025)}")

    events: list[dict] = []
    skipped_no_diag = 0
    skipped_unflagged = 0
    for _, sig in signings_2025.iterrows():
        team = str(sig["team"]).strip()
        pos = str(sig["position"]).strip()
        player = str(sig["player_name"]).strip()
        if not team or not pos or not player:
            continue
        gaps = diag_idx.get((EVAL_YEAR_FOR_DIAG, team))
        if gaps is None:
            skipped_no_diag += 1
            continue
        matching = next((g for g in gaps if str(g.get("position")) == pos), None)
        if matching is None:
            skipped_unflagged += 1
            continue
        events.append({
            "team": team, "position": pos, "player": player, "gap": matching,
            "signing_aav": sig.get("aav"),
        })
    print(f"  built {len(events)} test events")
    print(f"    skipped (no diag for team): {skipped_no_diag}")
    print(f"    skipped (position not in top-3 flagged): {skipped_unflagged}")

    if not events:
        raise SystemExit("No test events available — aborting.")

    # ── Run player_matcher on each event ──────────────────────────────────
    from core.player_matcher import find_matches, vectorstore_available
    if not vectorstore_available():
        raise SystemExit("Vectorstore unavailable — cannot run RAG-based retrieval test.")

    print(f"\n  running find_matches() for {len(events)} events ...")
    out_rows: list[dict] = []
    for i, ev in enumerate(events, 1):
        # Build the eligibility pool size for this position/year combination
        pool_at_pos = contracts[
            (contracts["position"] == ev["position"])
            & (contracts["signed_year"].fillna(9999) <= EVAL_YEAR_FOR_MATCH)
        ]
        pool_size = int(len(pool_at_pos))
        if pool_size == 0:
            continue

        try:
            matches = find_matches(
                ev["gap"], contracts, batting, pitching,
                evaluation_year=EVAL_YEAR_FOR_MATCH,
                single_signing_ceiling=NO_BUDGET_CEILING,
                k=max(K_VALUES),
                top_n_semantic=400,
            )
        except Exception as e:                                          # noqa: BLE001
            print(f"    [{i}/{len(events)}] {ev['player']} ({ev['team']}, {ev['position']}): "
                  f"find_matches failed: {type(e).__name__}: {e}")
            continue

        matched_names = [_ascii_fold(m.get("player_name", "")) for m in matches]
        target_name = _ascii_fold(ev["player"])
        rank = matched_names.index(target_name) + 1 if target_name in matched_names else None
        row = {
            "team":         ev["team"],
            "position":     ev["position"],
            "player":       ev["player"],
            "pool_size":    pool_size,
            "n_returned":   len(matches),
            "rank":         rank,
            "in_top_3":     bool(rank is not None and rank <= 3),
            "in_top_5":     bool(rank is not None and rank <= 5),
            "in_top_10":    bool(rank is not None and rank <= 10),
        }
        out_rows.append(row)
        flag = "✓" if rank and rank <= max(K_VALUES) else "·"
        print(f"    [{i:3d}/{len(events)}] {flag} {ev['player']:25s} ({ev['team']:3s}, {ev['position']:3s})  "
              f"pool={pool_size:3d}  rank={rank if rank else '—'}")

    if not out_rows:
        raise SystemExit("No successful find_matches results — aborting.")

    df = pd.DataFrame(out_rows)
    df.to_csv(RESULTS_DIR / "precision_at_k.csv", index=False, encoding="utf-8")

    # ── Aggregate stats + significance ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("PRECISION@K RESULTS")
    print("=" * 70)
    n = len(df)
    summary_rows: list[dict] = []
    for K in K_VALUES:
        col = f"in_top_{K}"
        observed_hits = int(df[col].sum())
        observed_prec = observed_hits / n
        # Per-event random baseline P(hit) = K / pool_size_i
        pK = (df["pool_size"].apply(lambda p: min(K / p, 1.0))).clip(0, 1)
        expected_hits = float(pK.sum())
        # Binomial-mixture: under null, X = sum of independent Bernoulli(p_i)
        # E[X] = sum(p_i); Var[X] = sum(p_i * (1-p_i))
        var = float((pK * (1 - pK)).sum())
        sd = math.sqrt(var) if var > 0 else 0.0
        z = (observed_hits - expected_hits) / sd if sd > 0 else float("nan")
        # Normal approximation for p-value (one-sided: are we above null?)
        p_one_sided = 1 - stats.norm.cdf(z) if not math.isnan(z) else float("nan")
        lift = observed_prec / (expected_hits / n) if expected_hits > 0 else float("nan")
        print(f"  precision@{K:2d}:  observed={observed_prec*100:5.1f}% ({observed_hits}/{n})  "
              f"random_baseline={(expected_hits/n)*100:5.1f}%  lift={lift:4.1f}x  "
              f"z={z:5.2f}  p={p_one_sided:.4f}")
        summary_rows.append({
            "K":                K,
            "n_events":         n,
            "observed_hits":    observed_hits,
            "observed_precision": round(observed_prec, 4),
            "random_baseline_precision": round(expected_hits / n, 4),
            "lift":             round(lift, 2) if not math.isnan(lift) else None,
            "z_score":          round(z, 3) if not math.isnan(z) else None,
            "p_value_one_sided": round(p_one_sided, 4) if not math.isnan(p_one_sided) else None,
            "significant_at_0_05": bool(p_one_sided < 0.05) if not math.isnan(p_one_sided) else False,
        })

    pd.DataFrame(summary_rows).to_csv(RESULTS_DIR / "precision_at_k_summary.csv",
                                       index=False, encoding="utf-8")

    print()
    print(f"  median pool size: {int(df.pool_size.median())}")
    retrieved = df.dropna(subset=["rank"])
    print(f"  among events where player was retrieved (n={len(retrieved)}):")
    if len(retrieved):
        print(f"    median rank = {retrieved['rank'].median():.1f}")
        print(f"    mean rank   = {retrieved['rank'].mean():.1f}")
    print()
    sig_count = sum(1 for r in summary_rows if r["significant_at_0_05"])
    print(f"  VERDICT: {sig_count}/{len(K_VALUES)} K-values reach p < 0.05.")
    if sig_count > 0:
        print(f"  Sabercast's RAG retrieval surfaces actual {SIGNED_YEAR} signings significantly above random chance.")
    else:
        print(f"  Sabercast's RAG retrieval does NOT significantly beat random retrieval at the K-values tested.")


if __name__ == "__main__":
    main()

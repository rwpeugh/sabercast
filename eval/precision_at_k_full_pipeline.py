"""eval/precision_at_k_full_pipeline.py — precision of the END-USER output.

The existing eval/precision_at_k.py measures the RETRIEVAL layer in isolation:
"of the top-K candidates returned by find_matches, does the actual 2025
signing appear?" That's the right test for retrieval quality.

This script measures the FULL PIPELINE OUTPUT — what the user actually sees
in the Gap Filler UI after every downstream stage runs:

    find_matches (top-N semantic)
        -> position + signed_year + AAV filtering
        -> incumbent identification per gap
        -> per-candidate composite improvement score
           (vs incumbent, gap-component weighted)
        -> tier classification (bargain / medium / premium) by AAV vs ceiling
        -> top-1 per tier (so up to 3 candidates total per gap)

Precision@3-full-pipeline = "of the 3 tier-bucketed candidates we surface,
is the actual 2025 signing one of them?" This is a strictly harder bar than
precision@10-retrieval (smaller set, applies budget + composite re-ranking).

This test answers a different question than the existing eval: NOT "is the
retrieval good?" (Entry 31: yes, 3.1x lift) but rather "does the orchestrator's
display logic — composite re-rank + tier bucketing — preserve, improve, or
degrade that retrieval quality at the smaller user-visible top-3?"

Methodology
-----------
1. Reuse the event-building logic from precision_at_k.py: 2025 signings where
   the team had a top-3 flagged gap at that position in 2024.
2. For each event:
   a. find_matches(gap, ..., k=20) -- get the wider candidate pool the
      production orchestrator works from.
   b. Look up team's actual 2024 committed payroll (Spotrac 2024 vintage,
      Entry 35 vintage) and a TOTAL-payroll input. Use the 2025 actual
      team payroll as the TOTAL budget proxy -- this approximates the
      "what they ultimately spent in 2025" envelope.
   c. Compute single_signing_ceiling = 30% * available_for_signings.
   d. For each candidate, compute improvement deltas vs incumbent (using
      the same _compute_improvement_deltas the production code uses).
   e. Tier-classify each candidate, pick top-1 per tier by composite score.
      Up to 3 candidates total.
   f. Check whether the actual 2025 signing appears in those 3.

3. Compare to:
   * Random-3-from-pool baseline (per event, P = min(3/pool, 1.0))
   * Existing precision@3 from raw retrieval (no re-ranking, no tier-bucketing)

Outputs
-------
  eval/results/precision_at_k_full_pipeline.csv
  eval/results/precision_at_k_full_pipeline_summary.csv
"""
from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_PROC    = PROJECT_ROOT / "data" / "processed"
RESULTS_DIR  = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_ROOT))

# Matches eval/precision_at_k.py for event-list parity
SIGNED_YEAR        = 2025
EVAL_YEAR_FOR_DIAG = 2024
EVAL_YEAR_FOR_MATCH = 2025  # so the 2025 signing's new contract is eligible
TOP_N_FROM_RETRIEVAL = 20   # pool the production orchestrator works from


def _ascii_fold(s: str) -> str:
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
    raw = json.loads((DATA_PROC / "correlation_diagnose_cache.json").read_text(encoding="utf-8"))
    by_key: dict[tuple[int, str], list[dict]] = {}
    for entry in raw.values():
        year = int(entry.get("year"))
        team = str(entry.get("team"))
        gaps = entry.get("gaps", []) or []
        by_key[(year, team)] = gaps
    return by_key


def _team_total_budget_proxy(team_abbr: str) -> float:
    """Use the team's actual 2025 payroll as the TOTAL-budget proxy. The 2025
    page captures what the team actually spent on the active roster after
    making 2024-25 offseason moves -- a reasonable proxy for the team's
    total-budget envelope.

    Why not a flat $200M for everyone: the budget envelope drives the
    single_signing_ceiling, which drives the tier bucketing. Using each
    team's actual envelope is closer to what a real GM working at that
    team would feed into the tool.
    """
    df = pd.read_csv(DATA_RAW / "team_payrolls_2025.csv")
    row = df[df["team_abbr"].astype(str) == team_abbr]
    if not row.empty:
        return float(row.iloc[0]["committed_total"])
    return 200_000_000.0  # fallback for unknown team


def main() -> None:
    print(f"=== eval/precision_at_k_full_pipeline.py "
          f"— END-USER top-3 (tier-bucketed) precision vs actual {SIGNED_YEAR} signings ===\n")

    from core.orchestrator import (
        compute_committed_payroll,
        get_position_incumbent,
        _compute_improvement_deltas,
        _classify_target_tier,
        _pick_top_per_tier,
        TIER_BARGAIN_RATIO,
    )
    from core.player_matcher import find_matches, vectorstore_available

    if not vectorstore_available():
        raise SystemExit("Vectorstore unavailable.")

    contracts = _load_combined_contracts()
    batting   = pd.read_csv(DATA_RAW / f"batting_{EVAL_YEAR_FOR_MATCH - 1}.csv")
    pitching  = pd.read_csv(DATA_RAW / f"pitching_{EVAL_YEAR_FOR_MATCH - 1}.csv")
    # Defense lookups for incumbent computation
    try:
        oaa_df = pd.read_csv(DATA_RAW / f"oaa_{EVAL_YEAR_FOR_DIAG}.csv")
    except FileNotFoundError:
        oaa_df = None
    try:
        catcher_df = pd.read_csv(DATA_RAW / f"catcher_defense_{EVAL_YEAR_FOR_DIAG}.csv")
    except FileNotFoundError:
        catcher_df = None
    try:
        sprint_df = pd.read_csv(DATA_RAW / f"sprint_{EVAL_YEAR_FOR_DIAG}.csv")
    except FileNotFoundError:
        sprint_df = None

    print(f"  combined contracts pool:        {len(contracts)}")
    print(f"  batting_{EVAL_YEAR_FOR_MATCH-1}.csv:                {len(batting)} rows")
    print(f"  pitching_{EVAL_YEAR_FOR_MATCH-1}.csv:               {len(pitching)} rows")
    print(f"  oaa_{EVAL_YEAR_FOR_DIAG}.csv:                  "
          f"{'unavailable' if oaa_df is None else f'{len(oaa_df)} rows'}")

    # ── Build event list (same logic as precision_at_k.py) ─────────────────
    diag_idx = _index_diagnose_cache()
    signings_2025 = contracts[contracts["signed_year"] == SIGNED_YEAR].copy()
    events: list[dict] = []
    skipped_no_diag = skipped_unflagged = 0
    for _, sig in signings_2025.iterrows():
        team = str(sig["team"]).strip()
        pos  = str(sig["position"]).strip()
        player = str(sig["player_name"]).strip()
        if not team or not pos or not player:
            continue
        gaps = diag_idx.get((EVAL_YEAR_FOR_DIAG, team))
        if gaps is None:
            skipped_no_diag += 1; continue
        matching = next((g for g in gaps if str(g.get("position")) == pos), None)
        if matching is None:
            skipped_unflagged += 1; continue
        events.append({
            "team": team, "position": pos, "player": player, "gap": matching,
            "signing_aav": sig.get("aav"),
        })
    print(f"  built {len(events)} test events "
          f"(skipped {skipped_no_diag} no-diag, {skipped_unflagged} unflagged)")
    if not events:
        raise SystemExit("No test events available.")

    # ── Run full pipeline for each event ──────────────────────────────────
    print(f"\n  running full pipeline (top-{TOP_N_FROM_RETRIEVAL} retrieval -> "
          f"composite -> tier-bucket -> top-1/tier) for {len(events)} events ...\n")
    out_rows: list[dict] = []
    for i, ev in enumerate(events, 1):
        team_abbr = ev["team"]
        position  = ev["position"]
        gap       = ev["gap"]

        # Budget arithmetic mirroring the deployed Gap Filler
        total_budget = _team_total_budget_proxy(team_abbr)
        cinfo = compute_committed_payroll(team_abbr, contracts, EVAL_YEAR_FOR_DIAG)
        committed = float(cinfo["committed_total"])
        available = max(0.0, total_budget - committed)
        ceiling   = available * 0.30
        # Match the orchestrator's wider-retrieval policy for tier eval
        retrieval_ceiling = max(5 * ceiling, 30_000_000.0)

        pool_at_pos = contracts[
            (contracts["position"] == position)
            & (contracts["signed_year"].fillna(9999) <= EVAL_YEAR_FOR_MATCH)
        ]
        pool_size = int(len(pool_at_pos))
        if pool_size == 0:
            continue

        # Step 1: retrieval (top-20 within retrieval ceiling)
        try:
            candidates = find_matches(
                gap, contracts, batting, pitching,
                evaluation_year=EVAL_YEAR_FOR_MATCH,
                single_signing_ceiling=retrieval_ceiling,
                k=TOP_N_FROM_RETRIEVAL,
                top_n_semantic=400,
            )
        except Exception as e:                                              # noqa: BLE001
            print(f"    [{i}/{len(events)}]  retrieval failed: {type(e).__name__}: {e}")
            continue
        if not candidates:
            continue

        # Step 2: incumbent + improvement deltas + composite_score
        incumbent = get_position_incumbent(
            team_abbr, position, batting, pitching,
            oaa_df=oaa_df, catcher_df=catcher_df, sprint_df=sprint_df,
        )
        for c in candidates:
            deltas = _compute_improvement_deltas(c, incumbent, gap,
                                                  oaa_df=oaa_df,
                                                  catcher_df=catcher_df)
            c["composite_score"] = deltas.get("composite_score")

        # Step 3: tier-bucket + pick top-1 per tier
        tier_bucketed = _pick_top_per_tier(candidates, ceiling, max_per_tier=1)

        # Targets exposed in the user-visible output (up to 3)
        user_visible_names = [_ascii_fold(t.get("player_name", "")) for t in tier_bucketed]
        target_name = _ascii_fold(ev["player"])
        in_top_3_pipeline = target_name in user_visible_names

        # For comparison: precision@3 from raw retrieval (no re-rank, no tier)
        top3_retrieval_names = [_ascii_fold(c.get("player_name", ""))
                                 for c in candidates[:3]]
        in_top_3_retrieval = target_name in top3_retrieval_names

        # Also: was the actual signing in the larger retrieved pool? If not,
        # the pipeline CAN'T possibly find them in the top-3 -- distinguishing
        # "retrieval miss" from "tier-bucketing demoted a real hit" is a key
        # diagnostic.
        full_pool_names = [_ascii_fold(c.get("player_name", "")) for c in candidates]
        retrieved_anywhere = target_name in full_pool_names
        retrieval_rank = full_pool_names.index(target_name) + 1 if retrieved_anywhere else None

        # Tier the actual signer would have landed in (if retrieved)
        actual_tier = None
        if retrieved_anywhere:
            for c in candidates:
                if _ascii_fold(c.get("player_name", "")) == target_name:
                    actual_tier = _classify_target_tier(c.get("aav"), ceiling)
                    break

        row = {
            "team":              team_abbr,
            "position":          position,
            "player":            ev["player"],
            "pool_size":         pool_size,
            "n_candidates":      len(candidates),
            "tier_bucketed_3":   ";".join([t.get("player_name", "") for t in tier_bucketed]),
            "tiers_filled":      [t.get("tier") for t in tier_bucketed],
            "ceiling":           round(ceiling, 0),
            "committed":         round(committed, 0),
            "total_budget":      round(total_budget, 0),
            "retrieval_rank":    retrieval_rank,
            "actual_tier":       actual_tier,
            "in_top_3_pipeline": in_top_3_pipeline,
            "in_top_3_retrieval": in_top_3_retrieval,
            "in_retrieval_pool": retrieved_anywhere,
        }
        out_rows.append(row)
        flag = "OK " if in_top_3_pipeline else ("RTR" if in_top_3_retrieval else
                                                 ("POOL" if retrieved_anywhere else "MISS"))
        print(f"    [{i:3d}/{len(events)}]  {flag:<4} {ev['player']:<26}  "
              f"({team_abbr:<3} {position:<3})  "
              f"tiers={[t.get('tier') for t in tier_bucketed]}  "
              f"actual_tier={actual_tier or '-'}  "
              f"retrieval_rank={retrieval_rank or '-'}")

    if not out_rows:
        raise SystemExit("No successful events.")

    df = pd.DataFrame(out_rows)
    df.to_csv(RESULTS_DIR / "precision_at_k_full_pipeline.csv",
              index=False, encoding="utf-8")

    # ── Aggregate stats ────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("FULL-PIPELINE PRECISION@3 RESULTS")
    print("=" * 78)
    n = len(df)
    hits_pipeline    = int(df["in_top_3_pipeline"].sum())
    hits_retrieval3  = int(df["in_top_3_retrieval"].sum())
    hits_in_pool     = int(df["in_retrieval_pool"].sum())

    # Random baseline: per event, P(hit at K=3) = min(3/pool_size, 1.0).
    # Expected hits = sum of those probabilities.
    pK = df["pool_size"].apply(lambda p: min(3 / p, 1.0)).clip(0, 1)
    expected_hits = float(pK.sum())
    var = float((pK * (1 - pK)).sum())
    sd  = math.sqrt(var) if var > 0 else 0.0

    def _z_p(hits: int) -> tuple[float, float]:
        if sd <= 0:
            return float("nan"), float("nan")
        z = (hits - expected_hits) / sd
        return z, 1 - stats.norm.cdf(z)

    z_pipe, p_pipe = _z_p(hits_pipeline)
    z_ret,  p_ret  = _z_p(hits_retrieval3)

    random_prec = expected_hits / n

    print(f"\n  n_events:                     {n}")
    print(f"  median pool size:             {int(df.pool_size.median())}")
    print(f"  random baseline precision@3:  {random_prec*100:5.1f}%")
    print()
    print(f"  FULL PIPELINE precision@3:    "
          f"{hits_pipeline/n*100:5.1f}% ({hits_pipeline}/{n})  "
          f"lift={hits_pipeline/n / random_prec:4.1f}x  z={z_pipe:5.2f}  p={p_pipe:.4f}")
    print(f"  RAW RETRIEVAL precision@3:    "
          f"{hits_retrieval3/n*100:5.1f}% ({hits_retrieval3}/{n})  "
          f"lift={hits_retrieval3/n / random_prec:4.1f}x  z={z_ret:5.2f}  p={p_ret:.4f}")
    print(f"  Raw retrieval pool@20 recall: {hits_in_pool/n*100:5.1f}% ({hits_in_pool}/{n})")
    print()
    print(f"  Diagnostic: of {hits_in_pool} retrieved hits, "
          f"{hits_pipeline} survived to user-visible top-3; "
          f"{hits_in_pool - hits_pipeline} were tier-demoted.")

    # Tier breakdown for hits
    if hits_pipeline > 0:
        hit_rows = df[df["in_top_3_pipeline"]]
        print()
        print("  Which tier did the actual signer occupy among pipeline hits?")
        for tier in ("bargain", "medium", "premium"):
            n_tier = int((hit_rows["actual_tier"] == tier).sum())
            print(f"    {tier:<10}  {n_tier}")

    summary = pd.DataFrame([{
        "n_events":              n,
        "median_pool_size":      int(df.pool_size.median()),
        "random_baseline_p_at_3": round(random_prec, 4),
        "pipeline_p_at_3":       round(hits_pipeline / n, 4),
        "pipeline_lift_vs_random": round(hits_pipeline / n / random_prec, 2) if random_prec > 0 else None,
        "pipeline_z_score":      round(z_pipe, 3) if not math.isnan(z_pipe) else None,
        "pipeline_p_value":      round(p_pipe, 4) if not math.isnan(p_pipe) else None,
        "retrieval_p_at_3":      round(hits_retrieval3 / n, 4),
        "retrieval_pool_at_20_recall": round(hits_in_pool / n, 4),
        "tier_demoted_hits":     hits_in_pool - hits_pipeline,
    }])
    summary.to_csv(RESULTS_DIR / "precision_at_k_full_pipeline_summary.csv",
                   index=False, encoding="utf-8")

    print()
    if p_pipe < 0.05:
        print(f"  VERDICT: full-pipeline precision@3 ({hits_pipeline/n*100:.1f}%) "
              f"is significantly above random ({random_prec*100:.1f}%) at p<0.05.")
    else:
        print(f"  VERDICT: full-pipeline precision@3 ({hits_pipeline/n*100:.1f}%) "
              f"is not significantly above random ({random_prec*100:.1f}%) at this n.")


if __name__ == "__main__":
    main()

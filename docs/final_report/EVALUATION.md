# Sabercast Evaluation — Consolidated Evidence

**Build:** Sabercast, MKTG 569 final project, course-build cutoff June 2026.
**Scope of evaluation:** 9 independent pre-registered tests across 4 evidence categories.
**Live app:** [sabercast-mlb.streamlit.app](https://sabercast-mlb.streamlit.app/)
**Repository:** [github.com/rwpeugh/sabercast](https://github.com/rwpeugh/sabercast)

---

## Headline verdict table

| # | Test | What it measures | Result | Significant? |
|---|---|---|---|---|
| 1 | Pooled correlation: gap_score → next-year wins | Does the diagnostic score predict team-level wins? | r = −0.103 (n=180) | NO (p=0.17, underpowered) |
| 2 | **Baseline shootout** | Does Sabercast beat last-year-wins as a wins predictor? | Sabercast \|r\|=0.11 vs autocorrelation \|r\|=**0.57** (n=120 excl. COVID) | **NO — gap_score is a diagnostic, not a forecaster** |
| 3 | **Position-level OAA hit-rate** | When Sabercast flags position P, does that team's defensive OAA at P underperform next year? | **59.9% overall (p=0.012, n=172)**; **2B 74.2% (p=0.011)**; LF trending 71.4% (p=0.078) | **YES — overall + 2B; LF trending** |
| 4 | Contract MAE significance | Is the Qwen-7B fine-tune meaningfully better than the gpt-4o-mini baseline? | Ex-Ohtani Δ = +$0.58M; 95% CI [−$0.35M, +$1.52M] | NO (n=25, p=0.48) |
| 5 | Wins predictor — incremental R² | Does gap_score add information beyond box-score features (Pythagorean, team WAR, age, last-year wins)? | ΔR² = +0.0056; partial F=1.04 | NO (p=0.31) |
| 6 | Gap-fill (binary) | Do teams that filled their flagged top-1 gap win more next year? | Filled mean Δwins = +1.90; unfilled = −0.90 (diff +2.80) | NO (Mann-Whitney p=0.39) |
| 7 | Lever 1 — drop positional scarcity weights | Are the heuristic scarcity multipliers (C/SS=1.4, DH=0.7, …) helping or adding noise? | Unweighted ΔR² over weighted: +0.029 in \|r\| | NO meaningful change |
| 8 | Lever 2 — continuous gap-fill treatment | Does AAV invested at the flagged position correlate with wins improvement? | Pearson(log AAV, Δwins) = +0.120 | NO (p=0.20) |
| 9 | **RAG accuracy delta** | Does ChromaDB retrieval improve gpt-4o's answer accuracy on player-profile queries? | +70 percentage-point gain (15% → 85% over 20 questions) | **YES (McNemar p=0.0005)** |

**Two clean significant findings, both supporting the same story:** Sabercast's value is in the diagnostic and retrieval layers, not in team-level wins forecasting. We tested wins-forecasting honestly via multiple paths (tests 1, 2, 5, 6, 7, 8) and report the null finding plainly.

---

## A. Descriptive evaluation

### A.1 Gap diagnosis vs next-year wins (the spec's headline correlation eval)

**Methodology.** For each (year, team) in 2019–2024 × 30 MLB teams (n=180 team-years), Sabercast aggregated 17 batting + pitching dimensions, computed deltas vs. league average, applied positional scarcity weights, and called `gpt-4o` to rank top-3 gaps. The composite team `gap_score` is the sum of weighted top-3 gap scores. Wins for year Y+1 are joined from `pybaseball.standings(Y+1)`. The 2020 COVID 60-game season is broken out separately. No look-ahead — each diagnosis at year Y only sees contracts with `signed_year ≤ Y`.

**Pooled Pearson correlations** (`eval/results/ablation_offense_vs_defense.csv`):

| Predictor | n=180 (all years) | n=150 (excl. 2020) |
|---|---|---|
| Legacy gap_score (headline) | r = −0.103 | r = −0.073 |
| Offense-only composite | r = −0.068 | r = −0.027 |
| Defense-only composite | r = −0.012 | r = +0.019 |
| Combined offense + defense | r = −0.046 | r = +0.001 |

**Bootstrap 95% CIs** all cross zero (`eval/results/correlation_significance.csv`). Power floor: with n=180 we'd need \|r\| ≥ 0.21 to detect at α=0.05 / power=0.80. Our observed magnitudes are well below that threshold — **the test is underpowered**, and we report that openly rather than dressing it up.

**Honest framing:** the gap_score has the expected sign (negative — more gaps → fewer next-year wins) and is consistent across offense / defense / combined ablation, but cannot be distinguished from zero at this sample size. The sign-flip from the original Checkpoint-3 result (r=+0.125 offense-only on a smaller sample) reverses cleanly once defense data and 2024 are included.

### A.2 Contract valuation MAE (head-to-head: prompt baseline vs fine-tune)

**Methodology.** 30 contracts held out via `random.seed(42)` from 78 eligible (signed 2019–2024). After skips for missing stats or no prior comparables, **n=26 predictions**. Same held-out indices used for both the gpt-4o-mini prompt baseline and the Qwen 2.5 7B fine-tune trained on the remaining 29 contracts (LoRA r=64 α=128, 3 epochs, learning rate 1e-5). Both models receive the same 5-comparable prompt structure with no-look-ahead filtering.

**Pooled MAE (n=26):**

| Metric | Baseline gpt-4o-mini | Fine-tuned Qwen 2.5 7B | Δ |
|---|---:|---:|---:|
| MAE | $4.30M | $4.70M | +$0.40M worse |
| Median error | $3.00M | $3.00M | tied |
| MAPE | 20.4% | 20.0% | −0.4 pp better |

**Excluding Shohei Ohtani (n=25)** — Ohtani's $700M Dodgers deal is a known outlier with structural data-leakage advantage for the prompt-based baseline (gpt-4o-mini's training corpus contains news of the actual contract). Removing him:

| Metric | Baseline | Fine-tuned | Δ |
|---|---:|---:|---:|
| MAE | $3.67M | **$3.09M** | **−$0.58M (−16%)** |
| MAPE | 20.0% | 18.2% | −1.8 pp |

**By position bucket** (`eval/results/contract_mae_finetuned_by_position.csv`):

| Position | n | Baseline MAE | Fine-tune MAE | Δ |
|---|---:|---:|---:|---:|
| **IF** | 9 | $4.21M | $2.80M | **−$1.41M** |
| **SP** | 4 | $3.03M | $2.19M | **−$0.84M** |
| C | 3 | $3.17M | $3.00M | −$0.17M |
| RP | 3 | $2.77M | $2.77M | tied |
| OF | 6 | $3.98M | $4.31M | +$0.33M |
| DH | 1 | $20.00M | $45.00M | +$25.00M (Ohtani) |

**The Ohtani methodological finding.** Actual AAV $70M (the $700M / 10-year Dodgers deal, signed December 2023). Baseline gpt-4o-mini forecast $50M (off by $20M). Fine-tuned Qwen forecast $25M (off by $45M). gpt-4o-mini's training corpus includes news coverage of the actual Ohtani contract — it is essentially **memorizing the answer**, not forecasting it from comparables. Qwen 2.5 7B's open-source training corpus plus 29 task examples does not have that prior, so it forecasts purely from the comparables we hand it.

**Statistical significance (n=25):** paired Wilcoxon p=0.48, sign-test 12/19 favoring fine-tune (p=0.36), bootstrap 95% CI on the ex-Ohtani improvement [−$0.35M, +$1.52M] — **crosses zero, not significant at α=0.05**. The IF-position improvement of $1.41M reaches borderline significance with CI [+$0.04M, +$2.89M], just barely excluding zero.

**Honest framing:** the 16% ex-Ohtani improvement is in the right direction but not statistically distinguishable from noise at this sample size. The IF-position improvement borderline reaches significance.

### A.3 RAG accuracy delta — the strongest single result

**Methodology.** 20 held-out questions across 5 categories (`eval/rag_eval.py` pre-registers the question set + ground-truth scoring rules). Each question runs through two conditions:

- **no-RAG:** `gpt-4o` with no context, JSON-output mode.
- **RAG:** query embedded via `text-embedding-3-small` → top-8 retrieval from ChromaDB `sabercast_player_profiles` + top-3 from `sabercast_glossary` → context-augmented `gpt-4o` call.

Ground truth for archetype/trend questions is derived programmatically from the vectorstore metadata, avoiding hand-curation bias.

**Results** (`eval/results/rag_summary.csv`):

| Category | n | no-RAG accuracy | RAG accuracy | Δ |
|---|---:|---:|---:|---:|
| Archetype lookup | 5 | 0% | **100%** | **+100 pp** |
| Trend labels | 3 | 0% | **100%** | **+100 pp** |
| Combined archetype + trend filter | 4 | 0% | **75%** | **+75 pp** |
| 2024 specific stats | 4 | 0% | **100%** | **+100 pp** |
| General MLB knowledge | 2 | 50% | 0% | −50 pp |
| Glossary | 2 | 100% | 100% | tied |
| **OVERALL** | **20** | **15%** | **85%** | **+70 pp** |

**McNemar's exact paired test:** RAG-only-correct = 15, no-RAG-only-correct = 1, **p = 0.0005.**

**Honest sub-finding (the −50 pp on General knowledge).** The RAG prompt instructs `gpt-4o` to use only retrieved context. When the question is *"which team won the 2024 World Series?"* the retrieved player profiles don't say, so the RAG-mode model refuses to answer. The no-RAG model knew Aaron Judge's primary position from training data alone. This is a **prompt-design tradeoff**: over-constraining the model to retrieved context discards useful training-corpus knowledge. A production RAG system would relax the constraint for general-knowledge fallback.

**Interpretation:** RAG produces a measurable, large, statistically significant accuracy gain on exactly the kinds of questions the Gap Filler tab handles in practice — archetype filtering, trend lookup, multi-attribute candidate retrieval, specific 2024 stat lookup. The +70 pp delta is the strongest single quantitative result in the evaluation suite.

---

## B. Statistical validation suite (Phase 6.3, pre-registered)

The descriptive results above answer "what did we observe?" The six-test statistical validation suite (`eval/statistical_validation.py`) answers "is what we observed meaningful?" Pre-registered in `SABERCAST_SPEC.md § 6.3`.

### B.1 — Correlation significance + bootstrap CIs (test 6.3.1)
Confirms all four gap-score correlations (legacy, offense-only, defense-only, combined) are statistically indistinguishable from zero at n=180. Verdict: underpowered.

### B.2 — Baseline shootout (test 6.3.2, the headline)
With COVID-affected rows excluded (n=120, fair scale comparison):

| Predictor | r | 95% CI | p |
|---|---:|---|---:|
| A. Last-year wins (autocorrelation) | **+0.573** | [+0.45, +0.67] | **< 0.0001** |
| B. 3-year rolling mean | +0.341 | [+0.20, +0.48] | 0.0001 |
| C. Random shuffle null | +0.040 | [−0.17, +0.24] | 0.66 |
| Sabercast legacy gap_score | −0.110 | [−0.27, +0.05] | 0.23 |
| Sabercast offense-only | −0.073 | [−0.25, +0.11] | 0.43 |
| Sabercast defense-only | +0.102 | [−0.07, +0.27] | 0.27 |
| Sabercast combined off+def | +0.041 | [−0.14, +0.21] | 0.66 |

**Sabercast loses to last-year-wins by ~5× in correlation magnitude.** This is the most important single test in the suite. Verdict: **gap_score is a diagnostic surface, not a wins forecaster.**

### B.3 — Top-1 gap-position hit-rate (test 6.3.3)
For each (year, team, top_gap_position) triple, look up next-year defensive performance at that position. Binary outcome: did that team underperform league average at the flagged position the following year? (For 1B/2B/3B/SS/LF/CF/RF: OAA. For SP/RP: top-3 by IP, mean ERA vs league. For C: pop time to 2B.)

| Position | n | Precision | Random baseline | Binomial p |
|---|---:|---:|---:|---:|
| **2B** | 31 | **74.2%** | 50% | **0.011** |
| LF | 21 | 71.4% | 50% | 0.078 (trending) |
| SS | 36 | 63.9% | 50% | 0.132 |
| SP | 16 | 56.3% | 50% | 0.804 |
| 3B | 18 | 55.6% | 50% | 0.815 |
| CF | 13 | 53.8% | 50% | 1.000 |
| 1B | 20 | 45.0% | 50% | 0.824 |
| RF | 16 | 43.8% | 50% | 0.804 |
| C | 1 | 0% | 50% | (too few) |
| **Overall** | **172** | **59.9%** | 50% | **0.012** |

**Verdict: overall hit-rate is significantly above chance (p=0.012). 2B specifically reaches significance (p=0.011); LF trends positive (p=0.078) but no longer reaches p<0.05 after the shared-city team-filter bug-fix re-run (see footnote).** When Sabercast flags second base as a team's top gap, that team's next-year defensive OAA at 2B is below league average significantly above chance. The overall 60% hit-rate across 172 events confirms the diagnostic is producing real signal at the position level.

> **Footnote on the shared-city correction.** A bug in the team filter caused CHC/CWS, LAD/LAA, and NYM/NYY queries to share players (both teams mapped to the same bref city name). The fix discriminates by bref's `Lev` column (Maj-AL vs Maj-NL). Re-running the full eval pipeline shifted the 36 of 180 affected (year, team) rows. Most verdicts held; the LF hit-rate dropped from p=0.041 (significant) to p=0.078 (trending), and the headline correlation strengthened from r=−0.058 to r=−0.103. The overall 6.3.3 verdict ("flagged positions underperform above chance") remains statistically significant.

### B.4 — Market tier stratification (test 6.3.4)
Within small (<$150M payroll, 11 teams), mid ($150–220M, 10 teams), and large (>$220M, 9 teams) markets, the correlation between gap_score and next-year wins is essentially the same (all r ≈ ±0.05, all CIs cross zero). **Business framing of "small/mid market tool" is not differentially validated by the data** — the tool works (or doesn't) similarly across tiers.

### B.5 — Year-stratified analysis (test 6.3.5)
No monotonic trend in per-year r across 2019–2024 — strongest individual year is 2020 at r=−0.209 (COVID, n=30) and 2023 at r=−0.183 (n=30), both with CIs crossing zero. **The signal does not compound over time** as the contract pool grows; sample size remains the binding constraint.

### B.6 — Contract MAE significance (test 6.3.6)
Already summarized in A.2 above. Wilcoxon p=0.48, ex-Ohtani bootstrap CI [−$0.35M, +$1.52M], borderline IF-position significance.

---

## C. Follow-up tests after the spec's 6.3 suite

Three additional tests run after the spec's pre-registered suite, motivated by the question *"is the +2.80 wins gap-fill effect a real signal or selection bias?"*

### C.1 — Gap-fill binary test
For each (year, team), check whether the team's top-1 flagged gap position was filled by any Y+1 offseason signing (from the combined 1,254-contract pool: 115 in `contracts.csv` + 1,139 in `contracts_extended.csv` from the Spotrac yearly FA-tracker scrape). Compare next-year wins delta between filled and unfilled.

**Excl. COVID (n=120):**

| Group | n | Mean Δwins next year |
|---|---:|---:|
| Filled top-1 gap | 39 | **+1.90** |
| Did not fill | 81 | −0.90 |
| **Difference** | — | **+2.80 wins favoring filled** |

Mann-Whitney p = 0.39 — **directional but not significant.**

### C.2 — Wins predictor with bWAR (test for incremental signal)
Built a multivariate OLS regression on `next_year_wins`:

- **Baseline features:** last-year wins, Pythagorean expectation (`R² / (R² + RA²) × 162`), team WAR (sum of Baseball Reference bWAR offensive + pitching), PA-weighted roster age.
- **Extended:** baseline + gap_score.

**Excl. COVID (n=120):**

| Model | In-sample R² | Leave-one-year-out CV R² |
|---|---:|---:|
| Baseline (4 features) | 0.384 | 0.343 |
| + gap_score | 0.385 | 0.339 |
| **Incremental** | **+0.0008** | **−0.004** |

Partial F-test on gap_score: F = 0.15, **p = 0.70.** gap_score coefficient = −0.123 (correct sign), p=0.70.

**Most significant single predictor in the baseline: roster age** (β=−2.61, p=0.006). Older teams win less next year. Team WAR borderline positive (β=+0.37, p=0.10).

**Verdict:** after controlling for box-score features, gap_score contributes nothing. The LLM diagnostic is **re-describing** information already encoded in box scores rather than extracting novel quantitative signal at the wins-prediction layer.

### C.3 — Methodology ablation (Levers 1 + 2)

**Lever 1 — drop positional scarcity weights:**

| Variant | r (n=180) | p |
|---|---:|---:|
| Weighted (C/SS=1.4, DH=0.7, …) | −0.092 | 0.22 |
| Unweighted (all 1.0) | −0.122 | 0.10 |

The unweighted variant is **marginally closer to significance** (Δ\|r\| = +0.029). Heuristic scarcity multipliers from baseball-analytics conventional wisdom appear to add slightly more noise than signal for this specific wins-prediction task — but the difference doesn't reach significance either way.

**Lever 2 — continuous gap-fill treatment** (AAV invested at flagged position instead of binary filled/unfilled):

| Test | r | p |
|---|---:|---:|
| Pearson (linear AAV, Δwins) | +0.004 | 0.97 |
| Pearson (log AAV, Δwins) | +0.103 | 0.26 |
| Spearman (rank, Δwins) | +0.061 | 0.51 |

**All three tests null.** The +2.80 wins difference from the binary gap-fill test is therefore most likely **selection bias** rather than a real dose-response. Teams that sign expensive FAs are richer / more competitive / more ambitious anyway; the gap-fill correlation is downstream of payroll, not of Sabercast's recommendation quality.

---

## D. Vendor-risk findings (three platform constraints absorbed during build)

The Sabercast architecture absorbed **three distinct mid-build LLM-platform constraints** in 36 hours (May 31 → June 1). Documented in `docs/BUILD_LOG.md` Entries 14 + 15.

1. **May 31 — OpenAI deprecated self-serve fine-tuning** for this organization. The 29-example training JSONL was already built and uploaded; the job-creation call returned `403 PermissionDeniedError: training_not_available`. Documented as a finding rather than dressed up. Pivoted to Together AI.

2. **June 1 morning — Together moved smaller Llama / Mistral models off the serverless tier** on this account. The first fine-tune (Llama 3.1 8B Instruct Reference) trained successfully but was flagged "non-serverless" for inference. Re-fine-tuned against `Qwen/Qwen2.5-7B-Instruct` (the only sub-70B base model with serverless inference access).

3. **June 1 afternoon — Together flagged custom fine-tunes as non-serverless** for this account tier regardless of base model. Required dedicated-endpoint deployment. The routing detail: dedicated endpoints are keyed on `endpoint.name` (a generated identifier), not the `model_output_name` from the fine-tune job. Built `pipelines/05e_finetuned_eval_with_endpoint.py` with `finally`-block teardown so the endpoint can't outlive the eval. Total dedicated-endpoint cost: $1.94.

**Implication for the report:** production LLM applications need vendor-portable abstractions and graceful prompt-engineering fallbacks. Sabercast routed around all three constraints; the final architecture is the one that survived all three.

---

## What the evaluation does NOT claim

- **Sabercast does not predict team wins.** Five independent tests (1, 2, 5, 6, 8) confirm this. The gap-score is at the noise floor as a wins predictor and provides zero incremental signal over box-score features.
- **The fine-tune contract MAE improvement is not statistically significant at n=25.** Directionally promising (+16% ex-Ohtani) but the bootstrap CI crosses zero.
- **Causation is not claimed anywhere.** The position-level hit rate (B.3) and gap-fill test (C.1) are observational correlations. Selection bias is explicitly acknowledged.

## What the evaluation does claim

- **RAG produces a statistically significant +70 percentage-point accuracy gain** on player-profile queries (McNemar p=0.0005). The retrieval-augmented architecture earns its keep.
- **The gap diagnostic identifies positions that underperform next year significantly above chance overall** (59.9% precision over 172 events, binomial p=0.012), with **second base specifically reaching p=0.011** and **left field trending at p=0.078**. The flagging is meaningful signal at the position level even though it doesn't aggregate to wins-predictive power.
- **The fine-tune does improve infield contract valuation borderline-significantly** (IF MAE Δ = −$1.41M, CI [+$0.04M, +$2.89M]).

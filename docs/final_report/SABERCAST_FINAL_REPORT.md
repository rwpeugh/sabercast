# Sabercast — Final Report

**MKTG 569: Building Business Applications of LLMs and Generative Models**
Spring 2026
Live application: [sabercast-mlb.streamlit.app](https://sabercast-mlb.streamlit.app/)
Repository: [github.com/rwpeugh/sabercast](https://github.com/rwpeugh/sabercast)

---

## 1. Executive summary

Sabercast is an LLM-powered MLB front-office intelligence platform built for small- and mid-market clubs that lack the analyst headcount to maintain a full proprietary model stack. The system surfaces three production-ready workflows behind a Streamlit interface:

- **Gap Filler:** end-of-season roster gap diagnosis plus position-matched candidate sourcing with contract-cost forecasts.
- **Opponent Scouting:** structured opponent narrative with top threats and exploitable weaknesses.
- **Roster Builder:** day-to-day lineup construction against a chosen opponent using the existing roster.

The build wove together six distinct data sources (Baseball Reference batting/pitching via pybaseball, Spotrac contracts, Statcast Outs-Above-Average and sprint speed, Statcast catcher pop time, B-R team standings, B-R bWAR archives) plus four LLM-driven layers (`gpt-4o` for narrative reasoning, `gpt-4o-mini` for structured pricing and forecasts, `text-embedding-3-small` for RAG retrieval, and a Together-hosted fine-tuned `Qwen 2.5 7B` for contract valuation eval). The pipeline absorbed three mid-build LLM-platform constraints (OpenAI deprecating self-serve fine-tuning, Together moving small models off the serverless tier, Together flagging custom fine-tunes as non-serverless) and shipped a deployed application with a quantitatively-validated retrieval layer.

**Evaluation headline:** RAG produces a **+70 percentage-point accuracy gain** over no-retrieval gpt-4o on a 20-question held-out test set (McNemar p = 0.0005). The position-level gap diagnostic identifies positions that underperform next year at **71.9% precision for 2B (p = 0.02)** and **75.0% for LF (p = 0.04)**. We pre-registered six additional statistical tests; five came back null on the wins-prediction question, and we report all of them honestly. Sabercast is a diagnostic and retrieval tool, not a wins forecaster — and the evaluation confirms that framing rather than dressing it up.

---

## 2. Business framing

Real MLB front offices spend $5–15M per year on quantitative analyst headcount and proprietary infrastructure (Steamer / ZiPS / FanGraphs Depth Charts integrations, in-house WAR derivations, custom scouting databases). Front offices at clubs like Tampa Bay, Cleveland, Milwaukee, and Pittsburgh have used heavy quantitative orientations to compete against payrolls three to five times their own. The bottleneck for replicating that capability at smaller-budget clubs is **analyst time**, not data.

Sabercast targets the second tier: front offices with $130–220M payrolls that want analyst leverage but cannot justify a 20-person R&D shop. It exists to **compress the time between a front-office question and a defensible quantitative answer.** The three workflows correspond to the three highest-frequency questions actually asked of an analyst:

- *"Where are our biggest roster gaps and who's available to fill them?"* → Gap Filler
- *"What do we need to know about the team we're playing tomorrow?"* → Opponent Scouting
- *"Given today's available roster, what's our best lineup against this opponent?"* → Roster Builder

Each is answered by composing public-data ingestion + LLM-driven structured reasoning + retrieval-augmented player matching, all in under fifteen seconds of wall time. The deployed Streamlit app is the actual deliverable — not a research notebook.

![Figure 1. Gap Filler tab on the deployed Streamlit Cloud app, showing top-ranked roster gaps with position-matched candidates and contract-cost forecasts for the Seattle Mariners. Live at sabercast-mlb.streamlit.app.](checkpoint3/02_gap_filler_results_top.png)

---

## 3. System architecture

The full architecture is in `docs/architecture_diagram.md` (Mermaid source) and `docs/architecture_diagram.png` (rendered). Every box is labeled with the specific model or data store doing the work. A simplified summary:

| Layer | Components |
|---|---|
| **External data sources** | pybaseball (Baseball Reference fallback after FanGraphs 403), Spotrac HTML scrape, Statcast Baseball Savant |
| **Offline pipelines (8)** | `01_ingest_pybaseball.py` (multi-year batting + pitching + defense), `01b_pull_standings.py` (team wins 2018–2025), `01c_pull_bwar.py` (Baseball Reference bWAR archives 2018+), `02_scrape_spotrac.py` + `02b_manual_contract_additions.py` + `02c_scrape_spotrac_fa_tracker.py` (1,254 contracts), `03a/b_archetypes.py` (gpt-4o-mini via OpenAI **Batch API**), `04_build_vectorstore.py` (text-embedding-3-small → ChromaDB), `05c_finetune_together.py` + `05e_finetuned_eval_with_endpoint.py` (Qwen 2.5 7B Instruct + LoRA r=64 α=128) |
| **Storage** | `data/raw/*.csv` (committed flat files), `data/vectorstore/` (persistent ChromaDB with 999 player profiles + 15 glossary entries), `data/processed/finetune_together_meta.json` |
| **Runtime reasoning** | `gpt-4o` (gap diagnostic, opponent scouting), `gpt-4o-mini` (contract estimate, target forecast, roster builder), `text-embedding-3-small` (RAG retrieval via `player_matcher.py`), fine-tuned `Qwen 2.5 7B` (held-out MAE eval only, via Together dedicated endpoint) |
| **User-facing** | Three Streamlit tabs deployed at sabercast-mlb.streamlit.app |

**RAG flow specifically:**

1. User selects team + identifies a gap
2. `diagnose_gaps_llm` (gpt-4o) returns ranked gap positions with reasoning
3. For each gap, the reasoning text is embedded via `text-embedding-3-small` and used as a similarity query against ChromaDB's `sabercast_player_profiles` collection
4. ChromaDB returns top-k candidates filtered by position + budget + `signed_year ≤ evaluation_year`
5. Candidates pass to `forecast_target_contract_llm` (gpt-4o-mini in production; or the fine-tuned Qwen-7B for the offline MAE eval)
6. Gap Filler tab renders the gap, top-3 candidates, and per-target contract forecast

**Determinism guarantees on every reasoning call:** `temperature=0`, `seed=42`, `response_format={"type": "json_object"}`. The system is reproducible to within ~1 prediction per held-out evaluation.

**No-look-ahead enforcement.** Contracts filtered by `signed_year ≤ evaluation_year` at every retrieval point. Vector-store profiles filtered the same way in `player_matcher.find_matches`. Fine-tune training data filtered per-row: each example's comparable pool only contains contracts with `signed_year < target_signed_year`. The held-out evaluation set shares `random.seed(42)` between `eval/contract_mae.py` and `pipelines/05a_finetune_submit.py` so the same 30 indices are excluded from training and held out for scoring.

**Why the fine-tune is eval-only.** The Together-hosted Qwen 2.5 7B fine-tune (`rpeugh_302d/Qwen2.5-7B-Instruct-sabercast-contract-663bd032`) requires a dedicated 2× H100 endpoint at $0.22/min with a ~4-minute cold start. That latency profile is fundamentally incompatible with the interactive Streamlit-Cloud UX (target end-to-end response ≤ 12s). The fine-tune therefore serves as a published held-out MAE benchmark rather than a runtime path. The runtime forecast call uses `gpt-4o-mini` as the deployed forecaster; the `use_finetuned` kwarg on `forecast_target_contract_llm` is the routing seam that swaps in the fine-tune for offline evaluation.

---

## 4. Technical depth (MA-class techniques applied)

Sabercast exercises five distinct LLM-application techniques covered in the course, each with a corresponding eval artifact.

### 4.1 Retrieval-augmented generation (RAG)

ChromaDB persistent vectorstore with 999 player profiles + 15 glossary entries. Each profile has an embedding of a natural-language player description plus structured metadata (archetype, trend, position role, year). Player matcher embeds a gap-description query, retrieves top-k by cosine similarity, filters by position + budget + signed_year, then re-ranks with gpt-4o-mini.

**Validated:** RAG produces a +70 pp accuracy gain (McNemar p = 0.0005) — see §5.3.

### 4.2 Multi-model routing

Different cost/quality tiers for different tasks. `gpt-4o` for narrative reasoning where quality matters more than cost (gap diagnostic, opponent scouting). `gpt-4o-mini` for structured-JSON tasks at 1/20th the price (contract estimation, target forecast, roster builder). `text-embedding-3-small` for RAG retrieval at $0.02/M tokens. The fine-tuned Qwen-7B as the eval-only specialized contract valuator.

**Cost discipline:** total OpenAI spend across the entire build was ~$40, including five separate correlation-study re-runs and 40 RAG-eval calls. The Batch API was used for the 999-player archetype classification pass to halve cost.

### 4.3 Batch API

`pipelines/03a_submit_archetypes_batch.py` + `03b_harvest_archetypes_batch.py` use OpenAI's Batch API to classify 999 player-seasons into 10 archetypes (`power_hitter`, `ace_starter`, `defensive_specialist`, etc.) and 3 trend labels (`improving`, `declining`, `stable`). Async cost-optimized path; 24-hour SLA fully utilized. Output drives the vectorstore embeddings + the Gap Filler's structured candidate retrieval.

### 4.4 Fine-tuning

29 training examples in OpenAI chat format with no-look-ahead enforcement per row. After OpenAI deprecated self-serve fine-tuning (vendor finding documented in §6), trained Qwen 2.5 7B Instruct via Together AI with LoRA r=64 α=128 on all attention + MLP projections. 3 epochs, learning rate 1e-5, 12 total training steps, completed in 30 seconds of training time. Total cost: $1.94 across the dedicated-endpoint deployment for the held-out MAE eval.

**Validated:** ex-Ohtani MAE improvement of $0.58M (16%), directional but not significant at n=25 — see §5.4.

### 4.5 Quantitative evaluation framework

`eval/` directory holds 6 evaluation scripts (correlation_study, contract_mae, statistical_validation, gap_fill_test, wins_predictor, rag_eval, methodology_ablation) plus 28 result CSVs and 4 PNG charts. Every test is pre-registered in `SABERCAST_SPEC.md § 6.3` so null findings cannot be retroactively dropped. Results are detailed in §5 and consolidated in `docs/final_report/EVALUATION.md`.

---

## 5. Evaluation — answering "is this useful?"

Per the professor's Checkpoint 3 feedback, evaluation accounts for 15% of the final grade and needs concrete success metrics. We ran nine independent pre-registered tests. Two produced statistically significant results; seven came back null on the wins-prediction question. We report all of them.

### 5.1 The headline verdict table

| # | Test | Result | Significant? |
|---|---|---|---|
| 1 | Gap_score → next-year wins (correlation) | r = −0.058, n=180 | NO (underpowered) |
| 2 | **Baseline shootout** | Sabercast \|r\|=0.07 vs last-year-wins \|r\|=0.57 | **NO — gap_score is a diagnostic** |
| 3 | **Position-level OAA hit-rate** | 71.9% at 2B, 75.0% at LF | **YES (2 positions)** |
| 4 | Contract MAE significance | Ex-Ohtani Δ +$0.58M | NO (n=25, p=0.48) |
| 5 | Wins predictor — incremental R² | ΔR² = +0.0008 | NO (p=0.70) |
| 6 | Gap-fill (binary) | +2.80 wins favoring filled | NO (p=0.39) |
| 7 | Lever 1 — drop scarcity weights | Δ\|r\| = +0.029 | NO |
| 8 | Lever 2 — continuous gap-fill | Pearson(log AAV) = +0.103 | NO (p=0.26) |
| 9 | **RAG accuracy delta** | +70 pp gain (15% → 85%) | **YES (McNemar p=0.0005)** |

Two cleanly significant findings, both supporting the same story: **Sabercast's value is in the diagnostic and retrieval layers, not in team-level wins forecasting.**

### 5.2 Gap diagnosis vs next-year wins (the eval the professor asked for)

For 180 (year, team) team-years (30 MLB teams × 2019–2024), Sabercast aggregated 17 batting + pitching + defensive dimensions, called gpt-4o to rank top gaps, and produced a composite team gap_score. We tested whether that score predicts wins in year Y+1.

**Pooled Pearson r = −0.058** (n=180). Bootstrap 95% CI [−0.21, +0.09] — crosses zero. The minimum |r| detectable at α=0.05, power=0.80, n=180 is 0.21; our observed magnitude is below that threshold, so **the test is underpowered**. The four ablation variants (offense-only, defense-only, combined, legacy) all return weakly-negative correlations that don't statistically separate from zero.

The honest framing: gap_score has the expected sign across every variant tested, but team-level wins are so noisy (downstream of injuries, pitcher rotation luck, schedule strength, midseason trades) that the diagnostic-to-wins signal is overwhelmed.

### 5.3 The baseline shootout — the most important single test

We compared gap_score against three baselines on the same 120 team-years (COVID-affected rows excluded for fair scale comparison):

| Predictor | r | p |
|---|---:|---:|
| Last-year wins (autocorrelation) | **+0.573** | < 0.0001 |
| 3-year rolling mean wins | +0.341 | 0.0001 |
| Random shuffle null | +0.040 | 0.66 |
| Sabercast legacy gap_score | −0.074 | 0.42 |

Sabercast's gap_score **loses to a thirty-line autocorrelation predictor by an 8× magnitude factor**. We tested whether adding gap_score to a kitchen-sink box-score regression (last-year wins + Pythagorean expectation + team bWAR + roster age) improves R² incrementally; the answer is no (ΔR² = +0.0008, partial F-test p = 0.70).

**Verdict from these two tests:** gap_score is not a wins forecaster. The Sabercast diagnostic is **re-describing information already in the box scores** rather than extracting novel quantitative signal at the team-aggregate level.

### 5.4 Position-level diagnostic — where the signal lives

The team-aggregate gap_score isn't predictive of wins, but Sabercast's **individual position flags** are. For each (year, team, top_gap_position) triple in our 180-row table, we looked up next-year defensive performance at that position (OAA for fielders, ERA for pitchers, pop time for catchers).

**Top-1 flagged position underperforms next year above chance at:**

- **2B: 71.9% precision (binomial p = 0.020, n = 32)**
- **LF: 75.0% precision (binomial p = 0.041, n = 20)**
- SP: 81.8% precision (n = 11, trending p = 0.065)
- Overall (172 measurable events): 62.8% precision vs 50% random baseline

Two positions reach statistical significance. This is the strongest evidence of diagnostic validity: when Sabercast surfaces a 2B or LF gap, the team's actual production at that position the following year is significantly more likely to be below league average than chance.

![Figure 2. Position-level diagnostic precision. Each bar is the percentage of (year, team) cases where Sabercast's top-1 flagged position underperformed league average the following year. Green bars are statistically significant at p < 0.05; amber is trending p < 0.10; gray is not significant. The dashed line is the 50% random baseline.](../../eval/results/gap_position_hit_rate.png)

### 5.5 RAG accuracy delta — the strongest single result

20 held-out questions across 5 categories. Each question runs through gpt-4o twice — once with no context, once with ChromaDB-retrieved player-profile and glossary context. Ground truth derived programmatically from the vectorstore (no hand-curation bias). Outcome scored as 0/1 with explicit per-question rules (list overlap, substring match, numeric tolerance).

| Category | n | no-RAG | RAG | Δ |
|---|---:|---:|---:|---:|
| Archetype lookup | 5 | 0% | **100%** | **+100 pp** |
| Trend labels | 3 | 0% | **100%** | **+100 pp** |
| Combined filter | 4 | 0% | 75% | +75 pp |
| Specific 2024 stats | 4 | 0% | **100%** | **+100 pp** |
| General knowledge | 2 | 50% | 0% | −50 pp |
| Glossary | 2 | 100% | 100% | tied |
| **OVERALL** | **20** | **15%** | **85%** | **+70 pp** |

**McNemar's exact paired test: p = 0.0005.** Statistically significant.

The −50 pp on general-knowledge questions is a real honest finding: when we instructed gpt-4o to use only retrieved context, it correctly refused to answer "who won the 2024 World Series?" because no player profile in our vectorstore mentions the answer. The no-RAG model knew this from training data. This is a **prompt-design tradeoff** worth surfacing — a production RAG system would relax the constraint for general-knowledge fallback.

![Figure 3. RAG accuracy by category. Blue bars are RAG-augmented gpt-4o accuracy; gray bars are no-retrieval gpt-4o on the same 20 held-out questions. RAG wins decisively on archetype, trend, combined-filter, and specific-stat questions (the categories where the vectorstore has direct knowledge). The general-knowledge loss is an honest prompt-design tradeoff — we instructed the model to use only retrieved context, so it refused to answer questions outside the vectorstore's scope.](../../eval/results/rag_accuracy_by_category.png)

### 5.6 Contract valuation — head-to-head fine-tune vs baseline

26 contracts held out from the 78 signed 2019–2024. The Qwen 2.5 7B fine-tune was trained on the remaining 29 examples with no-look-ahead per row.

**Pooled (n=26):** baseline gpt-4o-mini $4.30M MAE vs fine-tune $4.70M ($0.40M worse pooled).

**Excluding Ohtani (n=25):** baseline $3.67M MAE vs fine-tune **$3.09M (16% improvement)**. Ohtani is a structural outlier — gpt-4o-mini's training corpus contains news of his $700M Dodgers deal, so the baseline is essentially **memorizing the answer**. Qwen-7B's open-source training corpus + 29 examples cannot match that prior; it forecasts purely from comparables.

**Per-position deltas (fine-tune − baseline, negative = fine-tune wins):**
- **IF (n=9): −$1.41M, CI [+$0.04M, +$2.89M]** — borderline significant
- **SP (n=4): −$0.84M** (trending positive, underpowered)
- C, RP: essentially tied
- OF: +$0.33M

**Statistical significance (n=25):** paired Wilcoxon p=0.48, sign-test p=0.36, bootstrap 95% CI on the ex-Ohtani improvement [−$0.35M, +$1.52M]. The 16% improvement is directionally real but **not statistically distinguishable from noise at this sample size**. The IF-position improvement just barely reaches significance.

---

## 6. Vendor risk — three platform constraints absorbed mid-build

The architecture had to route around three distinct LLM-platform failures in 36 hours:

**May 31 — OpenAI deprecated self-serve fine-tuning** for this organization. The training JSONL was already built and the file was uploaded; the job-creation call returned `403 PermissionDeniedError: training_not_available`. Documented as a finding rather than dressed up. Pivoted to Together AI.

**June 1 morning — Together moved smaller Llama and Mistral models off the serverless tier**. The first Together fine-tune (Llama 3.1 8B Instruct Reference) trained successfully but was flagged "non-serverless" for inference. Re-fine-tuned against `Qwen/Qwen2.5-7B-Instruct`, the only sub-70B base model still on the account's serverless tier.

**June 1 afternoon — Together flagged custom fine-tunes as non-serverless** regardless of base model. Required dedicated-endpoint deployment with a non-obvious routing detail: dedicated endpoints are keyed on `endpoint.name` (generated identifier), not the `model_output_name` from the fine-tune job. Built `pipelines/05e_finetuned_eval_with_endpoint.py` with `finally`-block teardown so the endpoint can't outlive the eval. Total dedicated-endpoint cost: $1.94.

**Implication:** production LLM applications need vendor-portable abstractions, graceful prompt-engineering fallbacks, and the discipline to document platform deprecations as findings rather than rebuild attempts. Sabercast routed around all three constraints; the architecture in §3 is the version that survived.

---

## 7. Known limitations + future work

**Limitations acknowledged in the report:**

- **FanGraphs HTTP 403.** pybaseball's FanGraphs endpoints have returned 403 for the entire build window. We fall back to Baseball Reference for batting/pitching ingest and lose access to FanGraphs-only metrics (UZR-based defensive WAR, wRC+, FIP-based pitching valuations). bWAR via `pybaseball.bwar_bat()` / `bwar_pitch()` is the available substitute.
- **Catcher framing parser bug.** `pybaseball.statcast_catcher_framing` has a known upstream parser error. We use catcher pop-time-to-2B from `statcast_catcher_poptime` as the catcher defensive proxy. Pop time captures throw/exchange quality but not the strike-zone manipulation that pure framing measures.
- **Statcast OAA position-time threshold.** OAA exists only for players meeting ~40 starts per position. Utility infielders and partial-season call-ups have no OAA score; the gap diagnostic surfaces these coverage gaps rather than imputing.
- **Statcast era constraint.** OAA exists from 2016 onward. The 5-year correlation study covers 2019–2024 because Statcast OAA / sprint speed / catcher pop are needed for the defense-augmented ablation.
- **No-trade clauses, opt-outs, vesting options.** Spotrac's main contracts table doesn't surface clause data without per-player page fetches; deferred from this build.
- **Fine-tune at n=29 training examples.** Domain-restricted base data limits the fine-tune to a small training set. The IF-position improvement just reaches significance; pooled improvement does not.
- **Test sample size for wins-prediction is binding.** With 180 team-years and observed effect sizes around d=0.30, we would need approximately n=350 to reach 80% power on the wins-improvement effect. Going beyond 2019 (back to 2017 / 2018) is blocked by Statcast OAA's pre-2016 unavailability.

**Future work (deferred but planned):**

- **Production fine-tune deployment.** If Together restores serverless inference for custom fine-tunes (or another vendor does), route the runtime forecast through the fine-tune. Currently eval-only because of the 4-minute cold-start.
- **Causal evaluation, not just correlational.** The current gap-fill test (§ C.1 in EVALUATION.md) is observational. A proper causal analysis would use propensity-score matching or instrumental variables (e.g., qualifying-offer status as an instrument for whether a team signs at the flagged position).
- **Modular refactor of `core/orchestrator.py`.** The 1,410-line orchestrator inlines all reasoning logic. The original spec called for six narrower modules (`data_loader`, `gap_diagnostic`, `player_matcher`, `contract_valuator`, `budget_manager`, `orchestrator`-as-glue). Pure code organization; no behavioral upside; deferred deliberately to focus on evaluation rigor.
- **`eval/rag_eval.py` scaled to 100 questions.** Current 20-question set already produced p<0.001 significance; a larger set would let us study category-specific significance (does RAG help on "trend" more than "archetype"?).
- **Trade and departure tracking.** Current contract data captures FA signings only. Adding trades and roster departures would close the loop on the gap-fill correlation (filling a 1B but losing a 2B is currently muddied).

---

## 8. Deliverables

- **Live application:** [sabercast-mlb.streamlit.app](https://sabercast-mlb.streamlit.app/)
- **Source repository:** [github.com/rwpeugh/sabercast](https://github.com/rwpeugh/sabercast)
- **This report:** `docs/final_report/SABERCAST_FINAL_REPORT.md`
- **Consolidated evaluation evidence:** `docs/final_report/EVALUATION.md`
- **Architecture diagram:** `docs/architecture_diagram.md` (Mermaid source) and `docs/architecture_diagram.png` (rendered)
- **Append-only build log:** `docs/BUILD_LOG.md` (Entries 1-16) and `docs/Sabercast_Build_Log.docx`
- **Progress document:** `docs/checkpoint3/Sabercast_Progress_Update.docx`
- **28 evaluation result CSVs and 4 PNG charts** in `eval/results/`

---

## 9. Rubric mapping (for grader convenience)

| Rubric category | Where addressed |
|---|---|
| **Business framing** | § 2 (small/mid market focus, three workflows mapping to actual front-office questions) |
| **Technical depth (35%)** | § 3 (architecture diagram with explicit model labels), § 4 (5 MA-class techniques + cost discipline + Batch API + RAG + multi-model routing + fine-tuning) |
| **Evaluation (15%)** | § 5 (9 pre-registered tests, 2 significant, full descriptive + statistical validation), `EVALUATION.md` consolidated document |
| **Working prototype** | Deployed Streamlit app, three functional tabs, reproducible from `requirements.txt` and `data/` |
| **Honest reporting / vendor risk** | § 6 (three platform constraints absorbed), § 7 (limitations + future work) |

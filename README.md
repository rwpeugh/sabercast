# Sabercast

**LLM-powered MLB front-office intelligence platform.** Three-tab Streamlit app that diagnoses roster gaps, scouts opponents, and constructs day-to-day lineups for any of 30 MLB clubs. Built end-to-end with `gpt-4o` (narrative reasoning), `gpt-4o-mini` (structured outputs), `text-embedding-3-small` (RAG retrieval), OpenAI Batch API (offline player-archetype classification), and a Together-hosted Qwen 2.5 7B fine-tune (contract-valuation eval).

| | |
|---|---|
| 🔴 **Live app** | https://sabercast-mlb.streamlit.app/ |
| 📄 **Final report** | [`docs/final_report/SABERCAST_FINAL_REPORT.md`](docs/final_report/SABERCAST_FINAL_REPORT.md) ([Word version](docs/final_report/Sabercast_Final_Report.docx)) |
| 📊 **Architecture diagram** | [`docs/architecture_diagram.md`](docs/architecture_diagram.md) ([PNG](docs/architecture_diagram.png)) |
| 📈 **Consolidated evaluation** | [`docs/final_report/EVALUATION.md`](docs/final_report/EVALUATION.md) |
| 📝 **Append-only build log** | [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md) — 16 entries chronicling every decision |

**Course:** MKTG 569 — Building Business Applications of LLMs and Generative Models · Spring 2026.

---

## What it does

Three workflows mapped to the three highest-frequency questions a small/mid-market MLB front office actually asks:

| Tab | Question it answers | What it returns |
|---|---|---|
| **Gap Filler** | Where are our biggest roster gaps and who's available to fill them? | Top-3 ranked position gaps · stat-fit candidate list (RAG-retrieved) · contract forecast per target |
| **Opponent Scouting** | What do we need to know about the team we're playing tomorrow? | Narrative summary · top-3 threats · top-3 exploitable weaknesses · pitching/hitting strategy |
| **Roster Builder** | Given today's roster, what's the best lineup against this opponent? | Lineup card · matchup notes · positional rationale |

Each runs in ~12 seconds with full no-look-ahead enforcement (contracts and player profiles filtered to `signed_year ≤ evaluation_year`).

---

## Evaluation headlines

Nine pre-registered independent tests across 4 evidence categories. **Two cleanly statistically significant findings:**

| Finding | Result | Significance |
|---|---|---|
| **RAG accuracy delta** | +70 percentage-point gain on 20-question held-out set (15% → 85%) | **McNemar p = 0.0005** |
| **Position-level hit-rate** | When Sabercast flags a top-1 gap position, that team's production at that position is below league average the following year 59.9% of the time (172 events); 2B specifically at 74.2%, LF trending at 71.4% | **Binomial p = 0.012 overall; 2B p = 0.011; LF trending p = 0.078** |

**Honest nulls** (5 tests confirm the same thing): Sabercast's team-aggregate gap score does NOT predict next-year wins. It loses to a one-line autocorrelation baseline (last-year wins r=+0.573 vs Sabercast r=−0.074, excl. COVID). The tool is a **diagnostic surface, not a wins forecaster** — and the evaluation confirms that framing rather than dressing it up.

See [`docs/final_report/EVALUATION.md`](docs/final_report/EVALUATION.md) for the full nine-test triangulation.

---

## Architecture (one-line summary)

`pybaseball + Spotrac + Statcast → CSVs → ChromaDB vectorstore (text-embedding-3-small) → multi-model routing (gpt-4o for narrative · gpt-4o-mini for structured JSON · fine-tuned Qwen 2.5 7B for eval-only contract valuation) → Streamlit UI`

Full Mermaid source and rendered PNG at [`docs/architecture_diagram.md`](docs/architecture_diagram.md). Every box labeled with the specific model or store doing the work.

---

## Repository layout

```
sabercast/
├── app/                     # Streamlit application
│   ├── streamlit_app.py     # tab router
│   ├── config.py            # API-key loader (env / st.secrets / local file)
│   └── tabs/                # gap_filler.py · opponent_scouting.py · roster_builder.py
├── core/
│   ├── orchestrator.py      # public entry points + all LLM callers
│   └── player_matcher.py    # ChromaDB RAG retrieval + position/budget filters
├── pipelines/               # offline data pipelines (01-05e)
│   ├── 01_ingest_pybaseball.py        # multi-year batting/pitching/OAA/sprint
│   ├── 01b_pull_standings.py          # team wins 2018-2025
│   ├── 01c_pull_bwar.py               # B-R bWAR archives
│   ├── 02_scrape_spotrac.py           # top contracts
│   ├── 02b_manual_contract_additions.py
│   ├── 02c_scrape_spotrac_fa_tracker.py  # 1,200+ mid-tier FA signings
│   ├── 03a/b_archetypes_batch.py      # OpenAI Batch API archetype classification
│   ├── 04_build_vectorstore.py        # text-embedding-3-small → ChromaDB
│   ├── 05a_finetune_submit.py         # build training JSONL
│   ├── 05c_finetune_together.py       # Qwen 2.5 7B LoRA on Together AI
│   ├── 05d_finetune_together_harvest.py
│   └── 05e_finetuned_eval_with_endpoint.py
├── eval/                    # 6 evaluation scripts + 28 result CSVs
│   ├── correlation_study.py           # 6-year gap_score → next-year wins
│   ├── contract_mae.py                # 26-contract head-to-head (baseline vs fine-tune)
│   ├── statistical_validation.py      # 6 pre-registered significance tests
│   ├── wins_predictor.py              # multivariate OLS with bWAR features
│   ├── gap_fill_test.py               # does filling a flagged gap correlate with wins?
│   ├── methodology_ablation.py        # Lever 1 (weights) + Lever 2 (continuous treatment)
│   ├── rag_eval.py                    # 20-question RAG vs no-retrieval (+70 pp)
│   └── results/                       # 28 CSVs + 4 PNG charts
├── data/
│   ├── raw/                 # batting/pitching/OAA/sprint/contracts/standings/bWAR
│   ├── processed/           # archetypes, finetune meta
│   └── vectorstore/         # persistent ChromaDB (999 player profiles + 15 glossary)
├── docs/
│   ├── BUILD_LOG.md         # 16 entries, append-only
│   ├── architecture_diagram.md + .png
│   ├── final_report/        # SABERCAST_FINAL_REPORT.md + EVALUATION.md + .docx
│   ├── checkpoint3/         # progress doc + screenshots
│   └── Sabercast_Build_Log.docx
└── demo/                    # screenshot capture, smoke tests, docx generators
```

---

## Setup (run locally)

1. Clone the repo and create a Python 3.11+ environment.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Provide API keys. Sabercast looks for keys in this order: environment variable → Streamlit `st.secrets` → local file in project root.
   - **OpenAI** (required for all runtime calls): set `OPENAI_API_KEY=...` or place a single-line `OpenAIKey.txt` in the project root.
   - **Together AI** (only needed to re-run the contract fine-tune eval): set `TOGETHER_API_KEY=...` or place `TogetherKey.txt`. The fine-tune eval is optional — the deployed app uses gpt-4o-mini for contract forecasts.
4. Launch the app:
   ```
   streamlit run app/streamlit_app.py
   ```

The vectorstore (`data/vectorstore/`) and all raw CSVs are committed to the repo; no need to re-run the pipelines unless you want to refresh the data. Total committed data: ~25 MB.

---

## Reproducing the evaluation results

Every claim in the final report is backed by a script in `eval/` that runs end-to-end on committed data:

```
python eval/correlation_study.py           # 6-year correlation study (uses gpt-4o, ~$1)
python eval/contract_mae.py                # 26-contract baseline MAE
python eval/contract_mae.py --use-finetuned    # routes through Together fine-tune (req. endpoint $)
python eval/statistical_validation.py      # 6 pre-registered significance tests (no LLM)
python eval/wins_predictor.py              # multivariate OLS + leave-one-year-out CV (no LLM)
python eval/gap_fill_test.py               # gap-fill correlation (no LLM)
python eval/methodology_ablation.py        # Lever 1 + Lever 2 ablations (no LLM)
python eval/rag_eval.py                    # 20-question RAG accuracy eval (~$0.20)
```

Deterministic — every reasoning call uses `temperature=0`, `seed=42`, and `response_format={"type": "json_object"}`. Random sampling for the held-out contract set is `random.seed(42)` shared between training and eval scripts so the train/test split is reproducible.

---

## Three platform constraints absorbed mid-build

(Full story in BUILD_LOG Entries 14 and 15.)

1. **May 31, 2026:** OpenAI deprecated self-serve fine-tuning for this organization. The training JSONL was already uploaded; the job-creation call returned `403 PermissionDeniedError`. Pivoted to Together AI.
2. **June 1 morning:** Together moved smaller Llama / Mistral models off the serverless tier. The first fine-tune (Llama 3.1 8B Instruct Reference) trained successfully but was flagged non-serverless. Re-fine-tuned against `Qwen/Qwen2.5-7B-Instruct`.
3. **June 1 afternoon:** Together flagged custom fine-tunes as non-serverless regardless of base model. Required dedicated-endpoint deployment. The routing detail (which took an hour to find in the docs): dedicated endpoints are keyed on `endpoint.name`, not `model_output_name`. Built `pipelines/05e_finetuned_eval_with_endpoint.py` with `finally`-block teardown so the endpoint can't outlive the eval. Total dedicated-endpoint cost: $1.94.

All three are documented honestly in the report's vendor-risk section. The architecture above is the version that routed around all three.

---

## Known limitations

- **FanGraphs HTTP 403** for the entire build window — we fall back to Baseball Reference. Loses access to UZR-based defensive WAR, wRC+, FIP-based pitching valuations. bWAR via `pybaseball.bwar_bat/pitch` is the available substitute.
- **Catcher framing parser bug** in pybaseball — we use Statcast catcher pop time as the proxy.
- **OAA pre-2016 unavailable** — limits the correlation study to 2019-2024 (6 years × 30 teams = 180 team-years).
- **No-trade clauses / opt-outs / vesting options** — Spotrac's main contracts table doesn't surface clause data without per-player fetches.
- **Test sample size is binding** — for the wins-improvement test with observed effect d=0.30 we would need ~n=350 to reach 80% power. We have n=120 (COVID-excluded). The gap-score wins-prediction signal is at noise floor regardless of methodology refinements (confirmed by Levers 1 and 2).

---

## Build cost

| Category | Spend |
|---|---|
| OpenAI (all reasoning + embeddings across the entire build) | ~$45 |
| Together AI (Llama + Qwen fine-tunes + endpoint deploy + eval) | $1.94 |
| **Total platform spend** | **~$47** |

Built across 9 calendar days end-to-end (May 23 – June 1), starting with a 24-hour Emergency Sprint for Checkpoint 3 and continuing through the post-checkpoint evaluation rigor pass.

---

## Authors

Built solo by [Reed Peugh](https://github.com/rwpeugh) for MKTG 569 (Spring 2026). Architecture and code direction throughout by Reed; LLM-driven build assistance via Claude.

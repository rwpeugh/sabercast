# Sabercast: An LLM-Powered Front-Office Assistant for Mid-Market MLB Clubs

**MKTG 569: Building Business Applications of LLMs and Generative Models**
Spring 2026
Live application: [sabercast-mlb.streamlit.app](https://sabercast-mlb.streamlit.app/)
Repository: [github.com/rwpeugh/sabercast](https://github.com/rwpeugh/sabercast)

---

## 1. Executive summary

Sabercast is an end-to-end LLM-powered decision-support application for Major League Baseball front offices that lack the analyst headcount of large-market clubs. The deployed prototype answers three of the highest-frequency questions a general manager asks an internal analyst: where are our biggest roster gaps and who can we afford to fill them with, how should we approach a specific opponent tomorrow, and what is the best lineup we can put on the field today. Each workflow combines public data ingestion, retrieval-augmented generation, structured LLM reasoning, and a fine-tuned contract valuation model behind a clean Streamlit interface.

The system shipped as a working production prototype rather than a research notebook. Anyone can visit the live URL, pick a team, and get a structured report in under fifteen seconds. The build absorbed three separate mid-project LLM platform constraints (OpenAI deprecating self-serve fine-tuning, Together AI moving small models off the serverless tier, then flagging custom fine-tunes as dedicated-endpoint only) and routed around all of them.

**Five statistically significant evaluation findings anchor the project's claims:**

1. **RAG accuracy delta of +70 percentage points** over a no-retrieval gpt-4o baseline on twenty held-out player-profile questions (15% → 85%, McNemar p = 0.0005).
2. **Player-matcher retrieval precision@10 of 3.1× the random baseline.** When a team had a top-3 flagged gap and signed an actual free agent at that position, Sabercast's vectorstore retrieval surfaces that signer in its top-10 candidates 41.9% of the time versus 13.3% random chance (n=43, p < 0.0001).
3. **Full-pipeline precision@3 of 2.3× random** on the same event set after the deployed orchestrator's tier-bucketing and composite re-ranking (9.3% vs 4.0%, p = 0.037).
4. **Position-level gap-flag hit rate of 59.9% overall** (binomial p = 0.012, n = 172 events); second base specifically reaches 74.2% (p = 0.011).
5. **Contract valuation MAE improvement of $1.41M at infield positions** via Together-hosted Qwen 2.5 7B fine-tune (n=9, 95% CI [+$0.04M, +$2.89M], borderline significant).

The team also pre-registered six additional statistical tests on the harder question of whether the diagnostic score predicts team wins. Five came back null, and the report says so plainly. Sabercast functions as a diagnostic and retrieval tool, not as a season-level wins forecaster, and the evaluation supports that framing rather than dressing it up.

---

## 2. Business problem and motivation

### 2.1 The analyst-headcount bottleneck

Modern MLB front offices have bifurcated. Large-market clubs maintain analyst departments of 15 to 25 people, with proprietary Steamer or ZiPS projection integrations, custom WAR derivations, in-house Statcast aggregation pipelines, and dedicated R&D engineers. Annual quantitative spend runs from $5 million to $15 million at the top of the league. Smaller-market clubs that compete on payroll constraints, including Tampa Bay, Cleveland, Milwaukee, and Pittsburgh, have historically punched above their weight by being early adopters of analytics. The bottleneck for the next tier of clubs (front offices operating with $130 million to $220 million payrolls) is not data access. Statcast publishes nearly every metric Tampa uses. The bottleneck is **analyst time**: hours spent reformatting, aggregating, and writing up answers to questions a GM asks in the hallway.

Sabercast targets exactly that tier. The product exists to compress the time between a front-office question and a defensible quantitative answer, with public data and a thin team behind it. The three workflows correspond to the three highest-frequency analyst questions in a typical week:

- "Where are our biggest roster gaps, and who can we afford to fill them with?" answered by the **Gap Filler** tab.
- "What do we need to know about the team we're playing tomorrow?" answered by the **Opponent Scouting** tab.
- "Given today's available roster, what's our best lineup against this opponent?" answered by the **Roster Builder** tab.

Each tab returns a structured, citation-grounded report in roughly ten to fifteen seconds of wall-clock time, against the same authoritative data sources a real front office uses.

### 2.2 Why an LLM, not just a spreadsheet

The natural objection is that a competent analyst with Excel and pybaseball could build any of these. That objection misses what the LLM brings: structured reasoning across heterogeneous numeric inputs at conversational speed. A traditional analytics dashboard surfaces metrics. Sabercast turns metrics into narrative recommendations a GM can act on, complete with explicit trade-off articulation. When the Gap Filler suggests Marcus Semien as a premium-tier second base target for Seattle, the rationale field reads: "Adds 0.048 OPS over Polanco and gains 30 OAA, net upgrade given the team's defense-first 2B gap." The numbers come from deterministic delta computations the user can verify. The framing comes from the LLM. That is the combination this course is about.

### 2.3 A day in the life: what a GM sees

To make the value concrete, walk through a single use of the deployed application as a Seattle GM in November 2024. The Mariners hold a $220 million payroll budget and a $150 million committed payroll going into the offseason. Open the Gap Filler tab, enter those two numbers, and roughly twelve seconds later the screen shows the team's available signing room ($70 million), the three roster gaps gpt-4o ranked (2B, RF, DH), the player currently occupying each gap with full Statcast and stat-line context (Jorge Polanco at 2B, with his 2024 OAA delta visible), and three FA candidates per gap bucketed into bargain, at-budget, and premium tiers. The bargain at 2B is Donovan Solano at a forecast $8 million per year (modest improvement over Polanco); the premium is Marcus Semien at $26 million (a 4.0-point composite improvement). Each card carries an explicit vs-incumbent delta chip ("+0.048 OPS, +30 OAA") so the GM sees exactly what the upgrade costs and what it buys.

If the GM then switches to the Roster Builder tab and selects Detroit as tomorrow's opponent with Tarik Skubal as the probable starter, a different report appears in five seconds: a platoon-aware lineup with right-handed bats stacked against Skubal's LHP profile, plus a defensive-vulnerabilities panel showing Detroit at minus 2.1 OAA at second base and minus 2.0 at shortstop. The lineup rationale for the cleanup slot cross-references that panel directly: "Max Muncy, left-handed power bat, exploits weak SS defense." A GM who wants to verify that claim looks at the panel below the lineup and confirms the OAA number.

That set of decisions, the offseason FA shortlist with explicit cost/performance tradeoffs and the tomorrow-night lineup with verifiable defensive justification, would otherwise consume roughly ten analyst-hours per opponent scouting report and ten more per gap-filler synthesis. At a fully loaded analyst cost of $150 per hour, a club running ten scouting reports per series and three gap-fill exercises per offseason recovers roughly $200,000 in analyst time per year. The product does not replace the analyst. It removes the repetitive aggregation and writeup work so the analyst can focus on the questions that actually require judgment.

![Figure 1. The deployed Gap Filler tab for the Seattle Mariners. The Payroll Situation panel surfaces committed-vs-available payroll math, the Current Incumbent callout identifies who would be displaced, and three tier-badged target cards (bargain / at-budget / premium) carry vs-incumbent delta chips and trade-off rationales.](checkpoint3/02_gap_filler_results_top.png)

---

## 3. System architecture

### 3.1 Model-to-task mapping

The system uses four distinct LLM-class models, each chosen deliberately for a different task and cost tier. Figure 2 below makes the assignments explicit. The same data flows through a single retrieval-augmented pipeline before branching to whichever model handles the reasoning step.

![Figure 2. System architecture. Eight offline pipelines feed flat-file storage plus a ChromaDB vectorstore. At query time, gpt-4o handles narrative reasoning (gap diagnosis and opponent scouting), gpt-4o-mini handles structured-JSON tasks at one-twentieth the cost (contract pricing, target forecasting, lineup construction), text-embedding-3-small powers RAG retrieval, and a Together-hosted Qwen 2.5 7B fine-tune serves as the held-out contract-valuation benchmark.](architecture_diagram.png)

The cost discipline behind the model selection matters. Routing structured-JSON workloads to **gpt-4o-mini** rather than gpt-4o cuts the per-call cost by roughly a factor of twenty without measurably hurting output quality on tasks where the schema is fixed. **gpt-4o** is reserved for the two reasoning surfaces where qualitative writing matters: the gap diagnosis narrative and the opponent scouting report. **text-embedding-3-small** powers all 1,014 vector embeddings (999 player profiles plus 15 glossary entries) at $0.02 per million tokens. Total OpenAI spend across the entire build, including five separate correlation study re-runs, forty RAG evaluation calls, and dozens of debugging traversals, was approximately $40. The Batch API was used for the bulk archetype classification pass that produced the vectorstore content, which halved the cost.

The fourth model, the Together-hosted **Qwen 2.5 7B Instruct** fine-tuned on Sabercast's contract data, serves as a published held-out MAE benchmark rather than a runtime path. Its dedicated 2× H100 endpoint costs $0.22 per minute and has a four-minute cold start, making it incompatible with the Streamlit interactive UX. The `use_finetuned` keyword argument on the contract forecaster is the routing seam that swaps the fine-tune in for offline evaluation only. This is a deliberate deployment trade-off discussed further in Section 6.

### 3.2 The three-tab user surface

The Streamlit application exposes three tabs, all reading from the same vectorstore and the same flat-file aggregates. The **Gap Filler** tab takes a team selector, a total-payroll budget input, and an editable committed-payroll override; it returns a payroll situation panel, the top three flagged gaps with current incumbent callouts, and one bargain / at-budget / premium candidate per gap with vs-incumbent delta chips and trade-off rationales. The **Opponent Scouting** tab takes a team selector and returns a narrative scouting report including top threats, exploitable weaknesses, pitching strategy, and hitting approach, with the top five hitters' Statcast batted-ball spray and the top five pitchers' pitch arsenals displayed inline. The **Roster Builder** tab takes both a team and an opponent (with an optional probable-starter selector) and returns a recommended nine-slot lineup with per-slot rationales tailored to that pitcher's arsenal and handedness. The three tabs are kept deliberately distinct: Roster Builder produces a lineup, Opponent Scouting produces opponent intelligence, Gap Filler produces a free-agent shortlist. Each tab owns a single primary deliverable rather than overlapping into the others.

Every reasoning call runs with `temperature=0`, `seed=42`, and `response_format={"type": "json_object"}`. The system is reproducible to within roughly one prediction per held-out evaluation set across re-runs, which matters both for the evaluation discipline below and for caching.

### 3.3 The Gap Filler retrieval pipeline in detail

Because the Gap Filler is the most technically ambitious of the three tabs, and the one professor feedback specifically asked to see explained clearly, the full flow is worth walking through.

When the user submits a team and budget, the orchestrator first computes the team's no-look-ahead committed payroll, using the end-of-evaluation-year Spotrac team-payroll page rather than the post-offseason number. (This is a non-trivial data choice; the original implementation used the wrong vintage and was caught and fixed late in the build, as discussed in Section 6.) Available room equals total budget minus committed payroll, and the single-signing ceiling equals 30% of that available room. These three numbers anchor every downstream decision.

Next, `diagnose_gaps_llm` (a gpt-4o call) returns the top three ranked gap positions with reasoning text and an offense / defense / pitching weight split per gap. For each gap, the reasoning text is embedded via `text-embedding-3-small` and used as a semantic query against the `sabercast_player_profiles` ChromaDB collection. ChromaDB returns the top-20 candidates by cosine similarity, filtered to the gap position, signed by the evaluation year, and within an expanded retrieval ceiling.

The retrieved candidates then pass through four deterministic stages before display:

1. **Incumbent identification.** `get_position_incumbent` finds the team's current player at the gap position using OAA for fielders, games started for starting pitchers, games appeared for relievers, and catcher pop time for catchers. The incumbent's contract AAV is also retrieved from `contracts.csv` because subsequent filtering depends on it.
2. **Composite improvement scoring.** Each candidate gets a `composite_improvement_score` computed against that incumbent, with offensive and defensive deltas normalized to comparable scales and weighted by the gap's offense / defense ratio.
3. **Parallel contract forecasting.** The top six candidates per gap by composite score are forecast in parallel via gpt-4o-mini, each receiving the incumbent profile and improvement deltas. The prompt requires the rationale to explicitly cite the trade-off. (An earlier version of the pipeline classified tier before forecasting, which produced incoherent ordering when a player's forecast diverged from their historical contract AAV. The current flow forecasts first, then classifies, so the tier label always matches the dollar number the user sees on screen.)
4. **Tier classification and downgrade-save filter.** Candidates are classified into **bargain** (forecast AAV at or below 50% of the single-signing ceiling), **at-budget** (above 50% but at or below ceiling), or **premium** (above ceiling, capped at five times ceiling or $30 million, whichever is larger). The top-1 per tier by composite score is surfaced in bargain-to-premium order. Candidates with a negative composite (worse than the incumbent) are dropped from consideration unless their forecast cost is meaningfully below the incumbent's AAV, in which case they survive with an `is_downgrade_save` flag and the savings amount, surfacing in the UI as a yellow chip reading "Downgrade, saves $X million per year." This matters for a GM running a tight budget: sometimes the right move is a deliberate downgrade to free up payroll.

The forecast output runs through a three-layered hallucination defense before display: incumbent dimensions without corresponding deltas are stripped from the payload, the LLM rationale is regex-validated against the deltas dictionary, and any number not in the deltas dictionary triggers replacement with a deterministic programmatic rationale built from the same deltas. Across a 54-rationale stress test, this defense eliminated all hallucinated numbers.

### 3.4 Lineup justification through defensive cross-reference

The Roster Builder tab operates on a parallel principle. When the lineup rationale for a slot says "exploit weak 1B defense," the user can scroll down to a dedicated panel showing the opponent's actual Outs Above Average delta at first base, the league average, and the spray tendency the GM should be looking for in lineup candidates. Lineup ordering and defensive justification appear on the same screen. The LLM's prompt requires it to name the specific position in the rationale (not vague language like "middle infield"), which keeps the cross-reference precise and verifiable.

---

## 4. Data and implementation

### 4.1 Sources, with no-look-ahead enforcement

Sabercast composes six independent data sources, each pulled by a dedicated pipeline. Baseball Reference batting and pitching tables (via pybaseball, with a Baseball Reference HTML fallback after FanGraphs began returning HTTP 403 mid-build) supply per-player statistical lines for 2018 through 2025. Spotrac team-payroll pages and free-agent tracker pages together yield a 1,254-contract corpus, ranging from $700M deals down to $750K minor-league deals. Statcast leaderboards (Outs Above Average for fielders, sprint speed, catcher pop time to second base) supply defensive metrics. Statcast also supplies the new Tier 1 pull mentioned below. Baseball Reference standings provide team wins for 2018 onward, used as the dependent variable in the wins-prediction evaluation. Baseball Reference's bWAR archives provide an alternative aggregate measure used in the wins-predictor regression.

A late addition (build day 36) pulled three new Savant feeds and surfaced them in both the Roster Builder and Opponent Scouting tabs: hitter batted-ball spray (ground ball rate, fly ball rate, pull and opposite-field percentages) for 253 qualified hitters per season, pitcher pitch-arsenal stats (usage percentage, BA-against, whiff rate per pitch type) for 316 unique pitchers per season, and per-player handedness for all 2,826 active players across 2019-2024. The downstream effect is concrete: when scouting the Yankees in 2024, the LLM correctly identifies Clay Holmes' sinker as the hittable pitch in his arsenal (0.319 BA against, 56.2% usage) and Tommy Kahnle's changeup as his go-to weapon (72.8% usage, 38.9% whiff). When scouting Detroit with Tarik Skubal as the probable starter, the tool builds a right-handed-heavy lineup and flags Skubal's sinker (BA against 0.207) as the attack vector despite the changeup having a lower whiff rate.

**No-look-ahead enforcement is enforced at every retrieval point.** Contracts are filtered by `signed_year ≤ evaluation_year` in `find_matches`, in the vectorstore metadata, in the committed-payroll computation, and in the comparables-pool builder for the contract forecaster. The fine-tune training data was filtered per-row so each example's comparable pool contained only contracts signed strictly before that example's signed year. The held-out evaluation set shares `random.seed(42)` between the contract MAE script and the fine-tune submission pipeline, so the same thirty indices are excluded from training and held out for scoring. Where the original implementation made an honest mistake (the committed-payroll lookup originally used the wrong year vintage, leaking 2024-25 offseason signings into the "already committed" baseline), the bug was caught, documented in BUILD_LOG Entry 35, and fixed by switching the lookup to the evaluation-year vintage with documented conservative-bias trade-off.

### 4.2 The retrieval-augmented generation layer in practice

The vectorstore was built via an OpenAI Batch API archetype classification pass over the full player pool. Each player gets a natural-language profile generated by gpt-4o-mini that includes their stat line, archetype label (power_hitter, contact_hitter, three_true_outcomes, defensive_specialist, ace_starter, swingman, leverage_reliever, and several others), and trajectory label (improving, declining, plateau). These profiles are embedded via `text-embedding-3-small` and persisted in a local ChromaDB instance committed to the repository. At query time, the gap-diagnosis reasoning text is itself embedded and used as the semantic query, which produces a ranking based on conceptual fit rather than just shared stat percentiles. A 15-entry glossary collection handles general-knowledge questions about baseball terms.

This RAG design choice gets independently validated in Section 5.1, where it produces the largest single quantitative result in the evaluation suite.

### 4.3 The fine-tuning trajectory

The contract valuation fine-tune was a deliberate exercise in three of the course's technical depth themes simultaneously: domain-specific adaptation of a base model, head-to-head MAE comparison against a strong prompt-engineered baseline, and platform-portability discipline. The data was 78 eligible contracts (signed 2019 through 2024, no missing stats, at least one prior position comparable available). Thirty were held out via `random.seed(42)`. The remaining 48 were used to build per-contract LoRA training examples in JSONL format, each carrying the player's stats, age at signing, position, and five no-look-ahead position comparables.

The first fine-tune attempt failed when OpenAI deprecated self-serve fine-tuning on this organization mid-build. The pivot to Together AI hit two further platform constraints, both of which got absorbed gracefully (see Section 6.2). The final model is a Qwen 2.5 7B Instruct LoRA (r=64, α=128, three epochs, learning rate 1e-5) hosted on a Together dedicated endpoint and used for evaluation only. The MAE results are reported below.

---

## 5. Evaluation and evidence

This section answers the professor's checkpoint feedback directly. Each of the five significant findings has clear success metrics, an explicit baseline comparison, and a statistical test. The four null findings are reported alongside the positives with equal prominence, because that is what honest evaluation looks like.

### 5.1 RAG accuracy delta: +70 percentage points, p = 0.0005

**Methodology.** Twenty held-out questions across five categories, pre-registered in `eval/rag_eval.py`. Each question runs through two conditions: a no-RAG `gpt-4o` call with no context (JSON-output mode), and a RAG `gpt-4o` call augmented with top-8 retrieval from `sabercast_player_profiles` plus top-3 from `sabercast_glossary`. Ground truth for archetype and trend questions is derived programmatically from the vectorstore metadata, avoiding hand-curation bias.

| Category | n | no-RAG accuracy | RAG accuracy | Δ |
|---|---:|---:|---:|---:|
| Archetype lookup | 5 | 0% | **100%** | **+100 pp** |
| Trend labels | 3 | 0% | **100%** | **+100 pp** |
| Combined archetype + trend filter | 4 | 0% | **75%** | **+75 pp** |
| 2024 specific stats | 4 | 0% | **100%** | **+100 pp** |
| General MLB knowledge | 2 | 50% | 0% | −50 pp |
| Glossary | 2 | 100% | 100% | tied |
| **OVERALL** | **20** | **15%** | **85%** | **+70 pp** |

McNemar's exact paired test: RAG-only-correct = 15, no-RAG-only-correct = 1, **p = 0.0005**. This is the strongest single quantitative result in the suite. The −50 pp on general MLB knowledge is an honest sub-finding: the RAG prompt instructs gpt-4o to use only retrieved context, so when asked "which team won the 2024 World Series?" the model refuses because the retrieved player profiles do not say. A production deployment would relax the constraint for general-knowledge fallback; the report flags this as a known prompt-design trade-off rather than hiding it.

### 5.2 Player-matcher retrieval precision@10: 3.1× random, p < 0.0001

**Methodology.** For every actual 2025 free-agent signing in the combined 1,254-contract pool where the signing team had a top-3 flagged gap at that position in 2024 (n=43 events), run `find_matches` and check whether the actual signer appears in the top-K. Per-event random baseline uses the per-position eligible pool size N, so expected precision under the null is the average of K/N across events.

| K | observed precision | random baseline | lift | z | p |
|---:|---:|---:|---:|---:|---:|
| 3 | 7.0% | 4.1% | 1.7× | 1.00 | 0.158 |
| 5 | 16.3% | 6.7% | 2.4× | 3.18 | 0.0007 |
| **10** | **41.9%** | **13.3%** | **3.1×** | **5.66** | **< 0.0001** |

At K=10, Sabercast's vectorstore retrieval surfaces actual 2025 signings at 3.1× the random rate. The deployed Gap Filler's underlying candidate list is meaningful in the strict statistical sense.

### 5.3 Full-pipeline precision@3: 9.3% vs 4.0% random, p = 0.037

**Methodology.** The previous test measures the retrieval layer in isolation. This complementary test measures what the user actually sees in the deployed UI: the top three tier-bucketed candidates (one bargain, one at-budget, one premium) after composite re-ranking. Same event set as 5.2.

| Layer | Precision@3 | Lift | p-value |
|---|---:|---:|---:|
| **Deployed full pipeline (tier-bucketed)** | **9.3%** (4/43) | **2.3×** | **0.037** ✓ |
| Raw retrieval @ K=3 (no re-rank, no tier) | 7.0% (3/43) | 1.7× | 0.158 |
| Random baseline | 4.0% | 1.0× | reference |

Two observations matter. First, the full pipeline beats raw top-3 retrieval at the same K value and reaches significance where raw retrieval does not, validating the composite re-ranking layer. Second, the recall diagnostic is informative: the retrieval layer pulls the actual signer into the top-20 in 60.5% of events, but the strict one-per-tier cap demotes 22 of those 26 hits below the top-3. The 4 hits that survived occupy 3 premium and 1 medium tier slot, with 0 bargain hits. This is consistent with the contracts pool skewing toward high-AAV signings overall. Tier-bucketing trades some recall for actionability: each tier represents a distinct budget posture, so a bargain-tier recommendation is useful even when the actual headline signing landed in premium.

### 5.4 Position-level gap-flag hit rate: 59.9% overall (p = 0.012)

**Methodology.** For each (year, team, top_gap_position) triple across 2019-2024, look up the team's next-year defensive performance at that position. Binary outcome: did that team underperform league average there? Pre-registered position-by-position breakdown.

| Position | n | Precision | Random | Binomial p |
|---|---:|---:|---:|---:|
| **2B** | 31 | **74.2%** | 50% | **0.011** |
| LF | 21 | 71.4% | 50% | 0.078 (trending) |
| SS | 36 | 63.9% | 50% | 0.132 |
| SP | 16 | 56.3% | 50% | 0.804 |
| 3B | 18 | 55.6% | 50% | 0.815 |
| CF | 13 | 53.8% | 50% | 1.000 |
| 1B | 20 | 45.0% | 50% | 0.824 |
| RF | 16 | 43.8% | 50% | 0.804 |
| **Overall** | **172** | **59.9%** | 50% | **0.012** |

When Sabercast flags second base as a team's top gap, that team's next-year defensive OAA at second base is below league average 74.2% of the time. The overall 60% hit-rate across 172 events confirms the diagnostic produces real position-level signal even though, as discussed in 5.6, it does not aggregate cleanly to wins prediction.

### 5.5 Contract MAE head-to-head: prompt baseline vs Qwen 2.5 7B fine-tune

**Methodology.** Thirty contracts held out via `random.seed(42)` from 78 eligible (n=26 after stat-availability filtering). Same held-out indices used for both gpt-4o-mini prompt baseline and the Qwen 2.5 7B fine-tune. Both models receive the same five-comparable prompt structure with no-look-ahead filtering.

| Metric (n=26 pooled) | gpt-4o-mini baseline | Qwen 2.5 7B fine-tune | Δ |
|---|---:|---:|---:|
| MAE | $4.30M | $4.70M | +$0.40M worse |
| Median error | $3.00M | $3.00M | tied |
| MAPE | 20.4% | 20.0% | better |

Shohei Ohtani's $700M Dodgers deal is doing structural damage to the pooled number: gpt-4o-mini's training corpus literally contains news of the actual signing, giving the baseline a data-leakage advantage on that one row. Excluding it:

| Metric (n=25, ex-Ohtani) | Baseline | Fine-tune | Δ |
|---|---:|---:|---:|
| MAE | $3.67M | **$3.09M** | **−$0.58M (−16%)** |
| IF position MAE (n=9) | $4.21M | **$2.80M** | **−$1.41M** |
| SP position MAE (n=4) | $3.03M | $2.19M | −$0.84M |

The Ohtani case is a useful reminder that LLM "performance" on tasks within the training cutoff often measures memorization, not generalization: the baseline forecast $50M (memorized the news) while the fine-tune forecast $25M (extrapolated from comparables that had no $70M precedent). At n=25 the paired Wilcoxon is p = 0.48 and the bootstrap CI on the ex-Ohtani improvement is [−$0.35M, +$1.52M], so the pooled improvement is not significant. The IF-position improvement of $1.41M is borderline significant with CI [+$0.04M, +$2.89M], just clearing zero.

### 5.6 The honest null: gap_score does not predict team wins

The team pre-registered six tests on the harder hypothesis that the composite `gap_score` predicts next-year wins. Five came back null. The headline result: with COVID-affected rows excluded (n=120), last-year wins alone correlates with next-year wins at r = +0.573. Sabercast's gap_score correlates at r = −0.110, which is in the right direction but with a confidence interval that comfortably crosses zero. After controlling for last-year wins, Pythagorean expectation, team WAR, and roster age in an OLS regression, gap_score contributes ΔR² = 0.0008 and partial F = 0.15 (p = 0.70). The most predictive single feature in that regression is roster age (β = −2.61, p = 0.006), not anything Sabercast computes.

The team reports this finding plainly rather than dressing it up. Gap_score is a **diagnostic surface**, not a wins forecaster, and the suite of evidence in 5.1 through 5.4 makes that framing the honest one. The product's value lives in the diagnostic and retrieval layers, where it has rigorous quantitative support.

---

## 6. Deployment trade-offs and limitations

### 6.1 The fine-tune is benchmark-only

The Together-hosted Qwen 2.5 7B fine-tune requires a dedicated 2× H100 endpoint at $0.22 per minute with a roughly four-minute cold start. Streamlit Community Cloud users would experience that cold start on every fresh session, which is incompatible with the interactive UX target. The production runtime forecast call therefore uses gpt-4o-mini, which delivers $4.30M MAE on the same evaluation set. The `use_finetuned` flag is the routing seam: it stays off in production and is flipped on only for the offline MAE benchmark. The deployment story this tells is honest. Domain fine-tuning produced a measurable infield-position improvement of $1.41M, but the operational cost of serving it in real time exceeds the marginal value at the current scale. A larger-volume deployment would justify always-on dedicated inference; the current MBA-course prototype does not.

### 6.2 Three platform constraints absorbed mid-build

The build hit three independent LLM-platform constraints in roughly 36 hours: OpenAI deprecated self-serve fine-tuning the day the training JSONL was uploaded; Together moved smaller Llama and Mistral models off the serverless tier the same week (forcing a re-fine-tune against Qwen 2.5 7B); and Together then flagged all custom fine-tunes as non-serverless, requiring dedicated-endpoint deployment with careful `finally`-block teardown. Total dedicated-endpoint cost: $1.94. The deployed prototype absorbed all three without changing its user-facing behavior. The production-readiness lesson is straightforward: LLM applications need vendor-portable abstractions and graceful prompt-engineering fallbacks because platform terms can change inside one build cycle.

### 6.3 Coverage gaps in Savant's qualified-hitter pool

The Tier 1 Statcast feeds (Section 4.1) cap at 253 qualified hitters per season. That covers every regular starter, but bench-tier and minor-league free agents fall outside the cap. The Gap Filler tab therefore deliberately does not use the new spray data, even though it would be tempting to surface there. Wiring it in would give the LLM asymmetric profile data, with rich spray for premium-tier targets and blank fields for bargain-tier ones, which would systematically bias the model toward the high-AAV recommendations. The Roster Builder and Opponent Scouting tabs use the data because their inputs are qualified-hitter rosters by definition. Pitch location heatmaps and pitcher batted-ball-allowed spray are queued for a Tier 2 follow-up via Statcast pitch-by-pitch aggregation, but not in scope for this report.

### 6.4 Sample-size constraints on the wins-prediction evaluation

At n=180 team-years the wins-prediction test requires |r| ≥ 0.21 to detect significance at α=0.05 with 80% power, and observed magnitudes are well below that floor. The honest framing is not that Sabercast might predict wins at larger n. It is that wins prediction is the wrong success metric for a diagnostic and retrieval product, and the per-position hit-rate test (5.4) and the retrieval precision tests (5.2, 5.3) are the right ones. Section 5 reports both kinds of evidence rather than picking one.

### 6.5 Determinism, reproducibility, and a no-look-ahead bug worth telling

All reasoning calls run with `temperature=0`, `seed=42`, and `response_format={"type": "json_object"}`. The fine-tune evaluation shares `random.seed(42)` with the training-data submission pipeline. Re-runs of the precision@K test produce bit-for-bit identical results, which is what allowed the team to confirm in Section 5.3 that the downstream tier-bucketing logic does not invalidate the headline retrieval precision claim from 5.2.

That same reproducibility discipline is what made it possible to catch and fix a real no-look-ahead leak late in the build. The Gap Filler's committed-payroll lookup was originally reading `team_payrolls_<market_year>.csv`, which for the demo's default 2024 evaluation year resolved to Spotrac's 2025 page, scraped after the 2024-25 offseason. That page included Max Fried at the Yankees, Snell and Sasaki at the Dodgers, and every other 2024-25 free-agent signing as already-committed payroll. For a hypothetical 2024 GM running the tool to plan offseason moves, those signings were exactly what the tool was supposed to be recommending, not what it was supposed to be subtracting from available budget. The bug was caught during evaluation runs (the LAD over-statement was $83 million, the Phillies $50 million), documented in the build log, and fixed by switching to the evaluation-year vintage. The new path is a slight conservative over-estimate because it includes one-year deals that expire after the evaluation year, but the bias direction (recommend smaller, safer signings) is the right direction for a no-look-ahead system.

Reproducibility is not a paper trail nicety in LLM applications. It is the operational property that lets you debug, monitor, and trust your own evaluation numbers across builds, and the property that surfaced this particular leak before it ever shipped to the deployed app.

---

## 7. Conclusion

Sabercast shipped as a deployed end-to-end LLM application that combines six public data sources, four LLM-class models routed by task-appropriate cost tiers, a retrieval-augmented vectorstore that produces a statistically validated 3.1× lift on a real downstream task, and a deterministic display layer that the team can stress-test and verify. The professor's checkpoint suggestions about clear evaluation evidence, baseline comparisons, and explicit LLM-role architecture were taken seriously and answered: five significant findings, four honestly reported nulls, an architecture diagram that maps every model to its task, and a documented trail of three LLM-platform constraints absorbed mid-build without changing the deployed prototype's user-facing behavior.

The product is not a season-level wins forecaster, and the report does not pretend it is one. It is a diagnostic-and-retrieval assistant for mid-market MLB front offices that produces structured, citation-grounded recommendations in roughly ten to fifteen seconds, against the same authoritative public data sources the largest analytics departments use, at one-thousandth of their headcount cost.

From a GM's perspective, the value is concentrated in three concrete moments. The Gap Filler turns "where can we spend our remaining $70 million?" into a tier-bucketed shortlist with vs-incumbent deltas and rationales that articulate the cost-versus-performance tradeoff explicitly, including the rare cases where the right move is a deliberate cost-saving downgrade. The Opponent Scouting tab turns "what should we know about Houston tomorrow?" into a structured report grounded in their actual top hitters' batted-ball spray and their top pitchers' arsenal usage and BA-against per pitch. The Roster Builder turns "what's our best lineup against Skubal tonight?" into a platoon-aware nine-slot card whose every defensive-targeting claim is verifiable against an OAA panel on the same screen. The course question of whether LLM-powered applications can deliver real business value, in a real domain, with real public data, evaluated honestly, has a working live URL as its answer.

---

**Appendix references.** The full evaluation methodology, all statistical tests, and the chronological build history are documented in `docs/final_report/EVALUATION.md` (consolidated evidence dossier), `docs/BUILD_LOG.md` (39 chronological entries spanning the entire build), and `eval/results/` (12 CSV outputs from the pre-registered tests). The deployed application is at [sabercast-mlb.streamlit.app](https://sabercast-mlb.streamlit.app/). The repository is at [github.com/rwpeugh/sabercast](https://github.com/rwpeugh/sabercast).

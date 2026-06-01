# Checkpoint 3 Progress Update

**Project:** Sabercast — LLM-powered MLB front-office intelligence platform
**Course:** MKTG 569 (Spring 2026) — Building Business Applications of LLMs and Generative Models

---

## What we are building

Sabercast is a three-tab Streamlit application that uses LLM reasoning grounded in real MLB data to support front-office decisions for small- and mid-market teams. The three tabs are **Roster Builder** (construct lineups vs. a specific opponent), **Opponent Scouting** (identify exploitable weaknesses), and **Gap Filler** (diagnose roster gaps, suggest free-agent targets, and estimate contract values). The system combines pybaseball stat ingestion, Spotrac contract scraping, OpenAI batch classification, ChromaDB RAG, and an OpenAI-fine-tuned contract valuation model.

---

## Progress status

| Area | Status |
|---|---|
| Repository scaffolding, dependencies, OpenAI API access | Complete |
| 2024 batting + pitching data ingest (Baseball Reference via pybaseball, with documented FanGraphs fallback path) | Complete — 654 batting rows, 855 pitching rows |
| Top-100 active MLB contracts scraped from Spotrac, plus 15 hand-curated additions at thin positions (catcher, reliever, 2B) | Complete — **115 contracts** total; catcher pool went from 1 eligible (Will Smith only) to 10 once curated entries like Realmuto, Salvador Perez, Sean Murphy, Vazquez, Grandal, etc. were added |
| Gap Filler orchestrator: team-vs-league deltas, 1× `gpt-4o` diagnostic call, 3× `gpt-4o-mini` contract-pricing calls | Complete — end-to-end ~12–15 seconds, ~\$0.03 per run |
| No-look-ahead enforcement: contracts filtered to `signed_year <= evaluation_year`, pricing anchored to the next offseason, UI surfaces thin-sample warnings | Complete |
| Streamlit Gap Filler tab functional, with Plotly delta chart, multi-step status widget, gap cards with positional impact + reasoning + recommended targets + pricing comparables | Complete |
| **All 30 MLB teams selectable via dropdown**; editable payroll input pre-filled with team-specific 2025 default | Complete |
| **Per-target acquisition forecast** (one gpt-4o-mini call per target) — separate from each player's current contract; premium flag triggers when forecast >1.5× the gap-fill estimate | Complete |
| **Session-scoped result caching** — repeat queries for the same (team, year, budget) are instant on cache hit, full live progress on cache miss | Complete |
| **Opponent Scouting tab functional** — team dropdown, top hitters/pitchers tables, LLM-generated narrative, three top threats, three exploitable weaknesses, recommended pitching strategy + hitting approach (one gpt-4o call, ~5 sec) | Complete |
| Multi-year batting + pitching ingest for 2019–2024 (4,647 batting rows, 5,064 pitching rows total) | Complete |
| Statcast defensive metrics for 2024: per-position OAA (1B–RF, 282 rows), sprint speed (566 rows), catcher pop time (83 rows) | Complete |
| Defensive component wired into gap diagnostic — gap card shows offense/defense split (e.g., SEA 2B card: offense 5.0, defense 9.0, citing Jorge Polanco's −11 OAA); team-defense expander shows per-position OAA + catcher pop time + sprint-speed deltas | Complete |
| Pipeline 03 archetype batch (gpt-4o-mini Batch API) — 2,541 requests across 456 batters + 543 pitchers; archetype + role + trend labels with rationale; total cost ~$0.23 | Complete — 999 players classified, 0 failures. Distribution: power_hitter 255, mid_rotation_starter 178, speed_threat 88, ace_starter 27, etc. |
| Pipeline 04 ChromaDB vectorstore — 15 MLB analytics glossary entries (WAR, wRC+, wOBA, FIP, xFIP, BABIP, ISO, OPS, OAA, exit velocity, barrel rate, hard-hit rate, sprint speed, pop time, framing runs) + 999 player profiles (archetype + 2024 stats + trend), embedded with text-embedding-3-small | Complete — 1,014 embeddings persisted to `data/vectorstore/`. Retrieval smoke test verified: glossary queries return correct top-1 matches; player archetype queries return semantically appropriate clusters. |
| ChromaDB vectorstore for embedding-based player matching | In work |
| Fine-tuned contract valuation model (Pipeline 05) | **Blocked by platform deprecation.** Training data built and uploaded (29 examples, 86.8 KB JSONL); fine-tuning job submission returned HTTP 403 with "OpenAI is winding down the fine-tuning platform and your organization is no longer able to create new fine-tuning training jobs." The prompt-based forecaster with held-out MAE \$4.30M stands as the production system. See Entry 14 in `docs/BUILD_LOG.md`. |
| Roster Builder tab functional — team + opponent dropdowns, 9-slot lineup recommendation with per-slot rationale, three matchup advantages with HIGH/MEDIUM/LOW leverage chips, two matchup risks with mitigations, strategic summary narrative; one gpt-4o call grounded in both teams' aggregates and the opponent's per-position OAA deltas | Complete |
| Pre-cache layer for showcase demo scenarios | In work |
| Streamlit Community Cloud deployment with public URL at https://sabercast-mlb.streamlit.app (GitHub repo: github.com/rwpeugh/sabercast; continuous deploy from main; OPENAI_API_KEY set via Cloud secrets pane) | Complete |
| 5-year correlation study — composite gap_score (2019–2023 evaluation seasons) vs. next-year wins via pybaseball.standings, n=150 (team, year) observations, file-based diagnose-cache so reruns are free, scatter + per-year bar plots | Complete — see Quantitative evaluation section below for the findings |

---

## Screenshots

1. **`01_landing.png`** — Landing page with all three tabs visible. The default tab shown is Roster Builder, currently rendering an "In work" placeholder that lists the planned inputs and outputs — an intentional, honest signal of where the build is.
2. **`02_gap_filler_results_top.png`** — Gap Filler tab after running the diagnosis. Shows the **team dropdown** (any of 30 MLB teams), the **editable max-payroll input** pre-filled with the team's 2025 default ($165M for SEA), the multi-step status widget collapsed to "Done — 67.7s, 1 gpt-4o + 12 gpt-4o-mini calls", the LLM-generated roster summary (which now includes a defensive verdict: *"Defensively, the team has standout performances at third base and center field, but significant issues at second base and right field"*), and the Plotly delta chart visualizing team-vs-league averages.
3. **`03_top_gap_card_with_candidates.png`** — Top gap card for the Mariners: **second base** gap with HIGH win impact (9.5/10), with the new offense/defense split visible — **offense 5.0 · defense 9.0**. Reasoning cites the specific data point: *"Second base is a major gap due to a −11 OAA, which is 13.13 below league average, combined with offensive struggles..."* The diagnostic shifted from C/SS/DH (offense-only) to **2B/RF/SS** once Statcast OAA was added, because Jorge Polanco's −11 OAA at 2B was the team's most consequential single-position weakness. Estimated contract to fill: $20.0M AAV / 5 yr. Recommended targets ranked by 2024 statistical fit: **Brandon Lowe**, **Marcus Semien**, **Ozzie Albies**. Pricing comparables: Xander Bogaerts, Marcus Semien, Andres Gimenez.
4. **`04_contract_estimate_and_summary.png`** — Bottom of the Gap Filler results: full contract estimate for the DH gap ($20.0M AAV / 5 yr, 12% of payroll). Two recommended targets, each with a per-target forecast: **Yordan Alvarez** (fit 1.54 — .308/.392/.565, 35 HR; forecast $25.0M AAV / 8 yr; currently $19.2M / 6 yr) and **Masataka Yoshida** (fit 0.27; forecast $16.0M / 4 yr; currently $18.0M / 5 yr — note the forecast is *below* his current contract, reflecting his lower 2024 line). The **Pricing comparables** section includes Shohei Ohtani ($70M AAV / 10 yr) with the LLM-generated rationale *"outlier ceiling, not representative"* — Ohtani's contract is a useful pricing anchor but his $70M AAV exceeds the 30% single-signing ceiling so he never appears as a target. The summary banner names the C signing as the highest priority, with **Salvador Perez** as the top recommended target.
5. **`05_opponent_scouting.png`** — **Opponent Scouting tab (now functional)** with the Astros selected as the opponent. After one `gpt-4o` call (~5s) the tab renders an LLM-generated narrative ("strong offensive lineup ... slightly below average in drawing walks and stealing bases"), plus two data tables: **Top hitters by 2024 OPS** (Kyle Tucker .972, Yordan Alvarez .957, Jose Altuve .784, Alex Bregman .768, Yainer Diaz .765) and **Top pitchers by 2024 ERA** (Tayler Scott reliever 2.23, Ronel Blanco starter 2.76, Framber Valdez starter 2.99, ...). The raw player data is shown directly so the user can verify the LLM's conclusions against ground truth.
6. **`06_opponent_scouting_strategy.png`** — Bottom of the Opponent Scouting tab: **three top-threat cards** (Yordan Alvarez, Ronel Blanco, Kyle Tucker, each with role tag and a one-line "why"), **three exploitable-weakness cards** (base running MEDIUM, plate discipline MEDIUM, bullpen depth LOW, each with the stat evidence), and **two strategy cards** with concrete recommendations: a *Pitching strategy* (how to neutralize the Astros' lineup) and a *Hitting approach* (how to attack their staff). All ground in the data fed to the LLM, no fabricated player names.

**How the per-target forecast works:** Each recommended target gets its own `gpt-4o-mini` call (separate from the gap-fill estimate) that takes the player's 2024 line, age, position, and the same position-matched comparables, and returns a forecast AAV and years for what that player would actually command on a new free-agent deal in the upcoming offseason. The card surfaces both numbers — forecast prominently, current contract as supporting context — so the user sees both what the player is paid today and what acquiring them would realistically cost.

**Premium flag:** When a target's *forecast* AAV exceeds 1.5× the gap-fill estimate, the target card shows an orange "+X% vs estimate" chip and a short caption. The flag uses the forecast (cost to acquire) versus the estimate (what the role merits), not the player's current contract. Verified working on earlier runs that diagnosed CF as a gap (Aaron Judge: +67% vs estimate). For SEA's 2024 deltas the model deterministically picks C/SS/DH, where forecasts cluster close enough to estimates that the threshold doesn't trip in this run; the feature fires consistently on team/year combinations where the gap target pool spans a wider price range.

---

## Quantitative evaluation — gap score versus next-year wins

For each of the 150 (evaluation_year, team) observations across 2019–2023, the diagnostic was run against the team's offensive, pitching, and per-position defensive aggregates (Statcast OAA, sprint speed, catcher pop time). A composite gap score was computed by summing the top three gap scores weighted by positional scarcity. Each team's next-year win total was retrieved via `pybaseball.standings`.

**Headline finding: adding defense flipped the sign of the correlation.** An earlier study run on offense + pitching only produced a pooled r of **+0.125** — the wrong sign, near zero. After pulling historical Statcast defensive data for 2019–2023 and re-running with per-position OAA in the diagnostic prompt, the pooled correlation moved to **−0.063** (expected sign), a swing of 0.188.

| Sample | n | Offense-only run | **Defense-augmented run** |
|---|---|---|---|
| Pooled, all years | 150 | +0.125 | **−0.063** |
| Pooled, excluding 2020 | 120 | +0.210 | **−0.005** |
| 2019 → 2020 wins | 30 | +0.105 | +0.034 |
| 2020 → 2021 wins | 30 | −0.063 | **−0.209** |
| 2021 → 2022 wins | 30 | +0.088 | −0.016 |
| 2022 → 2023 wins | 30 | +0.099 | −0.068 |
| 2023 → 2024 wins | 30 | −0.098 | **−0.183** |

Four of five years are now negative in the defense-augmented run.

**Ablation (defense-augmented run only).** The LLM diagnostic returns each gap's score decomposed into offense and defense components; the table below shows Pearson r against next-year wins for each decomposition.

| Composite | n=150 | excluding 2020 (n=120) |
|---|---|---|
| Legacy gap_score (top-3 weighted by scarcity) | −0.063 | −0.005 |
| Offense-only composite | **−0.089** | **−0.086** |
| Defense-only composite | −0.047 | −0.012 |
| Combined offense + defense composite | −0.086 | −0.054 |

**Why the sign flipped.** In the offense-only run, the LLM selected catcher as the top gap in 75 of 150 observations (50%) — the catcher scarcity weight of 1.4 was dominating the actual stat deltas. Once per-position OAA was in the prompt, the LLM had a much richer team-specific signal: a 2B with −11 OAA is a real, differentiating problem in a way that "every team needs a better catcher" is not. Gap-score variance expanded and the correlation moved toward its expected direction.

**Honest scope on magnitude.** Absolute |r| in the defense-augmented run is still small (~0.05–0.10). The gap diagnostic is now directionally correct but a weak predictor of next-year team performance — consistent with the reality that a single offseason of roster construction is one of many forces shaping the following year (injuries, regression, in-season moves, manager decisions). The improvement is a methodology win; the absolute predictive-power claim remains modest.

**Output files:**

- `eval/results/correlation_table.csv` — 150 rows × {year, team, gap_score, gap_offense, gap_defense, gap_combined, has_defense_data, next_year_wins, top_gap_position}
- `eval/results/correlation_scatter.png` — pooled scatter colored by year
- `eval/results/correlation_by_year.png` — per-year bar chart of Pearson r
- `eval/results/ablation_offense_vs_defense.csv` — offense / defense / combined ablation table

---

## Quantitative evaluation — contract valuation MAE (held-out)

Thirty contracts were randomly sampled from `contracts.csv` (signed 2019–2024, random seed 42). For each contract the prompt-based forecaster was asked to predict the AAV using the player's signing-year stats and position-matched comparable contracts signed *strictly before* the test contract's signing year (no leakage). Skipped cases (4) where the player had no qualifying stats row or no prior position-matched comparable were excluded.

| Sample | n | MAE | Median abs err | MAPE |
|---|---|---|---|---|
| Pooled, all 26 predictions | 26 | **$4.30M** | $3.00M | 20.4% |
| Excluding Ohtani outlier | 25 | $3.67M | $3.00M | 20.1% |

**MAE by position bucket:** SP $3.03M (n=4, MAPE 12.9% — best), RP $2.77M (n=3), C $3.17M (n=3), OF $3.98M (n=6), IF $4.21M (n=9), DH $20.0M (n=1; Ohtani only).

The forecaster is approximately right within ±$3M for the median signing in the $10–40M AAV band. Notable: Aaron Judge predicted exactly ($40M actual / $40M predicted), Tyler Glasnow within $0.7M, Yan Gomes within $1.5M. The Shohei Ohtani contract drives the DH bucket's error — the LLM has no way to anticipate his uniquely deferred Dodgers deal.

**Output files:** `eval/results/contract_mae.csv` (26 rows), `eval/results/contract_mae_by_position.csv`, `eval/results/contract_mae_scatter.png` (predicted vs actual AAV with the 45° perfect-prediction line).

---

## Known limitations

- **Catcher framing data is not produced** by the working pybaseball Statcast endpoint (upstream parser bug); catcher pop time and catcher OPS together serve as the defensive proxy.
- **Catchers are excluded from Statcast's standard OAA leaderboard** by design (per the endpoint's own error message: *"This particular leaderboard does not include catchers"*). Catcher pop time fills the catcher defensive slot.
- **No no-trade clauses or opt-out cascades.** The Spotrac main contracts table does not expose clause data without per-player page fetches; deferred.
- **Contract pool is a 115-player subset.** Spotrac's top-100 plus 15 hand-curated additions at thin positions. When a diagnosed gap has fewer than three eligible targets the UI surfaces a thin-sample warning rather than masking it.

---

## Public URL

**<https://sabercast-mlb.streamlit.app>**

The app is deployed publicly on Streamlit Community Cloud, connected to the GitHub repository at <https://github.com/rwpeugh/sabercast>. Every push to the `main` branch redeploys automatically in approximately 30 seconds. End-to-end Gap Filler runs on the deployed instance complete in roughly 40 seconds for the full 12-LLM-call orchestration.

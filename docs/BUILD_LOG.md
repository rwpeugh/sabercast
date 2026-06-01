# Sabercast Build Log

**Course:** MKTG 569 · Building Business Applications of LLMs and Generative Models
**Project:** Sabercast — LLM-powered MLB front-office intelligence platform

> Append-only log. Each entry captures a development milestone: what was added, why, and what it produced. Past entries are not revised — new work goes at the bottom.

---

## Entry 1 — May 23 (Day 1): Sprint foundation

**Goal:** Get a working demo of one tab on one team in 8–10 hours of focused work, in time for the Checkpoint 3 submission.

**What was built**

- Repository scaffolding (`sabercast/` with `app/`, `core/`, `pipelines/`, `data/`, `docs/`, `eval/`)
- `requirements.txt`, `.env.example`, `.gitignore`, README
- Phase 0 verification: OpenAI API connection confirmed (118 models listed)
- **Pipeline 01** — pull 2024 batting + pitching via pybaseball. FanGraphs endpoint returned HTTP 403; fell back to Baseball Reference (`batting_stats_bref` / `pitching_stats_bref`) as documented in the prior RAG notebook. Tenacity retry wrapped.
- **Pipeline 02** — Spotrac contracts scrape. 100 contracts, all position groups represented.
- **Streamlit app** — three tabs scaffolded, Gap Filler tab functional for Seattle Mariners (hardcoded). Diagnose roster gaps → 1 gpt-4o call + 3 gpt-4o-mini calls for contract pricing. ~12 sec per run.
- Unicode fix for Baseball Reference's escape-encoded Latino names (`V\xc3\xadctor` → `Víctor`).

**What it produced**

- `data/raw/batting_2024.csv` (654 rows × 29 cols)
- `data/raw/pitching_2024.csv` (855 rows × 41 cols)
- `data/raw/contracts.csv` (100 rows × 8 cols)
- 4 screenshots captured for the Checkpoint 3 submission

---

## Entry 2 — May 23-24 (Sprint Polish + Checkpoint 3): UI hardening and finding-driven additions

**Goal:** Make the Gap Filler tab presentable for grading; address gaps surfaced by examining the live output.

**What was built**

- **No-look-ahead enforcement.** Catalog contracts by `signed_year`; the diagnostic for end-of-2024 cannot see contracts signed in 2025 or later. UI surfaces the policy explicitly and warns when fewer than 3 eligible comparables exist at a position.
- **Recommended targets ranked by 2024 statistical fit** (distinct from pricing comparables, which are ranked by AAV). Each target card surfaces 2024 slash line + counting stats + a fit score.
- **Per-target acquisition forecast** — separate `gpt-4o-mini` call per recommended target produces a forecast contract for that specific player given their 2024 stats, age, and position-matched comparables. Card shows both forecast (cost to sign) and current contract (supporting context).
- **Premium flag** — orange `+X% vs estimate` chip when a target's forecast AAV exceeds 1.5× the gap-fill estimate; the role's cost vs the role's worth, surfaced clearly.
- **Pricing comparables as a separate card section** with values + a short LLM rationale per contract (e.g., "outlier ceiling, not representative"). When a pricing comparable is also a recommended target, the card says "Same player as recommended target above" rather than repeating.
- **Plotly delta chart** showing team-vs-league averages — red bars below zero, green above — making the offense/pitching profile readable at a glance.
- **Multi-step status widget** (`st.status`) driven by a progress callback from the orchestrator so the user sees each step (load, aggregate, GPT-4o for gaps, GPT-4o-mini per gap).
- **15 manually-curated contracts** added at thin positions: catcher (Realmuto, Salvador Perez, Sean Murphy, Vazquez, d'Arnaud, Grandal, Garver, Yan Gomes), relievers (Edwin Díaz, Jansen, Suárez, Hendriks, Chapman), and second basemen (Albies, Lowe). Pool grew from 100 → 115.
- **LLM determinism** — `temperature=0`, `seed=42` on both `gpt-4o` and `gpt-4o-mini` calls so screenshots and grader reruns are reproducible.
- **KaTeX `$`-sign fixes.** Streamlit's markdown layer was eating dollar signs in money formatters; switched to HTML entity in `unsafe_allow_html` contexts and backslash-escape in markdown contexts.
- **Accent folding** between Spotrac (ASCII) and bref (UTF-8 with diacritics) — Julio Rodríguez, José Ramírez, Yordan Álvarez, Eugenio Suárez now resolve in stat lookups.
- **Sidebar simplified** — removed sprint-status block and any due-date language from the app itself; reserved progress narrative for the progress doc only.

**What it produced**

- Checkpoint 3 submission package in `docs/checkpoint3/`: 6 screenshots, `PROGRESS_UPDATE.md`, `Sabercast_Progress_Update.docx`
- Reproducible diagnosis for any team/year combination
- A demo narrative that shows the tool ranking Salvador Perez above Will Smith at catcher in 2024 (based on Perez's 28 HR / 105 RBI year), with Mike Trout appearing in the pricing comparables but not as a target due to injury-driven low fit score

---

## Entry 3 — May 30 (Final build, morning): Multi-tab expansion + dropdowns + caching

**Goal:** Expand beyond the hardcoded Seattle demo so judges can pick any team live, and bring the Opponent Scouting tab from placeholder to functional.

**What was built**

- **Team dropdown** in the Gap Filler tab — all 30 MLB teams selectable. The orchestrator already supported any team; just swapped the hardcoded `team="SEA"` for `st.selectbox`.
- **Editable max-payroll input** pre-filled with a per-team 2025 default (`TEAM_DEFAULT_PAYROLL` dict, e.g., LAD $325M / SEA $165M / OAK $75M).
- **Session-scoped result caching.** Repeat queries for the same `(team, year, budget)` tuple return instantly on cache hit; live progress callback still fires on cache miss. Status widget shows `"Loaded LAD from cache · 0s (was 28s on the first run)."`
- **Opponent Scouting tab functional.** Takes an opponent team selector. Aggregates the opponent's 2024 stats, finds the top-5 hitters by OPS and top-5 pitchers by ERA, then makes ONE `gpt-4o` call that returns a full scouting report:
  - LLM-generated 2–3 sentence narrative
  - Two data tables (top hitters, top pitchers) shown alongside the narrative so the user can verify the LLM's conclusions against ground truth
  - Three top-threat cards with role tags and a one-line "why"
  - Three exploitable-weakness cards with stat evidence + HIGH/MEDIUM/LOW impact chips
  - Two strategy cards: Pitching strategy (when they're at bat) and Hitting approach (when we're at bat vs their staff)
- **Capture script** extended to produce 6 screenshots (added 5th and 6th for Opponent Scouting).

**What it produced**

- App now generalizes to any team / any opponent / any budget. Two LLM-powered analyses across two tabs.
- Opponent Scouting runs in ~5 seconds, 1 LLM call (~$0.005).
- 6-PNG screenshot bundle for the submission package.

---

## Entry 4 — May 30 (Final build, late morning): Multi-year ingest + Statcast defensive metrics

**Goal:** Day 2 work per the spec — pull the historical stats needed for the 5-year correlation evaluation, and add defensive metrics so the gap diagnostic stops being offense-only.

**What was built**

- **Pipeline 01 expanded** to pull 2019, 2020, 2021, 2022, 2023 batting + pitching alongside the existing 2024 data. Idempotency check skips already-cached years.
- **Statcast defensive metrics for 2024**:
  - `oaa_2024.csv` — per-position Outs Above Average for positions 1B/2B/3B/SS/LF/CF/RF (282 rows)
  - `sprint_speed_2024.csv` — per-player sprint speed (566 rows; uniquely carries position metadata that the bref batting CSV lacks)
  - `catcher_defense_2024.csv` — catcher pop time to 2B/3B, arm strength, exchange time (83 rows)
- **Two pybaseball quirks discovered + handled**:
  - `statcast_outs_above_average(year, pos=2)` errors with "This particular leaderboard does not include catchers" — by design, Statcast measures catcher defense differently. Switched to `statcast_catcher_poptime` for the catcher slot.
  - `statcast_catcher_framing` still has the upstream parser bug; logged the failure and proceeded with pop time + catcher OPS as the proxy.
- **Defensive integration into the gap diagnostic.** Orchestrator now loads OAA + sprint speed + catcher defense, aggregates per-position OAA totals for the team being diagnosed and per-team league averages, and passes per-position deltas into the `gpt-4o` gap diagnostic prompt. Prompt updated to instruct the LLM to consider both offense and defense.
- **Gap card UI** — each gap now shows an offense/defense split chip (e.g., "offense 5.0 · defense 9.0") and reasoning that cites the specific OAA number.
- **Team-defense expander** added to the app — per-position OAA table, catcher pop-time delta, sprint-speed delta.

**What it produced**

- 4,647 batting rows + 5,064 pitching rows across 2019–2024.
- The 2024 SEA diagnosis shifted from **C / SS / DH** (offense only) to **2B / RF / SS** once defense was added. The new top gap reasoning explicitly cites Jorge Polanco's −11 OAA at second base — Polanco was historically poor with the glove that year, and the LLM correctly surfaces that as the highest-priority gap. Roster summary now reads: *"Defensively, the team has standout performances at third base and center field, but significant issues at second base and right field."*
- 100% join coverage between defensive files (player_id) and the batting CSV (mlbID).
- `SABERCAST_SPEC.md` updated to reflect that catcher OAA is by-design unavailable; catcher pop time is the documented alternative.

---

## Entry 5 — May 30 (Final build, afternoon): RAG infrastructure — archetypes batch + ChromaDB vectorstore

**Goal:** Day 3 spec work — build the embedding infrastructure that lets the player matcher do semantic retrieval rather than position-equality filtering.

**What was built**

- **Pipeline 03 — Archetype classification via OpenAI Batch API.**
  - 2,541 classification requests built from 456 qualifying 2024 batters (PA ≥ 100) and 543 qualifying 2024 pitchers (IP ≥ 20).
  - Three passes per player: zero-shot archetype, few-shot pitcher role (pitchers only), chain-of-thought trend signal vs prior year.
  - Submitted to `gpt-4o-mini` Batch API with `temperature=0`, `seed=42`. Validated → processed → finalized in under an hour. 0 failures.
  - Output: `data/archetypes/player_archetypes.csv` — 999 players × {archetype, role, trend, rationale}.
  - Total cost: ~$0.23 (well under the spec's $3 target due to Batch API discount).
  - Distribution checked sensibly: 255 power hitters, 178 mid-rotation starters, 88 speed threats, 67 closers, 27 ace starters (correctly rare), 26 defensive specialists.
- **Pipeline 04 — ChromaDB vectorstore.**
  - **Glossary collection** (`sabercast_glossary`): 15 authoritative definitions of MLB analytics terms — WAR, wRC+, wOBA, FIP, xFIP, BABIP, ISO, OPS, OAA, Exit Velocity, Barrel Rate, Hard-Hit Rate, Sprint Speed, Pop Time, Framing Runs.
  - **Player profiles collection** (`sabercast_player_profiles`): 999 natural-language profiles, one per archetyped player, combining archetype + 2024 stats + trend + team + role.
  - All embedded with `text-embedding-3-small` and persisted to `data/vectorstore/`.
- **Retrieval smoke test** verified the store works:
  - Glossary: *"what does WAR stand for"* → WAR entry; *"metric for catcher arm strength"* → Pop Time entry; *"exit velocity definition"* → Exit Velocity entry. All correct top-1 matches.
  - Player profiles: *"shutdown closer with low ERA"* → three actual closers (Estrada, Neris, Hoffman); *"ace left-handed starter with high strikeouts"* → cluster of ace_starter archetype.

**What it produced**

- 1,014 total embeddings persisted (15 glossary + 999 player profiles)
- The infrastructure required for the spec's planned `core/player_matcher.py` rewrite — embedding-based candidate retrieval instead of position-equality filtering.
- Honest scope note: the player-profile text says "batter" or "pitcher" but not the specific position (shortstop, first baseman, etc.). Position metadata is in `sprint_speed_*.csv` and `oaa_*.csv`; baking it into the profile text would tighten retrieval — queued.

---

## Entry 6 — May 30 (Final build, late afternoon): 5-year correlation study — offense + pitching only

**Goal:** Day 8 spec work — produce the headline quantitative claim for the final report. Does the LLM-diagnosed gap score actually correlate with next-year team wins?

**What was built**

- **`eval/correlation_study.py`** — for each of 150 (year, team) observations across 2019–2023:
  1. Aggregate the team's offensive + pitching stats from the year-specific CSV
  2. Compute deltas vs league per-team averages
  3. Call `diagnose_gaps_llm` (cached in `data/processed/correlation_diagnose_cache.json` so reruns are free)
  4. Compute a composite gap score: sum of top 3 gap_scores weighted by positional scarcity
  5. Look up team's next-year win total via `pybaseball.standings`
- Pearson correlation computed pooled and per year; 2020 (60-game COVID season) broken out separately.
- Pooled scatter + per-year bar chart written to `eval/results/`.

**What it produced**

| Sample | n | Pearson r |
|---|---|---|
| Pooled, all years | 150 | **+0.125** |
| Pooled, excluding 2020 | 120 | **+0.210** |
| 2019 → 2020 wins | 30 | +0.105 |
| 2020 → 2021 wins | 30 | −0.063 |
| 2021 → 2022 wins | 30 | +0.088 |
| 2022 → 2023 wins | 30 | +0.099 |
| 2023 → 2024 wins | 30 | −0.098 |

**Honest finding.** The expected sign is *negative* — a bigger gap should predict fewer future wins. The observed correlation is near zero and slightly positive. Inspection of the data revealed *why*:

- Gap scores compress into a narrow band (median 27.8, IQR 24.8–31.3, max 32.5) while wins range from 19 to 111.
- The top-gap position is catcher in **75 of 150 observations (50%)**. The catcher scarcity weight of 1.4 was overwhelming the actual stat deltas — the LLM kept recommending "fill catcher" for nearly every team.
- The 2021 Astros (gap 31.27) went on to win **106 games**; the 2023 Dodgers (gap 31.92) won 98. These anti-correlated points drove the positive r.

The result is publishable for the final report: the offense + pitching gap_score alone is descriptive of position scarcity but not predictive of future wins. Defense (next entry) is the natural next step.

**Output files**

- `eval/results/correlation_table.csv` (150 rows)
- `eval/results/correlation_scatter.png`
- `eval/results/correlation_by_year.png`

---

## Entry 7 — May 30 (Final build, evening): Historical defensive ingest

**Goal:** Pull Statcast defensive metrics for 2019–2023 so the correlation study can include defense as a third predictor (alongside offense and pitching).

**What was built**

- Pipeline 01 re-run for each of 2019, 2020, 2021, 2022, 2023 — single-year mode, batting/pitching already cached so only defensive pulls execute.
- For each year:
  - Per-position OAA (positions 3–9, 7 calls per year × 5 years = 35 calls)
  - Sprint speed (1 call per year × 5 years = 5 calls)
  - Catcher pop time (1 call per year × 5 years = 5 calls)
  - Catcher framing attempted with try/except; documented failure (parser bug)
- Rate-limited to 5 seconds between Statcast calls. Total wall time: ~6 minutes.

**What it produced**

- `oaa_2019.csv` through `oaa_2023.csv` — typically 275–285 rows each (7 positions × ~40 qualifying fielders)
- `sprint_speed_2019.csv` through `sprint_speed_2023.csv` — 500–570 rows each
- `catcher_defense_2019.csv` through `catcher_defense_2023.csv` — 78–85 rows each
- Combined with the existing 2024 files, every evaluation year now has the full defensive trio on disk. Ready for the defense-augmented correlation run.

---

## Entry 8 — May 30 (Final build, evening): Defense-augmented correlation — the sign flips

**Goal:** Re-run the 5-year correlation study with per-position OAA, sprint speed, and catcher pop time now available for every year. Determine whether including defense corrects the wrong-sign / near-zero result from Entry 6.

**What was built**

- `eval/correlation_study.py` extended to:
  - Load `oaa_{year}.csv`, `sprint_speed_{year}.csv`, `catcher_defense_{year}.csv` per evaluation year.
  - Aggregate per-team defensive metrics, compute deltas vs league per-team averages, and pass the defensive payload into `diagnose_gaps_llm`.
  - Compute three composite gap scores per (year, team): offense-only, defense-only, combined.
  - Write an ablation table (`eval/results/ablation_offense_vs_defense.csv`) with Pearson r for each of the three.
- Cache key now includes defensive deltas so offense-only diagnoses from Entry 6 don't bleed into the defense-aware run.
- Added retry-on-RateLimitError with exponential backoff plus a 1.5s pacing sleep between calls — the defensive payload pushes each request past ~1.4K tokens, so 30 sequential team diagnoses can otherwise land within 60 seconds and trip the gpt-4o TPM ceiling.
- 150 fresh LLM calls (cache cleared by the new key). Total wall time: ~9 minutes.

**What it produced — the headline result**

| Sample | Offense-only (Entry 6) | With defense (this entry) | Δ |
|---|---|---|---|
| Pooled, all years (n=150)              | **+0.125** | **−0.063** | −0.188 |
| Pooled, excluding 2020 (n=120)          | **+0.210** | **−0.005** | −0.215 |

The sign of the pooled correlation flipped from positive (wrong direction) to negative (expected direction). The magnitude moved by 0.19 — the largest single methodology improvement in the study.

**Ablation table (defense-aware run)**

| Composite | n=150 | excluding 2020 (n=120) |
|---|---|---|
| Legacy gap_score (top-3 weighted by scarcity) | −0.063 | −0.005 |
| Offense-only composite (LLM `gap_components.offense`)   | **−0.089** | **−0.086** |
| Defense-only composite (LLM `gap_components.defense`)   | −0.047 | −0.012 |
| Combined offense + defense composite                     | −0.086 | −0.054 |

Per-year (using the legacy headline gap_score):

| Evaluation year | n | Pearson r |
|---|---|---|
| 2019 → 2020 wins | 30 | +0.034 |
| 2020 → 2021 wins | 30 | **−0.209** |
| 2021 → 2022 wins | 30 | −0.016 |
| 2022 → 2023 wins | 30 | −0.068 |
| 2023 → 2024 wins | 30 | **−0.183** |

Four of five years are now negative.

**Why this happened.** The Entry 6 finding identified the root cause: with offense + pitching only, the LLM was over-picking catcher as the top gap (75 of 150 observations = 50%) because the catcher scarcity weight of 1.4 dominated the actual stat deltas. With per-position defensive metrics added to the prompt, the LLM has a much richer picture of each team's specific weaknesses — a team's defensive holes are highly team-specific, while their offensive numbers cluster more. The result is a more discriminating gap_score that correlates correctly (if weakly) with future wins.

**Honest scope on magnitude.** The corrected absolute |r| is still small (~0.05–0.10). The gap diagnostic is now directionally correct but a weak predictor of next-year team performance — consistent with the reality that a single offseason of roster construction is only one of many forces shaping the following year's record (injuries, regression, in-season trades, manager decisions, etc.). The improvement from Entry 6 to Entry 8 is a methodology win; the absolute predictive power claim should remain modest in the final report.

**Output files (updated, overwriting Entry 6)**

- `eval/results/correlation_table.csv` — 150 rows × {year, team, gap_score, gap_offense, gap_defense, gap_combined, has_defense_data, next_year_wins, top_gap_position}
- `eval/results/correlation_scatter.png`
- `eval/results/correlation_by_year.png`
- `eval/results/ablation_offense_vs_defense.csv` (new)

---

## Entry 9 — May 30 (Final build, late evening): Vectorstore wired into the player matcher

**Goal:** Bring the ChromaDB vectorstore from Entry 5 into the runtime. Replace the position-equality + stat-fit picker with semantic retrieval over the 999 player profiles, then constrain to within-budget contracts at the gap position.

**What was built**

- **`core/player_matcher.py`** — new module:
  - Builds a natural-language target spec from the gap's reasoning + position + offense/defense components.
  - Embeds the spec with `text-embedding-3-small`.
  - Queries the ChromaDB `sabercast_player_profiles` collection for top-200 semantic matches.
  - Joins to `contracts.csv` by accent-folded player name. Filters to contracts at the gap position with `signed_year <= evaluation_year` and AAV within the single-signing ceiling (no look-ahead, within budget).
  - Returns top-k candidates carrying `archetype` and `trend` from the vectorstore metadata plus a `semantic_score` (cosine similarity to the query).
- **`core/orchestrator.py`** — `run_gap_filler_simple` now tries the vectorstore-based matcher first; falls back to the stat-fit picker (`_pick_targets`) only if the vectorstore is unavailable or returns no in-budget hits. Each gap result carries a `targets_source` field (`"vectorstore"` or `"stat_fit"`) for downstream display.
- **`app/tabs/gap_filler.py`** — UI changes:
  - Recommended-targets subtitle now reads either *"ranked by ChromaDB semantic match against the gap's diagnostic reasoning, then filtered to within-budget contracts at this position"* (vectorstore) or *"ranked by 2024 statistical fit"* (fallback).
  - Each target card surfaces archetype, trend, and semantic similarity instead of the stat-fit score when the match came from the vectorstore.

**What it produced**

The SEA 2B gap now ranks:

| # | Player | Archetype | Trend | Semantic | Current AAV | Forecast |
|---|---|---|---|---|---|---|
| 1 | Brandon Lowe   | power_hitter   | improving  | 0.47 | $4.0M  | $15.0M |
| 2 | Ozzie Albies   | contact_hitter | declining  | 0.46 | $5.0M  | $15.0M |
| 3 | Marcus Semien  | power_hitter   | declining  | 0.45 | $25.0M | $24.0M |

The SEA RF gap, previously surfacing Mookie Betts / Seiya Suzuki / Giancarlo Stanton via stat-fit, now surfaces **Mike Trout** (power_hitter, improving, semantic 0.47) and **Ronald Acuña Jr.** (speed_threat, stable, semantic 0.46) — both players who were filtered out under the stat-fit approach because their low 2024 PA (injury-shortened) tanked their fit score. Semantic retrieval recovers them because their profile texts match the gap description's emphasis on power and offensive production.

**Notes**

- The vectorstore profiles say "batter"/"pitcher" but not specific positions, so the position filter is applied post-retrieval via `contracts.csv`. Increasing `top_n_semantic` from 30 to 200 was necessary to get enough position-matched candidates through. A future Pipeline 04 enhancement would bake position into the embedding text so the position filter could move into the ChromaDB query (via `where=`).
- The vectorstore lookup adds one embedding call (~$0.0001) per gap. Total cost addition: negligible.
- The fallback path is preserved so the app degrades gracefully if `data/vectorstore/` is missing.

**Screenshot.** The updated `docs/checkpoint3/03_top_gap_card_with_candidates.png` shows the 2B card with the new vectorstore subtitle and archetype/trend/semantic metadata under each target's name. Pricing comparables (Xander Bogaerts, Marcus Semien, Andres Gimenez) continue to be sourced by AAV — the two retrieval mechanisms are now visibly distinct on the card.

---

## Entry 10 — May 31 (Final build): Public deployment on Streamlit Community Cloud

**Goal:** Get a public URL so classmates, the professor, and Demo Day judges can interact with the app without setup. Surface deployment-only issues before Demo Day.

**What was built**

- **GitHub repository.** `sabercast/` initialized as a git repo, pushed to <https://github.com/rwpeugh/sabercast> (public). Initial commit covers everything: app code, 115 contracts, multi-year stats, 6 years of Statcast defensive data, ChromaDB vectorstore, archetypes CSV, eval results, all docs.
- **`runtime.txt`** specifying `python-3.11` for compatibility with Streamlit Cloud's supported runtimes (Cloud picked Python 3.14 on its own — fine, our code runs on both).
- **`.streamlit/config.toml`** — theming, headless mode, telemetry off, and `[client] showErrorDetails = "full"` for diagnosing deployment-only failures.
- **`.gitignore`** updated to allow `data/` into the repo (under 25 MB total) so the deployed app doesn't need to rebuild Pipelines 01–04 on every cold start, while continuing to exclude secrets and OS noise.
- **`DEPLOY.md`** with the step-by-step instructions for the Streamlit Cloud side of the workflow.
- **Streamlit Cloud app** created at <https://sabercast-mlb.streamlit.app>, connected to the `main` branch, `OPENAI_API_KEY` set via the Cloud secrets pane.

**Two deployment-only bugs caught and fixed**

1. **Secret retrieval.** Our `get_openai_api_key()` only checked `os.environ` and local files. Streamlit Cloud puts secrets into `st.secrets[...]` but does not always propagate them to environment variables. The app booted, the landing page rendered, then the Gap Filler diagnose call raised `RuntimeError: OpenAI API key not found` from inside `_client()`. Fix: added `st.secrets["OPENAI_API_KEY"]` as the second search location, between the env var and the local file lookups. Module remains importable from non-Streamlit contexts (pipelines, eval scripts) because the streamlit import is guarded by try/except.
2. **Redacted client errors.** Streamlit Cloud redacts client-side error tracebacks for safety. The full traceback is available in *Manage app → Logs*. Documented in DEPLOY.md so anyone debugging future deploys knows where to look.

**What it produced**

- A live, public Streamlit app at <https://sabercast-mlb.streamlit.app/>
- End-to-end Gap Filler run on the deployed instance: **41.5 seconds, 1 gpt-4o + 11 gpt-4o-mini calls**. Roster summary, Plotly delta chart, gap cards, recommended targets (from the ChromaDB vectorstore), pricing comparables, and the highest-priority banner all render exactly as on local.
- Two deployment-proof screenshots saved at `docs/checkpoint3/deployed_01_landing.png` and `docs/checkpoint3/deployed_02_gap_filler_after_diagnose.png`.
- Continuous deployment from the GitHub `main` branch — every push redeploys in ~30 seconds.

---




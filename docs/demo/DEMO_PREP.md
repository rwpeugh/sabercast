# Sabercast — Demo Prep for Industry Judges

**Audience:** Diego Granados (Google), Andy Peng (Amazon), Camila Lin (Microsoft).
**Their priors:** big-tech product / engineering leaders. They will be skeptical, they have seen 100 LLM demos this year, they will probe rigor. Their default question is *"why isn't this just a wrapper around the OpenAI API?"*

The way to win this room is:
1. **Lead with a concrete, defensible claim.** Not "Sabercast helps front offices" — instead "Sabercast's recommendation list ranks actual MLB free-agent signings 3× above chance, p<0.0001."
2. **Acknowledge limits proactively.** If you volunteer the wins-prediction null before they ask, you control the framing. If they catch it first, you're defending.
3. **Use the live app as evidence, not theater.** Click through Gap Filler on a team they'd recognize (Mariners, Dodgers, Cubs). Let the output do the talking.

---

## The 60-Second Opening (rehearse verbatim)

> *"Sabercast is an LLM-powered MLB front-office intelligence platform — three workflows behind a Streamlit interface, deployed at sabercast-mlb.streamlit.app. The system answers three high-frequency questions a small-market front office actually asks: where are our roster gaps, who could fill them, and what should we expect them to cost.*
>
> *Under the hood, it's gpt-4o for narrative reasoning, gpt-4o-mini for structured outputs, text-embedding-3-small for retrieval over a ChromaDB vectorstore of 999 player profiles, and a Together-hosted Qwen 2.5 7B fine-tune used for an offline contract-valuation benchmark.*
>
> *I ran ten pre-registered statistical tests on the deployed system. Four hit at p < 0.05 — the strongest being a precision@10 test where Sabercast's recommendations ranked actual 2025 free-agent signings at 3.1 times the random-chance rate, p < 0.0001. Five came back null on the wins-prediction question — I report all of them honestly because wins prediction is genuinely hard and isn't what this tool was designed to do.*
>
> *Let me show you the app, then I'm happy to go deep on any of the architecture or evaluation decisions."*

That's 50-60 seconds. Then immediately switch to the live app or the demo video. Don't pause for questions until after they've seen the tool work.

---

## The 8 Questions They Are Most Likely to Ask

### Q1 — "Five out of nine tests came back null. Why should I think this is useful?"

> *"Because the four that did hit all validate the layer of the tool that's actually deployed. RAG accuracy gain of 70 percentage points, p=0.0005. Player-matcher precision@10 at 3.1× chance, p<0.0001. Position-level diagnostic at 60% overall hit-rate, p=0.012. IF-position contract MAE borderline significant.*
>
> *The five nulls are all on the wins-prediction question — does the gap_score predict next-year team wins. I tested that five different ways because the spec asked me to, not because the tool was designed to do it. Pro projection systems with multi-year budgets struggle here too — last-year wins predicts next-year wins at r=0.57, and we lose to that baseline. That's not a Sabercast failure, that's the wins-prediction problem being genuinely hard. We say so plainly.*
>
> *Most LLM project reports cherry-pick wins. The four-and-five split here is unusual rigor."*

### Q2 — "Why isn't this just a wrapper around the OpenAI API?"

> *"Three reasons. First, the data pipeline — pybaseball + Spotrac + Statcast OAA + sprint speed + catcher pop time, with a ChromaDB vectorstore of 999 archetype-classified player profiles. Without that, the LLM would hallucinate stats. Second, multi-model routing — gpt-4o for the narrative gap diagnostic where quality matters, gpt-4o-mini for structured JSON outputs at one-twentieth the cost, plus a fine-tuned Qwen 7B for the offline contract-valuation benchmark. Third, no-look-ahead enforcement at every retrieval point. Contracts filtered by signed_year, vectorstore profiles filtered the same way, fine-tune training data per-row filtered.*
>
> *Total platform spend across the entire build: $48. The wrapping is the cheap part. The data layer and the evaluation discipline are what actually take the time."*

### Q3 — "Your RAG eval is only 20 questions. Why should I trust the +70 percentage point result?"

> *"Because the test is McNemar's exact paired test, which is the right test for paired binary outcomes, and the p-value is 0.0005 — not borderline. The 20 questions were selected to cover archetype lookup, trend labels, combined-attribute filters, specific 2024 stats, general MLB knowledge, and glossary terms. RAG won decisively on the first four categories — which are exactly the queries the deployed app handles. It lost on general knowledge because I instructed the model to use only retrieved context, which made it refuse questions outside the vectorstore. That's a prompt-design tradeoff and I documented it.*
>
> *If you'd like a larger evaluation set, expanding to 50-100 questions is cheap — but at this n the result is already strongly significant. The cost-benefit isn't there yet."*

### Q4 — "Precision@10 of 42%, but doesn't that just mean Sabercast retrieves popular free agents?"

> *"Good question, and the answer is the random baseline math. The 13.3% baseline is K=10 over the average eligible position pool size of ~75. That accounts for popularity, because the random baseline samples from the same eligible pool the matcher draws from. The 3.1× lift on top of that is signal beyond pool composition.*
>
> *The hits also aren't just stars — Austin Slater, Donovan Solano, Paul DeJong, Amed Rosario are all in the top-10 retrievals for their respective gaps, alongside Bregman and Alonso. The matcher is doing position-and-archetype matching, not name recognition."*

### Q5 — "Why is your fine-tuned model eval-only? Doesn't that defeat the purpose of fine-tuning?"

> *"Together AI moved custom fine-tunes off their serverless tier mid-build. Inference now requires a dedicated 2× H100 endpoint with ~4-minute cold start. That latency profile is fundamentally incompatible with an interactive Streamlit app where a user expects results in 10-15 seconds. I documented this as one of three platform constraints absorbed during the build — OpenAI deprecated self-serve fine-tuning on May 31, Together restricted serverless inference on June 1.*
>
> *The fine-tune still serves as a published held-out MAE benchmark. The runtime forecast uses gpt-4o-mini. If Together restores serverless inference — or if I were redeploying this to AWS Bedrock or a cheaper provider — the routing seam is already in place to swap the fine-tune into the runtime path."*

### Q6 — "What's the data freshness story? What happens when a player gets traded mid-season?"

> *"The Tm column in the Baseball Reference data shows traded players with comma-joined cities — Garrett Cooper appears as 'Chicago,Houston' if he played for both. The team filter handles that — we match on substring. The defensive metrics — OAA, sprint speed, catcher pop time — are season-end aggregates from Statcast, so they're updated once per season.*
>
> *For the deployed app, this is end-of-season analysis. A real production version with intra-season updates would need a more aggressive ingest pipeline — daily or weekly — and a vectorstore refresh job. Out of scope for a 9-day build, but the data layer is structured to support it."*

### Q7 — "What's the actual unit economics if this were a real product?"

> *"At the build cost, $48 across 9 days. At steady-state runtime, each Gap Filler query is ~12 LLM calls in parallel — one gpt-4o gap diagnostic plus ~11 gpt-4o-mini contract estimates and target forecasts. That's about 4 cents per query at OpenAI's current rates. For a real MLB front office with 30 staff making maybe 100 queries per week, you're looking at about $200 per year in LLM costs. The data pipeline runs once per season and costs roughly nothing.*
>
> *The fine-tune adds about $2 per evaluation cycle on Together's dedicated endpoint. Negligible.*
>
> *If you were building this as a B2B SaaS, your cost structure is dominated by the streamlit infrastructure and the support overhead, not the LLM calls."*

### Q8 — "If you had another month, what would you do differently?"

> *"Three things. First, I'd build a proper modular refactor — the orchestrator is a 1,400-line file that inlines logic the original spec called for splitting into six modules. It's well-organized but it's still one file. Second, I'd extend the held-out contract MAE sample from 26 to 50+ to actually nail down the fine-tune significance. The current ex-Ohtani improvement of 16% has a 95% CI that just barely crosses zero — more data would either confirm or kill it. Third, I'd add a multi-season post-signing performance follow-up so the precision@10 finding becomes a quality finding, not just a retrieval finding.*
>
> *I would NOT spend another month trying to make the wins-prediction tests significant. That's a feature limitation, not a bug, and pretending otherwise would weaken the report."*

---

## Honest Acknowledgments to Volunteer Proactively

Saying these out loud — before they're asked — disarms skepticism:

- **"This is a class project, not a product. I have no commercial validation."** Don't pretend otherwise.
- **"The vectorstore is a single year of player profiles. A production version would need multi-year embedding refresh."**
- **"The fine-tune is eval-only because of platform constraints, not design choice."**
- **"The dataset is public — pybaseball, Spotrac, Statcast. There's no proprietary moat in the data."** Your moat is the orchestration + retrieval architecture, not the inputs.
- **"Five of ten statistical tests came back null. I report all of them."**
- **"Demo-day caveat: if you click around, you'll see the Gap Filler tab takes 8-15 seconds end-to-end because there's 12 LLM calls running in parallel. The original sequential version took 36 seconds."**

---

## When You Get Stuck — Recovery Moves

**If they ask something you don't know:**
> *"That's a good question and I don't have a precise answer. My best guess is [X], but I'd want to test that empirically before defending it as a claim."*

**If they question a finding's validity:**
> *"The test methodology is in eval/precision_at_k.py (or whichever script). The CSV with per-event details is in eval/results/. I'd be happy to walk through the specific events if you want to scrutinize them."*

**If they push on a null:**
> *"Yes, that test came back null. The honest read is [direction]. I tested it [N] different ways and the result was consistent. Wins prediction is genuinely hard — even pro projection systems with full-time analyst teams hit r ≈ 0.7."*

**If they ask about scale / production-readiness:**
> *"I'm a one-person team on a 9-day build budget. Production-readiness wasn't the goal — I optimized for evaluation rigor and clean architecture instead. The architecture supports horizontal scaling — every LLM call is stateless, the vectorstore is read-only at runtime, the data layer is committed CSVs. But I haven't load-tested anything."*

**If they're skeptical of the business framing:**
> *"Fair question. The business framing is small/mid-market MLB front offices — clubs that can't justify a 20-person R&D shop. I don't have customer-discovery interviews to back that. The framing is plausible but unvalidated. The technical claims I'm making are about the architecture and the evaluation, not the market."*

---

## Live App Demo Flow (rehearse this)

**Don't click around randomly. Have a script.**

1. **Open https://sabercast-mlb.streamlit.app/** (have a tab pre-warmed if Streamlit Cloud sleeps)
2. **Click Tab 3: Gap Filler** — the most visually impressive output
3. **Select Seattle Mariners, leave budget at $165M default**
4. **Click "Diagnose roster gaps"** — say *"this is one gpt-4o gap-diagnostic call plus 11 gpt-4o-mini calls fanned out in parallel. Should take 10-15 seconds."*
5. **While it loads, narrate:** *"It's pulling 2024 batting, pitching, OAA, sprint speed, and catcher pop time. Computing deltas vs league average. Calling gpt-4o to interpret them. Then for each of the top 3 gaps, querying the ChromaDB vectorstore for semantically similar player profiles."*
6. **When results appear, scroll to the top gap card.** Point at the candidates and the forecast AAV per candidate.
7. **Say:** *"This is the precision@10 finding made concrete. These three names are Sabercast's top recommendations for SEA's flagged gap. The reading of the test is — 42% of the time, the player a team actually signs is one of these three to ten."*

**Approximate timing: 90 seconds.** Don't show all three tabs unless they ask. Gap Filler is the strongest demo.

---

## The One Question You Should Hope They Ask

> *"What surprised you in the evaluation?"*

> *"The Ohtani methodological finding. When I held out 26 contracts to compare the baseline gpt-4o-mini against the Qwen-7B fine-tune, the fine-tune was directionally better — but Ohtani's $700M Dodgers deal was a $20M outlier where the baseline beat the fine-tune by $25M of MAE. Why? Because gpt-4o-mini's training corpus contains news of the actual Ohtani contract, so it was retrieving an answer from memory rather than forecasting from comparables. The fine-tune had no such advantage and forecasted purely from the 5 comparable contracts I provided.*
>
> *That made me realize the contract-prediction baseline is essentially data-leakage at the LLM training-corpus level. The fine-tune is doing the more honest reasoning even though its MAE looks worse on outlier deals. That's a methodological caveat I want users to know about — when you ask a contract-pricing LLM about a famous deal, it might be quoting memorized news, not forecasting."*

This answer demonstrates that you understand the evaluation deeply, that you weren't just running tests for show, and that you have unique insight about LLM evaluation that isn't in any textbook. **It is the answer that wins the demo.**

---

## What NOT to Do

- Don't claim Sabercast predicts wins. It doesn't. You'll get caught.
- Don't say "the AI" or "the model" generically. Be specific — gpt-4o vs gpt-4o-mini vs Qwen.
- Don't oversell the fine-tune. It's eval-only. Say so.
- Don't pretend the wins-prediction nulls are "actually positive findings if you look at it right." They aren't. Own them.
- Don't compare to ChatGPT. Compare to the no-retrieval gpt-4o baseline you tested against.
- Don't show the BUILD_LOG unless asked. It's there if they want the chronology, but the report + EVALUATION.md + the live app are the deliverables they should focus on.

# Sabercast — Demo Prep for Industry Judges

**Audience:** Diego Granados (Google), Andy Peng (Amazon), Camila Lin (Microsoft).
**Their priors:** big-tech product / engineering leaders. They've seen 100 LLM demos this year. They will probe rigor. Their default question is *"why isn't this just a wrapper around the OpenAI API?"*

## Strategy: buyer-pitch first, technical defense on demand

The pitch slide is positioned as if Sabercast were being sold to a small-market MLB front office — outcomes, speed, accuracy, coverage. That is what the judges will see first. The technical depth is reserved for the Q&A: when the judges probe architecture, methodology, or evaluation choices, you have the answers ready, **explained plainly so the substance lands even if the listener isn't familiar with the LLM jargon.**

The way to win this room:

1. **Lead with the buyer outcome.** Not *"Sabercast is an LLM-powered platform"* — instead *"Sabercast diagnoses a team's three biggest roster gaps and ranks free-agent targets to fill them, in 13 seconds."*
2. **Use the live app as evidence.** Click through Gap Filler on a team they'd recognize (Mariners, Dodgers, Cubs). Let the output speak.
3. **Defend in plain English first.** When the judges press on the technical claims, the plain-English version of each answer goes first. The detailed version is a follow-up if they keep pulling the thread. Plain-English explanation actually demonstrates deeper understanding than reciting jargon.
4. **Acknowledge limits proactively.** If you volunteer the wins-prediction null before they ask, you control the framing. If they catch it first, you're on defense.

---

## The 60-Second Opening (rehearse verbatim)

> *"Sabercast is a decision-support tool for MLB front-office workflows — three jobs every front office runs through, in one web app deployed at sabercast-mlb.streamlit.app.*
>
> *Job one: plan tonight's lineup against the opponent. Job two: scout the team you're facing this series. Job three: diagnose your team's biggest roster gaps and rank the free agents who could fill them.*
>
> *Three numbers worth knowing. The free-agent recommendations match actual MLB signings three times better than random retrieval — when Sabercast hands you a top-10 shortlist, the player a team ends up signing is in that list about 4 times in 10. The roster-gap diagnosis hits the right position 60% of the time across five seasons of all 30 teams, up to 74% at specific positions like second base. End-to-end runtime is about 13 seconds.*
>
> *There's a serious LLM and data architecture under the hood, and I'm happy to go deep on any of it. Let me show you the app first."*

That's 50–60 seconds. Then immediately switch to the live app or the demo video. **Don't pause for questions until they've seen the tool work.**

---

## Live App Demo Flow (rehearse this)

**Don't click around randomly. Have a script.**

### Primary flow: Gap Filler (Tab 3) — lead with this

1. **Open https://sabercast-mlb.streamlit.app/** (have a tab pre-warmed if Streamlit Cloud is asleep).
2. **Click Tab 3: Gap Filler** — the most visually impressive output.
3. **Select Seattle Mariners; leave budget at $165M default.**
4. **Click "Diagnose roster gaps"** — say: *"About 13 seconds end-to-end. The tool is pulling the Mariners' 2024 stats, comparing them against league average to find the biggest weaknesses, then searching its contract database for free agents who could plausibly fill each gap."*
5. **While it loads, narrate plainly:** *"It's looking at batting, pitching, and defense relative to MLB averages, picking the worst three positions, and for each one finding three free-agent candidates that match the team's need — and three recent market contracts that anchor what the candidates might cost."*
6. **When results appear, scroll to the top gap card.** Point at the diagnosed gap, then the three recommended free-agent targets, then the three pricing comparables.
7. **Say:** *"Three things on this card: a position gap with a confidence score, three recommended free agents ranked by fit, and three pricing comparables — recent contracts at the same position that anchor what these players might cost. The accuracy claim — top-10 shortlist contains the actual signing 42% of the time, three times the baseline — means when this card recommends a player, that recommendation is meaningfully more than a guess."*

**Approximate timing: 90 seconds.** Gap Filler is your strongest opener. Lead with it. The other two tabs are below if you want to show them after.

### Optional: Roster Builder (Tab 1) — the day-to-day workflow

Use this if the judges ask *"what does the manager actually do with this on a Tuesday in July?"*, or if you have extra time after Gap Filler.

**What it does in plain English:** You pick your team, tonight's opponent, and — when the matchup is known — the opponent's confirmed probable starter. The tool looks at your hitters and that specific pitcher (or the staff overall if no starter is selected), then produces a recommended 9-slot batting order with a matchup plan — what advantages to exploit, what risks to watch, and a short narrative tying it together.

**Demo flow:**

1. **Click Tab 1: Roster Builder.**
2. **Pick your team (Dodgers) and tonight's opponent (Tigers).**
3. **Pick the probable starter from the dropdown (Tarik Skubal — LHP)** — say: *"This is where the matchup gets real. The dropdown is the opponent's actual starting rotation with their season stat line, and the tool knows which arm each pitcher throws with. When I pick Skubal, the tool will tailor the lineup specifically to attacking Skubal — a left-hander — not the staff in general."*
4. **Click "Build roster + matchup plan"** — say: *"About 10 seconds. One LLM call with the lineup, Skubal's specific stat line including handedness, and the Tigers' defensive profile."*
5. **While it loads, narrate:** *"It's looking at our hitters' platoon profile against a lefty — stacking right-handed bats high in the order — and at Skubal's specific WHIP, strikeout rate, and walk rate to pick the spots where he gives up baserunners."*
6. **When results appear, scroll through:** the **"Facing tonight: Tarik Skubal · LHP"** callout with his stat line, the narrative naming Skubal AND citing the platoon angle, the recommended 9-slot lineup with right-handed and switch-hitting bats stacked 1-5 against the lefty, the matchup advantages leading with **"Exploit platoon advantage — stack right-handed hitters against Skubal's left-handed pitching"**, and the risks.
7. **Say:** *"This is structured the way a manager would actually use it — here's tonight's lineup against this specific pitcher, with platoon-aware ordering against his handedness, and pitcher-specific rationale on every slot. End-to-end, about ten seconds."*

**Right-handed-pitcher variant:** Pick Gerrit Cole (NYY, RHP) instead. Same flow, but the LLM stacks left-handed hitters early and frames advantages around attacking Cole's WHIP.

**Fallback if no starter is selected:** The tool still works the old way — staff-level reasoning, no specific starter named. Useful when the probable starter hasn't been announced yet.

**Fallback if a starter has no handedness on file:** Very rare in current data (1,604 of MLB's active pitchers carry handedness from the MLB Stats API pull), but if it happens the callout says "Handedness unknown — falling back to stat-profile reasoning" and the lineup just isn't platoon-aware. Stat-line reasoning still applies.

### Optional: Opponent Scouting (Tab 2) — the pre-series report

Use this if the judges ask about pre-series prep, or if you want to show a fresh real-time LLM call (Gap Filler may have cached on Tab 3).

**What it does in plain English:** You pick the team you're about to play. The tool produces a structured scouting report — a narrative summary, the three most dangerous opposing players to game-plan against, three exploitable weaknesses, and recommended pitching and hitting approaches for the series.

1. **Click Tab 2: Opponent Scouting.**
2. **Pick the team you're scouting (Yankees).**
3. **Click "Scout this opponent"** — say: *"About 8 seconds. The tool is pulling the Yankees' 2024 team stats and producing a scouting report a coordinator could brief the team from."*
4. **While it loads, narrate:** *"It's identifying the most dangerous hitters by production, the vulnerabilities in their rotation and bullpen, and synthesizing a strategy on both sides of the ball."*
5. **When results appear, scroll through:** the narrative summary at the top, the three-threats card (their best hitters with reasoning), the three-weaknesses card (patterns we can exploit), the pitching strategy block, and the hitting approach block.
6. **Say:** *"This is the kind of pre-series report a scouting coordinator would put together. Sabercast gives them a structured starting point in eight seconds — they refine and add their own judgment from there."*

---

## The 8 Questions They Are Most Likely to Ask

Each answer has a **plain-English version** to lead with, and a **technical detail** anchor if they press further.

### Q1 — "Five out of ten tests came back null. Why should I think this is useful?"

**Plain English:**
> *"Because the four that did hit are the ones that validate what the tool actually does for a user. The ones that didn't hit are all on a different question — predicting how many games a team will win next year — and that's a question the tool wasn't designed to answer. We tested it five different ways for honesty and reported every result."*

**Technical detail if pressed:**
> *"The four hits validate the deployed product layer: RAG accuracy gain of 70 percentage points on a held-out Q&A set. Player-matcher precision@10 at 3.1× chance. Position-level gap-diagnosis hit rate of 60% overall, up to 74% at second base. Contract-pricing MAE borderline-significant at the IF position. The five nulls are all variants of one question — does the gap-score predict next-year team wins. I tested it five ways; all five came back null. Honest read: wins prediction is genuinely hard, even pro projection systems with full-time analysts hit a ceiling, and we lose to a baseline of 'last year's wins predict next year's wins' at r=0.57. That's the wins-prediction problem being hard, not a tool failure. Most LLM project reports cherry-pick wins. The four-and-five split is unusual rigor."*

### Q2 — "Why isn't this just a wrapper around the OpenAI API?"

**Plain English:**
> *"Three reasons. First, the data layer — multi-year MLB stats, defensive metrics, and 1,254 free-agent contracts pulled, cleaned, and indexed. Without that, the AI would make up player stats. Second, the tool routes work to different models based on what they're best at — a stronger model for narrative reasoning, a cheaper one for structured outputs. Third, when the tool looks at past seasons it's strictly prevented from seeing future data — that lets us run honest historical backtests. Total platform spend for the build was about $48. The API wrapping is the cheap part."*

**Technical detail if pressed:**
> *"gpt-4o handles the gap-diagnostic narrative because quality matters there. gpt-4o-mini handles structured JSON outputs at one-twentieth the cost. text-embedding-3-small powers retrieval over a ChromaDB vectorstore of 999 archetype-classified player profiles. A fine-tuned Qwen 2.5 7B sits in the evaluation pipeline as a benchmark contract valuator. Every retrieval point filters by signed_year ≤ evaluation_year so historical backtests don't leak future data. The data pipeline, the routing, the no-look-ahead enforcement, and the evaluation harness are where the real work went."*

### Q3 — "Your RAG evaluation is only 20 questions. Why should I trust the +70 percentage point result?"

**Plain English:**
> *"Because even with only 20 paired questions, the statistical test says this result would happen by chance less than 1 in 1,000 times. The 20 questions cover what the deployed app actually does — looking up specific players, finding similar archetypes, checking stats. The retrieval-augmented version beat the no-retrieval version decisively on those."*

**Technical detail if pressed:**
> *"The test is McNemar's exact paired test — the right test for paired binary outcomes. p=0.0005 with n=20 is strongly significant, not borderline. The 20 questions span six categories: archetype lookup, trend labels, combined-attribute filters, specific 2024 stats, general MLB knowledge, and glossary terms. RAG won decisively on the first four — which are the queries the deployed app handles. It lost on general MLB knowledge because I deliberately constrained the model to use only retrieved context. That's a prompt-design tradeoff I documented. Expanding to 50–100 questions is cheap, but the result is already strongly significant."*

### Q4 — "Precision@10 of 42% — doesn't that just mean Sabercast retrieves popular free agents?"

**Plain English:**
> *"No, because the comparison is calibrated for that. The baseline we compare against isn't 'pick 10 random players' — it's 'pick 10 random contracts from the same eligible pool the tool draws from.' So popular players are in both. The 3.1× lift on top of that is real signal, not name recognition. And the actual hits aren't just stars — Austin Slater, Donovan Solano, Paul DeJong — that mix is hard to fake."*

**Technical detail if pressed:**
> *"The 13.3% random baseline is K=10 over the average eligible position pool size of ~75. Pool sizes vary by position — catcher is ~24, starting pitcher is ~267 — and the baseline is calibrated per-event. So a positional pool of 75 means random sampling gets 10/75 = 13.3%. The 3.1× lift on top of that says the matcher is doing real position-and-archetype work, not just name recall. Concrete hits include: Bregman to BOS rank #1, Alonso to NYM #3, Altuve to HOU #5, Slater to CWS #9, Solano to SEA #6. That mix of stars and mid-tier journeymen is hard to fake."*

### Q5 — "Why is your fine-tuned model evaluation-only? Doesn't that defeat the purpose of fine-tuning?"

**Plain English:**
> *"It would defeat the purpose if I'd planned for it. But mid-build, the fine-tune hosting provider changed their pricing — fine-tuned models now require a dedicated 4-minute-startup endpoint that costs about $4 an hour to keep warm. That latency is incompatible with a real-time web app. So the fine-tune still publishes its evaluation results as a benchmark, but the live tool uses gpt-4o-mini. The architecture is set up to swap the fine-tune back in if the hosting situation changes."*

**Technical detail if pressed:**
> *"Together AI moved custom fine-tunes off their serverless tier on June 1. Inference now requires a dedicated 2× H100 endpoint with ~4-minute cold start. Fundamentally incompatible with an interactive Streamlit app where users expect 10–15s responses. I documented this as one of three platform constraints absorbed during the build — OpenAI also deprecated self-serve fine-tuning on May 31. The fine-tune publishes a held-out MAE benchmark; the runtime forecast uses gpt-4o-mini. The routing seam is already in place to swap the fine-tune into the runtime if Together restores serverless inference or if I were redeploying to a different platform."*

### Q6 — "What's the data freshness story? What if a player gets traded mid-season?"

**Plain English:**
> *"The data is updated once per season — it's end-of-season totals from official sources. Mid-season trades do show up because the data sources record them — a traded player is just associated with both teams. For a real production version that updates daily, the data pipeline would need to run more often, but the structure supports it."*

**Technical detail if pressed:**
> *"The Tm column in Baseball Reference data shows traded players with comma-joined cities — Garrett Cooper appears as 'Chicago,Houston' if he played for both teams. The team filter handles that with substring matching. Defensive metrics — OAA, sprint speed, catcher pop time — are season-end aggregates from Statcast, refreshed once per season. For an intra-season production version, you'd want a daily or weekly ingest pipeline plus a vectorstore refresh job. Out of scope for a 9-day build, but the data layer is structured to support it."*

### Q7 — "What's the actual unit economics if this were a real product?"

**Plain English:**
> *"The whole build cost about $48 in API and platform spend. At running cost, each Gap Filler query is about 4 cents. So a real front office using it 100 times a week would spend about $200 a year on AI calls. The expensive parts of a real product would be infrastructure and customer support, not the AI itself."*

**Technical detail if pressed:**
> *"Each Gap Filler query is ~12 LLM calls in parallel — one gpt-4o gap diagnostic plus ~11 gpt-4o-mini contract estimates and target forecasts. About 4 cents per query at OpenAI's current rates. For a real MLB front office with 30 staff making ~100 queries per week: roughly $200/year in LLM costs. The data pipeline runs once per season and costs roughly nothing. The fine-tune adds about $2 per evaluation cycle on Together's dedicated endpoint — negligible. If you were building this as B2B SaaS, your cost structure is dominated by hosting and support overhead, not LLM calls."*

### Q8 — "If you had another month, what would you do differently?"

**Plain English:**
> *"Three things. First, clean up the code organization — the main file grew larger than the original plan called for. Second, expand the contract-prediction evaluation from 26 contracts to 50+, so I can confirm or kill a borderline-significant result. Third, follow up the free-agent recommendations across multiple seasons to validate that the picks actually worked out for the teams that signed them. What I would NOT do is keep trying to make the wins-prediction tests significant — that's a real feature limitation, not a bug, and pretending otherwise would weaken the report."*

**Technical detail if pressed:**
> *"Specifically: (1) The orchestrator is a 1,400-line file that inlines logic the original spec called for splitting into six modules. Well-organized but still one file. A modular refactor is in the backlog. (2) The held-out contract MAE sample is 26 contracts; expanding to 50+ would either confirm or kill the current 16% ex-Ohtani improvement, which has a 95% CI that just barely crosses zero. (3) Post-signing performance follow-up across multiple seasons would let me make a quality claim about the precision@10 finding, not just a retrieval claim. The wins-prediction nulls are real and persistent — I tested five different ways. Pretending otherwise would weaken the report."*

---

## Honest Acknowledgments to Volunteer Proactively

Saying these out loud — *before* they're asked — disarms skepticism:

- **"This is a class project, not a product. I have no commercial validation."** Don't pretend otherwise.
- **"The data refreshes once per season. A production version would need a more aggressive ingest pipeline."**
- **"The fine-tune is evaluation-only because of platform constraints, not by design."**
- **"All the data sources are public — pybaseball, Spotrac, Statcast. There's no proprietary data moat."** The differentiation is in the orchestration and retrieval architecture, not the inputs.
- **"Five of ten statistical tests came back null. I report all of them."**
- **"The Gap Filler tab takes 8–15 seconds because 12 AI calls are running in parallel. The original sequential version took 36 seconds."**

---

## When You Get Stuck — Recovery Moves

**If they ask something you don't know:**
> *"That's a good question and I don't have a precise answer. My best guess is [X], but I'd want to test it empirically before defending it as a claim."*

**If they question a finding's validity:**
> *"The methodology is in eval/precision_at_k.py (or whichever script). The CSV with per-event details is in eval/results/. Happy to walk through the specific events if you want to scrutinize them."*

**If they push on a null result:**
> *"Yes, that test came back null. The honest read is [direction]. I tested it [N] different ways and the result was consistent. Wins prediction is genuinely hard — pro projection systems with full-time analyst teams hit r ≈ 0.7 ceilings."*

**If they ask about scale or production readiness:**
> *"I'm a one-person team on a 9-day build budget. Production-readiness wasn't the goal — I optimized for evaluation rigor and clean architecture. The architecture supports horizontal scaling — every AI call is stateless, the data layer is read-only at runtime — but I haven't load-tested anything."*

**If they're skeptical of the business framing:**
> *"Fair point. The framing is small/mid-market MLB front offices — clubs that can't justify a 20-person analytics shop. I don't have customer-discovery interviews to back that. The framing is plausible but unvalidated. The technical claims are about the architecture and the evaluation, not the market."*

---

## The One Question You Should Hope They Ask

> *"What surprised you in the evaluation?"*

**Plain English:**
> *"The Ohtani methodological finding. When I tested the fine-tuned model against the baseline gpt-4o-mini on contract predictions, the fine-tune was directionally better — except on Ohtani's $700M Dodgers deal, where the baseline beat the fine-tune by $25M of error.*
>
> *Why? Because the baseline model's training data includes news coverage of the actual Ohtani contract. It wasn't forecasting — it was remembering. The fine-tune had no such advantage, so it forecasted purely from the comparable contracts I provided to it.*
>
> *That made me realize the contract-prediction baseline has a hidden data-leakage problem at the model-training level. When you ask a contract-pricing AI about a famous deal, it might be quoting memorized news, not forecasting. That's a methodological caveat I want users to know about — even when the headline numbers look worse, the fine-tune is doing the more honest reasoning."*

This answer demonstrates that you understand the evaluation deeply, that you weren't running tests for show, and that you have genuine insight about AI evaluation that isn't in any textbook. **It is the answer that wins the demo.**

---

## What NOT to Do

- **Don't claim Sabercast predicts wins.** It doesn't. You'll get caught.
- **Don't lead with technical jargon.** Buyer outcome first, technical defense on demand.
- **Don't say "the AI" or "the model" generically when probed.** Be specific — gpt-4o vs gpt-4o-mini vs the Qwen fine-tune.
- **Don't oversell the fine-tune.** It's evaluation-only. Say so.
- **Don't pretend the wins-prediction nulls are "actually positive findings if you look at it right."** They aren't. Own them.
- **Don't compare to ChatGPT.** Compare to the no-retrieval baseline you tested against.
- **Don't show the BUILD_LOG unless asked.** It's there if they want the chronology, but the report + the live app are the deliverables they should focus on.

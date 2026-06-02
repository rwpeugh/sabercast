# Sabercast — Demo Video Voiceover Script

**Target runtime:** 1:50–2:10 (matches `demo/record_demo_video.py` output).
**Tone:** confident, conversational, lightly technical. The viewer is a hiring manager or course instructor — knows software well, may not know baseball.
**Recording suggestion:** read each segment as one breath of thought. Pauses at the dashes are intentional.

Timestamps below are approximate — they assume Streamlit Cloud responds in steady state (not cold start). If your actual recording runs longer because the deployed app was sleeping, hold lines longer or fold filler ("...the LLM call is finishing now...").

---

## Segment 1 — Landing  (0:00 – 0:13)

> "This is Sabercast — an LLM-powered MLB front-office intelligence platform I built for the MKTG 569 final project.
>
> It's three workflows behind a Streamlit interface, deployed at sabercast-mlb.streamlit.app, designed for small- and mid-market clubs that don't have a twenty-person analytics shop. Every box you'll see is grounded in real 2024 player data and recent free-agent contracts. Let me walk you through it."

**What's on screen:** Sabercast landing page. About sidebar visible left, three tab labels at top, intro paragraph in the main pane.

---

## Segment 2 — Roster Builder  (0:13 – 0:48)

> "First tab — Roster Builder. This answers the day-to-day question: given today's available roster, what's our best lineup against this opponent?
>
> I click Build. Behind the scenes Sabercast is aggregating my team's recent stats, the opponent's pitching staff, their defensive metrics, and then asking gpt-4o-mini to construct a position-by-position lineup with matchup rationale.
>
> Here's the output — a nine-slot recommended lineup, with the rationale for each placement, plus matchup advantages and risks the manager should be aware of going into the game."

**What's on screen:**
- 0:13-0:15 — Roster Builder tab activates
- 0:15-0:32 — "Building lineup..." spinner (the LLM call running)
- 0:32-0:48 — Scroll through: recommended lineup card → matchup advantages → matchup risks

**Filler if wait is long:** "...this is doing the full team + opponent aggregation and a single gpt-4o-mini call to compose the lineup..."

---

## Segment 3 — Opponent Scouting  (0:48 – 1:13)

> "Second tab — Opponent Scouting. Same kind of pre-game prep but from a different angle: what do we need to know about the team we're playing tomorrow?
>
> Sabercast pulls in the opponent's recent batting and pitching aggregates, their per-position defensive OAA from Statcast, and lets gpt-4o write a structured scouting report — three top threats, three exploitable weaknesses, and concrete pitching and hitting strategy.
>
> What's important here is the structured output — every field is consistent JSON, every recommendation grounded in a specific delta vs. league average."

**What's on screen:**
- 0:48-0:50 — Tab switch
- 0:50-1:02 — Scout call running
- 1:02-1:13 — Scroll through: narrative → top threats → exploitable weaknesses → pitching strategy → hitting approach

---

## Segment 4 — Gap Filler  (1:13 – 1:55)

> "Third tab — Gap Filler. This is the longer-horizon question: where are our biggest roster gaps and who's available to fill them?
>
> I click Diagnose. This kicks off the most complex orchestration in the app — one gpt-4o call to identify the top three gap positions, then for each gap, retrieval from a ChromaDB vectorstore of nine hundred and ninety-nine player profiles, three gpt-4o-mini contract estimates, and per-target contract forecasts. Twelve LLM calls total, running in parallel.
>
> Here's what comes back — a roster summary with offense and defense deltas, then three gap cards, each with three recommended target players, their archetype and trend labels from our pipeline, and a forecast for what each player would cost on a new free-agent deal.
>
> The 'no-look-ahead' note is important — every contract you see in the comparable pool was signed on or before 2024, so a GM running this at the end of the 2024 season couldn't see future signings. That discipline runs through every step of the pipeline."

**What's on screen:**
- 1:13-1:15 — Tab switch
- 1:15-1:35 — Diagnose call running (12 LLM calls in parallel)
- 1:35-1:55 — Scroll through: roster summary + delta chart → top gap card with targets → contract forecasts

---

## Optional closing line (1:55 – 2:05) — only if you want to add a static end card

> "Live at sabercast-mlb.streamlit.app. Full source, build log, and evaluation results at github-dot-com slash rwpeugh slash sabercast. Thanks for watching."

---

## If you record narration in one take

Practice once with the silent video playing. Read each segment as the on-screen action happens. Tolerate the latency in the "waiting for LLM" stretches — that's authentic to how the deployed app behaves, not dead air to be edited around. The voiceover should explain *what the model is doing during the wait* rather than apologize for it.

## If you record in segments

Record one segment at a time, then stitch in any free editor (CapCut, iMovie, Windows Clipchamp, DaVinci Resolve). The segment boundaries are at natural tab transitions, so cuts will look clean.

## Embedding the final video

- **GitHub README:** upload to YouTube (unlisted) or Loom, link from the README badges section.
- **Class submission:** depends on the deliverable format. A direct link works; embedded video in Word/PDF is finicky.
- **Portfolio:** YouTube unlisted + link from your LinkedIn About section or a personal site.

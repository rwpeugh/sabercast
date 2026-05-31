# Sabercast

LLM-powered MLB front-office intelligence platform. Three-tab Streamlit app using OpenAI + RAG + fine-tuning + batch analysis to support roster construction, opponent scouting, and roster gap filling.

Course: MKTG 569 — Building Business Applications of LLMs and Generative Models (Spring 2026)
Demo Day: June 3, 2026

## Setup

1. Clone or download this folder.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Provide your OpenAI API key. Either:
   - Create `OpenAIKey.txt` in the project root with the key on a single line, OR
   - Set the environment variable `OPENAI_API_KEY`.
4. Run the app:
   ```
   streamlit run app/streamlit_app.py
   ```

## Current Status (Emergency Sprint, May 23 2026)

- Data: 2024 batting + pitching ingested from pybaseball.
- Contracts: ~30 representative free-agent contracts populated (Spotrac scrape coming).
- App: Gap Filler tab functional for Seattle Mariners. Tabs 1 & 2 show "Coming soon".

See `SABERCAST_SPEC.md` (parent folder) for the canonical build spec.

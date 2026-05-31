# Deploying Sabercast to Streamlit Community Cloud

This is a one-time setup. After it's done, every git push to the connected branch redeploys automatically.

## Prerequisites (one-time)

1. **GitHub account.** Sign in at <https://github.com>.
2. **Streamlit Cloud account.** Free tier at <https://streamlit.io/cloud> — use "Continue with GitHub" so it can read your repos.

## Step 1 — Create the GitHub repository

1. Open <https://github.com/new>.
2. Repository name: **`sabercast`** (or any name you want).
3. Visibility: **Public** (Streamlit Cloud free tier requires public repos).
4. Do **NOT** check "Initialize this repository with a README" — the local repo already has files.
5. Click **Create repository**.
6. On the next page GitHub shows the remote URL. Copy the HTTPS one (looks like `https://github.com/<your-username>/sabercast.git`).

## Step 2 — Push the local repo

From a PowerShell prompt opened at the `sabercast/` folder:

```powershell
git remote add origin https://github.com/<your-username>/sabercast.git
git branch -M main
git push -u origin main
```

If git asks you to authenticate, use a personal access token or the GitHub CLI's browser flow. The token needs the `repo` scope.

## Step 3 — Connect Streamlit Cloud

1. Open <https://share.streamlit.io>.
2. Click **New app** (top right).
3. Fill in:
   - **Repository:** `<your-username>/sabercast`
   - **Branch:** `main`
   - **Main file path:** `app/streamlit_app.py`
   - **App URL (optional):** pick a slug (e.g. `sabercast-mlb`)
4. Click **Advanced settings** → **Secrets**, paste the following (replacing the placeholder with your actual key):

   ```toml
   OPENAI_API_KEY = "sk-..."
   ```

5. Click **Deploy**.

The first build takes 3–6 minutes (installing pybaseball + chromadb + streamlit + plotly). Subsequent deploys after a `git push` are ~30 seconds.

## Step 4 — Verify

When deploy completes, the URL will be `https://<your-slug>.streamlit.app/`. Open it and:

1. Confirm the landing page loads with all three tabs visible.
2. Switch to the Gap Filler tab, pick SEA, click **Diagnose roster gaps**. Expect ~30 seconds on first run.
3. Switch to the Opponent Scouting tab, pick HOU, click **Generate scouting report**. Expect ~5 seconds.

If the run fails with "OpenAI API key not found", double-check the secret in Streamlit Cloud's app settings.

## Step 5 — Iterate

Every git push to `main` redeploys automatically. To push a change:

```powershell
git add -A
git commit -m "Describe the change"
git push
```

## What's in the repo (size: ~25 MB)

- App code (`app/`, `core/`, `pipelines/`, `eval/`)
- Data files (`data/raw/*.csv`, `data/archetypes/`, `data/processed/`, `data/vectorstore/`) — required so the deployed app can run without re-pulling from pybaseball
- Docs (`docs/`)

What's intentionally **not** committed:
- `OpenAIKey.txt` and `.env` (secrets — set as Streamlit secrets instead)
- `.streamlit/secrets.toml` (use the Streamlit Cloud UI)
- `__pycache__/`, logs, OS noise

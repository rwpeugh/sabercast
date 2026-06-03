# Machine Switch Guide

How to pick up Sabercast development on a different computer.

The project lives in OneDrive at `OneDrive - UW\Courses\MKTG 569 Build AI\Final Project\sabercast\` and is also on GitHub at **github.com/rwpeugh/sabercast**. OneDrive handles the file-sync convenience layer; git is the source of truth for code changes.

---

## Pre-flight: before you leave the current machine

1. **Commit and push everything**

   ```powershell
   git status            # should show only vectorstore .bin churn + chroma_db/ (both harmless)
   git push origin main
   ```

2. **Let OneDrive finish syncing.** Check the system-tray icon — it should say "Up to date" (not "Syncing X items"). The vectorstore `.bin` files and the `chroma_db/` folder are touched by every smoke test and can take a few minutes to sync.

3. **Confirm `.env` and `TogetherKey.txt` are in the OneDrive folder.** Both are gitignored — OneDrive is the only path to the other machine for the keys.

4. **Close any apps holding file locks** before walking away: Streamlit, PowerPoint, anything reading the vectorstore. OneDrive sync stalls silently on locked files.

---

## On the new machine

### 1. Make sure OneDrive has the folder fully downloaded locally

In File Explorer, find the `sabercast` folder. Right-click → **"Always keep on this device"**. Without this, OneDrive's "Files on Demand" mode leaves files as cloud-only stubs that Python can't read until first access — which causes weird `FileNotFoundError`s during smoke tests.

### 2. Install / verify Python

Open PowerShell and check:

```powershell
python --version
```

- If it prints `Python 3.11.x` or higher → you're good.
- If it says "command not found" or opens the Microsoft Store, install Python from **https://www.python.org/downloads/** with the **"Add python.exe to PATH"** checkbox enabled. Close + reopen PowerShell after.

### 3. Recreate the virtual environment

The `.venv/` folder is **not portable** across machines — the Python interpreter paths are baked into its activation scripts. Recreating it is the only step that's genuinely mandatory.

#### 3a. Open PowerShell *in the project folder*

In File Explorer, navigate to:

```
C:\Users\<YourName>\OneDrive - UW\Courses\MKTG 569 Build AI\Final Project\sabercast
```

Click the address bar at the top, type `powershell`, hit Enter. PowerShell opens with the working directory already set:

```
PS C:\Users\<YourName>\OneDrive - UW\...\sabercast>
```

#### 3b. Create the venv

```powershell
python -m venv .venv
```

~10 seconds. Creates a `.venv\` folder inside the project.

#### 3c. Allow PowerShell to run activation scripts (one-time, per-user)

Windows blocks script execution by default. Fix it once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Type `Y` when prompted. Safe, common dev setup change.

#### 3d. Activate the venv

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt should now show `(.venv)` at the start:

```
(.venv) PS C:\Users\<YourName>\OneDrive - UW\...\sabercast>
```

#### 3e. Upgrade pip + install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3–5 minutes depending on internet speed. Installs openai, pybaseball, chromadb, streamlit, plotly, pandas, numpy, scikit-learn, tenacity, pyyaml, requests, beautifulsoup4, python-dotenv and their dependencies.

#### 3f. Verify

```powershell
python -c "import openai, pybaseball, chromadb, streamlit; print('all imports ok')"
```

Should print `all imports ok`.

#### 3g. (Optional) Playwright — only if you'll run the demo-video / screenshot scripts

```powershell
pip install playwright
playwright install chromium
```

### 4. Smoke-test before doing real work

```powershell
$env:PYTHONIOENCODING = "utf-8"
python demo\smoke_test_edge_cases.py
```

If you see `EDGE-CASE SMOKE TEST: 8 passed · 1 warned · 0 failed` you're fully set up.

### 5. Launch Claude Code in that folder

`cd` into the project (if not already there) and start Claude Code. It picks up `CLAUDE.md` and the git context automatically.

---

## Daily workflow rule once you're on two machines

**Git is the source of truth, OneDrive is the convenience layer.**

- Always `git pull origin main` *before* starting work on either machine.
- Always `git commit && git push` *before* leaving a machine.
- Don't edit on both machines simultaneously — OneDrive will silently create `file-conflict.ext` copies if it sees concurrent writes.

---

## Re-activating after the first setup

Every subsequent PowerShell window in this project, just:

```powershell
cd "<full path to sabercast folder>"
.\.venv\Scripts\Activate.ps1
```

That's it — the `(.venv)` prefix on your prompt = ready to go.

---

## What doesn't transfer cleanly (and what to do about it)

| Item | Status | What to do |
|------|--------|-----------|
| `.venv/` | Gitignored, NOT portable | Recreate via step 3 |
| `.env` and `TogetherKey.txt` | Gitignored, syncs via OneDrive | Verify they're present before running anything |
| `chroma_db/` | Auto-generated, untracked | If you see "database is locked", delete the folder and let it regenerate |
| `data/vectorstore/` | Tracked in git | Syncs cleanly via either git or OneDrive |
| Streamlit Cloud secrets | Stored in your Streamlit Cloud account | Lives outside the project folder, no sync needed |
| Playwright Chromium binaries | OS-specific, gitignored | Reinstall via `playwright install chromium` if you'll run video/screenshot scripts |
| Together AI fine-tune artifacts | Tracked in `data/processed/finetune_*` | Syncs via git |

---

## Common gotchas

| Problem | Fix |
|---------|-----|
| `python: command not found` | Python isn't on PATH. Reinstall from python.org with "Add to PATH" checked. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | You skipped step 3c. Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`. |
| `pip` is very slow on first install | Normal — chromadb pulls onnxruntime (~80MB). Wait it out. |
| `error: Microsoft Visual C++ 14.0 or greater is required` | Rare. Install **Visual Studio Build Tools** (free) from Microsoft, restart PowerShell, retry `pip install -r requirements.txt`. |
| `(.venv)` appeared but `python` still uses the system one | Run `where python` — first hit should be `...\sabercast\.venv\Scripts\python.exe`. If not, close the terminal and start over from step 3a. |
| `database is locked` errors when running smoke tests | A previous run held a ChromaDB lock and OneDrive sync replicated the lock file. Delete `chroma_db/` (untracked) and re-run. |
| `Sabercast_Pitch_Slide.pptx: Permission denied` when regenerating the slide | PowerPoint has the file open. Close PowerPoint and retry. |
| OneDrive shows `file-conflict.<timestamp>.<ext>` copies | You edited the same file on both machines. Compare both versions, keep the right one, delete the conflict copy. Then re-pull / re-push to align git. |

---

## Why both OneDrive + git instead of one or the other?

- **Git alone** would miss `.env`, `TogetherKey.txt`, anything gitignored, and any locally-cached files. You'd have to copy these manually every time.
- **OneDrive alone** doesn't give you version history, branches, or the ability to revert. And concurrent edits silently produce conflict files.
- **Both** = git handles code correctness, OneDrive handles the messy non-code bits. As long as you respect the "pull before, push after" rule, the two layers don't fight.

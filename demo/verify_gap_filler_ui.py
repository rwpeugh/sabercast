"""demo/verify_gap_filler_ui.py — visual check for Entry 25-29 UI elements.

Drives the local Streamlit app, runs the Gap Filler with SEA at $250M
(so the team has real available room above its ~$166M committed Spotrac
total), and captures screenshots of:

  1. Inputs row with the new committed-payroll override field
  2. Payroll Situation panel (4 metric tiles)
  3. Each gap card showing:
       - Current incumbent callout band
       - Per-target vs-incumbent delta chips
       - Tier badges (BARGAIN / AT BUDGET / PREMIUM)

Saved to docs/checkpoint3/entry29_*.png so they're available for review.
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT     = Path(__file__).resolve().parent.parent
OUT_DIR  = ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL  = "http://localhost:8501"
TEAM = "SEA"
BUDGET = "250000000"   # leaves real room above ~$166M committed


def _wait_for_text(page, text: str, timeout_ms: int = 60_000) -> None:
    page.wait_for_function(
        f"() => document.body.innerText.includes({text!r})",
        timeout=timeout_ms,
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.goto(URL, wait_until="networkidle")
        # Streamlit's first script run -- wait for any tab/sidebar content
        _wait_for_text(page, "Sabercast")
        time.sleep(2.0)

        # Switch to Gap Filler tab
        page.get_by_role("tab", name="3. Gap Filler").click()
        _wait_for_text(page, "Roster Gap Filler")
        time.sleep(1.5)

        # ── Screenshot 1: inputs row showing the new committed-payroll field
        out = OUT_DIR / "entry29_01_inputs_with_committed_field.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # Skip team change -- SEA is default. Set budget $250M via spinbutton
        # role (avoids matching the help button which shares the label).
        budget_box = page.get_by_role("spinbutton", name="Total payroll budget for 2025")
        budget_box.click()
        budget_box.press("Control+A")
        budget_box.type(BUDGET)
        budget_box.press("Tab")  # commit
        time.sleep(0.8)

        # Screenshot 1b: budget set, see live preview of payroll math
        out = OUT_DIR / "entry29_02_inputs_after_set.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # Click Diagnose
        page.get_by_role("button", name="Diagnose roster gaps").click()
        print("  clicked Diagnose; waiting for results...")
        try:
            _wait_for_text(page, "Highest priority:", timeout_ms=240_000)
        except Exception:
            dbg = OUT_DIR / "entry29_debug_timeout.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"  TIMEOUT. dumped {dbg.name}")
            raise
        time.sleep(3.0)

        # ── Screenshot 2: top of results page -- Payroll Situation panel
        page.evaluate(
            "() => { const h = [...document.querySelectorAll('h3')]"
            ".find(e => e.innerText.includes('Payroll situation')); h && h.scrollIntoView({block: 'start'}); }"
        )
        time.sleep(0.6)
        out = OUT_DIR / "entry29_03_payroll_situation_panel.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Screenshot 3: top gap card showing incumbent callout + tier badges
        page.evaluate(
            "() => { const h = [...document.querySelectorAll('h3,h4')]"
            ".find(e => e.innerText.includes('Top 3 gaps')); h && h.scrollIntoView({block: 'start'}); }"
        )
        time.sleep(0.6)
        out = OUT_DIR / "entry29_04_top_gap_card_with_incumbent.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Full-page screenshot for overall layout audit
        out = OUT_DIR / "entry29_05_full_page.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"saved {out.name}  (full page)")

        browser.close()
        print()
        print(f"All screenshots in: {OUT_DIR}")


if __name__ == "__main__":
    main()

"""Capture the 4 Checkpoint 3 screenshots from the running Streamlit app.

Requires the app to already be running at http://localhost:8501.
Outputs PNGs to docs/checkpoint3/.
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR      = PROJECT_ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = "http://localhost:8501"


def wait_for_text(page, text: str, timeout_ms: int = 60_000) -> None:
    page.wait_for_function(
        f"() => document.body.innerText.includes({text!r})",
        timeout=timeout_ms,
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        page.goto(URL, wait_until="networkidle")
        # Wait for Streamlit to finish its first script run — the Roster Builder
        # placeholder content is the signal everything has actually rendered.
        wait_for_text(page, "Planned inputs")
        time.sleep(1.0)

        # ── Screenshot 1: landing (Roster Builder default tab + sidebar) ─────
        out = OUT_DIR / "01_landing.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Switch to Gap Filler tab ─────────────────────────────────────────
        page.get_by_role("tab", name="3. Gap Filler").click()
        wait_for_text(page, "Roster Gap Filler")
        time.sleep(1.0)  # let layout settle

        # ── Click "Diagnose roster gaps" and wait for results ────────────────
        diag_btn = page.get_by_role("button", name="Diagnose roster gaps")
        diag_btn.wait_for(state="visible", timeout=10_000)
        diag_btn.click()
        print("  clicked Diagnose; waiting for results...")
        try:
            # Don't wait for the "Top 3 gaps" section header (renders early).
            # Wait for the gap-3 card content (#3) which only appears once all
            # cards have rendered — the most reliable end-of-render signal.
            wait_for_text(page, "Highest priority:", timeout_ms=240_000)
        except Exception:
            # Dump debug info before giving up
            dbg = OUT_DIR / "debug_post_click.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"  TIMEOUT. dumped {dbg.name} for inspection")
            print("  page text head:", page.inner_text("body")[:500])
            raise
        # Extra settle so all card layouts (Plotly, cards) finish painting.
        time.sleep(2.0)

        # ── Screenshot 2: Gap Filler top (roster summary + start of gaps) ────
        out = OUT_DIR / "02_gap_filler_results_top.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Screenshot 3: Top gap card (scroll so "Top 3 gaps" is at top) ────
        page.evaluate(
            "() => { const h = [...document.querySelectorAll('h3')]"
            ".find(e => e.innerText.includes('Top 3 gaps')); h && h.scrollIntoView({block: 'start'}); }"
        )
        time.sleep(0.5)
        out = OUT_DIR / "03_top_gap_card_with_candidates.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Screenshot 4: Wrap-up "highest priority" summary at the bottom ──
        page.evaluate(
            "() => { const main = document.querySelector('section[data-testid=\\\"stMain\\\"]')"
            " || document.scrollingElement; main.scrollTo(0, main.scrollHeight); }"
        )
        time.sleep(0.5)
        out = OUT_DIR / "04_contract_estimate_and_summary.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # ── Switch to Opponent Scouting tab and run a scouting report ───────
        page.get_by_role("tab", name="2. Opponent Scouting").click()
        wait_for_text(page, "Opponent Scouting", timeout_ms=10_000)
        time.sleep(1.0)
        # Scroll back to top so the inputs are visible in the screenshot
        page.evaluate(
            "() => { const main = document.querySelector('section[data-testid=\\\"stMain\\\"]')"
            " || document.scrollingElement; main.scrollTo(0, 0); }"
        )
        scout_btn = page.get_by_role("button", name="Generate scouting report")
        scout_btn.wait_for(state="visible", timeout=10_000)
        scout_btn.click()
        print("  clicked Generate scouting report; waiting for results...")
        try:
            wait_for_text(page, "How to attack", timeout_ms=60_000)
        except Exception:
            dbg = OUT_DIR / "debug_scouting.png"
            page.screenshot(path=str(dbg), full_page=True)
            print(f"  TIMEOUT. dumped {dbg.name}")
            raise
        time.sleep(1.5)
        # Capture the top of the scouting result (narrative + tables + top threats)
        page.evaluate(
            "() => { const main = document.querySelector('section[data-testid=\\\"stMain\\\"]')"
            " || document.scrollingElement; main.scrollTo(0, 0); }"
        )
        time.sleep(0.5)
        out = OUT_DIR / "05_opponent_scouting.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        # Also capture the bottom half of the scouting tab (weaknesses + strategy)
        page.evaluate(
            "() => { const main = document.querySelector('section[data-testid=\\\"stMain\\\"]')"
            " || document.scrollingElement; main.scrollTo(0, main.scrollHeight); }"
        )
        time.sleep(0.5)
        out = OUT_DIR / "06_opponent_scouting_strategy.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.name}")

        browser.close()


if __name__ == "__main__":
    main()

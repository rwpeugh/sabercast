"""Capture screenshots from the Roster Builder tab (SEA vs HOU default).

Outputs:
  docs/checkpoint3/07_roster_builder_top.png
  docs/checkpoint3/08_roster_builder_lineup_and_matchup.png
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT     = Path(__file__).resolve().parent.parent
OUT_DIR  = ROOT / "docs" / "checkpoint3"
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
        wait_for_text(page, "Sabercast")
        # Roster Builder is now the functional default tab; wait for the
        # build-button label rather than the old placeholder text.
        wait_for_text(page, "Build roster + matchup plan", timeout_ms=30_000)
        time.sleep(1.0)

        # Tab 1 = Roster Builder; it's the default tab so we don't need to click
        # but be explicit anyway for clarity
        page.get_by_role("tab", name="1. Roster Builder").click()
        wait_for_text(page, "Roster Builder")
        time.sleep(1.0)

        # Click "Build roster + matchup plan"
        btn = page.get_by_role("button", name="Build roster + matchup plan")
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        print("  clicked Build; waiting for results...")
        wait_for_text(page, "Risks to mitigate", timeout_ms=120_000)
        time.sleep(2.0)

        # Scroll to top for screenshot 1 (inputs + narrative + lineup top)
        page.evaluate(
            "() => { const main = document.querySelector('section[data-testid=\\\"stMain\\\"]')"
            " || document.scrollingElement; main.scrollTo(0, 0); }"
        )
        time.sleep(0.5)
        out1 = OUT_DIR / "07_roster_builder_top.png"
        page.screenshot(path=str(out1), full_page=False)
        print(f"saved {out1.name}")

        # Scroll to the matchup analysis section for screenshot 2
        page.evaluate(
            "() => { const h = [...document.querySelectorAll('h3')]"
            ".find(e => e.innerText.includes('Matchup analysis'));"
            " if (h) h.scrollIntoView({block: 'start'}); }"
        )
        time.sleep(0.5)
        out2 = OUT_DIR / "08_roster_builder_lineup_and_matchup.png"
        page.screenshot(path=str(out2), full_page=False)
        print(f"saved {out2.name}")

        browser.close()


if __name__ == "__main__":
    main()

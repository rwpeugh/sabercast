"""demo/verify_scouting_arsenal.py — Playwright check that the scouting tab
shows hitter spray columns and pitcher pitch-mix expanders after Entry 36."""
from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8501"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1700, "height": 2200},
                                  device_scale_factor=2)
        page.goto(URL, wait_until="load", timeout=60_000)
        time.sleep(6)
        page.get_by_role("tab", name="2. Opponent Scouting").click()
        time.sleep(1)
        page.get_by_role("button", name="Generate scouting report").click()
        page.wait_for_function(
            "() => document.body.innerText.includes('Top threats')",
            timeout=180_000,
        )
        time.sleep(3)

        # Confirm spray + arsenal expanders are present
        body_text = page.evaluate("() => document.body.innerText")
        for expected in ("GB%", "Pull%", "Pitch arsenal", "Usage %"):
            present = expected in body_text
            print(f"  {'OK ' if present else 'MISS'}  {expected!r} present={present}")

        out = OUT_DIR / "entry36_scouting_arsenal_full.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"  saved {out.name}")

        # Expand the first pitcher arsenal accordion and screenshot it specifically
        expanders = page.locator("[data-testid='stExpander']").all()
        print(f"  found {len(expanders)} expanders on page")
        if expanders:
            expanders[0].locator("summary, [role='button']").first.click()
            time.sleep(2)
            out2 = OUT_DIR / "entry36_scouting_arsenal_expanded.png"
            page.screenshot(path=str(out2), full_page=True)
            print(f"  saved {out2.name}")

        browser.close()


if __name__ == "__main__":
    main()

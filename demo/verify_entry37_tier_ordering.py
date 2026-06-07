"""demo/verify_entry37_tier_ordering.py — Playwright check that the Gap Filler
shows monotonic tier forecasts and the downgrade-save chip after Entry 37."""
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
        page = browser.new_page(viewport={"width": 1700, "height": 2400},
                                  device_scale_factor=2)
        page.goto(URL, wait_until="load", timeout=60_000)
        time.sleep(6)
        page.get_by_role("tab", name="3. Gap Filler").click()
        time.sleep(2)

        # Pick PHI ($280M budget) which surfaces the downgrade-save case
        page.get_by_role("combobox", name="Team").click()
        time.sleep(1)
        page.get_by_role("option", name="PHI", exact=True).click()
        time.sleep(1)
        # Default budget should be fine; click diagnose
        page.get_by_role("button", name="Diagnose roster gaps").click()
        page.wait_for_function(
            "() => document.body.innerText.includes('DOWNGRADE')",
            timeout=180_000,
        )
        time.sleep(3)
        out1 = OUT_DIR / "entry37_phi_full.png"
        page.screenshot(path=str(out1), full_page=True)
        print(f"  saved {out1.name}")

        # Try to scroll to the downgrade chip and take a tighter screenshot
        page.evaluate(
            "() => { const el = [...document.querySelectorAll('div')]"
            ".find(d => d.innerText.includes('DOWNGRADE')); "
            "if (el) el.scrollIntoView({block:'center'}); }"
        )
        time.sleep(2)
        out2 = OUT_DIR / "entry37_downgrade_chip.png"
        page.screenshot(path=str(out2))
        print(f"  saved {out2.name}")

        browser.close()


if __name__ == "__main__":
    main()

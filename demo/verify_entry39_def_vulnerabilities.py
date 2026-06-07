"""Playwright check that the Roster Builder defensive vulnerabilities panel
renders (LAD vs DET, Skubal probable) — Entry 39."""
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
        page.get_by_role("tab", name="1. Roster Builder").click()
        time.sleep(2)
        # Use defaults (SEA vs HOU). HOU 2024 has some weak positions too.
        page.get_by_role("button", name="Build roster + matchup plan").click()
        page.wait_for_function(
            "() => document.body.innerText.includes('Opponent defensive vulnerabilities')",
            timeout=180_000,
        )
        time.sleep(3)
        out = OUT_DIR / "entry39_def_vulnerabilities.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"  saved {out.name}")

        page.evaluate(
            "() => { const el = [...document.querySelectorAll('h3')]"
            ".find(d => d.innerText.includes('Opponent defensive vulnerabilities')); "
            "if (el) el.scrollIntoView({block:'start'}); }"
        )
        time.sleep(1)
        out2 = OUT_DIR / "entry39_def_vulnerabilities_zoom.png"
        page.screenshot(path=str(out2))
        print(f"  saved {out2.name}")
        browser.close()


if __name__ == "__main__":
    main()

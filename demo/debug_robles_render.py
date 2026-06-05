"""demo/debug_robles_render.py — inspect how Streamlit renders Víctor Robles.

The user reported a visible space between V and í in the Roster Builder
lineup table. Both Víctor Robles and Julio Rodríguez use the same Unicode
character (U+00ED, precomposed Latin small letter i with acute) in the
underlying data, so the issue is in the browser-side rendering, not the
data pipeline. This script drives the local Streamlit, captures the lineup
table screenshot at high zoom, and dumps the actual DOM text + bytes for
the affected row.
"""
from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT    = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL = "http://localhost:8501"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1800, "height": 1200},
                                  device_scale_factor=2)
        page.goto(URL, wait_until="load", timeout=60_000)
        time.sleep(8)
        page.get_by_role("tab", name="1. Roster Builder").click()
        time.sleep(2)
        page.get_by_role("button", name="Build roster + matchup plan").click()
        page.wait_for_function(
            "() => document.body.innerText.includes('Recommended starting lineup')",
            timeout=180_000,
        )
        time.sleep(4)

        # Pull the dataframe cells and inspect raw text
        cells = page.locator("[data-testid='stDataFrame'] [role='gridcell']").all()
        print(f"  found {len(cells)} dataframe cells")
        for i, cell in enumerate(cells):
            text = cell.text_content() or ""
            if "obles" in text.lower():
                inner_html = cell.inner_html()
                print(f"  cell {i}: text={text!r}")
                print(f"           bytes={text.encode('utf-8')!r}")
                print(f"           inner_html={inner_html!r}")
                # Computed style + bounding box can reveal kerning / spacing issues
                box = cell.bounding_box()
                print(f"           bounding_box={box}")
                attrs = cell.evaluate("e => Array.from(e.attributes).map(a => `${a.name}=${a.value}`).join('; ')")
                print(f"           attrs={attrs!r}")

        # Full lineup screenshot
        out = OUT_DIR / "debug_robles_lineup_full.png"
        page.evaluate(
            "() => { const h = [...document.querySelectorAll('h3')]"
            ".find(e => e.innerText.includes('Recommended starting lineup'));"
            " h && h.scrollIntoView({block: 'start'}); }"
        )
        time.sleep(1)
        page.screenshot(path=str(out), full_page=False)
        print(f"  saved {out.name}")
        browser.close()


if __name__ == "__main__":
    main()

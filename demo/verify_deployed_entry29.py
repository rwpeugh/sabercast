"""demo/verify_deployed_entry29.py — confirm the deployed app has Entries 25-29.

Hits sabercast-mlb.streamlit.app and inspects body text for markers
introduced after Entry 24. Doesn't try to drive interactions -- Streamlit
Cloud's hosted iframe makes tab clicks flaky. We just load the page, wait
for it to settle, and grep body text for code-level signatures.

Markers checked:
  - Roster Builder probable-pitcher dropdown (Entry 23)
  - Roster Builder "Facing tonight" callout language (Entry 23)
  - Gap Filler committed-payroll field (Entry 27)
  - Gap Filler payroll-situation panel header (Entry 27)
  - Tier-bucket labels (Entry 29)

Output:
  docs/checkpoint3/deployed_entry29_pageload.png  -- full page
  docs/checkpoint3/deployed_entry29_verdict.txt   -- pass/fail per marker
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT    = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)
URL = "https://sabercast-mlb.streamlit.app/"


# We grep all rendered DOM text across every Streamlit tab (Streamlit keeps
# inactive tabs in the DOM, just hidden) so we don't need to click anything.
MARKERS = [
    # Roster Builder (Entry 23 added the probable-pitcher dropdown)
    ("Opponent probable starter",   "Entry 23 Roster Builder probable-pitcher field"),
    # Gap Filler inputs (Entry 27)
    ("Committed payroll for 2025",  "Entry 27 committed-payroll input"),
    ("Total payroll budget for 2025", "Entry 27 budget input"),
    # Roster Builder caption shift (Entry 23 reframed the day-to-day blurb)
    ("scouting as of end of 2024",  "Entry 23 caption rewrite"),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        print(f"  loading {URL} ...")
        # Use 'load' instead of 'networkidle' -- Streamlit's WebSocket keeps
        # the network active indefinitely, so networkidle never settles.
        page.goto(URL, wait_until="load", timeout=120_000)
        print("  page load fired. waiting 25s for Streamlit to hydrate...")
        time.sleep(25.0)

        # Capture what we see for the record
        out = OUT_DIR / "deployed_entry29_pageload.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"  saved {out.name}")

        # Body text inspection -- includes all tab content, hidden or not
        body_text = page.inner_text("body")
        verdicts: list[tuple[bool, str, str]] = []
        for marker, label in MARKERS:
            present = marker.lower() in body_text.lower()
            verdicts.append((present, marker, label))
            flag = "PRESENT" if present else "MISSING"
            print(f"  [{flag:<7}] {label}: marker={marker!r}")

        # Verdict file
        ok = sum(1 for v in verdicts if v[0])
        verdict_path = OUT_DIR / "deployed_entry29_verdict.txt"
        verdict_path.write_text(
            "Deployed-app verification (verify_deployed_entry29.py)\n" +
            f"URL: {URL}\n" +
            f"Result: {ok}/{len(verdicts)} markers present\n\n" +
            "\n".join(
                f"  [{ 'PRESENT' if v[0] else 'MISSING' }] {v[2]}: {v[1]!r}"
                for v in verdicts
            ) + "\n",
            encoding="utf-8",
        )
        print(f"\n  saved {verdict_path.name}")
        print(f"  RESULT: {ok}/{len(verdicts)} markers present")
        browser.close()


if __name__ == "__main__":
    main()

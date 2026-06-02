"""demo/wait_for_redeploy.py — poll the deployed Streamlit Cloud app until the
Roster Builder tab no longer shows the 'In work / Planned inputs' placeholder.

Used to verify that a recent commit has been picked up by Streamlit Cloud
before re-running the demo recording. Each poll opens a fresh Playwright
session (no caching), so this is the truthful check.

Exits 0 when the placeholder is no longer visible (= new code deployed).
Exits 1 if the deadline (~5 minutes) is reached without the redeploy landing.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://sabercast-mlb.streamlit.app/"
POLL_INTERVAL_S = 25
MAX_WAIT_S = 360   # 6 minutes hard cap


def _check_once() -> bool:
    """Return True iff the Roster Builder tab shows the NEW (functional) UI.
    The old placeholder included 'Planned inputs' and 'Planned outputs' expanders;
    the new functional UI shows a 'Team' selectbox and a 'Build roster + matchup plan'
    button instead.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(URL, wait_until="networkidle", timeout=60_000)
            time.sleep(6)
            # Find the app frame
            frame = None
            for f in page.frames:
                try:
                    if f.locator("text=Sabercast").count() > 0:
                        frame = f
                        break
                except Exception:
                    continue
            if frame is None:
                return False
            try:
                frame.get_by_role("tab", name="1. Roster Builder").click()
                time.sleep(3)
            except Exception:
                return False
            # Old placeholder check: presence of 'Planned inputs' expander
            old_text_count = frame.locator("text=Planned inputs").count()
            # New functional check: presence of the Build button text
            new_text_count = frame.locator("text=Build roster + matchup plan").count()
            return new_text_count > 0 and old_text_count == 0
        finally:
            browser.close()


def main() -> None:
    start = time.time()
    attempt = 0
    while True:
        attempt += 1
        elapsed = int(time.time() - start)
        print(f"[{elapsed:4d}s] attempt {attempt} ...", flush=True)
        try:
            ok = _check_once()
        except Exception as e:                                          # noqa: BLE001
            print(f"          poll error: {type(e).__name__}: {e}", flush=True)
            ok = False
        if ok:
            print(f"[{int(time.time()-start):4d}s] NEW Roster Builder code is live. Exiting OK.",
                  flush=True)
            sys.exit(0)
        if time.time() - start > MAX_WAIT_S:
            print(f"[{int(time.time()-start):4d}s] TIMED OUT waiting for redeploy. "
                  f"Manual reboot may be needed (share.streamlit.io -> Sabercast -> Manage app -> Reboot).",
                  flush=True)
            sys.exit(1)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()

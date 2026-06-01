"""Verify the live Streamlit Cloud deployment by loading it in a real browser
and capturing two screenshots: the landing page (showing all 3 tabs and the URL
chrome from Streamlit Cloud), and the Gap Filler tab after a diagnosis.

Outputs:
  docs/checkpoint3/deployed_01_landing.png
  docs/checkpoint3/deployed_02_gap_filler_after_diagnose.png
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT     = Path(__file__).resolve().parent.parent
OUT_DIR  = ROOT / "docs" / "checkpoint3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://sabercast-mlb.streamlit.app/"


def _app_frame(page):
    """Streamlit Cloud iframes the actual app. Return the frame that has the
    'Sabercast' h1 in it."""
    for frame in page.frames:
        try:
            if frame.locator("text=Sabercast").count() > 0:
                return frame
        except Exception:
            continue
    return page.main_frame


def main() -> None:
    print(f"Loading {URL} ...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        page.goto(URL, wait_until="networkidle", timeout=120_000)
        print(f"  page title: {page.title()!r}")
        # Give Streamlit's iframe time to mount + the app to do its initial run
        time.sleep(8)

        out1 = OUT_DIR / "deployed_01_landing.png"
        page.screenshot(path=str(out1), full_page=False)
        print(f"  saved {out1.name}")

        # Switch to Gap Filler tab via the iframe and run a diagnosis
        frame = _app_frame(page)
        print(f"  app frame: {frame.url}")

        gap_tab = frame.get_by_role("tab", name="3. Gap Filler")
        gap_tab.click()
        time.sleep(1.5)

        diag_btn = frame.get_by_role("button", name="Diagnose roster gaps")
        diag_btn.wait_for(state="visible", timeout=10_000)
        diag_btn.click()
        print("  clicked Diagnose; waiting for results on the deployed app ...")

        # Wait for the "Top 3 gaps" heading inside the app frame. Cloud runs
        # are slower than local because of network latency + iframe RPC; allow
        # up to 8 minutes for the full ~12-call orchestration.
        out2 = OUT_DIR / "deployed_02_gap_filler_after_diagnose.png"
        try:
            frame.locator("h3:has-text('Top 3 gaps')").wait_for(timeout=480_000)
            time.sleep(3)
            page.screenshot(path=str(out2), full_page=False)
            print(f"  saved {out2.name}  (after full diagnose run)")
        except Exception as e:
            # Capture whatever state IS on screen so the user can diagnose
            page.screenshot(path=str(out2), full_page=False)
            print(f"  TIMED OUT waiting for 'Top 3 gaps'. Saved current state to {out2.name}.")
            print(f"  Diagnostic: {type(e).__name__}: {e}")
            print(f"  Check Streamlit Cloud Manage App → Logs to see why the diagnose call stalled.")

        browser.close()
        print("\n=== DEPLOYMENT VERIFIED ===")
        print(f"  URL:                  {URL}")
        print(f"  Landing screenshot:   {out1}")
        print(f"  Gap Filler screenshot:{out2}")


if __name__ == "__main__":
    main()

"""demo/verify_chc_cws_fix.py — confirm the shared-city bug fix is live.

Loads the deployed Streamlit Cloud app, selects CHC + MIL on the Roster
Builder tab, clicks Build, waits for results, and scans the rendered
content for the string "Vaughn". If Vaughn appears anywhere in the Cubs
output, the fix has NOT deployed (or never landed) and we exit 1.

This is a regression check for the bug user-reported on 2026-06-02 where
Andrew Vaughn (White Sox, AL) was being listed as a Cubs (NL) hitter
because both team abbreviations mapped to the bref city "Chicago".
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://sabercast-mlb.streamlit.app/"
MAX_WAIT_FOR_REDEPLOY_S = 240   # poll a few times if the build is still rolling


def _app_frame(page):
    for frame in page.frames:
        try:
            if frame.locator("text=Sabercast").count() > 0:
                return frame
        except Exception:
            continue
    return page.main_frame


def _run_once() -> tuple[bool, str]:
    """Returns (vaughn_present, page_text_snippet)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(URL, wait_until="networkidle", timeout=120_000)
            time.sleep(8)

            frame = _app_frame(page)

            # Click Roster Builder tab
            frame.get_by_role("tab", name="1. Roster Builder").click()
            time.sleep(3)

            # Set Team dropdown to CHC
            team_dd = frame.get_by_label("Team").first
            team_dd.click()
            time.sleep(1)
            page.keyboard.type("CHC")
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(2)

            # Set Opponent dropdown to MIL
            opp_dd = frame.get_by_label("Opponent").first
            opp_dd.click()
            time.sleep(1)
            page.keyboard.type("MIL")
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(2)

            # Click Build
            build_btn = frame.get_by_text("Build roster + matchup plan", exact=True).first
            build_btn.wait_for(state="visible", timeout=10_000)
            build_btn.click()

            # Wait for the lineup heading
            try:
                frame.locator("text=Recommended starting lineup").first.wait_for(timeout=180_000)
                time.sleep(2)
            except Exception:
                pass

            # Read all visible text in the iframe and look for Vaughn
            page_text = frame.locator("body").inner_text(timeout=10_000)
            vaughn_present = "Vaughn" in page_text
            # Capture a small relevant excerpt around the lineup area
            snippet = ""
            if "Recommended starting lineup" in page_text:
                start = page_text.find("Recommended starting lineup")
                snippet = page_text[start:start + 800]
            return vaughn_present, snippet
        finally:
            browser.close()


def main() -> None:
    start = time.time()
    attempt = 0
    while True:
        attempt += 1
        elapsed = int(time.time() - start)
        print(f"[{elapsed:4d}s] attempt {attempt}: hitting deployed app ...", flush=True)
        try:
            vaughn_present, snippet = _run_once()
        except Exception as e:                                          # noqa: BLE001
            print(f"          run failed: {type(e).__name__}: {e}", flush=True)
            vaughn_present = None
            snippet = ""

        if vaughn_present is False:
            print(f"\n[{int(time.time()-start):4d}s] PASS: Vaughn NOT present in CHC roster output.")
            if snippet:
                print(f"\nLineup excerpt (first 600 chars):\n{snippet[:600]}")
            sys.exit(0)
        if vaughn_present is True:
            elapsed = int(time.time() - start)
            if elapsed > MAX_WAIT_FOR_REDEPLOY_S:
                print(f"\n[{elapsed:4d}s] FAIL: 'Vaughn' still present after {elapsed}s. "
                      f"Streamlit Cloud may not have redeployed yet.")
                if snippet:
                    print(f"\nLineup excerpt:\n{snippet[:600]}")
                sys.exit(1)
            print(f"          'Vaughn' still in output, waiting for redeploy ...", flush=True)
        else:
            print(f"          (errored — retrying)", flush=True)

        if time.time() - start > MAX_WAIT_FOR_REDEPLOY_S:
            print(f"\n[{int(time.time()-start):4d}s] TIMED OUT.")
            sys.exit(1)
        time.sleep(30)


if __name__ == "__main__":
    main()

"""demo/record_demo_video.py — record a screencast of the deployed Sabercast app.

Drives the live Streamlit Cloud app through all three tabs with realistic
timing, captures the entire session as a single .webm video file.

Output: docs/demo/sabercast_demo.webm  (typically ~5-7 MB, 90-130s long)

Companion voiceover script (with timestamps) lives at:
    docs/demo/VOICEOVER_SCRIPT.md

Browsers play .webm natively. To convert to .mp4 for wider compatibility:
    ffmpeg -i sabercast_demo.webm -c:v libx264 -c:a aac sabercast_demo.mp4
(ffmpeg is not installed in the project environment — convert externally
if needed for portfolio purposes.)
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT      = Path(__file__).resolve().parent.parent
VIDEO_DIR = ROOT / "docs" / "demo"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
FINAL_OUT = VIDEO_DIR / "sabercast_demo.webm"

URL = sys.argv[1] if len(sys.argv) > 1 else "https://sabercast-mlb.streamlit.app/"

VIEWPORT = {"width": 1440, "height": 900}


def _app_frame(page):
    """Streamlit Cloud iframes the actual app. Return the frame whose URL
    matches the Streamlit app subdomain."""
    for frame in page.frames:
        try:
            if frame.locator("text=Sabercast").count() > 0:
                return frame
        except Exception:
            continue
    return page.main_frame


def _smooth_scroll(frame, target_y: int, steps: int = 6, pause: float = 0.25) -> None:
    """Scroll the iframe smoothly to a Y offset (in pixels) so the recording
    doesn't have abrupt jumps."""
    for i in range(1, steps + 1):
        frame.evaluate(f"window.scrollTo(0, {int(target_y * i / steps)})")
        time.sleep(pause)


def _scroll_top(frame) -> None:
    frame.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.4)


def main() -> None:
    print(f"Recording screencast of {URL} → {FINAL_OUT.name}")
    print("Total wall time expected: ~90-130 seconds.")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(VIDEO_DIR),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()

        # ── Segment 1: landing (~5s) ─────────────────────────────────────
        print("[ 0:00] Loading app + initial landing dwell")
        page.goto(URL, wait_until="networkidle", timeout=120_000)
        time.sleep(8)   # let Streamlit's iframe mount, app run its initial pass

        frame = _app_frame(page)

        # Linger on landing
        time.sleep(4)

        # ── Segment 2: Roster Builder (~30-40s) ──────────────────────────
        print("[ 0:13] Switching to Roster Builder tab")
        frame.get_by_role("tab", name="1. Roster Builder").click()
        time.sleep(3)   # let dropdowns render

        # Streamlit buttons are styled divs; text-content selector is more reliable
        # than aria role+name.
        try:
            build_btn = frame.get_by_text("Build roster + matchup plan", exact=True).first
            build_btn.wait_for(state="visible", timeout=10_000)
            print("[ 0:16] Clicking 'Build roster + matchup plan'")
            build_btn.click()
            time.sleep(2)
            print("[ 0:18] Waiting for Roster Builder to finish (one gpt-4o-mini call) ...")
            try:
                frame.locator("text=/Recommended lineup/i").first.wait_for(timeout=180_000)
                time.sleep(2)
            except Exception:
                print("  WARN: 'Recommended lineup' not found; continuing with whatever rendered")
        except Exception as e:
            print(f"  WARN: Roster Builder button not clickable: {type(e).__name__}: {e}")

        # Scroll through results
        _smooth_scroll(frame, 600, steps=6, pause=0.4)
        time.sleep(2)
        _smooth_scroll(frame, 1100, steps=4, pause=0.4)
        time.sleep(2)

        # ── Segment 3: Opponent Scouting (~25s) ──────────────────────────
        print("[ 0:55] Switching to Opponent Scouting tab")
        _scroll_top(frame)
        frame.get_by_role("tab", name="2. Opponent Scouting").click()
        time.sleep(3)

        try:
            scout_btn = frame.get_by_text("Generate scouting report", exact=True).first
            scout_btn.wait_for(state="visible", timeout=10_000)
            print("[ 0:58] Clicking 'Generate scouting report'")
            scout_btn.click()
            time.sleep(2)
            print("[ 1:00] Waiting for Scouting output (one gpt-4o call) ...")
            try:
                frame.locator("text=/Top threats|threats/i").first.wait_for(timeout=180_000)
                time.sleep(2)
            except Exception:
                print("  WARN: 'Top threats' not found; continuing")
        except Exception as e:
            print(f"  WARN: Scouting button not clickable: {type(e).__name__}: {e}")

        _smooth_scroll(frame, 500, steps=5, pause=0.4)
        time.sleep(2)
        _smooth_scroll(frame, 900, steps=4, pause=0.4)
        time.sleep(2)

        # ── Segment 4: Gap Filler (~30-40s) ──────────────────────────────
        print("[ 1:13] Switching to Gap Filler tab")
        _scroll_top(frame)
        frame.get_by_role("tab", name="3. Gap Filler").click()
        time.sleep(2)

        try:
            diag_btn = frame.get_by_role("button", name="Diagnose roster gaps")
            diag_btn.wait_for(state="visible", timeout=10_000)
            print("[ 1:15] Clicking Diagnose roster gaps")
            diag_btn.click()
            print("[ 1:16] Waiting for full Gap Filler orchestration (1 gpt-4o + 11 gpt-4o-mini calls in parallel) ...")
            try:
                frame.locator("h3:has-text('Top 3 gaps')").wait_for(timeout=300_000)
                time.sleep(2)
            except Exception:
                print("  WARN: 'Top 3 gaps' heading not found in 5 min; recording anyway")
        except Exception as e:
            print(f"  WARN: Diagnose button issue: {type(e).__name__}: {e}")

        # Scroll through the most important result sections
        _smooth_scroll(frame, 600, steps=6, pause=0.45)
        time.sleep(2)
        _smooth_scroll(frame, 1300, steps=5, pause=0.4)
        time.sleep(2)
        _smooth_scroll(frame, 2000, steps=5, pause=0.4)
        time.sleep(3)

        # Final dwell on results
        time.sleep(2)

        # ── Close: triggers Playwright to finalize the .webm ─────────────
        print("[end ] Closing context to finalize video file")
        page_video = page.video
        context.close()
        browser.close()

        # Playwright generates a hashed filename; move it to a predictable name
        generated = page_video.path() if page_video else None
        if generated and Path(generated).exists():
            shutil.move(generated, FINAL_OUT)
            print(f"\nFinal video: {FINAL_OUT}")
            size_mb = FINAL_OUT.stat().st_size / (1024 * 1024)
            print(f"Size: {size_mb:.1f} MB")
        else:
            # Fallback: pick the newest .webm in the directory
            webm_files = sorted(VIDEO_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
            if webm_files:
                webm_files[0].rename(FINAL_OUT)
                print(f"\nFinal video: {FINAL_OUT}")
                size_mb = FINAL_OUT.stat().st_size / (1024 * 1024)
                print(f"Size: {size_mb:.1f} MB")
            else:
                print("\nWARN: could not locate generated video file")

    print(f"\nVoiceover script: docs/demo/VOICEOVER_SCRIPT.md")
    print("To convert webm -> mp4 (ffmpeg required):")
    print(f"  ffmpeg -i {FINAL_OUT.name} -c:v libx264 -c:a aac sabercast_demo.mp4")


if __name__ == "__main__":
    main()

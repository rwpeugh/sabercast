"""demo/render_pitch_slide_png.py — render the same layout as
generate_pitch_slide.py to a PNG using matplotlib. Useful for embedding the
pitch slide in the README or sharing without opening PowerPoint.

Output: docs/demo/Sabercast_Pitch_Slide.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt


ROOT     = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "demo" / "Sabercast_Pitch_Slide.png"

# Color palette mirrored from generate_pitch_slide.py
NAVY    = "#102A55"
SLATE   = "#334455"
GRAY    = "#667080"
LIGHT   = "#F0F2F5"
ACCENT  = "#3A82CD"
GOOD    = "#2E863E"
NEUTRAL = "#C08C00"


def _text(ax, x, y, txt, *, size=12, weight="normal", color=SLATE,
          ha="left", va="top", style="normal"):
    ax.text(x, y, txt, fontsize=size, weight=weight, color=color,
            ha=ha, va=va, transform=ax.transAxes, fontstyle=style,
            family="DejaVu Sans")


def _hline(ax, x, y, w, color, lw=2):
    ax.add_patch(patches.Rectangle((x, y), w, 0.004, color=color,
                                    transform=ax.transAxes, clip_on=False))


def build_png() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 16:9 figure at 1920x1080 effective resolution
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    # Convert PPT inch coords (13.333 x 7.5) into [0,1] using the same proportions.
    # We'll work in normalized coords directly. PPT inch x / 13.333 -> 0..1
    PW, PH = 13.333, 7.5
    def fx(inches): return inches / PW
    def fy(inches): return 1 - (inches / PH)   # invert (matplotlib y from bottom)
    def fw(inches): return inches / PW
    def fh(inches): return inches / PH

    # ── Title ─────────────────────────────────────────────────────────────
    _text(ax, fx(0.5), fy(0.35), "Sabercast",
          size=44, weight="bold", color=NAVY)
    _text(ax, fx(0.5), fy(1.0),
          "LLM-powered MLB front-office intelligence — built for small / mid-market clubs",
          size=14, color=SLATE)
    _text(ax, fx(0.5), fy(1.30),
          "that need analyst leverage without a 20-person R&D shop.",
          size=14, color=SLATE)
    _hline(ax, fx(0.5), fy(1.65) - 0.004, fw(12.333), ACCENT)

    # ── Three columns ─────────────────────────────────────────────────────
    col_w = 4.05
    col_y = 1.95
    col_label_size = 11

    # LEFT — WHAT
    cx = 0.5
    _hline(ax, fx(cx), fy(col_y), fw(col_w), ACCENT, lw=3)
    _text(ax, fx(cx), fy(col_y + 0.20),
          "WHAT — three front-office workflows",
          size=col_label_size, weight="bold", color=ACCENT)
    left_text = (
        "1.  Roster Builder\n"
        "     Day-to-day lineup construction vs. a chosen opponent.\n"
        "     One gpt-4o call → 9-slot lineup + matchup notes.\n"
        "\n"
        "2.  Opponent Scouting\n"
        "     Narrative + top-3 threats + exploitable weaknesses\n"
        "     + pitching / hitting strategy.\n"
        "\n"
        "3.  Gap Filler\n"
        "     Top-3 roster gaps + position-matched candidate targets\n"
        "     from a ChromaDB vectorstore + contract-cost forecasts.\n"
        "     12 LLM calls running in parallel, ~13s end-to-end."
    )
    _text(ax, fx(cx), fy(col_y + 0.55), left_text, size=11, color=SLATE)

    # CENTER — HOW
    cx = 0.5 + col_w + 0.4
    _hline(ax, fx(cx), fy(col_y), fw(col_w), ACCENT, lw=3)
    _text(ax, fx(cx), fy(col_y + 0.20),
          "HOW — architecture",
          size=col_label_size, weight="bold", color=ACCENT)
    center_text = (
        "Data ingest\n"
        "    pybaseball · Spotrac · Statcast OAA + pop time\n"
        "\n"
        "LLM routing (cost-disciplined)\n"
        "    gpt-4o                  — narrative reasoning\n"
        "    gpt-4o-mini             — structured JSON output\n"
        "    text-embedding-3-small  — RAG retrieval\n"
        "    Qwen 2.5 7B + LoRA      — fine-tune (eval only)\n"
        "\n"
        "Storage\n"
        "    ChromaDB persistent — 999 player profiles + 15 glossary\n"
        "    1,254 contracts, no-look-ahead at every retrieval point\n"
        "\n"
        "Build economics\n"
        "    9-day end-to-end build · ~$47 total platform spend\n"
        "    Three vendor constraints absorbed mid-build"
    )
    _text(ax, fx(cx), fy(col_y + 0.55), center_text, size=10, color=SLATE,
          ha="left")

    # RIGHT — RESULTS
    cx = 0.5 + (col_w + 0.4) * 2
    _hline(ax, fx(cx), fy(col_y), fw(col_w), ACCENT, lw=3)
    _text(ax, fx(cx), fy(col_y + 0.20),
          "RESULTS — 9 pre-registered tests, 2 significant",
          size=col_label_size, weight="bold", color=ACCENT)

    by = col_y + 0.55
    _text(ax, fx(cx), fy(by), "RAG retrieval validated",
          size=13, weight="bold", color=GOOD)
    _text(ax, fx(cx), fy(by + 0.30),
          "+70 percentage-point accuracy gain on 20-question\n"
          "held-out set  ·  McNemar exact p = 0.0005",
          size=11, color=SLATE)

    _text(ax, fx(cx), fy(by + 0.95), "Position-level diagnostic validated",
          size=13, weight="bold", color=GOOD)
    _text(ax, fx(cx), fy(by + 1.25),
          "Flagged top-1 position underperforms next year\n"
          "59.9% overall (p=0.012)  ·  74.2% at 2B (p=0.011)",
          size=11, color=SLATE)

    _text(ax, fx(cx), fy(by + 1.90), "Honest null reported",
          size=13, weight="bold", color=NEUTRAL)
    _text(ax, fx(cx), fy(by + 2.20),
          "Gap_score does NOT predict next-year wins —\n"
          "loses to last-year-wins autocorrelation by ~5×.\n"
          "Five independent tests confirm. Reported plainly,\n"
          "not dressed up.",
          size=11, color=SLATE)

    _hline(ax, fx(cx), fy(by + 3.25) - 0.004, fw(col_w), NAVY, lw=2)
    _text(ax, fx(cx), fy(by + 3.36),
          "Sabercast is a diagnostic + retrieval tool,",
          size=12, weight="bold", color=NAVY)
    _text(ax, fx(cx), fy(by + 3.60),
          "NOT a wins forecaster.",
          size=12, weight="bold", color=NAVY)

    # ── Footer ────────────────────────────────────────────────────────────
    _hline(ax, fx(0.5), fy(6.7), fw(12.333), ACCENT, lw=2)
    _text(ax, fx(0.5), fy(6.85),
          "Live  ·  sabercast-mlb.streamlit.app",
          size=12, weight="bold", color=NAVY)
    _text(ax, fx(0.5 + 12.333), fy(6.85),
          "Source · github.com/rwpeugh/sabercast",
          size=12, weight="bold", color=NAVY, ha="right")
    _text(ax, fx(0.5), fy(7.18),
          "MKTG 569 · Building Business Applications of LLMs and Generative Models · Spring 2026",
          size=9, color=GRAY)

    plt.tight_layout(pad=0)
    plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"saved {OUT_PATH}")
    print(f"size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build_png()

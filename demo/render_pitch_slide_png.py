"""demo/render_pitch_slide_png.py — render the Sabercast pitch slide to PNG.

This is the image-rich version of the slide: title + hero stat band +
product screenshot + concise tech column + vendor-logo footer. The same
layout is mirrored in ``generate_pitch_slide.py`` for the PPTX output.

Output: docs/demo/Sabercast_Pitch_Slide.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from PIL import Image
import numpy as np


ROOT     = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "demo" / "Sabercast_Pitch_Slide.png"

LOGOS    = ROOT / "docs" / "demo" / "logos"
SHOTS    = ROOT / "docs" / "checkpoint3"

# Colour palette
NAVY    = "#102A55"
SLATE   = "#334455"
GRAY    = "#667080"
LIGHT   = "#F0F2F5"
CREAM   = "#FAFBFC"
ACCENT  = "#3A82CD"
GOOD    = "#2E863E"
GOOD_BG = "#E8F4EA"
NEUTRAL = "#C08C00"
NEUT_BG = "#FBF3DC"

# PPT slide is 13.333" x 7.5"; matplotlib axes are normalised [0,1].
PW, PH = 13.333, 7.5


def fx(inches: float) -> float:
    return inches / PW


def fy(inches: float) -> float:
    """Convert top-down inch coord to matplotlib bottom-up [0,1]."""
    return 1 - (inches / PH)


def fw(inches: float) -> float:
    return inches / PW


def fh(inches: float) -> float:
    return inches / PH


# ─────────────────────────────────────────────────────────────────────────
# Drawing helpers
# ─────────────────────────────────────────────────────────────────────────

def _text(ax, x, y, txt, *, size=12, weight="normal", color=SLATE,
          ha="left", va="top", style="normal"):
    ax.text(x, y, txt, fontsize=size, weight=weight, color=color,
            ha=ha, va=va, transform=ax.transAxes, fontstyle=style,
            family="DejaVu Sans")


def _hline(ax, x_in, y_in, w_in, color, lw=2):
    ax.add_patch(patches.Rectangle((fx(x_in), fy(y_in)), fw(w_in), 0.004,
                                    color=color, transform=ax.transAxes,
                                    clip_on=False))


def _rect(ax, x_in, y_in, w_in, h_in, *, color, alpha=1.0, zorder=2,
          round_pad=0.0):
    """Filled rectangle. If round_pad > 0, draws a rounded box."""
    x = fx(x_in)
    y = fy(y_in + h_in)
    w = fw(w_in)
    h = fh(h_in)
    if round_pad > 0:
        box = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={round_pad}",
                              linewidth=0, facecolor=color, alpha=alpha, zorder=zorder,
                              transform=ax.transAxes)
        ax.add_patch(box)
    else:
        ax.add_patch(patches.Rectangle((x, y), w, h, facecolor=color, edgecolor="none",
                                        alpha=alpha, zorder=zorder, transform=ax.transAxes))


def _border(ax, x_in, y_in, w_in, h_in, *, color=ACCENT, lw=1.2, zorder=3,
            round_pad=0.0):
    x = fx(x_in)
    y = fy(y_in + h_in)
    w = fw(w_in)
    h = fh(h_in)
    if round_pad > 0:
        box = FancyBboxPatch((x, y), w, h,
                              boxstyle=f"round,pad=0,rounding_size={round_pad}",
                              linewidth=lw, edgecolor=color, facecolor="none",
                              zorder=zorder, transform=ax.transAxes)
        ax.add_patch(box)
    else:
        ax.add_patch(patches.Rectangle((x, y), w, h, facecolor="none", edgecolor=color,
                                        linewidth=lw, zorder=zorder, transform=ax.transAxes))


def _image(ax, path: Path, x_in: float, y_in: float, w_in: float, h_in: float,
           *, alpha=1.0, zorder=10, preserve_aspect=True,
           crop_box: tuple | None = None):
    """Place an image at (x_in, y_in) with width/height in inches.

    If ``preserve_aspect`` is True, the image is centered inside the (w, h)
    slot at its true aspect ratio.

    ``crop_box`` is an optional (left_frac, top_frac, right_frac, bottom_frac)
    tuple in [0,1] to crop the source image before placement.
    """
    if not path.exists():
        print(f"  warn: missing image {path}")
        return
    img = Image.open(path).convert("RGBA")
    if crop_box is not None:
        l, t, r, b = crop_box
        W, H = img.size
        img = img.crop((int(W*l), int(H*t), int(W*r), int(H*b)))
    img_arr = np.asarray(img)
    ih, iw = img_arr.shape[:2]
    img_aspect = iw / ih

    if preserve_aspect:
        slot_aspect = w_in / h_in
        if img_aspect > slot_aspect:
            actual_w = w_in
            actual_h = w_in / img_aspect
        else:
            actual_h = h_in
            actual_w = h_in * img_aspect
        cx = x_in + (w_in - actual_w) / 2
        cy = y_in + (h_in - actual_h) / 2
    else:
        actual_w = w_in
        actual_h = h_in
        cx = x_in
        cy = y_in

    extent = [fx(cx), fx(cx + actual_w), fy(cy + actual_h), fy(cy)]
    ax.imshow(img_arr, extent=extent, alpha=alpha, zorder=zorder,
              aspect="auto", interpolation="bilinear")


# ─────────────────────────────────────────────────────────────────────────
# Component blocks
# ─────────────────────────────────────────────────────────────────────────

def _stat_card(ax, x_in: float, y_in: float, w_in: float, h_in: float,
               headline: str, label: str, detail: str, *, accent=GOOD,
               bg=GOOD_BG):
    """One big-number stat card. Filled rounded panel + headline + sublabel."""
    _rect(ax, x_in, y_in, w_in, h_in, color=bg, alpha=0.55, zorder=2,
          round_pad=0.015)
    _border(ax, x_in, y_in, w_in, h_in, color=accent, lw=1.0, zorder=3,
            round_pad=0.015)
    # Big headline number
    _text(ax, fx(x_in + w_in/2), fy(y_in + 0.35), headline,
          size=32, weight="bold", color=accent, ha="center", va="center")
    # Label
    _text(ax, fx(x_in + w_in/2), fy(y_in + 0.78), label,
          size=10, weight="bold", color=SLATE, ha="center", va="center")
    # p-value / detail
    _text(ax, fx(x_in + w_in/2), fy(y_in + 1.05), detail,
          size=8.5, color=GRAY, ha="center", va="center", style="italic")


def _logo_strip(ax, y_in: float, logo_h: float = 0.55):
    """Powered-by row: 5 logos centered with a label prefix.

    ``y_in`` is the vertical center of the logo band.
    ``logo_h`` is the slot height in inches. Logos preserve their aspect ratio
    inside their slot, so smaller logo_h = shorter logos.
    """
    # Logo files + nominal widths (inches in PPT space). We let preserve_aspect
    # do the math so we just need rough slot sizes.
    items = [
        ("openai.png.png",           0.80),
        ("together_ai.png.png",      0.80),
        ("chromadb.png",             0.65),
        ("streamlit.png.png",        0.65),
        ("Baseball_Reference_Logo.svg.png", 1.30),
    ]
    label_w = 1.15
    gap     = 0.40
    total_w = label_w + sum(w for _, w in items) + gap * len(items)
    start_x = (PW - total_w) / 2

    # Label — vertically centered on y_in
    _text(ax, fx(start_x + label_w * 0.5), fy(y_in + logo_h / 2),
          "Powered by", size=11, weight="bold", color=NAVY,
          ha="center", va="center")

    # Logos — slot top is y_in, slot height is logo_h
    x_cursor = start_x + label_w + gap
    for fname, w in items:
        _image(ax, LOGOS / fname, x_cursor, y_in, w, logo_h,
               preserve_aspect=True, zorder=12)
        x_cursor += w + gap


# ─────────────────────────────────────────────────────────────────────────
# Main slide builder
# ─────────────────────────────────────────────────────────────────────────

def build_png() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(CREAM)
    fig.patch.set_facecolor(CREAM)

    # ─── BACKGROUND: subtle diamond watermark, upper-right ─────────────
    _image(ax, LOGOS / "baseball_diamond.png",
           x_in=10.0, y_in=0.15, w_in=3.1, h_in=3.1,
           preserve_aspect=True, alpha=0.07, zorder=1)

    # ─── LEFT EDGE: vertical baseball-seam strand ──────────────────────
    _image(ax, LOGOS / "seam_strand.png",
           x_in=0.10, y_in=0.20, w_in=0.40, h_in=7.10,
           preserve_aspect=False, alpha=0.90, zorder=4)

    # ─── TITLE BLOCK ────────────────────────────────────────────────────
    _text(ax, fx(0.75), fy(0.45), "Sabercast",
          size=46, weight="bold", color=NAVY)
    _text(ax, fx(0.75), fy(1.10),
          "From roster gaps to ranked free-agent targets — in 13 seconds.",
          size=15, weight="bold", color=SLATE)
    _text(ax, fx(0.75), fy(1.40),
          "Plus lineup planning and series scouting. Built for small / mid-market "
          "MLB front offices needing analyst leverage without a 20-person R&D shop.",
          size=11.5, color=GRAY, style="italic")
    _hline(ax, 0.75, 1.78, 11.85, ACCENT, lw=2.5)

    # ─── HERO STAT BAND (4 cards) ───────────────────────────────────────
    cards_y = 1.95
    cards_h = 1.15
    band_x  = 0.75
    band_w  = 11.85
    gap     = 0.20
    card_w  = (band_w - 3 * gap) / 4
    cards = [
        ("13 sec", "Gap diagnosis to targets", "12 LLM calls parallelized",   GOOD, GOOD_BG),
        ("+70pp",  "RAG accuracy lift",        "20 Qs · McNemar p=0.0005",     GOOD, GOOD_BG),
        ("3.1×",   "Precision@10 lift",        "n=43 · p<0.0001 · finds signings", GOOD, GOOD_BG),
        ("59.9%",  "Position-gap hit rate",    "p=0.012 · 2B 74% (p=0.011)",   GOOD, GOOD_BG),
    ]
    for i, (head, label, detail, accent, bg) in enumerate(cards):
        x = band_x + i * (card_w + gap)
        _stat_card(ax, x, cards_y, card_w, cards_h, head, label, detail,
                   accent=accent, bg=bg)

    # ─── MAIN BODY: screenshot (LEFT) + tech column (RIGHT) ─────────────
    body_y     = 3.35
    body_h     = 2.45
    screen_x   = 0.75
    screen_w   = 7.45
    techcol_x  = 8.45
    techcol_w  = 4.15

    # Frame around the screenshot, then the screenshot itself.
    _rect(ax, screen_x - 0.04, body_y - 0.04, screen_w + 0.08, body_h + 0.08,
          color="white", alpha=1.0, zorder=5, round_pad=0.010)
    _border(ax, screen_x - 0.04, body_y - 0.04, screen_w + 0.08, body_h + 0.08,
            color=ACCENT, lw=1.0, zorder=6, round_pad=0.010)

    # Crop the screenshot to drop the empty left "About" sidebar (~22%) and the
    # very bottom rows (~5%) so the gap card + recommended targets dominate.
    _image(ax, SHOTS / "03_top_gap_card_with_candidates.png",
           x_in=screen_x, y_in=body_y, w_in=screen_w, h_in=body_h,
           preserve_aspect=True, zorder=7,
           crop_box=(0.21, 0.03, 1.00, 0.78))
    _text(ax, fx(screen_x + 0.05), fy(body_y + body_h + 0.30),
          "Position gap diagnosed  ·  3 free-agent targets ranked  ·  3 pricing comparables",
          size=9, color=GRAY, style="italic")

    # ─── RIGHT COLUMN: three short blocks ──────────────────────────────
    col_top = body_y + 0.05
    # Block 1 — three GM-office jobs (outcome-framed, not feature-framed)
    _text(ax, fx(techcol_x), fy(col_top),
          "THREE GM-OFFICE JOBS", size=10.5, weight="bold", color=ACCENT)
    _text(ax, fx(techcol_x), fy(col_top + 0.25),
          "• Plan tonight's lineup vs. the opponent",
          size=9.5, color=SLATE)
    _text(ax, fx(techcol_x), fy(col_top + 0.46),
          "• Scout the team you're facing",
          size=9.5, color=SLATE)
    _text(ax, fx(techcol_x), fy(col_top + 0.67),
          "• Diagnose roster gaps + rank FA targets",
          size=9.5, color=SLATE)

    # Block 2 — data + LLM stack
    _text(ax, fx(techcol_x), fy(col_top + 1.00),
          "DATA + LLM STACK", size=10.5, weight="bold", color=ACCENT)
    _text(ax, fx(techcol_x), fy(col_top + 1.25),
          "pybaseball · Spotrac · Statcast",
          size=9.5, color=SLATE)
    _text(ax, fx(techcol_x), fy(col_top + 1.46),
          "gpt-4o + 4o-mini · text-embed-3",
          size=9.5, color=SLATE)
    _text(ax, fx(techcol_x), fy(col_top + 1.67),
          "ChromaDB RAG (999 players)",
          size=9.5, color=SLATE)

    # Block 3 — build economics
    _text(ax, fx(techcol_x), fy(col_top + 2.00),
          "BUILD ECONOMICS", size=10.5, weight="bold", color=ACCENT)
    _text(ax, fx(techcol_x), fy(col_top + 2.25),
          "9-day build  ·  ~$47 platform spend",
          size=9.5, color=SLATE)

    # ─── HONEST-FRAMING LINE ───────────────────────────────────────────
    framing_y = 6.15
    _hline(ax, 0.75, framing_y, 11.85, NAVY, lw=1.5)
    _text(ax, fx(0.75), fy(framing_y + 0.22),
          "Decision-support tool — not a wins forecaster.",
          size=12, weight="bold", color=NAVY)
    _text(ax, fx(12.60), fy(framing_y + 0.22),
          "10 pre-registered tests  ·  4 significant  ·  5 honest nulls reported",
          size=10, color=GRAY, ha="right", style="italic")

    # ─── FOOTER: Powered-by logo strip (own row) ──────────────────────
    _logo_strip(ax, y_in=6.70, logo_h=0.40)

    # ─── URL strip (own row at the very bottom) ───────────────────────
    url_y = 7.25
    _hline(ax, 0.75, url_y - 0.10, 11.85, GRAY, lw=0.6)
    _text(ax, fx(0.75), fy(url_y),
          "Try the live app  ·  sabercast-mlb.streamlit.app",
          size=10, weight="bold", color=NAVY, va="center")
    _text(ax, fx(PW / 2), fy(url_y),
          "MKTG 569  ·  Spring 2026",
          size=9, color=GRAY, ha="center", va="center", style="italic")
    _text(ax, fx(12.60), fy(url_y),
          "github.com/rwpeugh/sabercast",
          size=10, weight="bold", color=NAVY, ha="right", va="center")

    plt.tight_layout(pad=0)
    plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight", facecolor=CREAM)
    plt.close()
    print(f"saved {OUT_PATH}")
    print(f"size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build_png()

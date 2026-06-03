"""demo/generate_pitch_slide.py — produce a one-slide pitch deck for Sabercast.

Output: docs/demo/Sabercast_Pitch_Slide.pptx

The slide is a single 16:9 PowerPoint slide laying out the project's
one-line value proposition + three-column structure (What / How / Results).
Editable in PowerPoint, Keynote, Google Slides, LibreOffice, etc.

To export a PNG for sharing:
    Open the PPTX -> File -> Export -> PNG/Image (PowerPoint or Keynote)
    Or use libreoffice --headless --convert-to png Sabercast_Pitch_Slide.pptx
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


ROOT     = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "demo" / "Sabercast_Pitch_Slide.pptx"


# Color palette — calm, defensible, low-key (a pitch slide, not a marketing ad)
NAVY      = RGBColor(0x10, 0x2A, 0x55)
SLATE     = RGBColor(0x33, 0x44, 0x55)
GRAY      = RGBColor(0x66, 0x70, 0x80)
LIGHT     = RGBColor(0xF0, 0xF2, 0xF5)
ACCENT    = RGBColor(0x3A, 0x82, 0xCD)   # blue
GOOD      = RGBColor(0x2E, 0x86, 0x3E)   # green for significant findings
NEUTRAL   = RGBColor(0xC0, 0x8C, 0x00)   # amber for honest nulls
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)


def _add_text(slide, x, y, w, h, text: str, *,
              size: int = 14, bold: bool = False, color: RGBColor = SLATE,
              align: PP_ALIGN = PP_ALIGN.LEFT, font: str = "Calibri") -> None:
    """Add a left-aligned text frame. text may contain \\n for line breaks."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color


def _add_box(slide, x, y, w, h, fill: RGBColor, line: RGBColor | None = None) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.5)
    shape.shadow.inherit = False


def _add_column_header(slide, x, y, w, label: str, accent: RGBColor) -> None:
    # Thin colored bar
    _add_box(slide, x, y, w, 0.06, accent)
    _add_text(slide, x, y + 0.08, w, 0.30, label,
              size=11, bold=True, color=accent, font="Calibri")


def build_slide() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width  = Inches(13.333)   # 16:9 widescreen
    prs.slide_height = Inches(7.5)

    slide = prs.slides.add_slide(prs.slide_layouts[6])   # blank

    # ── Top band: title + tagline ────────────────────────────────────────
    _add_text(slide, 0.5, 0.35, 12.5, 0.65,
              "Sabercast",
              size=42, bold=True, color=NAVY)
    _add_text(slide, 0.5, 1.0, 12.5, 0.5,
              "LLM-powered MLB front-office intelligence — built for small / mid-market clubs that need analyst leverage without a 20-person R&D shop.",
              size=14, color=SLATE)

    # Divider line
    _add_box(slide, 0.5, 1.65, 12.333, 0.025, ACCENT)

    # ── Three columns ────────────────────────────────────────────────────
    col_w = 4.05
    col_y = 1.95
    col_h = 4.30

    # LEFT — What
    cx = 0.5
    _add_column_header(slide, cx, col_y, col_w, "WHAT — three front-office workflows", ACCENT)
    _add_text(slide, cx, col_y + 0.55, col_w, col_h - 0.55,
              "1.  Roster Builder\n"
              "     Day-to-day lineup construction vs. a chosen opponent.\n"
              "     One gpt-4o call → 9-slot lineup + matchup notes.\n"
              "\n"
              "2.  Opponent Scouting\n"
              "     Narrative summary + top-3 threats + exploitable\n"
              "     weaknesses + pitching/hitting strategy.\n"
              "\n"
              "3.  Gap Filler\n"
              "     Top-3 roster gaps + position-matched candidate targets\n"
              "     from a ChromaDB vectorstore + contract-cost forecasts.\n"
              "     12 LLM calls running in parallel, ~13s end-to-end.",
              size=12, color=SLATE)

    # CENTER — How (Architecture)
    cx = col_w + 0.5 + 0.4
    _add_column_header(slide, cx, col_y, col_w, "HOW — architecture", ACCENT)
    _add_text(slide, cx, col_y + 0.55, col_w, col_h - 0.55,
              "Data ingest\n"
              "    pybaseball · Spotrac · Statcast OAA + pop time\n"
              "\n"
              "LLM routing (cost-disciplined)\n"
              "    gpt-4o            — narrative reasoning\n"
              "    gpt-4o-mini       — structured JSON output\n"
              "    text-embedding-3-small — RAG retrieval\n"
              "    Qwen 2.5 7B + LoRA  — fine-tune (eval only)\n"
              "\n"
              "Storage\n"
              "    ChromaDB persistent — 999 player profiles + 15 glossary entries\n"
              "    1,254 contracts, no-look-ahead at every retrieval point\n"
              "\n"
              "Build economics\n"
              "    9-day end-to-end build · ~$47 total platform spend\n"
              "    Three vendor constraints absorbed mid-build",
              size=11, color=SLATE)

    # RIGHT — Results
    cx = (col_w + 0.5 + 0.4) + col_w + 0.4
    _add_column_header(slide, cx, col_y, col_w, "RESULTS — 9 pre-registered tests, 2 significant", ACCENT)

    # Result blocks
    block_y = col_y + 0.55
    _add_text(slide, cx, block_y, col_w, 0.35,
              "RAG retrieval validated",
              size=13, bold=True, color=GOOD)
    _add_text(slide, cx, block_y + 0.30, col_w, 0.55,
              "+70 percentage-point accuracy gain on 20-question\n"
              "held-out set  ·  McNemar exact p = 0.0005",
              size=11.5, color=SLATE)

    _add_text(slide, cx, block_y + 0.95, col_w, 0.35,
              "Position-level diagnostic validated",
              size=13, bold=True, color=GOOD)
    _add_text(slide, cx, block_y + 1.25, col_w, 0.55,
              "Flagged top-1 position underperforms next year\n"
              "59.9% overall (p=0.012)  ·  74.2% at 2B (p=0.011)",
              size=11.5, color=SLATE)

    _add_text(slide, cx, block_y + 1.90, col_w, 0.35,
              "Honest null reported",
              size=13, bold=True, color=NEUTRAL)
    _add_text(slide, cx, block_y + 2.20, col_w, 0.85,
              "Gap_score does NOT predict next-year wins —\n"
              "loses to last-year-wins autocorrelation by ~5×.\n"
              "Five independent tests confirm. Reported plainly,\n"
              "not dressed up.",
              size=11.5, color=SLATE)

    # Bottom: takeaway
    _add_box(slide, cx, block_y + 3.20, col_w, 0.05, NAVY)
    _add_text(slide, cx, block_y + 3.32, col_w, 0.40,
              "Sabercast is a diagnostic + retrieval tool,\n"
              "NOT a wins forecaster.",
              size=12, bold=True, color=NAVY)

    # ── Bottom band: footer ──────────────────────────────────────────────
    _add_box(slide, 0.5, 6.7, 12.333, 0.025, ACCENT)
    _add_text(slide, 0.5, 6.78, 6.0, 0.30,
              "Live  ·  sabercast-mlb.streamlit.app",
              size=12, bold=True, color=NAVY)
    _add_text(slide, 6.5, 6.78, 6.333, 0.30,
              "Source · github.com/rwpeugh/sabercast",
              size=12, bold=True, color=NAVY, align=PP_ALIGN.RIGHT)
    _add_text(slide, 0.5, 7.10, 12.333, 0.25,
              "MKTG 569 · Building Business Applications of LLMs and Generative Models · Spring 2026",
              size=9, color=GRAY)

    prs.save(str(OUT_PATH))
    print(f"saved {OUT_PATH}")
    print(f"size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build_slide()

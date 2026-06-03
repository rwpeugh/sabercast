"""Render docs/demo/DEMO_PREP.md as a Word doc.

Output: docs/demo/Sabercast_Demo_Prep.docx

Re-uses the markdown -> docx renderer from generate_build_log_docx so all
formatting (headings, tables, blockquotes, code, bold, lists, horizontal
rules) is handled consistently.
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))

from generate_build_log_docx import render_md_to_docx   # noqa: E402


MD_PATH  = ROOT / "docs" / "demo" / "DEMO_PREP.md"
OUT_PATH = ROOT / "docs" / "demo" / "Sabercast_Demo_Prep.docx"


def main() -> None:
    if not MD_PATH.exists():
        raise SystemExit(f"Demo prep markdown not found at {MD_PATH}")
    md_text = MD_PATH.read_text(encoding="utf-8")

    doc = Document()
    for section in doc.sections:
        section.page_width    = Inches(8.5)
        section.page_height   = Inches(11)
        section.top_margin    = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin   = Inches(1.0)
        section.right_margin  = Inches(1.0)

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)

    render_md_to_docx(md_text, doc)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_PATH))
    print(f"saved {OUT_PATH}")
    print(f"size: {OUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

"""demo/prep_pitch_assets.py — one-time pre-processing of the logo folder.

* Convert ChromaDB icon (.ico) -> clean PNG with the largest embedded size.
* Crop the baseball-seams stock image down to ONLY the leftmost vertical
  strand. The source image has a "pngtree" watermark over the curved seams
  on the right side; the vertical strand on the left is clean and works as
  a top-edge accent on the pitch slide.
* Re-encode the baseball-diamond watermark as PNG. The downloaded file is
  named ``.jpg`` but actually contains WEBP-encoded bytes — python-pptx
  rejects WEBP, so we transcode to a clean PNG with alpha.

Output:
  docs/demo/logos/chromadb.png             — converted from .ico
  docs/demo/logos/seam_strand.png          — cropped vertical strand
  docs/demo/logos/baseball_diamond.png     — transcoded watermark
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT       = Path(__file__).resolve().parent.parent
LOGOS_DIR  = ROOT / "docs" / "demo" / "logos"


def convert_chromadb_ico() -> None:
    src = LOGOS_DIR / "chromadb.png.ico"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    img = Image.open(src)
    # ICO files contain multiple resolutions; pick the largest by area.
    best = None
    best_area = 0
    for size in (img.ico.sizes() if hasattr(img, "ico") else [img.size]):
        try:
            img.size = size            # request a specific resolution
        except Exception:
            pass
        w, h = img.size
        if w * h > best_area:
            best_area = w * h
            best = img.copy()
    out = LOGOS_DIR / "chromadb.png"
    best.convert("RGBA").save(out, format="PNG")
    print(f"converted {src.name}  ->  {out.name}  ({best.size[0]}x{best.size[1]})")


def crop_seam_strand() -> None:
    src = LOGOS_DIR / "pngtree-red-baseball-seams-illustration-png-image_16340566.png"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    # The vertical strand lives in the left ~22% of the image. Crop a tight
    # box around it to avoid the pngtree watermark on the right.
    left  = int(w * 0.05)
    right = int(w * 0.22)
    top   = int(h * 0.05)
    bot   = int(h * 0.95)
    strand = img.crop((left, top, right, bot))
    out = LOGOS_DIR / "seam_strand.png"
    strand.save(out, format="PNG")
    print(f"cropped {src.name}  ->  {out.name}  ({strand.size[0]}x{strand.size[1]})")


def transcode_diamond_watermark() -> None:
    src = LOGOS_DIR / "baseballdiamondwatermark.jpg"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    img = Image.open(src).convert("RGBA")
    out = LOGOS_DIR / "baseball_diamond.png"
    img.save(out, format="PNG")
    print(f"transcoded {src.name} ({img.format or 'unknown'} -> PNG)  "
          f"->  {out.name}  ({img.size[0]}x{img.size[1]})")


def main() -> None:
    convert_chromadb_ico()
    crop_seam_strand()
    transcode_diamond_watermark()


if __name__ == "__main__":
    main()

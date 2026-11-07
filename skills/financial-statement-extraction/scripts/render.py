"""Render PDF pages (or a crop) to PNG for reading by eye, and/or dump the text layer.

Token economy: a 1500 px page is enough for most statements; crop a region at higher resolution only where digits
are unclear, instead of rendering the whole page larger. Check the text layer first: when it is clean, use it to
confirm digits and look at the image only for layout (headers, which column is which, brackets).

Usage:
  python -I render.py <pdf> <pages> <out_dir> [--px 1500] [--clip x0,y0,x1,y1] [--text]
    pages: "3" or "3,5" or "3-6" (1-based)
    --clip: fractions of the page (0..1), e.g. 0,0.4,1,0.8 for the middle band; rendered at --px for the crop
    --text: also print each page's text layer (first 4000 chars) - often enough on its own for text PDFs
Prints the PNG paths; open them with the image-reading tool.
"""
import pathlib
import sys

import pymupdf


def pages_of(spec):
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main(pdf, spec, out_dir, px=1500, clip=None, text=False):
    doc = pymupdf.open(pdf)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = pathlib.Path(pdf).stem
    for p in pages_of(spec):
        pg = doc[p - 1]
        r = pg.rect
        area = r
        if clip:
            x0, y0, x1, y1 = clip
            area = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
        z = px / max(area.width, area.height)
        name = out / f"{stem}_p{p}{'_crop' if clip else ''}.png"
        pg.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=area).save(name)
        print(name)
        if text:
            t = pg.get_text()
            print(f"--- text p{p} ({len(t)} chars, rotation {pg.rotation}) ---")
            print(t[:4000])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("pages"); ap.add_argument("out_dir")
    ap.add_argument("--px", type=int, default=1500)
    ap.add_argument("--clip", type=lambda s: tuple(float(v) for v in s.split(",")))
    ap.add_argument("--text", action="store_true")
    o = ap.parse_args()
    main(o.pdf, o.pages, o.out_dir, o.px, o.clip, o.text)

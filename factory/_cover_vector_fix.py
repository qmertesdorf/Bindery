"""Replace a FLATTENED concept-book cover with a crisp VECTOR-text version.

build_cover() bakes the whole cover (art + title) into a 300-DPI raster via
_flatten_cover_pdf so Acrobat renders the full-page CSS background — but that
rasterises the title into jaggies on zoom. This reproduces the manual fix: render
the wrap HTML to a vector PDF (crisp title text) and embed cover_bg.png as a real
PDF image BEHIND the text (overlay=False), so Acrobat still shows the background
AND the title stays razor-sharp at any zoom. No GPU. Run from factory/ AFTER a build.

Usage:  ./.venv/Scripts/python.exe _cover_vector_fix.py [books/<slug>.config.json]
        (defaults to books/wild-golden-world.config.json)
"""
import sys
import shutil
from pathlib import Path
import fitz
from factory.config import load_config
from factory.cover import (render_cover_html, _verify_cover_pdf,
                           _verify_cover_dimensions, _verify_cover_text_zones)
from factory.browsepdf import html_to_pdf
from factory.copy import book_blurb
from factory import specs

cfg_path = sys.argv[1] if len(sys.argv) > 1 else "books/wild-golden-world.config.json"
cfg = load_config(cfg_path)
OUT = Path("out") / cfg.slug
pages = fitz.open(str(OUT / "interior.pdf")).page_count
per_page = specs.spine_per_page(cfg.book_type)
width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h, per_page)
print(f"[{cfg.slug}] interior pages={pages}  wrap={width_in:.2f}x{height_in:.2f}in", flush=True)

# 1) fresh VECTOR wrap PDF (this also regenerates cover_wrap.html + cover_bg.png)
wrap_html = render_cover_html(cfg, pages, OUT / "art.png", OUT, front_only=False)
vec = OUT / "_cover_vector.pdf"
html_to_pdf(wrap_html, vec, width_in=width_in, height_in=height_in,
            margins_in=0.0, prefer_css_page_size=True)

# 2) guards on the vector text (title/author/blurb present, size + safe zones)
req = [cfg.title, cfg.subtitle, cfg.author, book_blurb(cfg)]
if cfg.illustrator:
    req.append(cfg.illustrator)
_verify_cover_pdf(vec, req)
_verify_cover_dimensions(vec, pages, cfg.trim_w, cfg.trim_h, per_page=per_page)
_verify_cover_text_zones(vec, pages, cfg.trim_w, per_page=per_page)
print("vector guards passed", flush=True)

# 3) embed cover_bg.png BEHIND the vector text so Acrobat renders the background
doc = fitz.open(str(vec))
doc[0].insert_image(doc[0].rect, filename=str(OUT / "cover_bg.png"), overlay=False)
final = OUT / "cover-paperback.pdf"
if final.exists():
    shutil.copy(str(final), str(OUT / "cover-paperback.flat.pdf.bak"))
doc.save(str(final), deflate=True, garbage=4)
doc.close()
vec.unlink(missing_ok=True)

# sanity: reopen, confirm 1 page, right size, vector text still present
chk = fitz.open(str(final))
r = chk[0].rect
n_pages, has_text = chk.page_count, bool(chk[0].get_text().strip())
mb = final.stat().st_size / 1e6
chk.close()
print(f"CRISP COVER SAVED -> {final}  {r.width/72:.2f}x{r.height/72:.2f}in  "
      f"{mb:.1f}MB  pages={n_pages}  vector_text={has_text}", flush=True)
assert n_pages == 1 and has_text, "cover lost text or page count!"
print("OK", flush=True)

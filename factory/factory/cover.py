"""Stage 4: assemble wraparound cover PDF and ebook cover JPG."""
from __future__ import annotations
import shutil
from pathlib import Path
from jinja2 import Template
from .config import BookConfig
from .templating import render, TEMPLATES_DIR
from .browsepdf import html_to_pdf, html_to_screenshot
from . import specs

_CSS_TEMPLATE = (TEMPLATES_DIR / "cover" / "cover.css").read_text(encoding="utf-8") \
    if (TEMPLATES_DIR / "cover" / "cover.css").exists() else ""


def _css(width_in: float, height_in: float, art_file: str, fill: bool = False) -> str:
    return Template(_CSS_TEMPLATE).render(
        width_in=width_in, height_in=height_in, art_file=art_file,
        bleed=specs.BLEED_IN, trim_w=specs.TRIM_W_IN, fill=fill)


def render_cover_html(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                      front_only: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art_local = out_dir / Path(art_path).name
    if Path(art_path).resolve() != art_local.resolve():
        shutil.copy(art_path, art_local)
    if front_only:
        width_in = specs.TRIM_W_IN + 2 * specs.BLEED_IN
        height_in = specs.TRIM_H_IN + 2 * specs.BLEED_IN
        name = "cover_front.html"
    else:
        width_in, height_in = specs.cover_dimensions_in(pages)
        name = "cover_wrap.html"
    css = _css(width_in, height_in, art_local.name, fill=front_only)
    html = render("cover/cover.html.j2", cfg=cfg, css=css,
                  width_in=width_in, height_in=height_in)
    html_path = out_dir / name
    html_path.write_text(html, encoding="utf-8")
    return html_path


def _recompress_jpg(path: Path, quality: int = 90) -> None:
    """Re-encode the cover JPG at a sane quality. The browse screenshot backend
    saves near-lossless (multi-MB from hi-res art); q=90 is visually identical at
    roughly 1/8 the size, keeping the ebook cover and EPUB light — KDP delivery
    fees on the 70% royalty plan scale per megabyte."""
    import fitz
    try:
        data = fitz.Pixmap(str(path)).tobytes("jpg", jpg_quality=quality)
    except Exception:
        return  # not a decodable image (e.g. a test stub) — leave it untouched
    Path(path).write_bytes(data)


def build_cover(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                runner=None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    # wraparound paperback PDF
    wrap_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=False)
    width_in, height_in = specs.cover_dimensions_in(pages)
    pdf = out_dir / "cover-paperback.pdf"
    html_to_pdf(wrap_html, pdf, width_in=width_in, height_in=height_in,
                margins_in=0.0, runner=runner)
    # ebook front cover JPG. The fill=True CSS makes the front cover fill the
    # viewport; the browse backend emits a fixed ~1250x2000 JPG (1.6 ratio),
    # which clears KDP's 1000px-short-side minimum.
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg

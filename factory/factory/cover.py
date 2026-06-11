"""Stage 4: assemble wraparound cover PDF and ebook cover JPG."""
from __future__ import annotations
import shutil
from pathlib import Path
from jinja2 import Template
from .config import BookConfig
from .templating import render, TEMPLATES_DIR
from .browsepdf import html_to_pdf, html_to_screenshot
from .copy import book_blurb
from . import specs

_CSS_TEMPLATE = (TEMPLATES_DIR / "cover" / "cover.css").read_text(encoding="utf-8") \
    if (TEMPLATES_DIR / "cover" / "cover.css").exists() else ""


class CoverError(RuntimeError):
    pass


def _verify_cover_pdf(pdf: Path, required: list[str]) -> None:
    """Fail the build if the rendered cover PDF is missing expected text.

    Guards against the HTML->PDF renderer silently dropping an element (e.g. an
    absolutely-positioned author name, which Chromium's print path discards) —
    a defect that is otherwise invisible until someone inspects the file. Text
    is whitespace-normalised so line wraps in the rendered cover don't cause
    false alarms. Skips cleanly if the file isn't a real PDF (e.g. a test stub).
    """
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    raw = "\n".join(doc[i].get_text() for i in range(doc.page_count))
    # The renderer emits each line twice (text-shadow becomes a duplicate text
    # layer); drop consecutive duplicate lines so multi-line text stays contiguous.
    dedup = []
    for ln in raw.splitlines():
        if not dedup or dedup[-1] != ln:
            dedup.append(ln)
    norm = " ".join(" ".join(dedup).split())
    missing = [s for s in required if " ".join(s.split()) not in norm]
    if missing:
        raise CoverError(
            f"Cover PDF {pdf.name} is missing expected text: {missing}. The HTML "
            f"renderer likely dropped an element — check cover positioning/CSS.")


def _verify_cover_dimensions(pdf: Path, pages: int, tol_in: float = 0.05) -> None:
    """Fail the build if the rendered cover's physical size doesn't match the page
    count. The full-bleed wrap width encodes the spine (0.0025in/page on cream),
    so a wrong trim, a renderer that ignores the requested size, or a spine that
    doesn't fit the page count all surface here — and all get a KDP rejection.
    Skips cleanly if the file isn't a real PDF (e.g. a test stub).
    """
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    rect = doc[0].rect
    w_in, h_in = rect.width / 72, rect.height / 72
    exp_w, exp_h = specs.cover_dimensions_in(pages)
    errs = []
    if abs(w_in - exp_w) > tol_in:
        errs.append(f"width {w_in:.3f}in vs expected {exp_w:.3f}in "
                    f"(spine {specs.spine_width_in(pages)}in for {pages}pp)")
    if abs(h_in - exp_h) > tol_in:
        errs.append(f"height {h_in:.3f}in vs expected {exp_h:.3f}in")
    if errs:
        raise CoverError(f"Cover PDF {pdf.name} dimensions don't match "
                         f"{pages} pages: " + "; ".join(errs))


def _verify_cover_background(pdf: Path) -> None:
    """Fail the build if the cover's full-bleed background didn't render (a mostly
    white page) or if MULTIPLE background images are present (per-panel CSS crops,
    which Chromium bakes as oversized clipped patterns that bleed across panels in
    some PDF viewers). A single continuous full-page background can embed as zero
    image-XObjects, so presence is checked by rendered pixels, not image count.
    Skips a non-PDF stub."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    pg = doc[0]
    if len(pg.get_images(full=True)) > 1:
        raise CoverError(
            f"Cover PDF {pdf.name} has multiple background images — per-panel "
            f"crops were likely reintroduced; they render broken in some viewers.")
    pix = pg.get_pixmap(dpi=12)
    s, step, n = pix.samples, pix.n, pix.width * pix.height
    white = sum(1 for i in range(0, len(s), step)
                if s[i] >= 245 and s[i + 1] >= 245 and s[i + 2] >= 245)
    if n and white / n > 0.6:
        raise CoverError(
            f"Cover PDF {pdf.name} is {round(100 * white / n)}% white — the "
            f"full-bleed background art did not render.")


def _compose_wrap_bg(art_path: Path, out_dir: Path, width_in: float, height_in: float,
                     dpi: int = 300, subject_x: float = 0.5, front_x: float = 0.70) -> None:
    """Compose the wraparound as ONE continuous page-sized image with the subject
    shifted onto the FRONT cover.

    The image model centres the subject regardless of positional prompts, which
    would put it on the spine fold. Scale the art to the wrap height, shift it
    right so the (centred) subject lands at ``front_x`` of the width, and fill the
    exposed left edge by mirror-extending the adjacent scenery — for soft
    watercolour landscapes the reflection reads as a natural continuation. The
    result is a single full-page background (renders identically in every PDF
    viewer) with the subject on the front and the scene sweeping onto the back.
    Skips on a non-image stub (tests)."""
    from PIL import Image
    try:
        art = Image.open(art_path).convert("RGB")
    except Exception:
        return
    W, H = round(width_in * dpi), round(height_in * dpi)
    art = art.resize((max(1, round(art.width * H / art.height)), H))
    aw = art.width
    shift = round(front_x * W - subject_x * aw)
    canvas = Image.new("RGB", (W, H))
    canvas.paste(art, (shift, 0))
    if shift > 0:                                   # mirror-fill the left gap
        strip = art.crop((0, 0, min(shift, aw), H)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(strip, (0, 0))
    if shift + aw < W:                              # mirror-fill any right gap
        gap = W - (shift + aw)
        strip = art.crop((aw - min(gap, aw), 0, aw, H)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(strip, (shift + aw, 0))
    canvas.save(out_dir / "cover_bg.png")


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
        _compose_wrap_bg(art_local, out_dir, width_in, height_in)
    css = _css(width_in, height_in, art_local.name, fill=front_only)
    html = render("cover/cover.html.j2", cfg=cfg, css=css,
                  width_in=width_in, height_in=height_in,
                  front_only=front_only, blurb=book_blurb(cfg))
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
    # Regression guards: confirm the renderer placed the front-cover text and the
    # back-cover blurb, and that the cover's physical size matches the page count.
    _verify_cover_pdf(pdf, [cfg.title, cfg.subtitle, cfg.author, book_blurb(cfg)])
    _verify_cover_dimensions(pdf, pages)
    _verify_cover_background(pdf)
    # ebook front cover JPG. The fill=True CSS makes the front cover fill the
    # viewport; the browse backend emits a fixed ~1250x2000 JPG (1.6 ratio),
    # which clears KDP's 1000px-short-side minimum.
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg

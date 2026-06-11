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


def _verify_cover_single_image(pdf: Path) -> None:
    """Fail the build unless the cover is ONE full-page background image. Multiple
    images mean per-panel CSS background crops crept back in — Chromium bakes
    those as oversized, clipped patterns that bleed across panels in some PDF
    viewers (the cover looks broken outside Chromium). Skips a non-PDF stub."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    pg = doc[0]
    imgs = pg.get_images(full=True)
    if len(imgs) != 1:
        raise CoverError(
            f"Cover PDF {pdf.name} has {len(imgs)} images; expected exactly 1 "
            f"full-page background. Per-panel background crops were likely "
            f"reintroduced — they render broken in some PDF viewers.")
    page_area = pg.rect.width * pg.rect.height
    covered = any(r.width * r.height >= 0.95 * page_area
                  for r in pg.get_image_rects(imgs[0][0]))
    if not covered:
        raise CoverError(
            f"Cover PDF {pdf.name}'s background image doesn't cover the page — "
            f"the composed wrap background is missing or mis-sized.")


# Vertical scrim profiles (position-fraction, black-alpha), baked into the
# composed background. Front: dark top+bottom for title/author; back: dark
# middle band for the centred blurb.
_FRONT_SCRIM = [(0.0, 0.45), (0.16, 0.32), (0.40, 0.0), (0.80, 0.0), (1.0, 0.38)]
_BACK_SCRIM = [(0.0, 0.0), (0.04, 0.0), (0.24, 0.34), (0.66, 0.34), (0.88, 0.0), (1.0, 0.0)]


def _interp(stops, f):
    for (p0, a0), (p1, a1) in zip(stops, stops[1:]):
        if f <= p1:
            t = 0 if p1 == p0 else (f - p0) / (p1 - p0)
            return a0 + (a1 - a0) * max(0.0, min(1.0, t))
    return stops[-1][1]


def _bake_scrim(canvas, x0, w, stops):
    from PIL import Image
    H = canvas.size[1]
    col = Image.new("L", (1, H))
    px = col.load()
    for y in range(H):
        px[0, y] = int(_interp(stops, y / H) * 255)
    mask = col.resize((w, H))
    region = canvas.crop((x0, 0, x0 + w, H))
    region = Image.composite(Image.new("RGB", (w, H), (0, 0, 0)), region, mask)
    canvas.paste(region, (x0, 0))


def _avg_color(img):
    return img.resize((1, 1)).getpixel((0, 0))


def _compose_wrap_bg(art_path: Path, out_dir: Path,
                     width_in: float, height_in: float, dpi: int = 300) -> None:
    """Compose the whole wraparound background as ONE page-sized image.

    Front panel = the SUBJECT (sharp centre crop of the art). Back panel + spine
    = a single soft vertical wash sampled from the art's sky/ground tones — so no
    subject can appear on the back (the centred subject would otherwise bleed
    onto the back panel) and the spine is continuous with the back rather than a
    flat coloured strip. Scrims are baked in for text legibility.

    A single full-page background renders identically across PDF viewers, whereas
    per-panel CSS background crops are baked by Chromium as oversized, clipped
    patterns that bleed across panels in some viewers. Skips on a non-image stub
    (tests)."""
    from PIL import Image
    try:
        art = Image.open(art_path).convert("RGB")
    except Exception:
        return
    aw, ah = art.size
    W, H = round(width_in * dpi), round(height_in * dpi)
    panel_w = min(round((specs.TRIM_W_IN + specs.BLEED_IN) * dpi), W)
    front_x = W - panel_w                       # front panel left edge (px)

    # Front: sharp centre crop (the subject).
    cw = min(aw, max(1, round(ah * panel_w / H)))
    fx = (aw - cw) // 2
    front = art.crop((fx, 0, fx + cw, ah)).resize((panel_w, H))

    # Back + spine: vertical wash from the art's top (sky) to bottom (ground).
    band = max(1, ah // 6)
    top = _avg_color(art.crop((0, 0, aw, band)))
    bot = _avg_color(art.crop((0, ah - band, aw, ah)))
    col = Image.new("RGB", (1, H))
    cpx = col.load()
    for y in range(H):
        t = y / H
        cpx[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    back = col.resize((max(1, front_x), H))

    canvas = Image.new("RGB", (W, H))
    canvas.paste(back, (0, 0))
    canvas.paste(front, (front_x, 0))
    _bake_scrim(canvas, 0, front_x, _BACK_SCRIM)
    _bake_scrim(canvas, front_x, panel_w, _FRONT_SCRIM)
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
    _verify_cover_single_image(pdf)
    # ebook front cover JPG. The fill=True CSS makes the front cover fill the
    # viewport; the browse backend emits a fixed ~1250x2000 JPG (1.6 ratio),
    # which clears KDP's 1000px-short-side minimum.
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg

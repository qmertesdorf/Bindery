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
    # De-hyphenate line-break hyphenation: the renderer may wrap a hyphenated word
    # ("read-aloud" -> "read-\naloud"), which normalises to "read- aloud"; collapse
    # "- " back to "-" so a verbatim blurb still matches (em-dashes are U+2014 and
    # untouched).
    def _norm(t: str) -> str:
        return " ".join(t.split()).replace("- ", "-")
    norm = _norm(" ".join(dedup))
    missing = [s for s in required if _norm(s) not in norm]
    if missing:
        raise CoverError(
            f"Cover PDF {pdf.name} is missing expected text: {missing}. The HTML "
            f"renderer likely dropped an element — check cover positioning/CSS.")


def _verify_cover_dimensions(pdf: Path, pages: int, trim_w: float = specs.TRIM_W_IN,
                             trim_h: float = specs.TRIM_H_IN,
                             per_page: float = specs.SPINE_PER_PAGE_IN,
                             tol_in: float = 0.05) -> None:
    """Fail the build if the rendered cover's physical size doesn't match the page
    count. The full-bleed wrap width encodes the spine (0.0025in/page on cream,
    0.002252in/page on white/colour stock), so a wrong trim, a renderer that ignores
    the requested size, or a spine that doesn't fit the page count all surface here
    — and all get a KDP rejection. Skips cleanly if the file isn't a real PDF
    (e.g. a test stub).
    """
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    if doc.page_count != 1:
        raise CoverError(
            f"Cover PDF {pdf.name} has {doc.page_count} pages; a KDP cover must be "
            f"exactly 1. Content is overflowing the page box (check @page size / "
            f"overflow).")
    rect = doc[0].rect
    w_in, h_in = rect.width / 72, rect.height / 72
    exp_w, exp_h = specs.cover_dimensions_in(pages, trim_w, trim_h, per_page)
    errs = []
    if abs(w_in - exp_w) > tol_in:
        errs.append(f"width {w_in:.3f}in vs expected {exp_w:.3f}in "
                    f"(spine {specs.spine_width_in(pages, per_page)}in for {pages}pp)")
    if abs(h_in - exp_h) > tol_in:
        errs.append(f"height {h_in:.3f}in vs expected {exp_h:.3f}in")
    if errs:
        raise CoverError(f"Cover PDF {pdf.name} dimensions don't match "
                         f"{pages} pages: " + "; ".join(errs))


def _verify_cover_text_zones(pdf: Path, pages: int, trim_w: float = specs.TRIM_W_IN,
                             per_page: float = specs.SPINE_PER_PAGE_IN,
                             inset_in: float = 0.2) -> None:
    """Fail if any cover text strays outside its panel's safe area: into the bleed,
    across the spine, within ``inset_in`` of the trim, or into KDP's barcode
    keep-out (lower-right of the back cover). KDP rejects covers with text in
    these regions. Front vs back is decided by which side of the spine the text
    sits on. Skips a non-PDF stub."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    pg = doc[0]
    W, H = pg.rect.width / 72, pg.rect.height / 72
    bleed, tw = specs.BLEED_IN, trim_w
    spine_l = bleed + tw
    spine_c = spine_l + specs.spine_width_in(pages, per_page) / 2
    top, bot = bleed + inset_in, H - bleed - inset_in
    back_x = (bleed + inset_in, spine_l - inset_in)
    front_x = (W - bleed - tw + inset_in, W - bleed - inset_in)
    barcode = (spine_l - 2.0, spine_l, H - bleed - 1.2, H - bleed)  # x0,x1,y0,y1
    bad = []
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                x0, y0, x1, y1 = (v / 72 for v in s["bbox"])
                cx = (x0 + x1) / 2
                safe = front_x if cx > spine_c else back_x
                label = s["text"].strip()[:22]
                if x0 < safe[0] - 1e-3 or x1 > safe[1] + 1e-3 or y0 < top - 1e-3 or y1 > bot + 1e-3:
                    bad.append(f'"{label}" outside the safe area')
                elif cx <= spine_c and x1 > barcode[0] and x0 < barcode[1] \
                        and y1 > barcode[2] and y0 < barcode[3]:
                    bad.append(f'"{label}" overlaps the barcode zone')
    if bad:
        raise CoverError(f"Cover PDF {pdf.name} has text outside KDP safe zones: "
                         + "; ".join(sorted(set(bad))))


def _verify_cover_back_text_centered(pdf: Path, pages: int,
                                     trim_w: float = specs.TRIM_W_IN,
                                     per_page: float = specs.SPINE_PER_PAGE_IN,
                                     tol_in: float = 0.25) -> None:
    """Fail if the back-cover text block isn't centred in the back panel.

    Composition guard: the back blurb is meant to sit centred over its scrim. An
    asymmetric padding or a layout regression that shoves it high/low or off to one
    side is a defect KDP won't catch but a reader will — so check that the bounding
    box of all back-panel text is centred (within ``tol_in``) on the back panel's
    centre, horizontally and vertically. Front-cover text (an intentionally
    top-aligned title block) is excluded by the spine split. Skips a non-PDF stub
    or a cover with no back text (front-only)."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    pg = doc[0]
    W, H = pg.rect.width / 72, pg.rect.height / 72
    spine_l = specs.BLEED_IN + trim_w
    spine_c = spine_l + specs.spine_width_in(pages, per_page) / 2
    back_cx = specs.BLEED_IN + trim_w / 2
    x0 = y0 = x1 = y1 = None
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if not s["text"].strip():
                    continue
                bx0, by0, bx1, by1 = (v / 72 for v in s["bbox"])
                if (bx0 + bx1) / 2 > spine_c:
                    continue  # front-cover text
                x0 = bx0 if x0 is None else min(x0, bx0)
                y0 = by0 if y0 is None else min(y0, by0)
                x1 = bx1 if x1 is None else max(x1, bx1)
                y1 = by1 if y1 is None else max(y1, by1)
    if x0 is None:
        return  # no back-cover text (e.g. front-only)
    dx = abs((x0 + x1) / 2 - back_cx)
    dy = abs((y0 + y1) / 2 - H / 2)
    errs = []
    if dx > tol_in:
        errs.append(f"horizontally off-centre by {dx:.2f}in")
    if dy > tol_in:
        errs.append(f"vertically off-centre by {dy:.2f}in")
    if errs:
        raise CoverError(
            f"Cover PDF {pdf.name} back-cover text is not centred in its panel: "
            + "; ".join(errs) + " — check the .back padding / scrim placement.")


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


def _verify_cover_no_white_edge(pdf: Path, white: int = 252, frac: float = 0.55) -> None:
    """Fail if an outer edge of the cover is a hair-thin near-pure-white line — the
    signature of a full-bleed background that fell a few px short in the HTML->PDF
    render, letting the white page show through at the trim/bleed edge. KDP would
    print that white line. Full-bleed art never legitimately paints a pure-white
    (>=252) majority along an edge, so this won't fire on bright sky. Skips a
    non-PDF stub."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    pix = doc[0].get_pixmap(dpi=150)
    W, H, n, s = pix.width, pix.height, pix.n, pix.samples

    def is_white(x, y):
        i = (y * W + x) * n
        return min(s[i], s[i + 1], s[i + 2]) >= white

    bad = []
    ys = list(range(0, H, max(1, H // 250)))
    xs = list(range(0, W, max(1, W // 250)))
    for x, name in ((0, "left"), (W - 1, "right")):
        if sum(is_white(x, y) for y in ys) / len(ys) > frac:
            bad.append(name)
    for y, name in ((0, "top"), (H - 1, "bottom")):
        if sum(is_white(x, y) for x in xs) / len(xs) > frac:
            bad.append(name)
    if bad:
        raise CoverError(
            f"Cover PDF {pdf.name} has a thin white line at the {', '.join(bad)} "
            f"edge(s) — the full-bleed background fell short in the render and the "
            f"white page shows through. Overscan the cover background.")


def _compose_wrap_bg(art_path: Path, out_dir: Path, width_in: float, height_in: float,
                     trim_w: float = specs.TRIM_W_IN, dpi: int = 300,
                     subject_x: float = 0.5, front_x: float = 0.64) -> None:
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
    from PIL import Image, ImageFilter
    try:
        art = Image.open(art_path).convert("RGB")
    except Exception:
        return
    W, H = round(width_in * dpi), round(height_in * dpi)
    # Overscan: scale a touch larger than the wrap and crop the (often pale,
    # watercolour-faded) top/bottom margins so a near-white paper edge never lands
    # on the trim/bleed edge — which KDP would print as a white line and the
    # cover guard rejects. A few % zoom drops the faded border, not the subject.
    overscan = 1.08
    hs = round(H * overscan)
    art = art.resize((max(1, round(art.width * hs / art.height)), hs))
    top = (hs - H) // 2
    art = art.crop((0, top, art.width, top + H))
    aw = art.width
    shift = round(front_x * W - subject_x * aw)
    spine_left_px = round((specs.BLEED_IN + trim_w) * dpi)
    # Keep the sharp foreground OFF the back cover: start the art at the spine so the
    # entire BACK is just the soft mirror-fill (no dark tree/subject bleeding onto the
    # back-right, which unbalances it and makes centred blurb text read as off-centre).
    # The art must still cover the full FRONT — if it's too narrow to both clear the
    # spine and fill the front, fall back to right-aligning (cover the front).
    if spine_left_px + aw >= W:
        shift = spine_left_px
    elif 0 < shift + aw < W:
        shift = W - aw
    canvas = Image.new("RGB", (W, H))
    canvas.paste(art, (shift, 0))
    # Mirror-extend to fill exposed edges, but BLUR the mirrored strips so the
    # reflected scenery reads as soft, distant background rather than an obvious
    # symmetric copy of the foreground.
    blur = ImageFilter.GaussianBlur(round(0.14 * dpi))
    if shift > 0:                                   # left gap (back-cover edge)
        strip = art.crop((0, 0, min(shift, aw), H)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(strip.filter(blur), (0, 0))
    if shift + aw < W:                              # right gap (front-cover edge)
        gap = W - (shift + aw)
        strip = art.crop((aw - min(gap, aw), 0, aw, H)).transpose(Image.FLIP_LEFT_RIGHT)
        canvas.paste(strip.filter(blur), (shift + aw, 0))

    # The BACK cover (everything left of the spine) should read as a soft, uniform
    # blurred backdrop. The chosen art's sharp foreground often extends past the
    # spine into the back trim, so centred blurb text looks off against the sharp
    # content on one side. Blur the whole back region into a clean backdrop so the
    # centred blurb actually reads as centred.
    # Blur the whole back into a uniform soft backdrop. Only a small feather at the
    # spine is needed now (the sharp foreground starts at the spine, so nothing
    # straddles the fold to create a half-blurred seam).
    full_blur_px = max(0, round((specs.BLEED_IN + trim_w - 0.3) * dpi))
    if spine_left_px > 1:
        # Feathered blur: FULL behind the centred blurb (outer back), then ramp back
        # to SHARP as it reaches the spine — so foreground that crosses the fold stays
        # continuous (no hard half-blurred/half-sharp seam at the spine) and the front
        # cover is left entirely untouched.
        blurred = canvas.filter(ImageFilter.GaussianBlur(round(0.22 * dpi)))
        # Even out the backdrop behind the blurb: a bright pool on one side makes the
        # perfectly-centred blurb read as off-centre (a real defect the vision auditor
        # flags). Blend the blurred back toward its own average colour for a balanced,
        # uniform soft backdrop so centred text actually reads as centred.
        if full_blur_px > 0:
            avg = blurred.crop((0, 0, full_blur_px, H)).resize((1, 1)).getpixel((0, 0))
            blurred = Image.blend(blurred, Image.new("RGB", (W, H), avg), 0.55)
        mask = Image.new("L", (W, H), 0)
        if full_blur_px > 0:
            mask.paste(255, (0, 0, full_blur_px, H))
        ramp = spine_left_px - full_blur_px
        if ramp > 0:
            grad = Image.new("L", (ramp, 1))
            grad.putdata([round(255 * (1 - i / ramp)) for i in range(ramp)])
            mask.paste(grad.resize((ramp, H)), (full_blur_px, 0))
        canvas = Image.composite(blurred, canvas, mask)

    # Soft, localised scrims baked ONLY behind the title (top-front) and blurb
    # (mid-back): blurred ellipses, so the darkening has no hard rectangular
    # edges or spine seam and leaves the rest of the scene (incl. the subject)
    # untouched — unlike full-panel CSS gradients, which read as a grey overlay
    # over pale art.
    from PIL import ImageDraw, ImageFilter
    front_cx = W - round((specs.BLEED_IN + trim_w / 2) * dpi)
    back_cx = round((specs.BLEED_IN + trim_w / 2) * dpi)
    regions = [
        (front_cx, round(0.19 * H), round(3.3 * dpi), round(1.7 * dpi), 0.55),  # title
        (back_cx, round(0.50 * H), round(2.9 * dpi), round(2.0 * dpi), 0.62),   # blurb (panel centre) — darker so white text stays legible over bright art
    ]
    overlay = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(overlay)
    for cx, cy, rx, ry, alpha in regions:
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=int(alpha * 255))
    overlay = overlay.filter(ImageFilter.GaussianBlur(round(0.6 * dpi)))
    canvas = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), canvas, overlay)
    canvas.save(out_dir / "cover_bg.png")


def _audit_cover_composition(pdf: Path, auditor, dpi: int = 150) -> None:
    """Vision-audit the rendered cover for legibility/composition defects a
    geometry guard can't see — e.g. pale text over a bright area, text crammed or
    cut off. Renders the cover to an image and asks the injected vision auditor
    (kind='cover'); raises CoverError if it reports a problem, so a bad cover is
    caught at build time instead of by the human. No-op when no auditor is provided
    or the file isn't a real PDF (tests)."""
    if auditor is None:
        return
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    if doc.page_count < 1:
        doc.close()
        return
    img = Path(pdf).parent / "_cover_audit.png"
    doc[0].get_pixmap(dpi=dpi).save(str(img))
    doc.close()
    try:
        verdict = auditor.audit(img, anchor="", scene=None, kind="cover")
    finally:
        try:
            img.unlink()
        except OSError:
            pass
    if not verdict.get("ok"):
        raise CoverError(
            f"Cover {pdf.name} failed the composition audit: "
            + "; ".join(verdict.get("issues", []) or ["no reason given"])
            + ". Fix the cover (e.g. scrim/contrast/placement) and rebuild.")


def _flatten_cover_pdf(pdf: Path, dpi: int = 300) -> None:
    """Rewrite the cover PDF as a single full-page raster image at print DPI.

    Chromium embeds the full-page CSS background in a way some PDF viewers (notably
    Adobe Acrobat) silently fail to render — showing a blank page with floating
    white text that reads as 'text bleeding off the page'. Baking the whole cover
    (art + text) into one embedded image makes it render identically in EVERY viewer
    and in KDP's previewer. The cost is vector-text crispness, which is invisible at
    300 DPI print resolution. MUST run AFTER the text/geometry guards (they need the
    vector text). Page dimensions are preserved. Skips a non-PDF stub."""
    import fitz
    try:
        src = fitz.open(str(pdf))
    except Exception:
        return
    if src.page_count < 1:
        src.close()
        return
    page = src[0]
    w_pt, h_pt = page.rect.width, page.rect.height
    pix = page.get_pixmap(dpi=dpi)
    src.close()
    out = fitz.open()
    npg = out.new_page(width=w_pt, height=h_pt)
    npg.insert_image(npg.rect, pixmap=pix)
    out.save(str(pdf), deflate=True)
    out.close()


def _css(width_in: float, height_in: float, art_file: str, fill: bool = False,
         trim_w: float = specs.TRIM_W_IN) -> str:
    return Template(_CSS_TEMPLATE).render(
        width_in=width_in, height_in=height_in, art_file=art_file,
        bleed=specs.BLEED_IN, trim_w=trim_w, fill=fill)


def render_cover_html(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                      front_only: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art_local = out_dir / Path(art_path).name
    if Path(art_path).resolve() != art_local.resolve():
        shutil.copy(art_path, art_local)
    if front_only:
        width_in = cfg.trim_w + 2 * specs.BLEED_IN
        height_in = cfg.trim_h + 2 * specs.BLEED_IN
        name = "cover_front.html"
    else:
        per_page = specs.spine_per_page(cfg.book_type)
        width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h,
                                                        per_page)
        name = "cover_wrap.html"
        _compose_wrap_bg(art_local, out_dir, width_in, height_in, trim_w=cfg.trim_w)
    css = _css(width_in, height_in, art_local.name, fill=front_only, trim_w=cfg.trim_w)
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
                runner=None, make_ebook_cover: bool = True,
                auditor=None) -> tuple[Path, Path | None]:
    out_dir = Path(out_dir)
    per_page = specs.spine_per_page(cfg.book_type)
    # wraparound paperback PDF
    wrap_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=False)
    width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h,
                                                    per_page)
    pdf = out_dir / "cover-paperback.pdf"
    html_to_pdf(wrap_html, pdf, width_in=width_in, height_in=height_in,
                margins_in=0.0, runner=runner, prefer_css_page_size=True)
    # Regression guards: confirm the renderer placed the front-cover text and the
    # back-cover blurb, and that the cover's physical size matches the page count.
    _verify_cover_pdf(pdf, [cfg.title, cfg.subtitle, cfg.author, book_blurb(cfg)])
    _verify_cover_dimensions(pdf, pages, cfg.trim_w, cfg.trim_h, per_page=per_page)
    _verify_cover_background(pdf)
    _verify_cover_no_white_edge(pdf)
    _verify_cover_text_zones(pdf, pages, cfg.trim_w, per_page=per_page)
    _verify_cover_back_text_centered(pdf, pages, cfg.trim_w, per_page=per_page)
    # Bake the validated cover to a single image so it renders in every viewer
    # (Acrobat doesn't render the vector full-page background). Guards above ran on
    # the vector text; this must come after them. Re-check size survived the bake.
    _flatten_cover_pdf(pdf)
    _verify_cover_dimensions(pdf, pages, cfg.trim_w, cfg.trim_h, per_page=per_page)
    # Vision composition check (legibility/placement) on the finished cover.
    _audit_cover_composition(pdf, auditor)
    # Journals are paperback-only — skip the Kindle front-cover JPG entirely.
    if not make_ebook_cover:
        return pdf, None
    # ebook front cover JPG. The fill=True CSS makes the front cover fill the
    # viewport; the browse backend emits a fixed ~1250x2000 JPG (1.6 ratio),
    # which clears KDP's 1000px-short-side minimum.
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg

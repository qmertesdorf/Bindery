"""Stage 2: render interior to HTML (and later PDF + EPUB)."""
from __future__ import annotations
import re
import shutil
from pathlib import Path
from .config import BookConfig
from .templating import render, TEMPLATES_DIR
from .browsepdf import html_to_pdf
from . import specs
from ebooklib import epub


def render_interior_html(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = ("interior/standard.html.j2" if cfg.book_type == "standard"
                else "interior/journal.html.j2")
    html = render(template, cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    # copy CSS next to the HTML so the relative <link> resolves
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path


def count_pages(html_path: Path) -> int:
    text = Path(html_path).read_text(encoding="utf-8")
    return len(re.findall(r'<section class="page"', text))


def pdf_page_count(pdf: Path) -> int:
    """Real rendered page count of a PDF (0 for a non-PDF stub)."""
    import fitz
    try:
        with fitz.open(str(pdf)) as doc:
            return doc.page_count
    except Exception:
        return 0


class InteriorError(RuntimeError):
    pass


def _verify_interior_margins(pdf: Path, trim_w: float = specs.TRIM_W_IN,
                             trim_h: float = specs.TRIM_H_IN,
                             tol_in: float = 0.06) -> None:
    """Fail the build if any interior text falls outside the page margins (e.g. a
    page with too many fields whose content runs off the bottom into the trim).
    KDP rejects interiors with text in the margins. Skips a non-PDF stub."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return
    x0s = specs.MARGIN_INSIDE_IN
    x1s = trim_w - specs.MARGIN_OUTSIDE_IN
    y0s = specs.MARGIN_TOPBOTTOM_IN
    y1s = trim_h - specs.MARGIN_TOPBOTTOM_IN
    bad = []
    for pno in range(doc.page_count):
        for b in doc[pno].get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    x0, y0, x1, y1 = (v / 72 for v in s["bbox"])
                    if (x0 < x0s - tol_in or x1 > x1s + tol_in
                            or y0 < y0s - tol_in or y1 > y1s + tol_in):
                        bad.append((pno + 1, s["text"].strip()[:24]))
    if bad:
        msg = "; ".join(f'p{p} "{t}"' for p, t in bad[:5])
        raise InteriorError(
            f"Interior {pdf.name} has text outside the margins "
            f"({len(bad)} span(s)): {msg}")


def build_interior_pdf(html_path: Path, out_dir: Path, runner=None,
                       book_type: str = "journal",
                       trim_w: float = specs.TRIM_W_IN,
                       trim_h: float = specs.TRIM_H_IN) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    pdf = out_dir / "interior.pdf"
    # Page margins come from CSS @page, not this flag: browse renders without
    # --prefer-css-page-size, so a CSS `@page { margin: 0 }` (interior.css)
    # overrides any --margins value. Journals zero the @page margin and inset via
    # fixed .page padding; standard books flow prose across many pages and set a
    # real `@page { margin: 0.6in }` in standard.html.j2 so every page is inset.
    html_to_pdf(Path(html_path), pdf,
                width_in=trim_w, height_in=trim_h,
                margins_in=0.0, runner=runner)
    _verify_interior_margins(pdf, trim_w, trim_h)
    pages = (pdf_page_count(pdf) if book_type == "standard"
             else count_pages(html_path))
    if book_type == "standard" and pages < 1:
        # The standard page count is load-bearing: the cover spine width is derived
        # from it. A 0 here means the rendered PDF failed to open or is empty —
        # fail loudly rather than ship a spineless, KDP-invalid cover.
        raise InteriorError(
            f"Standard interior {pdf.name} rendered 0 pages — the PDF failed to "
            f"open or is empty; the cover spine width would be wrong.")
    return pdf, pages


def build_epub(cfg: BookConfig, content: dict, out_dir: Path,
               cover_path: Path | None = None) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"book-{cfg.slug}")
    book.set_title(cfg.title)
    book.set_language("en")
    book.add_author(cfg.author)

    # Embed the finished, title-bearing ebook cover JPG (≈1 MB) rather than the
    # print-resolution PNG, keeping the EPUB light (KDP charges per-MB delivery
    # on the 70% royalty plan).
    if cover_path is not None and Path(cover_path).exists():
        cp = Path(cover_path)
        book.set_cover("cover" + cp.suffix, cp.read_bytes())

    def chapter(title, body_html, fname):
        c = epub.EpubHtml(title=title, file_name=fname, lang="en")
        c.content = f"<h1>{title}</h1>{body_html}"
        book.add_item(c)
        return c

    items = []
    if content.get("preface"):
        pre_html = "".join(f"<p>{p}</p>" for p in content["preface"].split("\n") if p.strip())
        items.append(chapter("Preface", pre_html, "preface.xhtml"))
    for i, ch in enumerate(content["chapters"], 1):
        body = "".join(f"<p>{p}</p>" for p in ch["paragraphs"])
        items.append(chapter(ch["title"], body, f"chap{i}.xhtml"))

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    out = Path(out_dir) / "interior.epub"
    out.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out), book)
    return out

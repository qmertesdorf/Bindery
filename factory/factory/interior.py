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
    html = render("interior/book.html.j2", cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    # copy CSS next to the HTML so the relative <link> resolves
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path


def count_pages(html_path: Path) -> int:
    text = Path(html_path).read_text(encoding="utf-8")
    return len(re.findall(r'<section class="page"', text))


def build_interior_pdf(html_path: Path, out_dir: Path, runner=None) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    pdf = out_dir / "interior.pdf"
    html_to_pdf(Path(html_path), pdf,
                width_in=specs.TRIM_W_IN, height_in=specs.TRIM_H_IN,
                margins_in=0.0, runner=runner)
    return pdf, count_pages(html_path)


def build_epub(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"petloss-{cfg.slug}")
    book.set_title(cfg.title)
    book.set_language("en")
    book.add_author(cfg.author)

    def chapter(title, body_html, fname):
        c = epub.EpubHtml(title=title, file_name=fname, lang="en")
        c.content = f"<h1>{title}</h1>{body_html}"
        book.add_item(c)
        return c

    intro = chapter("Welcome", f"<p>{content['intro']}</p><p>{content['how_to_use']}</p>", "intro.xhtml")
    prompts_html = "".join(f"<p>{p}</p><hr/>" for p in content["prompts"])
    prompts = chapter("Reflections", prompts_html, "prompts.xhtml")
    miles = chapter("Milestones", "".join(f"<p>{m}</p>" for m in content["milestones"]), "miles.xhtml")

    book.toc = (intro, prompts, miles)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", intro, prompts, miles]

    out = Path(out_dir) / "interior.epub"
    out.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out), book)
    return out

"""Stage 2: render interior to HTML (and later PDF + EPUB)."""
from __future__ import annotations
import shutil
from pathlib import Path
from .config import BookConfig
from .templating import render, TEMPLATES_DIR


def render_interior_html(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render("interior/book.html.j2", cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    # copy CSS next to the HTML so the relative <link> resolves
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path

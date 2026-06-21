"""Stage 5: emit upload checklist with pre-filled AI disclosure."""
from __future__ import annotations
from pathlib import Path
from .config import BookConfig
from .templating import render
from .copy import listing_description, listing_keywords
from . import specs


def _keywords(cfg: BookConfig) -> str:
    """Comma-joined KDP keywords for the markdown checklist (one source of truth in
    copy.listing_keywords — written for natural-language buyer intent, WS6b)."""
    return ", ".join(listing_keywords(cfg))


def make_checklist(cfg: BookConfig, pages: int, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render("checklist.md.j2",
                cfg=cfg, pages=pages,
                spine=specs.spine_width_in(pages, specs.spine_per_page(cfg.book_type)),
                royalty=specs.royalty_usd(cfg.price_usd, pages,
                                          colour=cfg.book_type in ("picture", "concept")),
                print_cost=specs.printing_cost_usd(pages,
                                                   colour=cfg.book_type in ("picture", "concept")),
                keywords=_keywords(cfg), blurb=listing_description(cfg))
    out = out_dir / "upload-checklist.md"
    out.write_text(md, encoding="utf-8")
    return out

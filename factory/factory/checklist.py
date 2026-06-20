"""Stage 5: emit upload checklist with pre-filled AI disclosure."""
from __future__ import annotations
from pathlib import Path
from .config import BookConfig
from .templating import render
from .copy import book_blurb
from . import specs


def _keywords(cfg: BookConfig) -> str:
    if cfg.book_type == "concept":
        base = ["children's animal book", "nature book for kids",
                "toddler animal picture book", "early reader animals",
                "bedtime animal book", "wildlife book for children",
                "preschool nature picture book"]
        return ", ".join(base[:7])
    if cfg.book_type == "picture":
        base = [f"{cfg.pet_kind} loss children's book",
                f"pet loss book for kids", "grief picture book",
                f"death of a {cfg.pet_kind} kids", "rainbow bridge children",
                "memorial gift child", "saying goodbye pet"]
        return ", ".join(base[:7])
    if cfg.book_type == "standard":
        # Derive simple keyword seeds from the title; the publisher refines these
        # against live Amazon search before upload.
        base = [cfg.title.lower(), "comfort read", "grief support book",
                "pet loss book", "coping with loss", "memorial gift",
                "rainbow bridge"]
        return ", ".join(base[:7])
    base = [f"{cfg.pet_kind} loss gift", f"{cfg.pet_kind} memorial journal",
            "pet loss grief journal", "pet bereavement", "rainbow bridge keepsake",
            "in memory of pet", f"loss of a {cfg.pet_kind}"]
    return ", ".join(base[:7])


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
                keywords=_keywords(cfg), blurb=book_blurb(cfg))
    out = out_dir / "upload-checklist.md"
    out.write_text(md, encoding="utf-8")
    return out

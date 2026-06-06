"""Stage 5: emit upload checklist with pre-filled AI disclosure."""
from __future__ import annotations
from pathlib import Path
from .config import BookConfig
from .templating import render
from . import specs


def _keywords(cfg: BookConfig) -> str:
    base = [f"{cfg.pet_kind} loss gift", f"{cfg.pet_kind} memorial journal",
            "pet loss grief journal", "pet bereavement", "rainbow bridge keepsake",
            "in memory of pet", f"loss of a {cfg.pet_kind}"]
    return ", ".join(base[:7])


def make_checklist(cfg: BookConfig, pages: int, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render("checklist.md.j2",
                cfg=cfg, pages=pages,
                spine=specs.spine_width_in(pages),
                royalty=specs.royalty_usd(cfg.price_usd, pages),
                print_cost=specs.printing_cost_usd(pages),
                keywords=_keywords(cfg))
    out = out_dir / "upload-checklist.md"
    out.write_text(md, encoding="utf-8")
    return out

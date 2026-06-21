"""WS6c — per-book provenance + rights log.

Writes a `provenance.json` recording how the book was generated: the art recipe
(engine, base model, LoRAs, guidance, seeds, upscale target/model, QA policy) and a
rights note. Two regimes the log keeps straight (verified research 2026-06-21):
  • KDP requires disclosing AI-generated content (images count even if hand-edited).
  • US Copyright Office registration: the human-authored TEXT and the human
    selection/arrangement ARE copyrightable, but AI-generated image parts must be
    disclaimed. KDP disclosure ≠ USCO registration — two separate things.

Pure (no I/O) `build_provenance`; `write_provenance` is the thin file writer."""
from __future__ import annotations
import json
from pathlib import Path
from .config import BookConfig
from . import specs


def build_provenance(cfg: BookConfig, content: dict, *, seed: int,
                     flagged=None) -> dict:
    """Assemble the provenance record from the config + generated content. Seeds are
    reconstructed from the deterministic schedule the art loop uses (page i →
    seed + i*17, cover → seed + 42), so the log matches a rerun without threading
    state out of the render loop."""
    flux = cfg.book_type in ("picture", "concept") and cfg.art_engine == "flux"
    pages = content.get("pages", [])
    art = {
        "engine": cfg.art_engine,
        "guidance": cfg.flux_guidance if flux else None,
        "style": (cfg.flux_style or content.get("art_style", "")) if flux else None,
        "seed_base": seed,
        "cover_seed": seed + 42,
    }
    if flux:
        from .flux_art import BASE_UNET
        art["base_model"] = BASE_UNET
        art["loras"] = [{"lora": c.lora, "trigger": c.trigger, "strength": c.strength}
                        for c in cfg.characters]
        art["upscale_px"] = specs.print_art_px(cfg.trim_w, cfg.trim_h)
        art["upscale_model"] = cfg.upscale_model or "lanczos (no ESRGAN model)"
    art["pages"] = [
        {"index": i, "subject": pg.get("subject", ""), "scene": pg.get("scene", ""),
         "seed": seed + i * 17}
        for i, pg in enumerate(pages, 1)]
    art["qa_policy"] = {
        "candidates": cfg.qa_candidates, "vqa": cfg.qa_vqa,
        "vqa_threshold": cfg.qa_vqa_threshold, "anatomy": cfg.qa_anatomy,
        "repair": cfg.qa_repair, "tifa": cfg.qa_tifa,
        "tifa_threshold": cfg.qa_tifa_threshold,
    }
    return {
        "slug": cfg.slug,
        "title": cfg.title,
        "author": cfg.author,
        "illustrator": cfg.illustrator,
        "book_type": cfg.book_type,
        "trim_in": [cfg.trim_w, cfg.trim_h],
        "pages_flagged_for_review": list(flagged or []),
        "art": art,
        "rights": {
            "kdp_ai_disclosure": "REQUIRED — declare AI-generated images (count even "
                                 "if hand-edited) and AI-assisted text in KDP's "
                                 "content questionnaire.",
            "usco_registration": "Human-authored text and the human selection/"
                                 "arrangement are copyrightable; AI-generated image "
                                 "parts must be disclaimed at registration.",
            "note": "KDP disclosure and USCO registration are separate regimes — "
                    "doing one does not satisfy the other.",
        },
    }


def write_provenance(cfg: BookConfig, content: dict, out_dir: Path, *, seed: int,
                     flagged=None) -> Path:
    """Write provenance.json into the book's output folder; returns the path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = build_provenance(cfg, content, seed=seed, flagged=flagged)
    out = out_dir / "provenance.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out

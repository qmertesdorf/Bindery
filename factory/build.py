"""One-command orchestrator for the pet-loss journal factory."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from factory.config import load_config
from factory.content import generate_content, claude_generate
from factory.interior import render_interior_html, build_interior_pdf, build_epub
from factory.art import ComfyClient, generate_picture_art
from factory.audit import ClaudeVisionAuditor
from factory.cover import build_cover
from factory.checklist import make_checklist

DEFAULT_SEED = 12345


def run_build(config_path, out_root="out", *, generate_fn=claude_generate,
              comfy=None, workflow=None, positive_node="6", sampler_node="3",
              runner=None, seed=DEFAULT_SEED, auditor=None) -> Path:
    cfg = load_config(config_path)
    out_dir = Path(out_root) / cfg.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # ① content
    content = generate_content(cfg, generate_fn=generate_fn)
    (out_dir / "content.json").write_text(json.dumps(content, indent=2), encoding="utf-8")

    # Resolve image backend + workflow up front (picture needs art before interior).
    if comfy is None:
        comfy = ComfyClient()
    if workflow is None:
        workflow = json.loads((Path(__file__).parent / "comfyui" / "workflow.template.json")
                              .read_text(encoding="utf-8"))
    if "REPLACE_WITH_YOUR_CHECKPOINT" in json.dumps(workflow):
        raise SystemExit(
            "ComfyUI workflow still has the placeholder checkpoint. Edit "
            "comfyui/workflow.template.json and set ckpt_name to a real checkpoint "
            "from your ComfyUI install before running the factory.")

    if cfg.book_type == "picture":
        # ②③ Picture books illustrate every page, so art runs BEFORE the interior
        # (the interior embeds page_NN.png). Consistency is enforced by the auditor.
        if auditor is None:
            auditor = ClaudeVisionAuditor()
        art = generate_picture_art(cfg, content, out_dir, comfy, workflow,
                                   positive_node=positive_node,
                                   sampler_node=sampler_node, seed=seed,
                                   auditor=auditor)
        html = render_interior_html(cfg, content, out_dir)
        _, pages = build_interior_pdf(html, out_dir, runner=runner,
                                      book_type=cfg.book_type,
                                      trim_w=cfg.trim_w, trim_h=cfg.trim_h)
        art_path = art["cover"]
    else:
        # ② interior (PDF + page count; EPUB built after art so it can embed the cover)
        html = render_interior_html(cfg, content, out_dir)
        _, pages = build_interior_pdf(html, out_dir, runner=runner,
                                      book_type=cfg.book_type,
                                      trim_w=cfg.trim_w, trim_h=cfg.trim_h)
        # ③ art
        art_path = comfy.generate(workflow, positive_node=positive_node,
                                  sampler_node=sampler_node, prompt=cfg.art_prompt,
                                  seed=seed, out_path=out_dir / "art.png")

    # ④ cover (paperback wrap; ebook JPG only for standard books), then EPUB
    #    embedding that JPG cover. Journals are paperback-only — no Kindle edition.
    _, cover_jpg = build_cover(cfg, pages, art_path, out_dir, runner=runner,
                               make_ebook_cover=cfg.makes_ebook)
    if cfg.makes_ebook:
        build_epub(cfg, content, out_dir, cover_path=cover_jpg)

    # ⑤ checklist
    make_checklist(cfg, pages, out_dir)
    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Build a KDP pet-loss journal bundle")
    ap.add_argument("config", help="path to book.config.json")
    ap.add_argument("--out", default="out", help="output root dir")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    out = run_build(args.config, out_root=args.out, seed=args.seed)
    print(f"Done. Bundle in: {out}")


if __name__ == "__main__":
    main()

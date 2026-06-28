"""One-command orchestrator for the pet-loss journal factory."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from factory.config import load_config
from factory.content import generate_content, claude_generate
from factory.interior import render_interior_html, build_interior_pdf, build_epub
from factory.art import ComfyClient, generate_picture_art
from factory.flux_art import generate_flux_art, generate_concept_art
from factory.qa import build_ensemble_auditor
from factory.cover import build_cover
from factory.checklist import make_checklist
from factory.copy import verify_listing_copy
from factory.paste_console import make_paste_console
from factory.readability import verify_readability
from factory.provenance import write_provenance
from factory.subject_fallback import suggest_subject


def _default_suggest_fn(generate_fn):
    """Wrap the book's LLM generate_fn as a keyword-arg subject suggester for the
    concept auto-subject-fallback path."""
    def _fn(*, theme, used, failed):
        return suggest_subject(generate_fn, theme, used, failed)
    return _fn


DEFAULT_SEED = 12345


def run_build(config_path, out_root="out", *, generate_fn=claude_generate,
              comfy=None, workflow=None, positive_node="6", sampler_node="3",
              runner=None, seed=DEFAULT_SEED, auditor=None, suggest_fn=None) -> Path:
    cfg = load_config(config_path)
    out_dir = Path(out_root) / cfg.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # ① content — reuse an already-generated & reviewed content.json if present, so
    # repeat art passes don't silently re-roll the story (delete it to force fresh).
    content_path = out_dir / "content.json"
    if content_path.exists():
        content = json.loads(content_path.read_text(encoding="utf-8"))
    else:
        content = generate_content(cfg, generate_fn=generate_fn)
        content_path.write_text(json.dumps(content, indent=2), encoding="utf-8")

    # WS6a readability guard: kids' (picture/concept) text must read at/under the
    # early-reader grade ceiling. Runs on cached content too (the LLM can't be
    # trusted to self-level), and only for kids' books — adult grief prose is exempt.
    if cfg.book_type in ("picture", "concept"):
        rep = verify_readability(content, cfg.max_reading_grade)
        print(f"[readability] kids' text grade {rep['grade']} "
              f"(ease {rep['reading_ease']}), ceiling {cfg.max_reading_grade:g}")

    # Resolve image backend up front (picture needs art before interior). Give the
    # real client a restart_fn so a native ComfyUI crash mid-build self-heals
    # (relaunch + re-submit) instead of killing the whole render; no-op without a
    # local ComfyUI install (tests inject their own comfy, so they're unaffected).
    if comfy is None:
        from factory.comfy_runtime import make_restart_fn
        comfy = ComfyClient(restart_fn=make_restart_fn())

    flux = cfg.book_type in ("picture", "concept") and cfg.art_engine == "flux"
    if not flux:
        # The SDXL path needs the workflow template + a real checkpoint; the Flux
        # path builds its own graph and needs neither.
        if workflow is None:
            workflow = json.loads((Path(__file__).parent / "comfyui" / "workflow.template.json")
                                  .read_text(encoding="utf-8"))
        if "REPLACE_WITH_YOUR_CHECKPOINT" in json.dumps(workflow):
            raise SystemExit(
                "ComfyUI workflow still has the placeholder checkpoint. Edit "
                "comfyui/workflow.template.json and set ckpt_name to a real checkpoint "
                "from your ComfyUI install before running the factory.")

    if cfg.book_type in ("picture", "concept"):
        # ②③ Picture/concept books illustrate every page, so art runs BEFORE the
        # interior (the interior embeds page_NN.png). The auditor enforces quality.
        # Reuse already-rendered (and reviewed) art if every page + cover exists, so
        # a rerun to fix metadata or the cover doesn't re-roll every illustration —
        # symmetric to the content.json reuse above. Delete the page_*.png to force
        # a fresh render.
        existing_pages = [out_dir / f"page_{i:02d}.png"
                          for i in range(1, len(content["pages"]) + 1)]
        cover_png = out_dir / "art.png"
        if all(p.exists() for p in existing_pages) and cover_png.exists():
            art = {"pages": existing_pages, "cover": cover_png, "flagged": []}
        else:
            if auditor is None:
                # Bare ClaudeVisionAuditor unless the book enables WS1 QA stages,
                # in which case this returns an EnsembleAuditor (drop-in).
                auditor = build_ensemble_auditor(cfg)
            if cfg.book_type == "concept":
                art = generate_concept_art(
                    cfg, content, out_dir, comfy, seed=seed, auditor=auditor,
                    generate_fn=generate_fn,
                    suggest_fn=suggest_fn or _default_suggest_fn(generate_fn))
            elif flux:
                art = generate_flux_art(cfg, content, out_dir, comfy,
                                        seed=seed, auditor=auditor)
            else:
                art = generate_picture_art(cfg, content, out_dir, comfy, workflow,
                                           positive_node=positive_node,
                                           sampler_node=sampler_node, seed=seed,
                                           auditor=auditor)
        # Persist content.json AFTER concept art so an auto-subject-fallback swap
        # (which mutates content["pages"][i] in place) reaches the interior PDF
        # caption rendering. No-op when nothing swapped (rewrites identical JSON).
        if cfg.book_type == "concept":
            content_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
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
                               make_ebook_cover=cfg.makes_ebook, auditor=auditor)
    if cfg.makes_ebook:
        build_epub(cfg, content, out_dir, cover_path=cover_jpg)

    # ⑤ checklist + interactive HTML paste console (the house standard for the
    #    manual KDP upload — one field at a time, copy-to-clipboard). Guard the
    #    listing copy first (WS6b): valid KDP keywords + natural-language, un-stuffed.
    verify_listing_copy(cfg)
    make_checklist(cfg, pages, out_dir)
    make_paste_console(cfg, pages, out_dir)

    # ⑥ provenance + rights log (WS6c): records the art recipe, seeds, QA policy, and
    #    the AI-disclosure / copyright notes for this title.
    flagged = art.get("flagged", []) if cfg.book_type in ("picture", "concept") else []
    write_provenance(cfg, content, out_dir, seed=seed, flagged=flagged)
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

"""Full picture-book build using the validated Approach B recipe.

Two-hero IPAdapter character conditioning + two-tier vision audit, then assembles
the KDP bundle with the factory's existing interior/cover/checklist stages.

  hero_child  : child only (animal-suppressed)         -> absence / grief pages
  hero_pair   : child + dog, boy carried from hero_child -> memory pages
Each page is conditioned (IPAdapterAdvanced) on the hero matching whether Biscuit
is in that page's scene, then audited; a page that can't pass keeps its best
attempt (flagged) rather than failing the whole book.

This is a prototype runner; once the output is approved it folds into build.py.
Usage:  python build_picture_ipa.py [books/dog-loss-kids.config.json]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import requests

from factory.config import load_config
from factory.content import claude_generate
from factory.picture_content import generate_picture_content
from factory.art import ComfyClient, square_workflow, _generate_audited
from factory.audit import ClaudeVisionAuditor
from factory.interior import render_interior_html, build_interior_pdf
from factory.cover import build_cover
from factory.checklist import make_checklist

BASE = "http://127.0.0.1:8188"
WEIGHT, END_AT = 0.5, 0.6  # lower than the hero so page scenes compose richer backgrounds
NO_ANIMALS = "dog, puppy, animal, pet, creature, second animal"
IPA_TEMPLATE = Path("comfyui") / "workflow.ipadapter.template.json"


def upload_image(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{BASE}/upload/image",
                          files={"image": (Path(path).name, f, "image/png")},
                          data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()["name"]


SMILE_NEG = "big smile, grin, grinning, laughing, cheerful, beaming"


def ipa_page(comfy, auditor, hero_name, *, style, scene, anchor, ref_path, out,
             seed, suppress_animals=False, no_smile=False, weight=WEIGHT,
             end_at=END_AT, max_tries=4) -> bool:
    """Generate one IPAdapter page conditioned on hero_name; audit vs ref_path.
    Returns True if it passed; keeps the best attempt (never fails the book)."""
    issues: list[str] = []
    for attempt in range(max_tries):
        wf = json.loads(IPA_TEMPLATE.read_text(encoding="utf-8"))
        wf["22"]["inputs"]["image"] = hero_name
        wf["23"]["inputs"]["weight"] = weight
        wf["23"]["inputs"]["end_at"] = end_at
        neg_extra = ([NO_ANIMALS] if suppress_animals else []) + ([SMILE_NEG] if no_smile else [])
        if neg_extra:
            wf["7"]["inputs"]["text"] = wf["7"]["inputs"]["text"] + ", " + ", ".join(neg_extra)
        prompt = f"{style}. {scene}"
        if issues:
            prompt += " Fix these problems: " + "; ".join(issues)
        comfy.generate(wf, positive_node="6", sampler_node="3", prompt=prompt,
                       seed=seed + attempt * 1009, out_path=out)
        v = auditor.audit(out, anchor=anchor, reference_path=ref_path, scene=scene)
        if v.get("ok"):
            print(f"  [audit] {out.name}: OK" + (f" (try {attempt + 1})" if attempt else ""),
                  flush=True)
            return True
        issues = v.get("issues", [])
        print(f"  [audit] {out.name}: REJECT {attempt + 1}/{max_tries} — {'; '.join(issues)}",
              flush=True)
    print(f"  [audit] {out.name}: kept best after {max_tries} tries (REVIEW)", flush=True)
    return False


def main() -> int:
    cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "books/dog-loss-kids.config.json")
    out = Path("out") / cfg.slug
    out.mkdir(parents=True, exist_ok=True)
    comfy = ComfyClient()
    auditor = ClaudeVisionAuditor()

    print("[book] 1/5 content (bible + pages)…", flush=True)
    content = generate_picture_content(cfg, claude_generate)
    (out / "content.json").write_text(json.dumps(content, indent=2), encoding="utf-8")
    anchor, style = content["character_anchor"], content["art_style"]
    child = anchor.split(cfg.pet_name)[0].rstrip(" .,;")
    dog_desc = (anchor.split(cfg.pet_name, 1)[1].lstrip(" is").strip().rstrip(".")
                if cfg.pet_name in anchor else "a small dog")
    base_wf = json.loads((Path("comfyui") / "workflow.template.json").read_text(encoding="utf-8"))

    print("[book] 2/5 hero A (child only)…", flush=True)
    wfc = square_workflow(base_wf)
    wfc["7"]["inputs"]["text"] = wfc["7"]["inputs"]["text"] + ", " + NO_ANIMALS
    hero_child = out / "hero_child.png"
    _generate_audited(
        comfy, wfc, positive_node="6", sampler_node="3",
        prompt=(f"{style}. A single young child, full body, standing, facing forward, "
                f"calm gentle neutral expression, plain pale background, no animals. {child}"),
        seed=777, out_path=hero_child, auditor=auditor, anchor=child,
        reference_path=None, scene="a single child, full body, no animals", max_tries=5)
    child_name = upload_image(hero_child)

    print("[book] 3/5 hero B (child + dog, boy from hero A)…", flush=True)
    hero_pair = out / "hero_pair.png"
    ipa_page(comfy, auditor, child_name, style=style,
             scene=(f"the same boy with a calm gentle smile kneeling with his arm gently "
                    f"around his {dog_desc}, both shown full body together, plain pale background"),
             anchor=anchor, ref_path=hero_child, out=hero_pair, seed=555,
             weight=0.55, end_at=0.7, max_tries=5)
    pair_name = upload_image(hero_pair)

    print("[book] 4/5 pages…", flush=True)
    pages = content["pages"]
    n = len(pages)
    flagged = []
    grief = {"sad", "lonely", "wistful", "grieving", "somber", "melancholy", "heavy",
             "aching", "empty", "quiet", "reflective", "missing", "sorrowful", "tearful"}
    for i, pg in enumerate(pages, 1):
        scene = pg["scene"]
        mood = pg.get("mood", "tender")
        dog = pg.get("moment") == "memory"  # authored by the bible, not guessed
        somber = mood.lower() in grief
        hero_name, ref = (pair_name, hero_pair) if dog else (child_name, hero_child)
        audit_anchor = anchor if dog else child  # present pages: don't expect the absent dog
        expr = "a quiet, gentle, NOT smiling face" if somber else "a warm gentle smile"
        cast = "only the boy and his dog" if dog else "only the boy, no other people, no animals"
        art_scene = (f"{scene} The boy shows {expr}, clearly {mood}. {cast}. "
                     f"Richly illustrated, detailed background setting.")
        print(f"[book]   page {i}/{n} ({'memory+dog' if dog else 'present,no dog'}, "
              f"{mood}{'/no-smile' if somber else ''}): {scene[:40]}", flush=True)
        # memory pages hold two characters → a touch more conditioning; present
        # pages have only the boy → lower weight lets the setting compose richer.
        w, e = (0.6, 0.8) if dog else (0.5, 0.6)
        ok = ipa_page(comfy, auditor, hero_name, style=style, scene=art_scene,
                      anchor=audit_anchor, ref_path=ref, out=out / f"page_{i:02d}.png",
                      seed=100 + i, suppress_animals=not dog, no_smile=somber,
                      weight=w, end_at=e)
        if not ok:
            flagged.append(i)

    print("[book] 5/5 cover + interior + checklist…", flush=True)
    cover = out / "art.png"
    comfy.generate(
        base_wf, positive_node="6", sampler_node="3",
        prompt=(f"{style}. Front cover illustration, the boy and his {dog_desc} sitting "
                f"together on a grassy hill at warm golden sunset, tender and hopeful. {anchor}"),
        seed=42, out_path=cover)

    html = render_interior_html(cfg, content, out)
    _, npages = build_interior_pdf(html, out, book_type=cfg.book_type,
                                   trim_w=cfg.trim_w, trim_h=cfg.trim_h)
    build_cover(cfg, npages, cover, out, make_ebook_cover=cfg.makes_ebook)
    make_checklist(cfg, npages, out)

    print(f"[book] DONE — bundle in {out} ({npages} interior pages).", flush=True)
    if flagged:
        print(f"[book] REVIEW these pages (audit not fully passed): {flagged}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

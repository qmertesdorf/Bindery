"""Tuning harness for Approach B (IPAdapter character conditioning).

Generates ONE clean, audited child hero (persisted + reused across runs), then
conditions a story page on it via IPAdapterAdvanced and audits the result — so
you can sweep the IPAdapter weight / end_at against a FIXED hero cheaply.

  python ipadapter_smoke.py [config] [weight=0.55] [end_at=0.7] [fresh]

`fresh` forces regeneration of the bible + hero (otherwise the saved hero in
out/<slug>/_ipa_smoke/ is reused). Eyeball hero.png vs page_ipa.png.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import requests

from factory.config import load_config
from factory.content import claude_generate
from factory.picture_content import generate_picture_content
from factory.art import ComfyClient, square_workflow, _generate_audited
from factory.audit import ClaudeVisionAuditor

BASE = "http://127.0.0.1:8188"
NO_ANIMALS = "dog, puppy, animal, pet, creature, beagle, fox, cat, kitten"


def upload_image(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{BASE}/upload/image",
                          files={"image": (Path(path).name, f, "image/png")},
                          data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()["name"]


def ensure_hero(cfg, out: Path, comfy, auditor, fresh: bool) -> dict:
    """Return {hero, anchor, style, scene}; build+persist a clean hero if needed."""
    meta_path = out / "meta.json"
    hero = out / "hero.png"
    if not fresh and hero.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"[ipa] reusing hero {hero}", flush=True)
        return {"hero": hero, **meta}

    print("[ipa] generating story bible via claude…", flush=True)
    content = generate_picture_content(cfg, claude_generate)
    anchor, style = content["character_anchor"], content["art_style"]
    scene = content["pages"][0]["scene"]
    print(f"[ipa]   anchor: {anchor}", flush=True)

    print("[ipa] rendering CHILD+DOG hero (audited — anchors both identities)…", flush=True)
    base_wf = json.loads((Path("comfyui") / "workflow.template.json").read_text(encoding="utf-8"))
    _generate_audited(
        comfy, square_workflow(base_wf), positive_node="6", sampler_node="3",
        prompt=(f"{style}. A cheerful little boy kneeling with his arm gently around "
                f"his small fluffy white dog, both shown full body together, facing "
                f"forward, plain pale background. {anchor}"),
        seed=777, out_path=hero, auditor=auditor, anchor=anchor, reference_path=None,
        scene="the boy and his small white dog together, full body", max_tries=4)
    meta = {"anchor": anchor, "style": style, "scene": scene}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"hero": hero, **meta}


def main() -> int:
    args = sys.argv[1:]
    fresh = "fresh" in args
    args = [a for a in args if a != "fresh"]
    cfg_path = args[0] if len(args) > 0 else "books/dog-loss-kids.config.json"
    weight = float(args[1]) if len(args) > 1 else 0.55
    end_at = float(args[2]) if len(args) > 2 else 0.7
    cfg = load_config(cfg_path)
    out = Path("out") / cfg.slug / "_ipa_smoke"
    out.mkdir(parents=True, exist_ok=True)
    comfy = ComfyClient()
    auditor = ClaudeVisionAuditor()

    h = ensure_hero(cfg, out, comfy, auditor, fresh)
    name = upload_image(h["hero"])
    print(f"[ipa] hero uploaded as {name}", flush=True)

    scene = os.environ.get("IPA_SCENE") or h["scene"]  # override to test a specific scene
    print(f"[ipa] generating page via IPAdapter (weight={weight}, end_at={end_at})…", flush=True)
    print(f"[ipa]   scene: {scene}", flush=True)
    ipa_wf = json.loads(
        (Path("comfyui") / "workflow.ipadapter.template.json").read_text(encoding="utf-8"))
    ipa_wf["22"]["inputs"]["image"] = name
    ipa_wf["23"]["inputs"]["weight"] = weight
    ipa_wf["23"]["inputs"]["end_at"] = end_at
    page = out / f"page_w{weight}_e{end_at}.png"
    comfy.generate(ipa_wf, positive_node="6", sampler_node="3",
                   prompt=f"{h['style']}. {scene}", seed=101, out_path=page)

    pv = auditor.audit(page, anchor=h["anchor"], reference_path=h["hero"], scene=scene)
    print(f"[ipa] PAGE VERDICT (w={weight}, end_at={end_at}): {pv}", flush=True)
    print(f"[ipa] eyeball {h['hero']} vs {page}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

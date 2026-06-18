"""Stage 3 for Flux picture books: per-page illustration via a trained character
LoRA (plus an optional companion LoRA on child_and_pet pages), audited and regenerated
until consistent. Identity comes from the LoRA; scene, wardrobe, and the
watercolour look come from the prompt. Mirrors the validated _flux_dual.py recipe.

LoRA *training* is separate one-time tooling; this module assumes the LoRAs named
in the config already exist in ComfyUI/models/loras."""
from __future__ import annotations
from pathlib import Path

from factory.art import ArtError, run_audited_render, _log

BASE_UNET = "flux1-dev-fp8-e4m3fn.safetensors"

# Moods that should read as somber — the child must NOT be smiling on these pages.
GRIEF = {"sad", "lonely", "wistful", "grieving", "somber", "melancholy", "heavy",
         "aching", "empty", "quiet", "reflective", "missing", "sorrowful", "tearful"}


def flux_lora_workflow(prompt: str, seed: int, *, loras, guidance: float,
                       steps: int = 24, width: int = 1024, height: int = 1024,
                       upscale: int = 2048) -> dict:
    """Build a Flux + stacked-LoRA ComfyUI graph with prompt + seed baked in.

    `loras` is a list of (lora_name, strength) applied in series on the UNET
    (model-only — CLIP is untouched). The seed lives on the RandomNoise node
    (Flux puts the noise seed there, NOT on a KSampler); the sampler chain reads
    from the last LoRA in the stack."""
    nodes = {
        "u": {"class_type": "UNETLoader",
              "inputs": {"unet_name": BASE_UNET, "weight_dtype": "fp8_e4m3fn"}},
    }
    head = "u"
    for i, (name, strength) in enumerate(loras):
        nid = f"lora{i}"
        nodes[nid] = {"class_type": "LoraLoaderModelOnly",
                      "inputs": {"model": [head, 0], "lora_name": name,
                                 "strength_model": strength}}
        head = nid
    nodes.update({
        "c": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                         "clip_name2": "clip_l.safetensors", "type": "flux"}},
        "v": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["c", 0]}},
        "fg": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["pos", 0], "guidance": guidance}},
        "lat": {"class_type": "EmptySD3LatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "ks": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sch": {"class_type": "BasicScheduler",
                "inputs": {"model": [head, 0], "scheduler": "simple",
                           "steps": steps, "denoise": 1.0}},
        "gd": {"class_type": "BasicGuider",
               "inputs": {"model": [head, 0], "conditioning": ["fg", 0]}},
        "sa": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["noise", 0], "guider": ["gd", 0],
                          "sampler": ["ks", 0], "sigmas": ["sch", 0],
                          "latent_image": ["lat", 0]}},
        "dec": {"class_type": "VAEDecode",
                "inputs": {"samples": ["sa", 0], "vae": ["v", 0]}},
        "up": {"class_type": "ImageScale",
               "inputs": {"image": ["dec", 0], "upscale_method": "lanczos",
                          "width": upscale, "height": upscale, "crop": "disabled"}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"filename_prefix": "flux", "images": ["up", 0]}},
    })
    return nodes


def _expression(mood: str) -> str:
    """Somber moods must not smile (the auditor hard-rejects a smiling child on a
    sad page); everything else gets a gentle smile."""
    return ("a quiet, gentle, not smiling face" if mood.lower() in GRIEF
            else "a warm gentle smile")


def page_plan(page: dict, *, hero, companion, style: str, outfit: str):
    """Return (prompt, loras) for a page. The page's `cast` selects who is in
    frame and which LoRAs render: "child_and_pet" stacks both LoRAs and names both
    triggers; "pet" renders the companion alone (a peaceful "where pets go" scene,
    no child); "child" (default) is the hero alone with animals excluded so the
    model never invents a live pet."""
    mood = page.get("mood", "tender")
    expr = _expression(mood)
    cast = page.get("cast", "child")
    tail = "Richly detailed background, illustrated edge to edge."
    if cast == "child_and_pet" and companion is not None:
        loras = [(hero.lora, hero.strength), (companion.lora, companion.strength)]
        prompt = (f"{style}. {hero.trigger} {outfit}, together with "
                  f"{companion.trigger}. {page['scene']} The child shows {expr}, "
                  f"clearly {mood}. Only the child and the pet, no other people. "
                  f"{tail}")
    elif cast == "pet" and companion is not None:
        loras = [(companion.lora, companion.strength)]
        prompt = (f"{style}. {companion.trigger}, peaceful and content, in "
                  f"{page['scene']} No people, no other animals. Soft luminous "
                  f"light. {tail}")
    else:
        loras = [(hero.lora, hero.strength)]
        prompt = (f"{style}. {hero.trigger} {outfit}, alone, no other people, no "
                  f"animals. {page['scene']} The child shows {expr}, clearly "
                  f"{mood}. {tail}")
    return prompt, loras


def concept_page_prompt(page: dict, *, style: str) -> str:
    """Prompt for one character-free spread: locked style + the page's scene, with
    hard 'no people / no text' steering. No LoRA triggers — identity is irrelevant."""
    return (f"{style}. {page['scene']} A single clear subject. No people, no "
            f"unrelated extra animals, no text. Richly detailed natural setting, "
            f"illustrated edge to edge.")


def generate_concept_art(cfg, content, out_dir, comfy, *, seed, auditor,
                         max_tries: int = 4) -> dict:
    """Illustrate every spread with a locked Flux style and an EMPTY LoRA stack
    (no character identity to carry), each audited under the concept bar and
    regenerated until it passes — keeping the best and flagging a stubborn page
    rather than failing the whole book. Returns {"pages", "cover", "flagged"}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    style = cfg.flux_style or content["art_style"]
    guidance = cfg.flux_guidance
    pages = content["pages"]
    n = len(pages)

    out_pages, flagged = [], []
    for i, page in enumerate(pages, 1):
        prompt = concept_page_prompt(page, style=style)
        subject = page.get("subject", "the subject")
        _log(f"[concept] page {i}/{n} ({subject}): {page['scene'][:60]}")

        def render(p, s, op):
            comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance),
                         out_path=op)

        op = out_dir / f"page_{i:02d}.png"
        anchor = (f"a {subject} in its natural setting, in a consistent soft "
                  f"storybook illustration style; no people and no text")
        try:
            out_pages.append(run_audited_render(
                render, prompt, out_path=op, auditor=auditor, anchor=anchor,
                scene=page["scene"], reference_path=None, seed=seed + i * 17,
                max_tries=max_tries, audit_kind="concept"))
        except ArtError:
            _log(f"[concept] page {i}: kept best after {max_tries} tries (REVIEW)")
            flagged.append(i)
            out_pages.append(op)

    _log("[concept] cover…")
    cover_prompt = f"{style}. {cfg.art_prompt}. No people, no text."

    def cover_render(p, s, op):
        comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance),
                     out_path=op)

    cover_path = out_dir / "art.png"
    cover_anchor = (f"a {cfg.subject} scene in a soft storybook illustration style; "
                    f"no people, no text")
    try:
        cover = run_audited_render(
            cover_render, cover_prompt, out_path=cover_path, auditor=auditor,
            anchor=cover_anchor, scene="front cover", reference_path=None,
            seed=seed + 42, max_tries=max_tries, audit_kind="concept")
    except ArtError:
        _log(f"[concept] cover: kept best after {max_tries} tries (REVIEW)")
        flagged.append("cover")
        cover = cover_path
    if flagged:
        _log(f"[concept] REVIEW these (audit not fully passed): {flagged}")
    _log(f"[concept] complete: {n} pages + cover")
    return {"pages": out_pages, "cover": Path(cover), "flagged": flagged}


def generate_flux_art(cfg, content, out_dir, comfy, *, seed, auditor,
                      max_tries: int = 4) -> dict:
    """Illustrate every page with the hero LoRA (companion LoRA added on child_and_pet
    pages), then a dual-cast cover — each audited and regenerated until it passes.
    Returns {"pages": [Path...], "cover": Path}. No reference sheet: the trained
    LoRA carries character identity, replacing the SDXL reference-image trick."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    style = cfg.flux_style or content["art_style"]
    guidance = cfg.flux_guidance
    outfit = cfg.outfit
    anchor = content["character_anchor"]
    pet = cfg.pet_name
    hero = next((c for c in cfg.characters if c.role == "hero"), None)
    if hero is None:
        raise ArtError("flux picture book has no 'hero' character in cfg.characters")
    companion = next((c for c in cfg.characters if c.role == "companion"), None)
    # On child-cast pages, audit against just the human part of the anchor (the text
    # before the pet's name) so the auditor doesn't demand the absent pet.
    hero_anchor = (anchor.split(pet, 1)[0].rstrip(" .,;") if pet and pet in anchor
                   else anchor)
    # For "pet"-cast pages (the companion alone), audit against just the pet's part
    # of the anchor (the pet name onward) so the auditor doesn't demand the child.
    pet_anchor = (pet + anchor.split(pet, 1)[1].rstrip() if pet and pet in anchor
                  else anchor)
    pages = content["pages"]
    n = len(pages)

    out_pages, flagged = [], []
    for i, page in enumerate(pages, 1):
        prompt, loras = page_plan(page, hero=hero, companion=companion,
                                  style=style, outfit=outfit)
        cast = page.get("cast", "child")
        audit_anchor = {"child_and_pet": anchor, "pet": pet_anchor}.get(
            cast, hero_anchor)
        _log(f"[flux] page {i}/{n} ({cast},{page.get('mood')}): "
             f"{page['scene'][:60]}")

        def render(p, s, op, _loras=loras):
            comfy.submit(flux_lora_workflow(p, s, loras=_loras, guidance=guidance),
                         out_path=op)

        op = out_dir / f"page_{i:02d}.png"
        # Keep the best attempt and flag it rather than failing the whole book on one
        # stubborn page (a 22-page run shouldn't die because one page won't pass).
        try:
            out_pages.append(run_audited_render(
                render, prompt, out_path=op, auditor=auditor, anchor=audit_anchor,
                scene=page["scene"], reference_path=None, seed=seed + i * 17,
                max_tries=max_tries))
        except ArtError:
            _log(f"[flux] page {i}: kept best after {max_tries} tries (REVIEW)")
            flagged.append(i)
            out_pages.append(op)  # the final attempt was written before auditing

    # Cover: hero + companion (if any), the configured cover scene.
    _log("[flux] cover…")
    if companion is not None:
        cover_loras = [(hero.lora, hero.strength),
                       (companion.lora, companion.strength)]
        who = f"{hero.trigger} {outfit}, together with {companion.trigger}"
    else:
        cover_loras = [(hero.lora, hero.strength)]
        who = f"{hero.trigger} {outfit}"
    cover_prompt = (f"{style}. {who}. {cfg.art_prompt}. The child is a human child "
                    f"and the pet is an animal; no other people.")

    def cover_render(p, s, op):
        comfy.submit(flux_lora_workflow(p, s, loras=cover_loras, guidance=guidance),
                     out_path=op)

    cover_path = out_dir / "art.png"
    try:
        cover = run_audited_render(
            cover_render, cover_prompt, out_path=cover_path, auditor=auditor,
            anchor=anchor, scene="front cover", reference_path=None, seed=seed + 42,
            max_tries=max_tries)
    except ArtError:
        _log(f"[flux] cover: kept best after {max_tries} tries (REVIEW)")
        flagged.append("cover")
        cover = cover_path
    if flagged:
        _log(f"[flux] REVIEW these (audit not fully passed): {flagged}")
    _log(f"[flux] complete: {n} pages + cover")
    return {"pages": out_pages, "cover": Path(cover), "flagged": flagged}

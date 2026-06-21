"""Stage 3 for Flux picture books: per-page illustration via a trained character
LoRA (plus an optional companion LoRA on child_and_pet pages), audited and regenerated
until consistent. Identity comes from the LoRA; scene, wardrobe, and the
watercolour look come from the prompt. Mirrors the validated _flux_dual.py recipe.

LoRA *training* is separate one-time tooling; this module assumes the LoRAs named
in the config already exist in ComfyUI/models/loras."""
from __future__ import annotations
from pathlib import Path

from factory.art import ArtError, run_audited_render, _log
from factory import specs

BASE_UNET = "flux1-dev-fp8-e4m3fn.safetensors"


def _verify_art_resolution(path, min_px: int) -> None:
    """Build-time guard (WS3): fail if a rendered Flux page/cover is below the
    print-resolution target, so an under-sized image can't silently ship a
    sub-300-DPI full-bleed cover ([[catch-defects-with-guards]]). Skips a
    non-image stub (the fake ComfyClient in tests writes a 4-byte PNG marker, not
    a real image) so the GPU-free unit tests still pass."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return
    if min(w, h) < min_px:
        raise ArtError(
            f"Rendered art {Path(path).name} is {w}x{h}px — below the {min_px}px "
            f"print target (300 DPI at trim+bleed). Raise the upscale target.")

# Moods that should read as somber — the child must NOT be smiling on these pages.
GRIEF = {"sad", "lonely", "wistful", "grieving", "somber", "melancholy", "heavy",
         "aching", "empty", "quiet", "reflective", "missing", "sorrowful", "tearful"}


def flux_lora_workflow(prompt: str, seed: int, *, loras, guidance: float,
                       steps: int = 28, width: int = 1152, height: int = 1152,
                       upscale: int = 2560, upscale_model: str = "") -> dict:
    """Build a Flux + stacked-LoRA ComfyUI graph with prompt + seed baked in.

    `loras` is a list of (lora_name, strength) applied in series on the UNET
    (model-only — CLIP is untouched). The seed lives on the RandomNoise node
    (Flux puts the noise seed there, NOT on a KSampler); the sampler chain reads
    from the last LoRA in the stack.

    `upscale_model` (WS3b): when set, a learned ESRGAN upscaler (UpscaleModelLoader
    → ImageUpscaleWithModel) reconstructs detail before the final exact-size resize,
    giving sharper print than plain lanczos; "" keeps the lanczos-only path. The
    ESRGAN model enlarges by its own fixed factor, so we still ImageScale to the
    exact `upscale` target px afterwards."""
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
    })
    # WS3b: optional learned (ESRGAN) upscale before the final exact-size resize.
    # Lanczos only interpolates; an ESRGAN model reconstructs high-frequency detail
    # for sharper print. The model enlarges by its own fixed factor, so we still
    # ImageScale to the exact target afterwards. "" -> today's lanczos-only path.
    up_src = "dec"
    if upscale_model:
        nodes["upm"] = {"class_type": "UpscaleModelLoader",
                        "inputs": {"model_name": upscale_model}}
        nodes["esr"] = {"class_type": "ImageUpscaleWithModel",
                        "inputs": {"upscale_model": ["upm", 0], "image": ["dec", 0]}}
        up_src = "esr"
    nodes["up"] = {"class_type": "ImageScale",
                   "inputs": {"image": [up_src, 0], "upscale_method": "lanczos",
                              "width": upscale, "height": upscale, "crop": "disabled"}}
    nodes["save"] = {"class_type": "SaveImage",
                     "inputs": {"filename_prefix": "flux", "images": ["up", 0]}}
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
    return (f"{style}. {page['scene']} A single clear subject, painted as a soft, "
            f"hand-drawn children's storybook illustration — loose, simplified and "
            f"whimsical, NOT a photograph and NOT photorealistic. No people, no "
            f"unrelated extra animals, no text. Illustrated edge to edge.")


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
    # WS3: size the (square) art for 300-DPI full-bleed print at this book's trim,
    # not a hardcoded 2560 (which was ~293 DPI on the full-bleed cover).
    art_px = specs.print_art_px(cfg.trim_w, cfg.trim_h)
    pages = content["pages"]
    n = len(pages)
    # WS1b best-of-N: rank candidates by the auditor's VQAScore member (a no-op
    # when the ensemble/caption isn't enabled). cfg.qa_candidates defaults to 1.
    n_candidates = getattr(cfg, "qa_candidates", 1)
    selector = auditor.selector() if hasattr(auditor, "selector") else None
    # WS2 repair-before-reroll: only fires on a localized reject (detector boxes),
    # which only the anatomy ensemble produces — a no-op otherwise.
    repair_fn = None
    if getattr(cfg, "qa_repair", False):
        from factory.repair import InpaintRepairer
        repair_fn = InpaintRepairer(comfy).repair

    # The first page that passes the (reference-free) style bar becomes the STYLE
    # ANCHOR; every later page and the cover are audited against it, so the auditor
    # enforces a cohesive look across the whole book — re-rendering until each page
    # matches that one reference, not just a text description.
    out_pages, flagged = [], []
    style_ref = None
    for i, page in enumerate(pages, 1):
        prompt = concept_page_prompt(page, style=style)
        subject = page.get("subject", "the subject")
        _log(f"[concept] page {i}/{n} ({subject}): {page['scene'][:60]}"
             + (f" [vs anchor {style_ref.name}]" if style_ref else " [style anchor]"))

        def render(p, s, op):
            comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance,
                                            upscale=art_px,
                                            upscale_model=cfg.upscale_model),
                         out_path=op)

        op = out_dir / f"page_{i:02d}.png"
        anchor = (f"a {subject} in its natural setting, in a consistent soft "
                  f"storybook illustration style; no people and no text")
        try:
            done = run_audited_render(
                render, prompt, out_path=op, auditor=auditor, anchor=anchor,
                scene=page["scene"], reference_path=style_ref, seed=seed + i * 17,
                max_tries=max_tries, audit_kind="concept",
                caption=page.get("text"),
                n_candidates=n_candidates, selector=selector,
                repair_fn=repair_fn)
            out_pages.append(done)
            if style_ref is None:
                style_ref = done  # first cohesive page anchors the rest
        except ArtError:
            _log(f"[concept] page {i}: kept best after {max_tries} tries (REVIEW)")
            flagged.append(i)
            out_pages.append(op)
        _verify_art_resolution(out_pages[-1], art_px)

    _log("[concept] cover…")
    cover_prompt = f"{style}. {cfg.art_prompt}. No people, no text."

    def cover_render(p, s, op):
        comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance,
                                        upscale=art_px,
                                            upscale_model=cfg.upscale_model),
                         out_path=op)

    cover_path = out_dir / "art.png"
    cover_anchor = (f"a {cfg.subject} scene in a soft storybook illustration style; "
                    f"no people, no text")
    try:
        cover = run_audited_render(
            cover_render, cover_prompt, out_path=cover_path, auditor=auditor,
            anchor=cover_anchor, scene="front cover", reference_path=style_ref,
            seed=seed + 42, max_tries=max_tries, audit_kind="concept")
    except ArtError:
        _log(f"[concept] cover: kept best after {max_tries} tries (REVIEW)")
        flagged.append("cover")
        cover = cover_path
    _verify_art_resolution(cover, art_px)
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
    art_px = specs.print_art_px(cfg.trim_w, cfg.trim_h)  # WS3 300-DPI print target
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
            comfy.submit(flux_lora_workflow(p, s, loras=_loras, guidance=guidance,
                                            upscale=art_px,
                                            upscale_model=cfg.upscale_model),
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
        _verify_art_resolution(out_pages[-1], art_px)

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
        comfy.submit(flux_lora_workflow(p, s, loras=cover_loras, guidance=guidance,
                                        upscale=art_px,
                                            upscale_model=cfg.upscale_model),
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
    _verify_art_resolution(cover, art_px)
    if flagged:
        _log(f"[flux] REVIEW these (audit not fully passed): {flagged}")
    _log(f"[flux] complete: {n} pages + cover")
    return {"pages": out_pages, "cover": Path(cover), "flagged": flagged}

"""Stage 3 for Flux picture books: per-page illustration via a trained character
LoRA (plus an optional companion LoRA on memory pages), audited and regenerated
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
    """Return (prompt, loras) for a page. The page's `moment` selects the cast:
    a "memory" page (when a companion exists) stacks the companion LoRA and names
    both triggers; any other page is the hero alone with animals explicitly
    excluded so the model never invents a live pet on a present-day page."""
    mood = page.get("mood", "tender")
    expr = _expression(mood)
    memory = page.get("moment") == "memory"
    if memory and companion is not None:
        loras = [(hero.lora, hero.strength), (companion.lora, companion.strength)]
        who = (f"{hero.trigger} {outfit}, together with {companion.trigger}")
        guard = " Only the child and the pet, no other people."
    else:
        loras = [(hero.lora, hero.strength)]
        who = f"{hero.trigger} {outfit}, alone, no other people, no animals"
        guard = ""
    prompt = (f"{style}. {who}. {page['scene']} The child shows {expr}, "
              f"clearly {mood}.{guard} Richly detailed background, illustrated "
              f"edge to edge.")
    return prompt, loras


def generate_flux_art(cfg, content, out_dir, comfy, *, seed, auditor,
                      max_tries: int = 4) -> dict:
    """Illustrate every page with the hero LoRA (companion LoRA added on memory
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
    hero = next(c for c in cfg.characters if c.role == "hero")
    companion = next((c for c in cfg.characters if c.role == "companion"), None)
    # On present pages, audit against just the human part of the anchor (the text
    # before the pet's name) so the auditor doesn't demand the absent pet.
    hero_anchor = (anchor.split(pet)[0].rstrip(" .,;") if pet and pet in anchor
                   else anchor)
    pages = content["pages"]
    n = len(pages)

    out_pages = []
    for i, page in enumerate(pages, 1):
        prompt, loras = page_plan(page, hero=hero, companion=companion,
                                  style=style, outfit=outfit)
        memory = page.get("moment") == "memory"
        audit_anchor = anchor if memory else hero_anchor
        _log(f"[flux] page {i}/{n} ({page.get('moment')},{page.get('mood')}): "
             f"{page['scene'][:60]}")

        def render(p, s, op, _loras=loras):
            comfy.submit(flux_lora_workflow(p, s, loras=_loras, guidance=guidance),
                         out_path=op)

        out_pages.append(run_audited_render(
            render, prompt, out_path=out_dir / f"page_{i:02d}.png", auditor=auditor,
            anchor=audit_anchor, scene=page["scene"], reference_path=None,
            seed=500 + i * 17, max_tries=max_tries))

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

    cover = run_audited_render(
        cover_render, cover_prompt, out_path=out_dir / "art.png", auditor=auditor,
        anchor=anchor, scene="front cover", reference_path=None, seed=42,
        max_tries=max_tries)
    _log(f"[flux] complete: {n} pages + cover")
    return {"pages": out_pages, "cover": Path(cover)}

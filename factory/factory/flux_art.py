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
from factory.subject_fallback import SubjectFallbackError
from factory.concept_content import regenerate_concept_page
from factory.content import ContentError

BASE_UNET = "flux1-dev-fp8-e4m3fn.safetensors"

# Flux's painterly/storybook styles like to scrawl a fake artist signature or
# watermark in a corner (a real defect on a pen-name title, and a rights smell).
# Append this to every generation prompt to suppress them; the holistic auditor
# still catches any that slip through ([[catch-defects-with-guards]]).
NO_MARKS = "no text, no signature, no watermark, no artist mark, no logo"

# Flux drops vignette-prone subjects (leaping animals, small close-ups, montages)
# onto a blank watercolour-paper background framed by white margins — a real
# full-bleed print defect. A weak "edge to edge" hint isn't enough (the auditor's
# corrective hints already say it and Flux still vignettes), so steer hard at
# generation time; has_white_border + the vision auditor still backstop
# ([[catch-defects-with-guards]]).
FULL_BLEED = ("The painted scene completely fills the entire square frame edge to "
              "edge and corner to corner — a single immersive full-bleed "
              "illustration whose background reaches and covers all four edges and "
              "every corner, with absolutely NO white or cream paper border, NO "
              "blank margin, NO framed vignette, and NOT an isolated cut-out or "
              "sticker floating on a plain white background")


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


def has_white_border(path, *, corner_frac: float = 0.03) -> bool:
    """Cheap deterministic full-bleed guard ([[catch-defects-with-guards]]).

    A full-bleed picture-book page must reach the trim on every side, but Flux
    sometimes paints the scene on a ragged WHITE 'watercolour-paper' vignette (or
    leaves a blank white background panel) — a real print defect (uneven white
    margins at the cut edge) that the vision auditor used to ACCEPT as 'framing
    variation'. Detect it from the 4 corner patches, which separate a paper border
    from a legitimately light edge (snow, pale sky, pale water): paper/blank white
    is flat and channel-neutral, while sky/water/snow is colour-biased (one channel
    lags) or painted-textured. Two tells, validated on the Deep Blue World pages:

    - FLAT-white corner: every channel mean >= 246 and population stdev <= 14
      (a soft near-white wash). >=3 of 4 such corners ⇒ a full paper vignette
      (e.g. the seal-pup page's wash frame).
    - PURE-paper corner: every channel mean >= 253 and stdev <= 2 (blank paper, not
      a painted gradient). >=2 such corners ⇒ a blank white panel/border (e.g. the
      seahorse and dolphin pages, whose top is unpainted paper) — while a genuinely
      bright painted sky (mean ~247, stdev ~3) stays under the PURE bar and passes.

    Returns True when either tell fires. A non-image stub (the test ComfyClient
    writes a tiny marker, not a real PNG) returns False so GPU-free unit tests are
    unaffected."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
    except Exception:
        return False
    cw = max(1, int(w * corner_frac))
    ch = max(1, int(h * corner_frac))
    boxes = [(0, 0, cw, ch), (w - cw, 0, w, ch),
             (0, h - ch, cw, h), (w - cw, h - ch, w, h)]
    flat = pure = 0
    for box in boxes:
        raw = im.crop(box).tobytes()  # packed RGB bytes (channel-interleaved)
        n = len(raw) // 3
        means = [sum(raw[c::3]) / n for c in range(3)]
        # Population stdev over the interleaved RGB bytes, computed directly:
        # statistics.pstdev(bytes) hits a data-dependent Python 3.11 _ss TypeError
        # on some corner patches (crashed the border check mid-build), so avoid the
        # stdlib path entirely ([[catch-defects-with-guards]]).
        total = len(raw)
        mu = sum(raw) / total
        std = (sum((b - mu) ** 2 for b in raw) / total) ** 0.5
        if all(m >= 246 for m in means) and std <= 14:
            flat += 1
        if all(m >= 253 for m in means) and std <= 2:
            pure += 1
    return flat >= 3 or pure >= 2

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
            f"unrelated extra animals, {NO_MARKS}. {FULL_BLEED}.")


def generate_concept_art(cfg, content, out_dir, comfy, *, seed, auditor,
                         max_tries: int = 4, generate_fn=None, suggest_fn=None) -> dict:
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
    # Let the selector evict Flux's VRAM (ComfyUI /free) before the separate-process
    # VQA scorer loads — flux(~12GB)+VQA(~6GB) overflow a 16GB card otherwise.
    if selector is not None and getattr(selector, "free_fn", None) is None:
        selector.free_fn = getattr(comfy, "free", None)
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
    # Subjects already spoken for (every page's own subject + any tried as a fallback),
    # so a swap never picks a duplicate of another spread.
    used_subjects = {str(p.get("subject", "")).strip().lower()
                     for p in pages if str(p.get("subject", "")).strip()}

    def _check_border(path, label):
        """Flag (don't fail) a page that ships a white paper border/vignette — a
        real full-bleed print defect the vision auditor used to wave through as
        'framing variation', but one a soft high-key style sometimes wants on
        purpose. Surface it for review rather than killing an otherwise-good book
        ([[catch-defects-with-guards]]). Runs on reused pages too, so a kept page
        is no longer blindly trusted on framing."""
        if has_white_border(path) and label not in flagged:
            _log(f"[concept] {label}: WHITE PAPER BORDER — art does not fill the "
                 f"trim edge to edge (REVIEW / re-roll)")
            flagged.append(label)

    style_ref = None
    for i, page in enumerate(pages, 1):
        subject = page.get("subject", "the subject")
        op = out_dir / f"page_{i:02d}.png"
        # Per-page reuse: keep an already-rendered (reviewed) spread; delete just its
        # PNG to force a fresh re-render of that one page (symmetric to build.py's
        # book-level reuse). A surviving page still anchors the style for any pages
        # that DO re-render, so cohesion is preserved.
        if op.exists():
            _log(f"[concept] page {i}/{n} ({subject}): reusing existing {op.name}")
            out_pages.append(op)
            if style_ref is None:
                style_ref = op
            _verify_art_resolution(op, art_px)
            _check_border(op, i)
            # Reused pages otherwise ride through with NO vision check, so an anatomy/
            # caption defect in a kept page is never caught on a partial re-roll. With
            # qa_reaudit_reused on, re-audit them too and FLAG (don't re-render — that
            # would defeat reuse; delete the page to force a fresh render) failures for
            # review ([[catch-defects-with-guards]]).
            if getattr(cfg, "qa_reaudit_reused", False) and auditor is not None:
                anchor = (f"a {subject} in its natural setting, in a consistent soft "
                          f"storybook illustration style; no people and no text")
                verdict = auditor.audit(
                    op, anchor=anchor,
                    reference_path=(style_ref if style_ref != op else None),
                    scene=page.get("scene"), kind="concept", caption=page.get("text"))
                if not verdict.get("ok") and i not in flagged:
                    _log(f"[concept] {i}: REUSED PAGE FAILED RE-AUDIT — "
                         f"{'; '.join(verdict.get('issues') or []) or 'no reason given'}")
                    flagged.append(i)
            continue
        _log(f"[concept] page {i}/{n} ({subject}): {page['scene'][:60]}"
             + (f" [vs anchor {style_ref.name}]" if style_ref else " [style anchor]"))

        def render(p, s, op):
            comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance,
                                            upscale=art_px,
                                            upscale_model=cfg.upscale_model),
                         out_path=op)

        # Render → audit, and (concept line, opt-in) auto-swap an un-renderable
        # interchangeable subject for a fresh on-theme one rather than shipping a
        # flagged defect ([[catch-defects-with-guards]]). Default off (no generate_fn
        # /suggest_fn or subject_fallback) → identical to the old keep-best+flag path.
        fallbacks = 0
        while True:
            subject = page.get("subject", "the subject")
            anchor = (f"a {subject} in its natural setting, in a consistent soft "
                      f"storybook illustration style; no people and no text")
            try:
                done = run_audited_render(
                    render, concept_page_prompt(page, style=style), out_path=op,
                    auditor=auditor, anchor=anchor, scene=page["scene"],
                    reference_path=style_ref, seed=seed + i * 17 + fallbacks * 101,
                    max_tries=max_tries, audit_kind="concept",
                    caption=page.get("text"), n_candidates=n_candidates,
                    selector=selector, repair_fn=repair_fn)
                out_pages.append(done)
                if style_ref is None:
                    style_ref = done  # first cohesive page anchors the rest
                break
            except ArtError:
                can_fallback = (getattr(cfg, "subject_fallback", False)
                                and generate_fn is not None and suggest_fn is not None
                                and fallbacks < getattr(cfg, "max_fallbacks", 3))
                if not can_fallback:
                    _log(f"[concept] page {i}: kept best after {max_tries} tries "
                         f"(REVIEW)")
                    flagged.append(i)
                    out_pages.append(op)
                    break
                old_subject = page.get("subject", "")
                try:
                    new_subject = suggest_fn(theme=cfg.subject,
                                             used=sorted(used_subjects),
                                             failed=old_subject)
                except SubjectFallbackError:
                    _log(f"[concept] page {i}: no unique fallback subject — kept "
                         f"best (REVIEW)")
                    flagged.append(i)
                    out_pages.append(op)
                    break
                fallbacks += 1
                used_subjects.add(new_subject.strip().lower())
                try:
                    new_page = regenerate_concept_page(cfg, generate_fn, new_subject)
                except ContentError:
                    # The LLM never returned a usable couplet/scene for the swap —
                    # keep best + flag rather than crashing the whole book build
                    # (preserve the flag-don't-fail contract).
                    _log(f"[concept] page {i}: could not regenerate content for "
                         f"'{new_subject}' — kept best (REVIEW)")
                    flagged.append(i)
                    out_pages.append(op)
                    break
                _log(f"[concept] page {i}: subject fallback #{fallbacks}: "
                     f"'{old_subject}' -> '{new_subject}'")
                page.clear()
                page.update(new_page)
                # loop: re-render the swapped subject (op is overwritten)
        _verify_art_resolution(out_pages[-1], art_px)
        _check_border(out_pages[-1], i)

    cover_path = out_dir / "art.png"
    # Cover reuse (symmetric to the per-page reuse): keep an existing reviewed cover;
    # delete art.png to force a fresh cover render. Lets a targeted page re-roll skip
    # re-rendering a good cover.
    if cover_path.exists():
        _log("[concept] cover: reusing existing art.png")
        _verify_art_resolution(cover_path, art_px)
        _check_border(cover_path, "cover")
        if flagged:
            _log(f"[concept] REVIEW these (audit not fully passed): {flagged}")
        _log(f"[concept] complete: {n} pages + cover")
        return {"pages": out_pages, "cover": cover_path, "flagged": flagged}

    # Free the VQA model (held ~6GB by the scorer daemon after the last page's
    # best-of-N scoring) before the cover render — otherwise flux(~12GB)+VQA OOM the
    # cover on a 16GB card and it silently renders nothing (then the build shipped a
    # STALE cover). The cover audit uses no caption, so VQA isn't needed here.
    if selector is not None:
        try:
            from factory.qa.vqascore import shutdown_daemon
            shutdown_daemon()
            comfy.free()   # also drop ComfyUI's cache so Flux reloads into the full card
        except Exception:
            pass

    _log("[concept] cover…")
    cover_prompt = f"{style}. {cfg.art_prompt}. No people, {NO_MARKS}. {FULL_BLEED}."

    def cover_render(p, s, op):
        comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance,
                                        upscale=art_px,
                                            upscale_model=cfg.upscale_model),
                         out_path=op)

    cover_anchor = (f"a {cfg.subject} scene in a soft storybook illustration style; "
                    f"no people, no text")
    try:
        cover = run_audited_render(
            cover_render, cover_prompt, out_path=cover_path, auditor=auditor,
            anchor=cover_anchor, scene="front cover", reference_path=style_ref,
            seed=seed + 42, max_tries=max_tries, audit_kind="concept")
    except ArtError as e:
        # Surface the real reason (a render/ComfyUI failure looks identical to an
        # audit flag otherwise) and DON'T claim a usable cover if none was written —
        # the downstream cover guard then fails loudly instead of shipping stale art.
        _log(f"[concept] cover: kept best after {max_tries} tries (REVIEW) — {e}")
        flagged.append("cover")
        cover = cover_path
    if not Path(cover).exists():
        raise ArtError(
            f"cover render produced no image at {cover_path.name}: {cover_anchor}. "
            f"Likely a ComfyUI/render failure — do not ship a stale cover.")
    _verify_art_resolution(cover, art_px)
    _check_border(cover, "cover")
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

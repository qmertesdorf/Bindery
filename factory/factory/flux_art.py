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

"""Repair-before-reroll: detect -> mask -> localized inpaint (research §WS2).

When a reject is LOCALIZED — the anatomy detector (§WS1c) hands back bounding
boxes for a malformed hand/face/limb — we can fix just that region with a
masked inpaint instead of burning a whole fresh-seed reroll. This builds the
mask from the detector boxes and runs a Flux Fill (`flux1-fill-dev`) +
DifferentialDiffusion inpaint pass over only the masked area (arXiv 2306.00950).

Wired into run_audited_render via the optional `repair_fn` hook, tried before a
reroll on any verdict carrying `defects`. The ComfyUI seams (upload + submit)
and image I/O are injectable so the orchestration is unit-testable without a GPU;
the real Flux-Fill graph needs `flux1-fill-dev` provisioned in ComfyUI.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

from .art import BASE

FILL_UNET = "flux1-fill-dev.safetensors"


def _bbox(defect) -> tuple[float, float, float, float]:
    """Accept either a qa.Defect (has .bbox) or a raw (x0, y0, x1, y1) tuple."""
    return tuple(getattr(defect, "bbox", defect))  # type: ignore[return-value]


def mask_rects_from_defects(defects, width: int, height: int, *,
                            pad_frac: float = 0.08) -> list[tuple[int, int, int, int]]:
    """Convert detector boxes to padded, clamped integer pixel rects. Padding
    gives the inpaint room to blend a fixed hand into its wrist/sleeve; degenerate
    or out-of-frame boxes are dropped so we never mask an empty region."""
    px, py = pad_frac * width, pad_frac * height
    rects = []
    for d in defects:
        x0, y0, x1, y1 = _bbox(d)
        rx0, ry0 = max(0, int(x0 - px)), max(0, int(y0 - py))
        rx1, ry1 = min(width, int(x1 + px)), min(height, int(y1 + py))
        if rx1 > rx0 and ry1 > ry0:
            rects.append((rx0, ry0, rx1, ry1))
    return rects


def build_mask_image(rects, width: int, height: int, *, blur: int = 12):
    """White (inpaint) rects on a black (keep) field, feathered so the repair
    blends. Returns an 'L' PIL image. PIL is already a project dependency."""
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(m)
    for (x0, y0, x1, y1) in rects:
        draw.rectangle([x0, y0, x1, y1], fill=255)
    return m.filter(ImageFilter.GaussianBlur(blur)) if blur else m


def flux_fill_workflow(image_name: str, mask_name: str, prompt: str, seed: int, *,
                       guidance: float = 30.0, steps: int = 20) -> dict:
    """Flux Fill (flux1-fill-dev) + DifferentialDiffusion masked-inpaint graph,
    with prompt + seed baked in. The uploaded source image and mask are loaded
    by name; InpaintModelConditioning carries the noise_mask so only the masked
    region is denoised. Flux Fill wants a high guidance (~30)."""
    return {
        "img": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "msk": {"class_type": "LoadImageMask",
                "inputs": {"image": mask_name, "channel": "red"}},
        "u": {"class_type": "UNETLoader",
              "inputs": {"unet_name": FILL_UNET, "weight_dtype": "default"}},
        "dd": {"class_type": "DifferentialDiffusion", "inputs": {"model": ["u", 0]}},
        "c": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                         "clip_name2": "clip_l.safetensors", "type": "flux"}},
        "v": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "pos": {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["c", 0]}},
        "fg": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["pos", 0], "guidance": guidance}},
        "neg": {"class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["c", 0]}},
        "inp": {"class_type": "InpaintModelConditioning",
                "inputs": {"positive": ["fg", 0], "negative": ["neg", 0],
                           "vae": ["v", 0], "pixels": ["img", 0],
                           "mask": ["msk", 0], "noise_mask": True}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "ks": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sch": {"class_type": "BasicScheduler",
                "inputs": {"model": ["dd", 0], "scheduler": "simple",
                           "steps": steps, "denoise": 1.0}},
        "gd": {"class_type": "BasicGuider",
               "inputs": {"model": ["dd", 0], "conditioning": ["inp", 0]}},
        "sa": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["noise", 0], "guider": ["gd", 0],
                          "sampler": ["ks", 0], "sigmas": ["sch", 0],
                          "latent_image": ["inp", 2]}},
        "dec": {"class_type": "VAEDecode",
                "inputs": {"samples": ["sa", 0], "vae": ["v", 0]}},
        "save": {"class_type": "SaveImage",
                 "inputs": {"filename_prefix": "repair", "images": ["dec", 0]}},
    }


def _upload_image(base: str, path: Path) -> str:
    """Upload an image to ComfyUI's input store; return its server-side name
    (mirrors build_picture_ipa.upload_image)."""
    import requests  # pragma: no cover - real ComfyUI path
    with open(path, "rb") as f:
        r = requests.post(f"{base}/upload/image",
                          files={"image": (Path(path).name, f, "image/png")},
                          data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()["name"]


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


class InpaintRepairer:
    """Localized Flux-Fill inpaint over detector boxes. The ComfyUI upload/submit
    seams and image-size lookup are injectable so the orchestration runs with
    fakes; the default seams hit a live ComfyUI."""

    def __init__(self, comfy, *, base: str = BASE,
                 upload_fn: Callable[[Path], str] | None = None,
                 image_size_fn: Callable[[Path], tuple] | None = None,
                 guidance: float = 30.0, steps: int = 20,
                 mask_pad_frac: float = 0.08, mask_blur: int = 12):
        self.comfy = comfy
        self.upload_fn = upload_fn or (lambda p: _upload_image(base, p))
        self.image_size_fn = image_size_fn or _image_size
        self.guidance = guidance
        self.steps = steps
        self.mask_pad_frac = mask_pad_frac
        self.mask_blur = mask_blur

    def repair(self, image_path, defects, *, prompt: str, seed: int = 0) -> Path:
        """Inpaint the defect regions in place and return image_path. A no-op
        (returns unchanged) when the boxes clamp to nothing."""
        image_path = Path(image_path)
        w, h = self.image_size_fn(image_path)
        rects = mask_rects_from_defects(defects, w, h, pad_frac=self.mask_pad_frac)
        if not rects:
            return image_path
        mask_path = image_path.with_name(f"{image_path.stem}__mask.png")
        build_mask_image(rects, w, h, blur=self.mask_blur).save(mask_path)
        try:
            image_name = self.upload_fn(image_path)
            mask_name = self.upload_fn(mask_path)
            wf = flux_fill_workflow(image_name, mask_name, prompt, seed,
                                    guidance=self.guidance, steps=self.steps)
            self.comfy.submit(wf, out_path=image_path)  # overwrite with the repair
        finally:
            mask_path.unlink(missing_ok=True)
        return image_path

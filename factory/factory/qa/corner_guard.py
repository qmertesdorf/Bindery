"""High-res corner guard (research §WS-crops).

A VLM's vision encoder holds fine detail, but the language model fails to decode it
at small scale — accuracy jumps when content is enlarged ("VLMs are Blind"). On a
downscaled full page a faint corner signature, watermark, or a thin band of blank
trim-margin paper is sub-pixel and invisible, so the holistic auditor's "scan all
four corners" instruction cannot actually see them.

This guard crops each of the four corners at FULL resolution and runs a focused
probe on each — looking only for stray text/signatures/watermarks and blank
unpainted paper at the edge — then reports the defect localised to its corner. Pure
PIL plus a vision probe (no GPU); injectable so the suite runs without a CLI.
"""
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from ..audit import _claude_vision, parse_verdict


def _corner_boxes(width: int, height: int,
                  frac: float) -> list[tuple[str, tuple[int, int, int, int]]]:
    """The four corner crop boxes (left, upper, right, lower), each `frac` of the
    page in width and height. Pure geometry — no image needed."""
    fw = max(1, int(width * frac))
    fh = max(1, int(height * frac))
    return [
        ("top-left", (0, 0, fw, fh)),
        ("top-right", (width - fw, 0, width, fh)),
        ("bottom-left", (0, height - fh, fw, height)),
        ("bottom-right", (width - fw, height - fh, width, height)),
    ]


def build_corner_prompt(label: str, image_path: Path) -> str:
    return f"""Read the image at {image_path}. It is the {label} CORNER, cropped at
FULL resolution from a children's picture-book page, so small details are clearly
visible. Look for ONLY these two defects in this crop:
- any TEXT, letters, numbers, an artist's SIGNATURE or initials, or a watermark —
  including faint, stylised, or scribbled marks tucked into the corner;
- a band, wedge, or border of BLANK unpainted white or cream PAPER at the outer
  edge/corner (an uneven print-trim margin). A soft painterly fade INTO colour is
  fine; plain unpainted paper is not.

Set ok=false if either defect is present in this corner crop, otherwise ok=true.
Return ONLY JSON: {{"ok": true|false, "issues": ["short issue", ...]}}
Output the JSON and nothing else."""


def _claude_corner_probe(label: str, crop_path: Path) -> dict:
    return parse_verdict(_claude_vision(build_corner_prompt(label, Path(crop_path))))


class CornerGuard:
    """Full-res four-corner inspector. `probe_fn(label, crop_path) -> {ok, issues}`
    judges one corner crop; defaults to a focused Claude vision probe. `frac` is the
    fraction of each dimension the corner crop spans."""

    def __init__(self, probe_fn: Callable[[str, Path], dict] | None = None,
                 frac: float = 0.28):
        self.probe_fn = probe_fn or _claude_corner_probe
        self.frac = frac

    def check(self, image_path) -> list[str]:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        issues: list[str] = []
        tmp = Path(tempfile.mkdtemp(prefix="corner_"))
        try:
            for label, box in _corner_boxes(w, h, self.frac):
                crop_path = tmp / f"{label}.png"
                img.crop(box).save(crop_path)
                verdict = self.probe_fn(label, crop_path)
                if not verdict.get("ok", True):
                    for i in verdict.get("issues", []) or ["defect"]:
                        issues.append(f"{label} corner: {i}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return issues

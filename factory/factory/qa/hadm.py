"""HADM anatomy-defect detector (research §WS1c).

A specialized detector for human/animal anatomy defects — extra / missing /
malformed limbs, hands, eyes, faces — that general VLMs miss (GPT-4o / LLaVA
score ~chance AUC on anatomy). HADM-L localizes malformed *local* parts and
HADM-G flags *global* missing/extra parts; it generalizes to FLUX.1-dev
(github.com/wangkaihong/HADM, arXiv 2411.13842). Its bounding boxes are what the
WS2 repair pass inpaints, so this stage's output is structured (boxes), not prose.

Injected like the other QA stages; the real adapter lazily loads the HADM
weights (GPU) only on first call, so import and the unit suite stay GPU-free.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_MODEL = None  # cached HADM model (loaded once, on first use)


class AnatomyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Defect:
    """One detected anatomy defect.

    `bbox` is (x0, y0, x1, y1) in PIXELS — the region the WS2 repair pass masks
    and inpaints. `label` is HADM's class (e.g. "malformed hand", "extra limb"),
    `score` is detector confidence in [0, 1], and `kind` distinguishes HADM-L
    ("local" malformed part) from HADM-G ("global" missing/extra part).
    """
    label: str
    bbox: tuple[float, float, float, float]
    score: float
    kind: str = "local"


def _load_model():
    """Lazily import + construct the real HADM model. HADM ships as a detectron2
    project with downloaded weights (not a pip package), so until those weights
    are provisioned in the build environment this raises with guidance rather
    than silently passing every image."""
    global _MODEL
    if _MODEL is None:  # pragma: no cover - exercised only on a real GPU build
        raise AnatomyError(
            "HADM weights are not wired into this environment yet. Provision the "
            "HADM-L/HADM-G checkpoints (github.com/wangkaihong/HADM) and implement "
            "_load_model, or leave qa_anatomy disabled in the book config to keep "
            "the Claude-only anatomy check.")
    return _MODEL


def _hadm_detect(image_path: Path) -> list[Defect]:
    """Real adapter: run HADM-L + HADM-G and return their detections as Defects.
    GPU-gated; see _load_model."""
    model = _load_model()  # pragma: no cover - real GPU path
    return model.detect(str(image_path))  # pragma: no cover


class AnatomyDetector:
    """Returns the anatomy defects in an image. `detect_fn` is injectable for
    tests; the default lazily loads the real HADM model on first call.
    `min_score` filters out low-confidence detections so a faint false positive
    doesn't burn a reroll."""

    def __init__(self, detect_fn: Callable[[Path], list] | None = None,
                 min_score: float = 0.5):
        self.detect_fn = detect_fn or _hadm_detect
        self.min_score = min_score

    def detect(self, image_path) -> list[Defect]:
        raw = self.detect_fn(Path(image_path))
        return [d for d in raw if d.score >= self.min_score]

    def is_clean(self, image_path) -> bool:
        return not self.detect(image_path)

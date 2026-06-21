"""VQAScore caption-fidelity stage (research §WS1a).

A numeric image-text faithfulness gate: the probability a VQA model answers
"Yes" to *"Does this figure show {caption}?"*. VQAScore is SOTA on caption
fidelity across eight benchmarks and beats CLIPScore — which is bag-of-words and
unreliable on the relational prompts our captions use ("wrapping its tail round
the grass") — per arXiv 2404.01291 (ECCV 2024). We use it on the concept path
(captions are read aloud beside the picture) and on covers.

Injected exactly like judge_fn / ComfyClient so the art loop stays unit-testable
without a GPU. The real adapter lazily loads the open `t2v_metrics` package
(CLIP-FlanT5; needs a GPU) only on first call and caches it, so importing this
module — and running the test suite — never requires the model or a GPU.
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable

_MODEL = None  # cached t2v_metrics VQAScore model (loaded once, on first use)


class VQAScoreError(RuntimeError):
    pass


def _load_model():
    """Lazily import + construct the real VQAScore model. Heavy GPU dependency,
    so it is imported on demand (never at module import) and cached."""
    global _MODEL
    if _MODEL is None:
        try:
            import t2v_metrics  # noqa: PLC0415 — heavy GPU dep, import on demand
        except ImportError as e:  # pragma: no cover - exercised only without the dep
            raise VQAScoreError(
                "t2v_metrics is not installed; `pip install t2v_metrics` to enable "
                "the VQAScore caption-fidelity gate, or leave qa_vqa disabled in the "
                "book config to keep the Claude-only path.") from e
        _MODEL = t2v_metrics.VQAScore(model="clip-flant5-xxl")
    return _MODEL


def _t2v_score(image_path: Path, caption: str) -> float:
    """Real adapter: P("Yes" | image, "Does this figure show {caption}?") via
    t2v_metrics' VQAScore. Returns a scalar in [0, 1]."""
    model = _load_model()
    score = model(images=[str(image_path)], texts=[caption])
    # t2v_metrics returns a (1, 1) tensor; coerce to a plain float.
    return float(score.item() if hasattr(score, "item") else score[0][0])


class VQAScorer:
    """Scores image<->caption faithfulness in [0, 1]. `score_fn` is injectable
    for tests; the default lazily loads the real GPU model on first call.
    `threshold` is the pass bar — tune empirically in config (the research gives
    no fixed number)."""

    def __init__(self, score_fn: Callable[[Path, str], float] | None = None,
                 threshold: float = 0.6):
        self.score_fn = score_fn or _t2v_score
        self.threshold = threshold

    def score(self, image_path, caption: str) -> float:
        return float(self.score_fn(Path(image_path), caption))

    def passes(self, image_path, caption: str) -> tuple[bool, float]:
        """Return (meets_threshold, score) so callers can both gate and report
        the number (used in the reject reason and for best-of-N selection)."""
        s = self.score(image_path, caption)
        return (s >= self.threshold, s)

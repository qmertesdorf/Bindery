"""EnsembleAuditor (research §WS1d): combine the specialized QA stages with the
holistic Claude vision auditor so no single metric is the sole judge.

The holistic auditor stays a full member (it owns style cohesion, caption
mismatch in prose, and the two-character attribute-bleed rules); the VQAScore
gate adds a numeric caption-fidelity floor, and the HADM detector adds an
anatomy check VLMs are weak at. The ensemble ANDs the verdicts (any member can
reject) and merges issues, while surfacing structured extras — `vqa_score` for
best-of-N selection and `defects` (HADM boxes) for the WS2 repair pass.

It is a drop-in for ClaudeVisionAuditor: same `audit(...)` signature, same
`{ok, issues}` core verdict. With both extra stages disabled (the default), it
delegates verbatim to the holistic auditor — so the Claude-only path is byte-for
-byte unchanged and the existing build/test behaviour is preserved.
"""
from __future__ import annotations

from ..audit import ClaudeVisionAuditor
from .vqascore import VQAScorer
from .hadm import AnatomyDetector
from .selection import BestOfNSelector


class EnsembleAuditor:
    """Holistic auditor plus optional VQAScore and anatomy-detector members."""

    def __init__(self, holistic, *, vqa: VQAScorer | None = None,
                 anatomy: AnatomyDetector | None = None):
        self.holistic = holistic
        self.vqa = vqa
        self.anatomy = anatomy

    def selector(self) -> BestOfNSelector | None:
        """A best-of-N selector backed by the VQAScore member, or None when there
        is no scorer to rank candidates with."""
        return BestOfNSelector(self.vqa) if self.vqa is not None else None

    def audit(self, image_path, *, anchor: str, reference_path=None,
              scene: str | None = None, kind: str = "character",
              caption: str | None = None) -> dict:
        verdict = self.holistic.audit(
            image_path, anchor=anchor, reference_path=reference_path,
            scene=scene, kind=kind, caption=caption)
        ok = bool(verdict.get("ok"))
        issues = list(verdict.get("issues", []))
        extras: dict = {}

        # VQAScore caption-fidelity gate — only when there is a caption to check
        # (character/cover-only pages have none) and it is not a wraparound cover
        # (the cover auditor judges layout, not subject fidelity).
        if self.vqa is not None and caption and kind != "cover":
            passed, score = self.vqa.passes(image_path, caption)
            extras["vqa_score"] = score
            if not passed:
                ok = False
                issues.append(
                    f"low caption fidelity (VQAScore {score:.2f} < "
                    f"{self.vqa.threshold:.2f}): the picture does not clearly "
                    f"show \"{caption}\"")

        # HADM anatomy-defect gate; its boxes drive the WS2 repair pass.
        if self.anatomy is not None and kind != "cover":
            defects = self.anatomy.detect(image_path)
            if defects:
                ok = False
                extras["defects"] = defects
                issues.extend(f"anatomy defect: {d.label}" for d in defects)

        return {"ok": ok, "issues": issues, **extras}


def build_ensemble_auditor(cfg, *, holistic=None, judge_fn=None,
                           vqa_score_fn=None, anatomy_detect_fn=None):
    """Assemble the auditor for a book from its config flags.

    Returns the bare holistic `ClaudeVisionAuditor` when no extra QA stage is
    enabled (the default) so behaviour is unchanged; otherwise wraps it in an
    EnsembleAuditor with the configured members. The `*_fn` hooks let tests
    inject fakes for every stage without a GPU.
    """
    holistic = holistic or ClaudeVisionAuditor(judge_fn=judge_fn)
    use_vqa = getattr(cfg, "qa_vqa", False)
    use_anatomy = getattr(cfg, "qa_anatomy", False)
    if not use_vqa and not use_anatomy:
        return holistic
    vqa = (VQAScorer(score_fn=vqa_score_fn,
                     threshold=getattr(cfg, "qa_vqa_threshold", 0.6))
           if use_vqa else None)
    anatomy = (AnatomyDetector(detect_fn=anatomy_detect_fn,
                               min_score=getattr(cfg, "qa_anatomy_min_score", 0.5))
               if use_anatomy else None)
    return EnsembleAuditor(holistic, vqa=vqa, anatomy=anatomy)

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
from .selection import BestOfNSelector, ClaudeBestOfNSelector
from .tifa import TifaDecomposer, TifaEvaluator
from .count_guard import CountGuard
from .corner_guard import CornerGuard


class EnsembleAuditor:
    """Holistic auditor plus optional VQAScore, anatomy, TIFA, count, and corner
    members."""

    def __init__(self, holistic, *, vqa: VQAScorer | None = None,
                 anatomy: AnatomyDetector | None = None,
                 tifa: TifaEvaluator | None = None,
                 count_guard: CountGuard | None = None,
                 corner_guard: CornerGuard | None = None,
                 select_mode: str = "vqa", judge_fn=None):
        self.holistic = holistic
        self.vqa = vqa
        self.anatomy = anatomy
        self.tifa = tifa
        self.count_guard = count_guard
        self.corner_guard = corner_guard
        self.select_mode = select_mode
        # Vision call for the Claude taste-selector; default to the holistic auditor's
        # own judge_fn so "claude"/"hybrid" selection works with no extra wiring.
        self.judge_fn = judge_fn or getattr(holistic, "judge_fn", None)

    def selector(self):
        """The best-of-N chooser for this book's qa_select mode: a Claude-vision TASTE
        pick ("claude"/"hybrid", literal best on the soft-watercolour rubric) or the
        VQAScore FIDELITY pick ("vqa"). None when nothing can rank candidates."""
        mode = self.select_mode
        if mode in ("claude", "hybrid") and self.judge_fn is not None:
            return ClaudeBestOfNSelector(
                self.judge_fn, vqa=(self.vqa if mode == "hybrid" else None))
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

        # Deterministic exact-count gate: for every <count, part> claim the author
        # wrote in the scene/caption, an isolated probe counts that part and code
        # compares integers — the holistic VLM's canonical-count bias never decides.
        if self.count_guard is not None and (scene or caption) and kind != "cover":
            cissues = self.count_guard.check(image_path, scene=scene, caption=caption)
            if cissues:
                ok = False
                issues.extend(cissues)

        # Full-res four-corner gate: catches stray corner text/signatures and blank
        # trim-margin paper that are sub-pixel (invisible) on the downscaled full
        # page. Skipped on covers, which legitimately carry title/blurb text.
        if self.corner_guard is not None and kind != "cover":
            gissues = self.corner_guard.check(image_path)
            if gissues:
                ok = False
                issues.extend(gissues)

        # HADM anatomy-defect gate; its boxes drive the WS2 repair pass.
        if self.anatomy is not None and kind != "cover":
            defects = self.anatomy.detect(image_path)
            if defects:
                ok = False
                extras["defects"] = defects
                issues.extend(f"anatomy defect: {d.label}" for d in defects)

        # TIFA per-fact decomposition — interpretable caption fidelity. Gates on
        # the mean probe score; on a reject it contributes TARGETED per-fact hints
        # (which fact failed and why) to steer the reroll. Same caption/cover guard
        # as the VQAScore gate; the full report rides along for the provenance log.
        if self.tifa is not None and caption and kind != "cover":
            report = self.tifa.evaluate(image_path, caption)
            extras["tifa"] = report
            if not report["ok"]:
                ok = False
                issues.extend(report["hints"])

        return {"ok": ok, "issues": issues, **extras}


def build_ensemble_auditor(cfg, *, holistic=None, judge_fn=None,
                           vqa_score_fn=None, anatomy_detect_fn=None,
                           tifa_decompose_fn=None, count_fn=None,
                           corner_probe_fn=None):
    """Assemble the auditor for a book from its config flags.

    Returns the bare holistic `ClaudeVisionAuditor` when no extra QA stage is
    enabled (the default) so behaviour is unchanged; otherwise wraps it in an
    EnsembleAuditor with the configured members. The `*_fn` hooks let tests
    inject fakes for every stage without a GPU.
    """
    holistic = holistic or ClaudeVisionAuditor(
        judge_fn=judge_fn, passes=getattr(cfg, "qa_audit_passes", 1),
        aggregate=getattr(cfg, "qa_audit_aggregate", "any_fail"),
        describe_first=getattr(cfg, "qa_describe_first", False))
    use_vqa = getattr(cfg, "qa_vqa", False)
    use_anatomy = getattr(cfg, "qa_anatomy", False)
    use_tifa = getattr(cfg, "qa_tifa", False)
    use_count = getattr(cfg, "qa_count_guard", False)
    use_corner = getattr(cfg, "qa_corner_crops", False)
    select_mode = getattr(cfg, "qa_select", "vqa")
    # A Claude TASTE selector needs no VQA model, so it must still build the ensemble
    # (which exposes .selector()) even when every other stage is off.
    claude_select = select_mode in ("claude", "hybrid")
    if not (use_vqa or use_anatomy or use_tifa or use_count or use_corner
            or claude_select):
        return holistic
    vqa = (VQAScorer(score_fn=vqa_score_fn,
                     threshold=getattr(cfg, "qa_vqa_threshold", 0.15))
           if use_vqa else None)
    anatomy = (AnatomyDetector(detect_fn=anatomy_detect_fn,
                               min_score=getattr(cfg, "qa_anatomy_min_score", 0.5))
               if use_anatomy else None)
    tifa = None
    if use_tifa:
        # Reuse the fidelity-gate scorer so only ONE VQA model loads; when the
        # scalar gate is off, TIFA gets its own scorer (still the shared daemon).
        scorer = vqa or VQAScorer(score_fn=vqa_score_fn)
        tifa = TifaEvaluator(TifaDecomposer(decompose_fn=tifa_decompose_fn), scorer,
                             threshold=getattr(cfg, "qa_tifa_threshold", 0.4))
    count_guard = CountGuard(count_fn=count_fn) if use_count else None
    corner_guard = CornerGuard(probe_fn=corner_probe_fn) if use_corner else None
    return EnsembleAuditor(holistic, vqa=vqa, anatomy=anatomy, tifa=tifa,
                           count_guard=count_guard, corner_guard=corner_guard,
                           select_mode=select_mode, judge_fn=judge_fn)

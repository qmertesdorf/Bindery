"""Layered QA ensemble for the art loop (research §WS1).

No single metric is a complete judge of a generated image (arXiv 2412.13989):
specialized detectors beat general VLMs on anatomy, and VQA-based metrics beat
CLIPScore on caption fidelity. So instead of one holistic vision call we run an
ENSEMBLE — the holistic Claude auditor stays a member, joined by a numeric
caption-fidelity gate (VQAScore, §WS1a) and an anatomy-defect detector
(HADM, §WS1c) — and we select the best of N candidates (§WS1b) before auditing.

Every stage follows the project's injectable-fake pattern (like judge_fn /
ComfyClient): a thin class with an injectable callable whose default lazily
loads a real GPU model only on first use, so importing this package and running
the unit suite never needs a GPU or downloaded weights.
"""
from .vqascore import VQAScorer, VQAScoreError, shutdown_daemon
from .hadm import AnatomyDetector, AnatomyError, Defect
from .selection import (BestOfNSelector, ClaudeBestOfNSelector,
                        build_select_prompt, parse_best)
from .tifa import TifaProbe, TifaDecomposer, TifaEvaluator, TifaError
from .count_guard import CountGuard, extract_count_claims
from .corner_guard import CornerGuard
from .ensemble import EnsembleAuditor, build_ensemble_auditor

__all__ = [
    "VQAScorer", "VQAScoreError", "shutdown_daemon",
    "AnatomyDetector", "AnatomyError", "Defect",
    "BestOfNSelector", "ClaudeBestOfNSelector", "build_select_prompt", "parse_best",
    "TifaProbe", "TifaDecomposer", "TifaEvaluator", "TifaError",
    "CountGuard", "extract_count_claims",
    "CornerGuard",
    "EnsembleAuditor", "build_ensemble_auditor",
]

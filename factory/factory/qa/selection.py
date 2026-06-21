"""Best-of-N candidate selection (research §WS1b).

Generating 3-9 candidates per page and picking the highest-VQAScore one lifts
human ratings ~0.2-0.3 on a 5-pt scale and is 2-3x better than PickScore / DSG
selection (GenAI-Bench). It both raises the floor quality and bounds reroll cost
— a weak first draw no longer forces a fresh-seed reroll if a sibling candidate
is good. N is configured per book (default 1 = today's single-candidate path).
"""
from __future__ import annotations
from pathlib import Path


class BestOfNSelector:
    """Pick the highest-VQAScore candidate. Wraps a VQAScorer; with no caption
    (or a single candidate) there is nothing to score, so it returns the first
    candidate unchanged — keeping caption-free pages on today's behaviour."""

    def __init__(self, vqa, free_fn=None):
        self.vqa = vqa
        # Optional callback invoked once before scoring a batch — used to evict the
        # renderer's VRAM (ComfyUI /free) so the separate-process VQA model fits on
        # a 16GB card. None = no-op (tests, or when renderer/scorer don't contend).
        self.free_fn = free_fn

    def select(self, candidates, caption: str | None):
        candidates = [Path(c) for c in candidates]
        if not candidates:
            raise ValueError("BestOfNSelector.select needs at least one candidate")
        if len(candidates) == 1 or not caption:
            return candidates[0]
        if self.free_fn is not None:
            self.free_fn()   # free the renderer's VRAM before the VQA model loads
        scored = [(self.vqa.score(c, caption), c) for c in candidates]
        # Highest score wins; ties keep the earlier (lower-seed) candidate stable.
        best = max(range(len(scored)), key=lambda i: scored[i][0])
        return scored[best][1]

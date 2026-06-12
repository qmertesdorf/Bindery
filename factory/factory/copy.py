"""Shared marketing copy derived from a BookConfig (back-cover blurb, etc.)."""
from __future__ import annotations
from .config import BookConfig


def book_blurb(cfg: BookConfig) -> str:
    """One-paragraph back-cover / listing blurb for a title."""
    if cfg.book_type == "standard":
        return cfg.blurb or cfg.synopsis
    return (f"A gentle, guided journal to help you grieve and remember your beloved "
            f"{cfg.pet_kind}. Undated reflective prompts, memory pages, and milestone "
            f"reflections give you a private space to process loss at your own pace. "
            f"A comforting keepsake and a thoughtful gift.")

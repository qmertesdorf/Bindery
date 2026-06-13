"""Shared marketing copy derived from a BookConfig (back-cover blurb, etc.)."""
from __future__ import annotations
from .config import BookConfig


def book_blurb(cfg: BookConfig) -> str:
    """One-paragraph back-cover / listing blurb for a title."""
    if cfg.book_type == "standard":
        return cfg.blurb or cfg.synopsis
    if cfg.book_type == "picture":
        return cfg.blurb or (
            f"A gentle, beautifully illustrated picture book for a little one saying "
            f"goodbye to a beloved {cfg.pet_kind}. Through a child's eyes and soft, "
            f"tender pictures, it holds space for big feelings and helps a family "
            f"remember {cfg.pet_name} with love. A comforting read-aloud and a "
            f"caring gift.")
    return (f"A gentle, guided journal to help you grieve and remember your beloved "
            f"{cfg.pet_kind}. Undated reflective prompts, memory pages, and milestone "
            f"reflections give you a private space to process loss at your own pace. "
            f"A comforting keepsake and a thoughtful gift.")

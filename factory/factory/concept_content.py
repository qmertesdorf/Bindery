"""Concept (character-free) picture-book content: a style bible + per-page
{subject, text, scene}. No recurring characters — every spread is independent,
held together only by a locked art style."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences


def build_concept_bible_prompt(cfg: BookConfig) -> str:
    return f"""You are designing a character-free children's picture book about \
{cfg.subject} for early readers (around age 5). Title: {cfg.title}. Each spread shows
a different subject; there are NO recurring characters and NO people anywhere.

Produce the STYLE BIBLE. Return ONLY valid JSON (no markdown, no commentary):
{{"art_style": "...", "dedication": "..."}}
- "art_style": one short, vivid illustration-style string reused on every page so
  the look stays consistent, e.g. "soft storybook watercolour, warm natural palette,
  gentle edges, no text".
- "dedication": one warm line for the dedication page.
Output the JSON and nothing else."""


def build_concept_story_prompt(cfg: BookConfig) -> str:
    if cfg.topics:
        topics = ("Use exactly these subjects, one per spread, IN THIS ORDER: "
                  + "; ".join(cfg.topics) + ".\n")
    else:
        topics = (f"Choose {cfg.page_count} varied, child-friendly subjects within "
                  f'"{cfg.subject}", one per spread.\n')
    return f"""You are writing the character-free children's picture book \
"{cfg.title}" about {cfg.subject}, for early readers (around age 5). Warm, simple,
concrete, never scary.
{topics}
Return ONLY valid JSON:
{{"pages": [{{"subject": "...", "text": "...", "scene": "..."}}], "closing": "..."}}
- "subject": the single subject of this spread (e.g. an animal name).
- "text": a SHORT rhyming couplet — exactly TWO lines that rhyme (AABB), separated
  by a single newline ("\\n") — that an early reader can read aloud. Keep it gentle,
  simple and concrete, weaving in one easy true thing about the subject. The rhyme
  must be natural, never forced or nonsensical. Vary the rhymes across pages.
- "scene": a RICH, concrete visual of the subject in its natural setting — what it
  looks like and where it is. CRITICAL: NO people, NO unrelated extra animals, and
  NO words/letters/numbers in the picture. One clear subject per page.
- "closing": one warm closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def validate_concept_bible(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContentError("concept bible is not a JSON object")
    for k in ("art_style", "dedication"):
        if not str(data.get(k, "")).strip():
            raise ContentError(f"concept bible missing '{k}'")


def validate_concept_story(data: dict, expected_pages: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("concept story is not a JSON object")
    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ContentError(
            f"concept story must have exactly {expected_pages} pages, got "
            f"{len(pages) if isinstance(pages, list) else 'non-list'}")
    for i, pg in enumerate(pages, 1):
        if not isinstance(pg, dict):
            raise ContentError(f"concept page {i} is not an object")
        for k in ("subject", "text", "scene"):
            if not str(pg.get(k, "")).strip():
                raise ContentError(f"concept page {i} missing '{k}'")
    if not str(data.get("closing", "")).strip():
        raise ContentError("concept story missing 'closing'")


def _generate_concept_bible(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_concept_bible_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"concept bible is not valid JSON: {e}") from e
    validate_concept_bible(data)
    return data


def _generate_concept_story(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_concept_story_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"concept story is not valid JSON: {e}") from e
    validate_concept_story(data, cfg.page_count)
    return data


def generate_concept_content(cfg: BookConfig,
                             generate_fn: Callable[[str], str]) -> dict:
    # One retry each: a transient LLM blip should not nuke the whole build.
    try:
        bible = _generate_concept_bible(cfg, generate_fn)
    except ContentError:
        bible = _generate_concept_bible(cfg, generate_fn)
    art_style = cfg.art_style or bible["art_style"]
    try:
        story = _generate_concept_story(cfg, generate_fn)
    except ContentError:
        story = _generate_concept_story(cfg, generate_fn)
    return {"art_style": art_style, "character_anchor": "",
            "dedication": bible["dedication"], "pages": story["pages"],
            "closing": story["closing"]}

"""Picture-book content: a frozen story bible + per-page story text & scenes."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences


def build_bible_prompt(cfg: BookConfig) -> str:
    return f"""You are designing a gentle children's picture book for a young child
(ages 4-8) grieving the death of their {cfg.pet_kind}, named {cfg.pet_name}. The
child narrates; {cfg.pet_name} appears in soft, remembered moments. Title: {cfg.title}.

First produce the STORY BIBLE. Return ONLY valid JSON (no markdown, no commentary):
{{"character_anchor": "...", "art_style": "...", "dedication": "..."}}
- "character_anchor": a SIMPLE, ICONIC, fixed visual description reused on every
  page so an image model can repeat it — the child (age, hair, skin, ONE simple
  outfit) and {cfg.pet_name} the {cfg.pet_kind} (breed, colour, markings). Keep it
  concrete and free of scene details. No proper nouns an image model can't draw.
- "art_style": one short style string, e.g.
  "soft flat storybook watercolor, muted palette, soft edges, no text".
- "dedication": one tender line for the dedication page.
Output the JSON and nothing else."""


def build_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle children's picture book "{cfg.title}" for a
child (ages 4-8) grieving their {cfg.pet_kind}, {cfg.pet_name}. The child narrates;
{cfg.pet_name} appears in soft remembered moments. Warm, simple, never clinical;
never the "Rainbow Bridge" poem.

The recurring characters (keep every page consistent with this): {anchor}

Write EXACTLY {cfg.page_count} story pages that move gently from loss to remembering
with love. Return ONLY valid JSON:
{{"pages": [{{"text": "...", "scene": "..."}}], "closing": "..."}}
- each "text": 1-2 short child-friendly sentences for that page.
- each "scene": a concrete VISUAL description of what to illustrate on that page
  (setting, what the child and {cfg.pet_name} are doing), consistent with the
  characters above. Do NOT include any words/letters to render in the picture.
- "closing": one comforting closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def validate_bible(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContentError("story bible is not a JSON object")
    for k in ("character_anchor", "art_style", "dedication"):
        if not str(data.get(k, "")).strip():
            raise ContentError(f"story bible missing '{k}'")


def validate_story(data: dict, expected_pages: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("story is not a JSON object")
    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ContentError(
            f"story must have exactly {expected_pages} pages, got "
            f"{len(pages) if isinstance(pages, list) else 'non-list'}")
    for i, pg in enumerate(pages, 1):
        if not isinstance(pg, dict) or not str(pg.get("text", "")).strip():
            raise ContentError(f"story page {i} missing 'text'")
        if not str(pg.get("scene", "")).strip():
            raise ContentError(f"story page {i} missing 'scene'")
    if not str(data.get("closing", "")).strip():
        raise ContentError("story missing 'closing'")


def _generate_bible(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_bible_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"story bible is not valid JSON: {e}") from e
    validate_bible(data)
    return data


def _generate_story(cfg: BookConfig, anchor: str,
                    generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_story_prompt(cfg, anchor))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"story is not valid JSON: {e}") from e
    validate_story(data, cfg.page_count)
    return data


def generate_picture_content(cfg: BookConfig,
                             generate_fn: Callable[[str], str]) -> dict:
    # One retry each: a transient LLM blip should not nuke the whole build
    # (same pattern as the standard strategy).
    try:
        bible = _generate_bible(cfg, generate_fn)
    except ContentError:
        bible = _generate_bible(cfg, generate_fn)
    # Config-locked art_style / character_anchor always win so the look never
    # drifts run to run (and let us pin SDXL-friendly, renderable character traits).
    art_style = cfg.art_style or bible["art_style"]
    anchor = cfg.character_anchor or bible["character_anchor"]
    try:
        story = _generate_story(cfg, anchor, generate_fn)
    except ContentError:
        story = _generate_story(cfg, anchor, generate_fn)
    return {"character_anchor": anchor, "art_style": art_style,
            "dedication": bible["dedication"], "pages": story["pages"],
            "closing": story["closing"]}

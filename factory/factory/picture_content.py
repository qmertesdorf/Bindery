"""Picture-book content: a frozen story bible + per-page story text & scenes."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences


def build_bible_prompt(cfg: BookConfig) -> str:
    premise = (
        f"a gentle, comforting children's picture book that reassures a young child "
        f"(ages 4-8) about where their {cfg.pet_kind}, named {cfg.pet_name}, has gone"
        if cfg.theme == "comfort" else
        f"a gentle children's picture book for a young child (ages 4-8) grieving the "
        f"death of their {cfg.pet_kind}, named {cfg.pet_name}")
    return f"""You are designing {premise}. The child narrates; {cfg.pet_name} appears
in soft, tender moments. Title: {cfg.title}.

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
    if cfg.theme == "comfort":
        return _comfort_story_prompt(cfg, anchor)
    return _grief_story_prompt(cfg, anchor)


def _grief_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle children's picture book "{cfg.title}" for a
child (ages 4-8) whose {cfg.pet_kind}, {cfg.pet_name}, has died. The child narrates.
Warm, simple, honest, never clinical; never the "Rainbow Bridge" poem.

The recurring characters (keep every page consistent with this): {anchor}

This is a grief book. {cfg.pet_name} is GONE. Structure the {cfg.page_count} pages as
a gentle arc: a few happy MEMORIES of {cfg.pet_name} alive → the loss and the empty
home → missing {cfg.pet_name}, sad and comforted (sometimes by a parent, or looking
at a photo) → slowly remembering with love and quiet hope.

Return ONLY valid JSON:
{{"pages": [{{"text": "...", "cast": "child|child_and_pet", "mood": "...",
            "scene": "..."}}], "closing": "..."}}
- "text": 1-2 short child-friendly sentences for the page.
- "cast": who is in THIS page's PICTURE — "child_and_pet" for a happy flashback when
  {cfg.pet_name} was alive (the child AND {cfg.pet_name} together); "child" for now,
  after the loss (the child ALONE). A grief book uses only these two.
- "mood": the child's feeling on this page (e.g. happy, playful, tender, sad,
  lonely, wistful, comforted, hopeful) — vary it honestly with the cast.
- "scene": a RICH, concrete visual description — the SETTING (a real place: a
  sunlit park, a cozy living room with furniture, a bedroom at dusk), what the
  child is doing, and the child's expression matching the mood.
  CRITICAL constraints (an image model can only reliably draw the child alone, or
  the child with the {cfg.pet_kind}):
  * The picture shows ONLY the child — never any other PEOPLE (no parent, no
    friends); a parent's comfort belongs in the "text", not the picture.
  * On a "child" page the scene must show ONLY the child in a setting with an
    expression matching the mood, and must NOT mention or depict {cfg.pet_name},
    the {cfg.pet_kind}, a photo/picture of it, or its bed/leash/toys — naming the
    animal makes the image model draw a live one. The loss is carried by the
    "text", not the picture.
  * Only "child_and_pet" pages show {cfg.pet_name} (alive, with the child).
  Keep objects simple. No words/letters in the picture.
- "closing": one comforting closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def _comfort_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle, comforting children's picture book
"{cfg.title}" for a child (ages 4-8) whose {cfg.pet_kind}, {cfg.pet_name}, has died.
The child narrates. Warm, simple, honest, reassuring; never the "Rainbow Bridge"
poem; no religious afterlife claims.

The recurring characters (keep every page consistent with this): {anchor}

This is a COMFORT book answering a child's question: "where did {cfg.pet_name} go?"
Structure the {cfg.page_count} pages as a gentle arc: the child misses {cfg.pet_name}
(alone) → wonders where {cfg.pet_name} went → gentle, dreamlike VISIONS of
{cfg.pet_name} safe and at peace in a luminous natural place (sunlit meadows, soft
warm light, drifting stars) — sometimes {cfg.pet_name} alone, sometimes the child
imagining herself THERE with {cfg.pet_name} → reassurance that {cfg.pet_name} is
happy and safe → close on the comforting truth that {cfg.pet_name} stays in your
HEART, in love and memory and the warm world around us.

Return ONLY valid JSON:
{{"pages": [{{"text": "...", "cast": "child|child_and_pet|pet", "mood": "...",
            "scene": "..."}}], "closing": "..."}}
- "text": 1-2 short child-friendly sentences for the page.
- "cast": who is in THIS page's PICTURE —
  * "child": the child ALONE (missing {cfg.pet_name}, wondering, or held in a warm
    quiet moment of "they stay in your heart").
  * "pet": {cfg.pet_name} ALONE, peaceful and content, in the luminous place — no
    people at all. Use these for the "where {cfg.pet_name} is now" visions.
  * "child_and_pet": the child AND {cfg.pet_name} together in that gentle place
    (the child imagining herself there with {cfg.pet_name}).
- "mood": the feeling on this page (e.g. wondering, wistful, gentle, peaceful,
  tender, comforted, hopeful, warm) — vary it honestly with the cast.
- "scene": a RICH, concrete visual — the SETTING and the subject's expression.
  CRITICAL constraints (an image model can only reliably draw the child alone, the
  child with {cfg.pet_name}, or {cfg.pet_name} alone):
  * NEVER any other PEOPLE (no parent, no friends).
  * On a "child" page show ONLY the child; do NOT depict {cfg.pet_name}.
  * On a "pet" page show ONLY {cfg.pet_name} in the luminous place; NO people.
  * On a "child_and_pet" page show the child and {cfg.pet_name} together.
  Keep objects simple. No words/letters in the picture.
- "closing": one comforting closing line about {cfg.pet_name} staying in your heart.
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
        if str(pg.get("cast", "")).strip() not in ("child", "child_and_pet", "pet"):
            raise ContentError(
                f"story page {i} 'cast' must be 'child', 'child_and_pet', or 'pet'")
        if not str(pg.get("mood", "")).strip():
            raise ContentError(f"story page {i} missing 'mood'")
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

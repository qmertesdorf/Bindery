"""Concept (character-free) picture-book content: a style bible + per-page
{subject, text, scene}. No recurring characters — every spread is independent,
held together only by a locked art style."""
from __future__ import annotations
import json
import re
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences, generate_json
from .readability import flesch_kincaid_grade

_WORD_RE = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def _last_word(line: str) -> str:
    words = _WORD_RE.findall(line)
    return words[-1].lower() if words else ""


def couplet_issues(text: str) -> list[str]:
    """Deterministic couplet-contract guard ([[catch-defects-with-guards]]).

    The story prompt demands a TWO-line AABB couplet, but the validator only
    checked the field was non-empty — so a one-line 'couplet' or a fake rhyme
    (both lines ending on the SAME word) could ship in a read-aloud learning book.
    This guard catches the two UNAMBIGUOUS violations only — wrong line count and
    an identical end-word — so a legitimate near-rhyme is never falsely rejected
    (no phonetic matching, which would be noisy). Returns a list of issues (empty
    when the couplet is well-formed)."""
    lines = [ln.strip() for ln in str(text).split("\n") if ln.strip()]
    if len(lines) != 2:
        return [f"couplet must be exactly two lines, got {len(lines)}"]
    w1, w2 = _last_word(lines[0]), _last_word(lines[1])
    if w1 and w1 == w2:
        return [f"couplet lines both end on '{w1}' — an identical word is not a rhyme"]
    return []


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
  looks like and where it is. ACCURATE BUT FRIENDLY: describe the subject's TRUE body
  shape, real proportions and — most importantly — the SIGNATURE features that make
  the species instantly recognizable (e.g. a pufferfish's SPINES, a swordfish's long
  bill, a narwhal's tusk, an octopus's eight arms, the correct fins/tail shape) so a
  child could name the animal from the picture alone; never smooth away or omit a
  defining feature. The scene text is fed VERBATIM to the image model, so NEVER
  describe a feature by comparing it to a feature the animal does NOT have (not
  "ear tufts like horns", not "a tail like a fish") — the image model paints the
  compared thing literally (real horns, a fish tail). Name only what the feature
  actually IS ("two soft upright feather tufts on its head"). Keep
  the FACE and expression sweet and friendly (soft gentle eyes, a gentle smile), but
  keep the BODY true to the real animal — do NOT round every creature into the same
  chubby ball or blob: an elongated animal stays long and sleek, a flat animal stays
  flat. CRITICAL: NO people, NO unrelated extra animals, and NO words/letters/numbers
  in the picture. One clear subject per page.
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
        ci = couplet_issues(pg["text"])
        if ci:
            raise ContentError(f"concept page {i} couplet: {ci[0]}")
    if not str(data.get("closing", "")).strip():
        raise ContentError("concept story missing 'closing'")


def _generate_concept_bible(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    def _pv(data):
        validate_concept_bible(data)
        return data
    return generate_json(generate_fn, lambda: build_concept_bible_prompt(cfg),
                         _pv, label="concept bible")


def _generate_concept_story(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    def _pv(data):
        validate_concept_story(data, cfg.page_count)
        return data
    return generate_json(generate_fn, lambda: build_concept_story_prompt(cfg),
                         _pv, label="concept story")


def generate_concept_content(cfg: BookConfig,
                             generate_fn: Callable[[str], str]) -> dict:
    # Each artifact retries once, feeding the rejection reason back into the prompt
    # (generate_json) so a transient blip OR a systematic contract miss self-corrects
    # instead of failing identically twice.
    bible = _generate_concept_bible(cfg, generate_fn)
    art_style = cfg.art_style or bible["art_style"]
    story = _generate_concept_story(cfg, generate_fn)
    return {"art_style": art_style, "character_anchor": "",
            "dedication": bible["dedication"], "pages": story["pages"],
            "closing": story["closing"]}


def build_concept_page_prompt(cfg: BookConfig, subject: str) -> str:
    """Prompt to regenerate ONE spread's content for a NEW subject, consistent with
    the book's voice (rhyming AABB couplet, concrete scene, no people/text). Used by
    the auto-subject-fallback path; mirrors build_concept_story_prompt for one page."""
    return f"""You are writing ONE spread of the character-free children's picture \
book "{cfg.title}" about {cfg.subject}, for early readers (around age 5). Warm, simple,
concrete, never scary.

The subject of THIS spread is: {subject}.

Return ONLY valid JSON:
{{"subject": "...", "text": "...", "scene": "..."}}
- "subject": the subject of this spread ({subject}).
- "text": a SHORT rhyming couplet — exactly TWO lines that rhyme (AABB), separated by
  a single newline ("\\n") — an early reader can read aloud. Gentle, simple, concrete,
  weaving in one easy true thing about the subject. Natural rhyme, never forced.
- "scene": a RICH, concrete visual of the subject in its natural setting. ACCURATE
  BUT FRIENDLY: describe its TRUE body shape, real proportions and the SIGNATURE
  features that make the species instantly recognizable (e.g. a pufferfish's spines, a
  swordfish's bill, a narwhal's tusk; the correct fins/tail/limb count) so a child
  could name it from the picture — never smooth away or omit a defining feature. The
  scene text is fed VERBATIM to the image model, so NEVER describe a feature by
  comparing it to a feature the animal does NOT have (not "ear tufts like horns",
  not "a tail like a fish") — the image model paints the compared thing literally;
  name only what the feature actually IS. Keep
  the FACE sweet and friendly (soft gentle eyes,
  a gentle smile) but keep the BODY true to the animal — do NOT round it into a chubby
  ball or blob (an elongated animal stays long and sleek, a flat animal stays flat).
  CRITICAL: NO people, NO unrelated extra animals, NO words/letters/numbers in the
  picture. One clear subject.
Output the JSON and nothing else."""


def regenerate_concept_page(cfg: BookConfig, generate_fn: Callable[[str], str],
                            subject: str, *, max_retries: int = 1) -> dict:
    """Regenerate one concept page `{subject, text, scene}` for `subject`. Retries up
    to `max_retries` extra times if the JSON is unusable OR the couplet reads above
    cfg.max_reading_grade; returns the best clean draft (last one if readability never
    clears, so the caller can flag rather than loop forever). Raises ContentError if
    nothing parseable was ever returned."""
    last = None
    for _ in range(max_retries + 1):
        raw = generate_fn(build_concept_page_prompt(cfg, subject))
        try:
            data = json.loads(_strip_fences(raw))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        page = {k: str(data.get(k, "")).strip() for k in ("subject", "text", "scene")}
        if not all(page.values()):
            continue
        last = page
        grade_ok = (not cfg.max_reading_grade or cfg.max_reading_grade <= 0
                    or flesch_kincaid_grade(page["text"]) <= cfg.max_reading_grade)
        couplet_ok = not couplet_issues(page["text"])
        if grade_ok and couplet_ok:
            return page
    if last is None:
        raise ContentError(
            f"could not regenerate a usable concept page for subject {subject!r}")
    return last

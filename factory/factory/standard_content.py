"""Standard (read-through) book content: two-pass outline + per-chapter prose."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences

MIN_CHAPTER_WORDS = 20    # hard floor that catches an empty / refused generation
LENGTH_FLOOR_RATIO = 0.8  # below this fraction of the target, retry once for length


def build_outline_prompt(cfg: BookConfig) -> str:
    return f"""You are an author planning a warm, comforting read-through book.
Title: {cfg.title}
Subtitle: {cfg.subtitle}
What the book is about: {cfg.synopsis}

Plan exactly {cfg.chapter_count} chapters that flow as a gentle, supportive read.

Return ONLY valid JSON (no markdown, no commentary) for this OUTLINE:
{{"preface": "2-4 warm sentences introducing the book",
  "chapters": [{{"title": "chapter title", "synopsis": "one sentence"}}]}}
with exactly {cfg.chapter_count} chapter objects. Output the JSON and nothing else."""


def build_chapter_prompt(cfg: BookConfig, chapter: dict, n: int,
                         prior_titles: list[str], expand: bool = False) -> str:
    prior = "; ".join(prior_titles) if prior_titles else "(this is the first chapter)"
    prompt = f"""You are writing one chapter of the book "{cfg.title}" ({cfg.subtitle}).
Premise: {cfg.synopsis}
This is chapter {n} of {cfg.chapter_count}: "{chapter['title']}" — {chapter.get('synopsis', '')}
Earlier chapters so far: {prior}

Write a complete, unhurried chapter of AT LEAST {cfg.words_per_chapter} words in
7-10 full paragraphs of warm, gentle, tender prose. Develop the theme with
concrete sensory detail and small, specific moments; reflect slowly and offer
quiet comfort. Do not summarize, rush, or end the chapter early. Do NOT repeat
the chapter title or add headings.

Return ONLY valid JSON: {{"paragraphs": ["paragraph 1", "paragraph 2", ...]}}
Output the JSON and nothing else."""
    if expand:
        prompt += (
            f"\n\nYour previous draft was TOO SHORT. Write a substantially longer, "
            f"richer version — at least {cfg.words_per_chapter} words across 8-10 "
            f"full paragraphs. Deepen each beat with more detail; do not pad with "
            f"repetition.")
    return prompt


def validate_outline(data: dict, expected_chapters: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("outline is not a JSON object")
    if not data.get("preface"):
        raise ContentError("outline missing 'preface'")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != expected_chapters:
        raise ContentError(
            f"outline must have exactly {expected_chapters} chapters, got "
            f"{len(chapters) if isinstance(chapters, list) else 'non-list'}")
    for i, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict) or not str(ch.get("title", "")).strip():
            raise ContentError(f"outline chapter {i} missing 'title'")


def validate_chapter(data: dict, min_words: int = MIN_CHAPTER_WORDS,
                     chapter_n: int | None = None) -> None:
    where = f"chapter {chapter_n}" if chapter_n else "chapter"
    paras = data.get("paragraphs") if isinstance(data, dict) else None
    if not isinstance(paras, list) or not paras:
        raise ContentError(f"{where} has no paragraphs")
    if not all(isinstance(p, str) for p in paras):
        raise ContentError(f"{where} paragraphs must all be strings")
    words = sum(len(p.split()) for p in paras)
    if words < min_words:
        raise ContentError(
            f"{where} prose too short ({words} words < {min_words}); "
            f"the generation was likely truncated or refused")


def _chapter_words(body: dict) -> int:
    return sum(len(p.split()) for p in body["paragraphs"])


def _generate_one_chapter(cfg: BookConfig, ch: dict, n: int, titles: list[str],
                          generate_fn: Callable[[str], str],
                          expand: bool = False) -> dict:
    raw_c = generate_fn(build_chapter_prompt(cfg, ch, n, titles, expand=expand))
    try:
        body = json.loads(_strip_fences(raw_c))
    except json.JSONDecodeError as e:
        raise ContentError(f"chapter {n} is not valid JSON: {e}") from e
    validate_chapter(body, chapter_n=n)
    return body


def generate_standard_content(cfg: BookConfig,
                              generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_outline_prompt(cfg))
    try:
        outline = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"outline is not valid JSON: {e}") from e
    validate_outline(outline, cfg.chapter_count)

    target = cfg.words_per_chapter
    chapters, titles = [], []
    for i, ch in enumerate(outline["chapters"], 1):
        body = _generate_one_chapter(cfg, ch, i, titles, generate_fn)
        # LLMs routinely under-deliver on length. If a chapter lands well under
        # the target, retry ONCE with an explicit expand instruction and keep the
        # longer draft — a build-time guard against a too-thin book, bounded so a
        # stubbornly-short model can't loop the build forever.
        if target and _chapter_words(body) < target * LENGTH_FLOOR_RATIO:
            retry = _generate_one_chapter(cfg, ch, i, titles, generate_fn, expand=True)
            if _chapter_words(retry) > _chapter_words(body):
                body = retry
        chapters.append({"title": ch["title"], "paragraphs": body["paragraphs"]})
        titles.append(ch["title"])

    return {"preface": outline["preface"], "chapters": chapters}

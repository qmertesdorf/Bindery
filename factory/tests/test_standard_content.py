import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError, generate_content
from factory.standard_content import (
    build_outline_prompt, build_chapter_prompt,
    validate_outline, validate_chapter, generate_standard_content,
)


def cfg(**over):
    base = dict(slug="comp", title="Gentle Goodbye", subtitle="Sub", author="A",
                art_prompt="x", book_type="standard", synopsis="Grieving a dog.",
                chapter_count=3, words_per_chapter=40)
    base.update(over)
    return BookConfig(**base)


def _para(n_words=30):
    return " ".join(["word"] * n_words)


def _fake(outline_chapters=3):
    """A prompt-aware fake LLM: outline call vs chapter call."""
    outline = {"preface": "A short preface.",
               "chapters": [{"title": f"Chapter {i}", "synopsis": "s"}
                            for i in range(1, outline_chapters + 1)]}

    def fn(prompt):
        if "OUTLINE" in prompt:
            return json.dumps(outline)
        return json.dumps({"paragraphs": [_para(), _para()]})
    return fn


def test_outline_prompt_mentions_synopsis_and_count():
    p = build_outline_prompt(cfg())
    assert "Grieving a dog." in p
    assert "3" in p
    assert "OUTLINE" in p          # marker the fake/tests key on


def test_chapter_prompt_includes_prior_titles():
    p = build_chapter_prompt(cfg(), {"title": "Two", "synopsis": "s"}, 2, ["One"])
    assert "Two" in p
    assert "One" in p              # continuity context


def test_generate_standard_two_pass_accumulates_chapters():
    out = generate_standard_content(cfg(chapter_count=3), generate_fn=_fake(3))
    assert out["preface"] == "A short preface."
    assert len(out["chapters"]) == 3
    assert out["chapters"][0]["title"] == "Chapter 1"
    assert out["chapters"][0]["paragraphs"]


def test_outline_wrong_length_is_rejected():
    # config asks for 3 chapters, outline returns 2 -> guard fires
    with pytest.raises(ContentError):
        generate_standard_content(cfg(chapter_count=3), generate_fn=_fake(2))


def test_validate_chapter_rejects_too_short():
    with pytest.raises(ContentError):
        validate_chapter({"paragraphs": ["too short"]}, min_words=20)


def test_validate_outline_rejects_missing_preface():
    with pytest.raises(ContentError):
        validate_outline({"chapters": [{"title": "a", "synopsis": "s"}]}, 1)


def test_validate_chapter_rejects_nonstring_paragraphs():
    with pytest.raises(ContentError):
        validate_chapter({"paragraphs": [{"text": "x"}]}, min_words=1)


def test_validate_outline_rejects_whitespace_title():
    with pytest.raises(ContentError):
        validate_outline({"preface": "p", "chapters": [{"title": "   "}]}, 1)


def test_generate_content_dispatches_standard():
    # the content.py dispatcher must route standard books to the two-pass path
    out = generate_content(cfg(chapter_count=2), generate_fn=_fake(2))
    assert "chapters" in out and len(out["chapters"]) == 2

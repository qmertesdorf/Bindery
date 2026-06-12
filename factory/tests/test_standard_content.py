import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError, generate_content
from factory.standard_content import (
    build_outline_prompt, build_chapter_prompt,
    validate_outline, validate_chapter, generate_standard_content,
    build_matter_prompt, validate_matter,
)


def cfg(**over):
    base = dict(slug="comp", title="Gentle Goodbye", subtitle="Sub", author="A",
                art_prompt="x", book_type="standard", synopsis="Grieving a dog.",
                chapter_count=3, words_per_chapter=40)
    base.update(over)
    return BookConfig(**base)


def _para(n_words=30):
    return " ".join(["word"] * n_words)


_MATTER_RESPONSE = {"epigraph": "Softly now.", "readings": ["r one", "r two", "r three"],
                    "closing_letter": "Dear friend, be gentle."}


def _fake(outline_chapters=3):
    """A prompt-aware fake LLM: outline call vs chapter call vs matter call."""
    outline = {"preface": "A short preface.",
               "chapters": [{"title": f"Chapter {i}", "synopsis": "s"}
                            for i in range(1, outline_chapters + 1)]}

    def fn(prompt):
        if "OUTLINE" in prompt:
            return json.dumps(outline)
        if "MATTER" in prompt:
            return json.dumps(_MATTER_RESPONSE)
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


def _one_chapter_outline():
    return json.dumps({"preface": "p",
                       "chapters": [{"title": "C1", "synopsis": "s"}]})


def test_short_chapter_triggers_one_retry_and_keeps_longer():
    # target 100 words; first draft is short (60) -> one "expand" retry; the
    # retry is longer (200) so it's kept. Exactly one retry, never a loop.
    state = {"calls": 0}
    long_para = " ".join(["word"] * 200)
    short_para = " ".join(["word"] * 60)

    def fn(prompt):
        if "OUTLINE" in prompt:
            return _one_chapter_outline()
        if "MATTER" in prompt:
            return json.dumps(_MATTER_RESPONSE)
        state["calls"] += 1
        if "TOO SHORT" in prompt:                      # the expand-retry prompt
            return json.dumps({"paragraphs": [long_para]})
        return json.dumps({"paragraphs": [short_para]})

    out = generate_standard_content(cfg(chapter_count=1, words_per_chapter=100), fn)
    wc = sum(len(p.split()) for p in out["chapters"][0]["paragraphs"])
    assert wc == 200            # kept the longer retry draft
    assert state["calls"] == 2  # one generate + one retry, no runaway loop


def test_adequate_chapter_skips_retry():
    # a chapter at/above the length floor must NOT trigger a wasteful retry
    state = {"calls": 0}

    def fn(prompt):
        if "OUTLINE" in prompt:
            return _one_chapter_outline()
        if "MATTER" in prompt:
            return json.dumps(_MATTER_RESPONSE)
        state["calls"] += 1
        return json.dumps({"paragraphs": [" ".join(["word"] * 120)]})  # >= 100*0.8

    generate_standard_content(cfg(chapter_count=1, words_per_chapter=100), fn)
    assert state["calls"] == 1  # no retry


def test_expand_prompt_demands_more_length():
    p = build_chapter_prompt(cfg(words_per_chapter=1800),
                             {"title": "T", "synopsis": "s"}, 1, [], expand=True)
    assert "TOO SHORT" in p
    assert "1800" in p


def test_matter_prompt_mentions_title_and_marker():
    p = build_matter_prompt(cfg())
    assert "Gentle Goodbye" in p
    assert "MATTER" in p          # marker the fake/dispatch key on


def test_validate_matter_requires_keys():
    with pytest.raises(ContentError):
        validate_matter({"epigraph": "x"})          # missing readings/closing_letter
    validate_matter({"epigraph": "x", "readings": ["a", "b", "c"],
                     "closing_letter": "Dear friend, ..."})   # ok


def test_generate_includes_matter():
    def fn(prompt):
        if "OUTLINE" in prompt:
            return json.dumps({"preface": "p",
                               "chapters": [{"title": "C1", "synopsis": "s"}]})
        if "MATTER" in prompt:
            return json.dumps({"epigraph": "A few gentle lines.",
                               "readings": ["r one", "r two", "r three"],
                               "closing_letter": "Dear friend, be gentle."})
        return json.dumps({"paragraphs": [_para(), _para()]})
    out = generate_standard_content(cfg(chapter_count=1), generate_fn=fn)
    assert out["epigraph"].startswith("A few gentle")
    assert len(out["readings"]) == 3
    assert out["closing_letter"].startswith("Dear friend")

import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.concept_content import (
    generate_concept_content, validate_concept_story, build_concept_story_prompt)


def _cfg(**over):
    base = dict(slug="tiny", title="Tiny Creatures", subtitle="sub",
                author="Eleanor Hartley", art_prompt="meadow, no text",
                book_type="concept", art_engine="flux",
                subject="small animals", flux_style="soft watercolour, no text",
                page_count=4)
    base.update(over)
    return BookConfig(**base)


def _fake_llm(bible, story):
    calls = {"n": 0}
    def fn(prompt):
        calls["n"] += 1
        return bible if calls["n"] == 1 else story
    return fn


def test_generate_concept_content_shape():
    bible = json.dumps({"art_style": "soft watercolour", "dedication": "For the curious."})
    story = json.dumps({"pages": [
        {"subject": "a fox", "text": "A fox is red.", "scene": "a fox in tall grass"},
        {"subject": "a snail", "text": "A snail is slow.", "scene": "a snail on a leaf"},
        {"subject": "an owl", "text": "An owl hoots.", "scene": "an owl in an oak at dusk"},
        {"subject": "a frog", "text": "A frog hops.", "scene": "a frog on a lily pad"},
    ], "closing": "So many tiny friends!"})
    content = generate_concept_content(_cfg(), _fake_llm(bible, story))
    assert content["dedication"] == "For the curious."
    assert content["closing"] == "So many tiny friends!"
    assert len(content["pages"]) == 4
    assert content["pages"][0]["subject"] == "a fox"
    assert content["pages"][0]["text"] == "A fox is red."
    # no character anchor for a character-free book
    assert content["character_anchor"] == ""


def test_concept_story_validates_page_count():
    with pytest.raises(ContentError, match="exactly 4"):
        validate_concept_story({"pages": [], "closing": "x"}, 4)


def test_concept_story_requires_scene():
    bad = {"pages": [{"subject": "a fox", "text": "hi", "scene": ""}], "closing": "x"}
    with pytest.raises(ContentError, match="scene"):
        validate_concept_story(bad, 1)


def test_concept_story_prompt_includes_explicit_topics():
    prompt = build_concept_story_prompt(_cfg(topics=("a fox", "a snail")))
    assert "a fox" in prompt and "a snail" in prompt

import json
import pytest
from factory.subject_fallback import (SubjectFallbackError, build_subject_prompt,
                                      suggest_subject)


def test_build_subject_prompt_includes_theme_used_failed_and_avoidance():
    p = build_subject_prompt("ocean animals", ["a whale", "a crab"], "a manatee")
    low = p.lower()
    assert "ocean animals" in low
    assert "a whale" in low and "a crab" in low      # the used list is shown
    assert "a manatee" in low                          # the failed subject is named
    assert "replacement subject" in low                # build-test marker phrase
    # best-judgment guidance to avoid Flux-hard body plans
    assert "avoid" in low and ("flat" in low or "eel" in low)


def test_suggest_subject_returns_clean_first_choice():
    out = suggest_subject(lambda prompt: '  "a sea turtle"\n',
                          theme="ocean animals", used=["a whale"], failed="a manatee")
    assert out == "a sea turtle"        # quotes/whitespace stripped, first line only


def test_suggest_subject_reasks_on_duplicate():
    seq = iter(["a whale", "a sea otter"])   # first is a dup of `used`, must re-ask
    out = suggest_subject(lambda prompt: next(seq), theme="ocean animals",
                          used=["a whale"], failed="a manatee", max_retries=2)
    assert out == "a sea otter"


def test_suggest_subject_raises_when_only_duplicates():
    # never offers anything new → give up this fallback slot (caller flags the page)
    with pytest.raises(SubjectFallbackError):
        suggest_subject(lambda prompt: "A Whale.", theme="ocean animals",
                        used=["a whale"], failed="a manatee", max_retries=1)


def test_suggest_subject_rejects_the_failed_subject():
    seq = iter(["a manatee", "a dolphin"])   # re-offering the failed subject is a dup
    out = suggest_subject(lambda prompt: next(seq), theme="ocean animals",
                          used=[], failed="a manatee", max_retries=2)
    assert out == "a dolphin"


from factory.config import BookConfig
from factory.concept_content import build_concept_page_prompt, regenerate_concept_page


def _cfg(**over):
    base = dict(slug="dbw", title="Deep Blue World", subtitle="sub",
                author="Hannah Whitfield",
                art_prompt="an ocean scene, soft watercolour, no text",
                book_type="concept", art_engine="flux",
                subject="ocean animals", flux_style="soft watercolour, no text",
                page_count=20)
    base.update(over)
    return BookConfig(**base)


def test_build_concept_page_prompt_names_subject_and_constraints():
    p = build_concept_page_prompt(_cfg(), "a sea turtle")
    low = p.lower()
    assert "a sea turtle" in low
    assert "subject of this spread" in low      # build-test marker phrase
    assert "rhyming couplet" in low or "two lines" in low
    assert "no people" in low


def test_regenerate_concept_page_returns_clean_fields():
    cfg = _cfg(max_reading_grade=0)             # readability gate off for this test
    page = regenerate_concept_page(cfg, lambda prompt: json.dumps(
        {"subject": "a sea turtle", "text": "A turtle swims,\nslow and calm.",
         "scene": "a green sea turtle gliding over a coral reef"}), "a sea turtle")
    assert page == {"subject": "a sea turtle",
                    "text": "A turtle swims,\nslow and calm.",
                    "scene": "a green sea turtle gliding over a coral reef"}


def test_regenerate_concept_page_retries_on_too_hard_readability():
    cfg = _cfg(max_reading_grade=3.0)
    seq = iter([
        # draft 1: far too hard for an early reader → rejected
        json.dumps({"subject": "a sea turtle",
                    "text": "The magnificent leatherback navigates extraordinary "
                            "transoceanic currents relentlessly.",
                    "scene": "a turtle"}),
        # draft 2: simple → accepted
        json.dumps({"subject": "a sea turtle", "text": "A turtle swims,\nby the reef.",
                    "scene": "a green sea turtle over a coral reef"}),
    ])
    page = regenerate_concept_page(cfg, lambda prompt: next(seq), "a sea turtle",
                                   max_retries=1)
    assert "magnificent" not in page["text"]    # the too-hard draft was rejected
    assert page["text"] == "A turtle swims,\nby the reef."


def test_regenerate_concept_page_raises_on_unusable_output():
    from factory.content import ContentError
    cfg = _cfg(max_reading_grade=0)
    with pytest.raises(ContentError):
        regenerate_concept_page(cfg, lambda prompt: "not json at all",
                                "a sea turtle", max_retries=1)

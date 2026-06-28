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


def test_build_subject_prompt_forbids_duplicates_relatives_and_offpalette():
    # The chooser must avoid a duplicate/relative/life-stage of an already-used animal
    # (the book teaches DISTINCT animals) and stay in the book's bright daytime palette
    # — the two failures seen on the first live run (turtle hatchling dup + night beach).
    p = build_subject_prompt("ocean animals", ["a green sea turtle"], "a manatee")
    low = p.lower()
    assert "different kind" in low
    assert "relative" in low or "life-stage" in low or "life stage" in low
    assert "distinct" in low                              # tour of distinct animals
    # palette/setting consistency: no night/off-palette subjects
    assert "night" in low and ("palette" in low or "setting" in low)


def test_suggest_subject_returns_clean_first_choice():
    out = suggest_subject(lambda prompt: '  "a sea turtle"\n',
                          theme="ocean animals", used=["a whale"], failed="a manatee")
    assert out == "a sea turtle"        # quotes/whitespace stripped, first line only


def test_suggest_subject_reasks_on_duplicate():
    seq = iter(["a whale", "a sea otter"])   # first is a dup of `used`, must re-ask
    out = suggest_subject(lambda prompt: next(seq), theme="ocean animals",
                          used=["a whale"], failed="a manatee", max_retries=2)
    assert out == "a sea otter"


def test_suggest_subject_rejects_near_duplicate_relative():
    # The real failures from the first live run: the chooser proposed a relative /
    # life-stage of an existing animal (a "harbor seal" when a "harbor seal pup" is
    # already in the book; a "sea turtle hatchling" when a "green sea turtle" is). The
    # code guard rejects these as near-duplicates and re-asks, even though the LLM
    # ignored the prompt's no-relatives instruction.
    seq = iter(["a round, smooth-bodied harbor seal", "a puffin"])
    out = suggest_subject(lambda prompt: next(seq), theme="ocean animals",
                          used=["a harbor seal pup", "a green sea turtle"],
                          failed="a manatee", max_retries=2)
    assert out == "a puffin"        # the harbor-seal near-duplicate was skipped

    seq2 = iter(["a sea turtle hatchling", "a sea otter"])
    out2 = suggest_subject(lambda prompt: next(seq2), theme="ocean animals",
                           used=["a green sea turtle"], failed="a manatee",
                           max_retries=2)
    assert out2 == "a sea otter"    # 'turtle' is already used → hatchling rejected


def test_suggest_subject_rejects_singular_of_plural_subject():
    # The book lists "dolphins"/"penguins" (plural); a singular "a dolphin" is still a
    # duplicate. The crude singulariser catches the plural/singular mismatch.
    seq = iter(["a dolphin", "a puffin"])
    out = suggest_subject(lambda prompt: next(seq), theme="ocean animals",
                          used=["dolphins", "penguins"], failed="a manatee",
                          max_retries=2)
    assert out == "a puffin"


def test_suggest_subject_allows_distinct_animal_sharing_only_generic_words():
    # A genuinely distinct animal must NOT be falsely rejected just for sharing a
    # generic descriptor (colour/habitat) with an existing subject: "a blue tang" and
    # "a blue lobster" share only "blue"; "a sea otter" and "a sea lion" share "sea".
    out = suggest_subject(lambda prompt: "a sea otter", theme="ocean animals",
                          used=["a sea lion", "a blue whale"], failed="a manatee")
    assert out == "a sea otter"     # shares only 'sea' (generic) → allowed


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


def test_build_concept_page_prompt_requires_accurate_but_friendly_body():
    # The single-page regenerator must carry the same friendly-face / accurate-body
    # (no-blob) house style as the full story prompt.
    low = build_concept_page_prompt(_cfg(), "a swordfish").lower()
    assert "friendly" in low
    assert "body" in low
    assert "blob" in low or "chubby ball" in low


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


def test_regenerate_concept_page_returns_last_draft_when_readability_never_clears():
    # If every parseable draft reads above the grade ceiling, regenerate does NOT
    # loop forever or raise — it returns the LAST parseable draft so the caller can
    # flag it (rather than failing the whole build on a stubborn caption).
    cfg = _cfg(max_reading_grade=3.0)
    seq = iter([
        json.dumps({"subject": "a sea turtle",
                    "text": "The magnificent leatherback navigates extraordinary "
                            "transoceanic currents relentlessly.",
                    "scene": "a turtle one"}),
        json.dumps({"subject": "a sea turtle",
                    "text": "An astonishing reptile traverses immeasurable oceanic "
                            "expanses persistently.",
                    "scene": "a turtle two"}),
    ])
    page = regenerate_concept_page(cfg, lambda prompt: next(seq), "a sea turtle",
                                   max_retries=1)
    assert page["scene"] == "a turtle two"      # the LAST parseable draft is returned


def test_regenerate_concept_page_raises_on_unusable_output():
    from factory.content import ContentError
    cfg = _cfg(max_reading_grade=0)
    with pytest.raises(ContentError):
        regenerate_concept_page(cfg, lambda prompt: "not json at all",
                                "a sea turtle", max_retries=1)

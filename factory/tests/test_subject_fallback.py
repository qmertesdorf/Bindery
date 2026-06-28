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

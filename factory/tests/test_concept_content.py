import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.concept_content import (
    generate_concept_content, validate_concept_story, build_concept_story_prompt,
    couplet_issues)


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
        {"subject": "a fox", "text": "A fox is red,\ncurled in its bed.",
         "scene": "a fox in tall grass"},
        {"subject": "a snail", "text": "A snail is slow,\nwith far to go.",
         "scene": "a snail on a leaf"},
        {"subject": "an owl", "text": "An owl can fly,\nhigh in the sky.",
         "scene": "an owl in an oak at dusk"},
        {"subject": "a frog", "text": "A frog can hop,\nand never stop.",
         "scene": "a frog on a lily pad"},
    ], "closing": "So many tiny friends!"})
    content = generate_concept_content(_cfg(), _fake_llm(bible, story))
    assert content["dedication"] == "For the curious."
    assert content["closing"] == "So many tiny friends!"
    assert len(content["pages"]) == 4
    assert content["pages"][0]["subject"] == "a fox"
    assert content["pages"][0]["text"] == "A fox is red,\ncurled in its bed."
    # no character anchor for a character-free book
    assert content["character_anchor"] == ""


def test_concept_story_validates_page_count():
    with pytest.raises(ContentError, match="exactly 4"):
        validate_concept_story({"pages": [], "closing": "x"}, 4)


def test_concept_story_requires_scene():
    bad = {"pages": [{"subject": "a fox", "text": "hi", "scene": ""}], "closing": "x"}
    with pytest.raises(ContentError, match="scene"):
        validate_concept_story(bad, 1)


def test_couplet_issues_accepts_a_real_two_line_rhyme():
    assert couplet_issues("A turtle swims by,\nunder the sky.") == []
    # punctuation/case differences don't break a legit rhyme
    assert couplet_issues("Deep in the SEA,\nan octopus swims free!") == []


def test_couplet_issues_flags_wrong_line_count():
    assert couplet_issues("A fox is red.")                      # one line
    assert couplet_issues("one\ntwo\nthree")                    # three lines


def test_couplet_issues_flags_identical_end_word_fake_rhyme():
    # both lines ending on the SAME word is not an AABB rhyme
    assert couplet_issues("A whale is blue,\nthe sea is blue.")


def test_concept_generation_feeds_rejection_reason_into_retry():
    # A first response that fails validation must be retried with the REASON fed back
    # into the prompt (not a blind identical re-roll), so a systematic miss self-corrects.
    bible = json.dumps({"art_style": "soft watercolour", "dedication": "For all."})
    good_pages = [
        {"subject": "a fox", "text": "A fox is red,\ncurled in its bed.",
         "scene": "a fox in grass"},
        {"subject": "an owl", "text": "An owl can fly,\nhigh in the sky.",
         "scene": "an owl at dusk"},
    ]
    bad_story = json.dumps({"pages": good_pages[:1], "closing": "x"})   # too few pages
    good_story = json.dumps({"pages": good_pages, "closing": "Bye!"})
    seen = []
    calls = {"n": 0}
    def fn(prompt):
        calls["n"] += 1
        seen.append(prompt)
        if calls["n"] == 1:
            return bible
        if calls["n"] == 2:
            return bad_story          # first story attempt: wrong page count
        return good_story             # retry succeeds
    content = generate_concept_content(_cfg(page_count=2), fn)
    assert len(content["pages"]) == 2
    # the retry prompt (4th call slot is story-retry = index 2) carries the rejection reason
    assert "REJECTED" in seen[2] and "exactly 2" in seen[2]


def test_concept_story_validates_couplet_contract():
    # a single-line 'couplet' in a read-aloud learning book is a real defect
    bad = {"pages": [{"subject": "a fox", "text": "A fox is red.",
                      "scene": "a fox in grass"}], "closing": "x"}
    with pytest.raises(ContentError, match="couplet"):
        validate_concept_story(bad, 1)


def test_concept_story_prompt_includes_explicit_topics():
    prompt = build_concept_story_prompt(_cfg(topics=("a fox", "a snail")))
    assert "a fox" in prompt and "a snail" in prompt


def test_concept_story_prompt_requires_rhyme():
    prompt = build_concept_story_prompt(_cfg()).lower()
    assert "rhym" in prompt  # text must be a rhyming couplet


def test_concept_story_prompt_requires_accurate_but_friendly_body():
    # House style: a friendly cute FACE but an ACCURATE, true-to-species BODY — never
    # rounded into the same chubby blob (the swordfish-look direction).
    low = build_concept_story_prompt(_cfg()).lower()
    assert "friendly" in low                              # keep the cute face
    assert "body" in low and ("true" in low or "accurate" in low
                              or "proportion" in low)     # accurate body
    assert "blob" in low or "chubby ball" in low          # explicit anti-blob guard
    # signature/defining features so the animal is recognizable (the spineless-puffer gap)
    assert "signature" in low and "recogniz" in low
    assert "spine" in low or "tusk" in low or "bill" in low


def test_scene_prompts_forbid_wrong_feature_similes():
    """'ear tufts like horns' in a scene begets literal ram horns (live defect,
    wild-green-world owl 2026-07-02): both scene-writing prompts must carry the
    anti-simile rule since scene text feeds the image model verbatim."""
    from factory.concept_content import build_concept_page_prompt
    rule = "NEVER describe a feature by comparing"
    flat = lambda s: " ".join(s.split())   # the prompts hard-wrap mid-sentence
    assert rule in flat(build_concept_story_prompt(_cfg()))
    assert rule in flat(build_concept_page_prompt(_cfg(), "a great horned owl"))


def test_scene_prompts_forbid_unpaintable_contact_actions():
    """'The baby elephant drinks with its trunk' failed 8/8 audits (live defect,
    wild-golden-world 2026-07-07): Flux never painted the trunk touching the water,
    so the caption audit could never pass. Both content prompts must steer couplets
    toward timeless facts and scenes toward simple calm poses, never a precise
    happening-right-now contact action the picture must then prove."""
    from factory.concept_content import build_concept_page_prompt
    flat = lambda s: " ".join(s.split()).lower()
    for p in (flat(build_concept_story_prompt(_cfg())),
              flat(build_concept_page_prompt(_cfg(), "an elephant calf"))):
        assert "paintable" in p
        assert "contact" in p
        assert "timeless" in p


def test_scene_prompts_forbid_negated_features():
    """A scene saying 'a plain tail, NOT ringed' made Flux paint a ringed tail (live
    defect, wild-golden-world meerkat 2026-07-07): the image model can't process
    'not' and paints the negated thing. Both scene prompts must forbid feature
    negation and demand positive-only description (same root as the anti-simile rule,
    since scene text feeds the model verbatim)."""
    from factory.concept_content import build_concept_page_prompt
    flat = lambda s: " ".join(s.split())
    for p in (flat(build_concept_story_prompt(_cfg())),
              flat(build_concept_page_prompt(_cfg(), "a meerkat"))):
        assert "never NEGATE" in p
        assert "positive appearance" in p


def test_story_prompt_corrects_wrong_fact_counts_in_topics():
    """A config topic said 'one large horn' on a rhino — real rhinos have two, Flux
    painted two, and the count guard rejected 8/8 (live defect, wild-golden-world
    2026-07-07). The story prompt must tell the writer to correct a mis-stated body
    fact from a provided topic rather than copy it verbatim."""
    flat = " ".join(build_concept_story_prompt(_cfg()).split()).lower()
    assert "mis-state" in flat
    assert "true fact" in flat


def test_story_prompt_demands_backdrop_variety():
    """20 forest pages converged to one repeated glowing-glade backdrop (user
    flag, wild-green-world 2026-07-02): the story prompt must explicitly demand
    per-page setting/light/framing variety within one cohesive style."""
    flat = " ".join(build_concept_story_prompt(_cfg()).split())
    assert "VARY THE BACKDROPS" in flat
    assert "No two consecutive pages" in flat

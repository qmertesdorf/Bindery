import json, pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.picture_content import (
    build_bible_prompt, build_story_prompt, validate_bible, validate_story,
    generate_picture_content)

def _cfg(**kw):
    base = dict(slug="k", title="Sunny's Last Walk", subtitle="S", author="A",
                art_prompt="x", book_type="picture", pet_kind="dog",
                pet_name="Sunny", page_count=4, trim_w=8.5, trim_h=8.5)
    base.update(kw); return BookConfig(**base)

def _page(i):
    return {"text": f"line {i}", "scene": f"scene {i}",
            "cast": "child_and_pet" if i % 2 else "child", "mood": "tender"}

def test_bible_prompt_mentions_pet_name_and_audience():
    p = build_bible_prompt(_cfg())
    assert "Sunny" in p and "dog" in p


def test_picture_generation_feeds_rejection_reason_into_retry():
    # the standard/picture paths now route through content.generate_json, so a first
    # bad story is retried with the rejection reason fed back into the prompt
    bible = json.dumps({"character_anchor": "a child and a dog",
                        "art_style": "soft watercolour", "dedication": "For Sunny."})
    good_pages = [_page(i) for i in range(1, 5)]
    bad_story = json.dumps({"pages": good_pages[:2], "closing": "x"})   # wrong count
    good_story = json.dumps({"pages": good_pages, "closing": "Goodnight."})
    seen = []
    calls = {"n": 0}
    def fn(prompt):
        seen.append(prompt); calls["n"] += 1
        if calls["n"] == 1:
            return bible
        if calls["n"] == 2:
            return bad_story
        return good_story
    out = generate_picture_content(_cfg(page_count=4), fn)
    assert len(out["pages"]) == 4
    assert "REJECTED" in seen[2] and "exactly 4" in seen[2]

def test_story_prompt_requests_exact_page_count():
    p = build_story_prompt(_cfg(page_count=4), anchor="a child and a dog")
    assert "4" in p and "a child and a dog" in p

def test_validate_story_rejects_wrong_page_count():
    with pytest.raises(ContentError, match="4 pages"):
        validate_story({"pages": [{"text": "t", "scene": "s"}], "closing": "c"}, 4)

def test_validate_story_rejects_empty_scene():
    pages = [{"text": "t", "scene": "", "cast": "child", "mood": "sad"}] * 4
    with pytest.raises(ContentError, match="scene"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_validate_story_rejects_bad_cast():
    pages = [{"text": "t", "scene": "s", "cast": "flashback", "mood": "sad"}] * 4
    with pytest.raises(ContentError, match="cast"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_validate_story_rejects_missing_mood():
    pages = [{"text": "t", "scene": "s", "cast": "child", "mood": ""}] * 4
    with pytest.raises(ContentError, match="mood"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_generate_picture_content_assembles_schema():
    bible = {"character_anchor": "a small girl with a golden dog",
             "art_style": "soft flat storybook watercolor", "dedication": "For Sunny"}
    story = {"pages": [_page(i) for i in range(4)],
             "closing": "We will always remember you."}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_picture_content(_cfg(page_count=4), fake_llm)
    assert out["character_anchor"].startswith("a small girl")
    assert out["art_style"] == "soft flat storybook watercolor"
    assert len(out["pages"]) == 4 and out["closing"].startswith("We will")
    assert out["pages"][0]["cast"] in ("child", "child_and_pet", "pet")

def test_config_art_style_overrides_bible():
    bible = {"character_anchor": "anchor", "art_style": "MODEL CHOICE", "dedication": "d"}
    story = {"pages": [_page(i) for i in range(4)], "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_picture_content(_cfg(page_count=4, art_style="LOCKED STYLE"), fake_llm)
    assert out["art_style"] == "LOCKED STYLE"

def test_comfort_story_prompt_uses_all_three_casts_and_frame():
    p = build_story_prompt(_cfg(theme="comfort"), anchor="a girl and a cat")
    assert "child_and_pet" in p and "pet" in p and "child" in p
    assert "peaceful" in p.lower()           # the luminous "beyond" framing
    assert "heart" in p.lower()              # closes on "stays in your heart"
    assert "GONE" not in p                   # not the grief framing

def test_grief_story_prompt_still_grief_by_default():
    p = build_story_prompt(_cfg(), anchor="a child and a dog")   # theme defaults grief
    assert "GONE" in p and "grief book" in p

def test_comfort_bible_prompt_framing():
    p = build_bible_prompt(_cfg(theme="comfort"))
    assert "Sunny" in p and "comfort" in p.lower()
    assert "grieving the death" not in p    # comfort bible must not use grief framing


def test_grief_bible_prompt_keeps_remembered_wording():
    p = build_bible_prompt(_cfg())   # grief default
    assert "remembered moments" in p
    assert "grieving the death" in p

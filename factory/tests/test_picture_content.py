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
            "moment": "memory" if i % 2 else "present", "mood": "tender"}

def test_bible_prompt_mentions_pet_name_and_audience():
    p = build_bible_prompt(_cfg())
    assert "Sunny" in p and "dog" in p

def test_story_prompt_requests_exact_page_count():
    p = build_story_prompt(_cfg(page_count=4), anchor="a child and a dog")
    assert "4" in p and "a child and a dog" in p

def test_validate_story_rejects_wrong_page_count():
    with pytest.raises(ContentError, match="4 pages"):
        validate_story({"pages": [{"text": "t", "scene": "s"}], "closing": "c"}, 4)

def test_validate_story_rejects_empty_scene():
    pages = [{"text": "t", "scene": "", "moment": "present", "mood": "sad"}] * 4
    with pytest.raises(ContentError, match="scene"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_validate_story_rejects_bad_moment():
    pages = [{"text": "t", "scene": "s", "moment": "flashback", "mood": "sad"}] * 4
    with pytest.raises(ContentError, match="moment"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_validate_story_rejects_missing_mood():
    pages = [{"text": "t", "scene": "s", "moment": "present", "mood": ""}] * 4
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
    assert out["pages"][0]["moment"] in ("memory", "present")

def test_config_art_style_overrides_bible():
    bible = {"character_anchor": "anchor", "art_style": "MODEL CHOICE", "dedication": "d"}
    story = {"pages": [_page(i) for i in range(4)], "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_picture_content(_cfg(page_count=4, art_style="LOCKED STYLE"), fake_llm)
    assert out["art_style"] == "LOCKED STYLE"

import json
import pytest
from factory.config import BookConfig
from factory.content import build_prompt, generate_content, ContentError, validate_content


@pytest.fixture
def cfg():
    return BookConfig(slug="dog-loss", title="T", subtitle="S", author="A",
                      pet_kind="dog", art_prompt="x", prompt_count=5)


def test_build_prompt_mentions_pet_and_count(cfg):
    p = build_prompt(cfg)
    assert "dog" in p
    assert "5" in p
    assert "JSON" in p


def test_generate_content_parses_fenced_json(cfg, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    fake = lambda prompt: "```json\n" + json.dumps(sample_content) + "\n```"
    out = generate_content(cfg, generate_fn=fake)
    assert len(out["prompts"]) == 5
    assert out["intro"]


def test_generate_content_rejects_bad_json(cfg):
    with pytest.raises(ContentError):
        generate_content(cfg, generate_fn=lambda p: "not json at all")


def test_validate_rejects_missing_key(sample_content):
    del sample_content["prompts"]
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=70)


def test_validate_rejects_wrong_prompt_count(sample_content):
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=999)


import json
from factory.config import BookConfig
from factory.content import generate_content

def test_generate_content_dispatches_picture():
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="picture", pet_kind="dog", pet_name="Sunny",
                     page_count=4, trim_w=8.5, trim_h=8.5)
    bible = {"character_anchor": "a child and a golden dog",
             "art_style": "soft watercolor", "dedication": "For Sunny"}
    story = {"pages": [{"text": f"t{i}", "scene": f"s{i}",
                        "moment": "present", "mood": "tender"} for i in range(4)],
             "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_content(cfg, generate_fn=fake_llm)
    assert len(out["pages"]) == 4 and out["character_anchor"].startswith("a child")

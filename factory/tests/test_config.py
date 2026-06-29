import json
import pytest
from factory.config import load_config, BookConfig, ConfigError


def test_load_valid(sample_config_file):
    cfg = load_config(sample_config_file)
    assert isinstance(cfg, BookConfig)
    assert cfg.slug == "dog-loss"
    assert cfg.pet_kind == "dog"
    assert cfg.prompt_count == 70
    assert cfg.price_usd == 9.99


def test_missing_required_field(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"slug": "x"}), encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "title" in str(e.value)


def test_defaults_applied(tmp_path):
    p = tmp_path / "min.json"
    p.write_text(json.dumps({
        "slug": "cat-loss", "title": "T", "subtitle": "S", "author": "A",
        "pet_kind": "cat", "art_prompt": "watercolor cat",
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.prompt_count == 70      # default
    assert cfg.price_usd == 9.99       # default
    # WS1 QA stages default OFF so behaviour is unchanged until provisioned
    assert cfg.qa_vqa is False and cfg.qa_anatomy is False
    assert cfg.qa_candidates == 1 and cfg.qa_repair is False
    assert cfg.qa_tifa is False and cfg.qa_tifa_threshold == 0.4
    assert cfg.qa_max_tries == 4       # default render→audit attempts per page
    assert cfg.qa_border_gate is False  # hard full-bleed gate OFF by default (keeps soft watercolour edges)
    assert cfg.qa_select == "claude"    # best-of-N taste selector is the default chooser
    # the load_config default must match the calibrated dataclass default (0.15),
    # not the old stray 0.6, so an omitting config gets the calibrated floor
    assert cfg.qa_vqa_threshold == 0.15
    assert cfg.max_reading_grade == 6.0   # WS6a default early-reader ceiling


def test_qa_flags_loaded(tmp_path):
    p = tmp_path / "qa.json"
    p.write_text(json.dumps({
        "slug": "ocean", "title": "T", "subtitle": "S", "author": "A",
        "pet_kind": "cat", "art_prompt": "watercolor ocean",
        "qa_vqa": True, "qa_vqa_threshold": 0.7, "qa_anatomy": True,
        "qa_anatomy_min_score": 0.4, "qa_candidates": 5, "qa_repair": True,
        "qa_tifa": True, "qa_tifa_threshold": 0.6, "qa_max_tries": 8,
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.qa_vqa is True and cfg.qa_vqa_threshold == 0.7
    assert cfg.qa_anatomy is True and cfg.qa_anatomy_min_score == 0.4
    assert cfg.qa_candidates == 5 and cfg.qa_repair is True
    assert cfg.qa_tifa is True and cfg.qa_tifa_threshold == 0.6
    assert cfg.qa_max_tries == 8


def test_book_type_defaults_to_journal(sample_config_file):
    cfg = load_config(sample_config_file)
    # the factory makes journals by default; journals are paperback-only
    assert cfg.book_type == "journal"
    assert cfg.makes_ebook is False


def test_standard_book_type_makes_ebook(tmp_path):
    p = tmp_path / "std.json"
    p.write_text(json.dumps({
        "slug": "memoir", "title": "T", "subtitle": "S", "author": "A",
        "art_prompt": "x", "book_type": "standard",
        "synopsis": "A gentle read.", "chapter_count": 8,
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.book_type == "standard"
    assert cfg.makes_ebook is True


def test_invalid_book_type_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "slug": "x", "title": "T", "subtitle": "S", "author": "A",
        "pet_kind": "dog", "art_prompt": "x", "book_type": "magazine",
    }), encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "book_type" in str(e.value)


def _write(tmp_path, **over):
    base = {"slug": "x", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "art"}
    base.update(over)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_journal_requires_pet_kind(tmp_path):
    # journal is the default; without pet_kind it must fail
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path))            # no pet_kind
    assert "pet_kind" in str(e.value)


def test_standard_requires_synopsis_and_chapters(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, book_type="standard"))  # no synopsis/chapter_count
    msg = str(e.value)
    assert "synopsis" in msg or "chapter_count" in msg


def test_standard_config_loads_fields(tmp_path):
    cfg = load_config(_write(tmp_path, book_type="standard",
                             synopsis="A gentle book.", chapter_count=8,
                             words_per_chapter=1500, blurb="Back cover."))
    assert cfg.book_type == "standard"
    assert cfg.synopsis == "A gentle book."
    assert cfg.chapter_count == 8
    assert cfg.words_per_chapter == 1500
    assert cfg.blurb == "Back cover."
    assert cfg.pet_kind == ""                    # optional for standard
    assert cfg.makes_ebook is True


def test_trim_defaults_to_6x9(tmp_path):
    cfg = load_config(_write(tmp_path, pet_kind="dog"))
    assert cfg.trim_w == 6.0 and cfg.trim_h == 9.0


def test_trim_override_for_standard(tmp_path):
    cfg = load_config(_write(tmp_path, book_type="standard",
                             synopsis="A gentle read.", chapter_count=8,
                             trim_w=5.5, trim_h=8.5))
    assert cfg.trim_w == 5.5 and cfg.trim_h == 8.5


def test_trim_must_be_positive(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, pet_kind="dog", trim_w=0))


def _write_d(tmp_path, d):
    p = tmp_path / "b.config.json"; p.write_text(json.dumps(d), encoding="utf-8"); return p


def test_picture_config_loads(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "dog-loss-kids", "title": "T", "subtitle": "S", "author": "A",
        "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
        "pet_name": "Sunny", "page_count": 22, "trim_w": 8.5, "trim_h": 8.5,
        "price_usd": 10.99}))
    assert cfg.book_type == "picture"
    assert cfg.pet_name == "Sunny" and cfg.page_count == 22
    assert cfg.makes_ebook is False


def test_picture_requires_pet_name(tmp_path):
    with pytest.raises(ConfigError, match="pet_name"):
        load_config(_write_d(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
            "page_count": 22}))


def test_picture_page_count_even_and_min(tmp_path):
    with pytest.raises(ConfigError, match="page_count"):
        load_config(_write_d(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
            "pet_name": "Sunny", "page_count": 21}))


from pathlib import Path


def test_dog_loss_kids_config_is_valid():
    p = Path(__file__).resolve().parent.parent / "books" / "dog-loss-kids.config.json"
    cfg = load_config(p)
    assert cfg.book_type == "picture" and cfg.pet_kind == "dog"
    assert cfg.trim_w == 8.5 and cfg.trim_h == 8.5
    assert cfg.page_count >= 20 and cfg.page_count % 2 == 0


def _flux_dict(**over):
    d = {"slug": "k", "title": "T", "subtitle": "S", "author": "A",
         "art_prompt": "cover scene", "book_type": "picture", "pet_kind": "dog",
         "pet_name": "Biscuit", "page_count": 22, "trim_w": 8.5, "trim_h": 8.5,
         "art_engine": "flux",
         "flux_style": "watercolour storybook, no text",
         "flux_guidance": 2.4,
         "outfit": "a red sweater and blue overalls",
         "characters": [
             {"role": "hero", "lora": "boy.safetensors", "trigger": "b1scuitboy boy",
              "strength": 0.9},
             {"role": "companion", "lora": "dog.safetensors", "trigger": "b1scuitdog dog",
              "strength": 0.85, "appears_on": "memory"}]}
    d.update(over)
    return d

def test_flux_picture_config_parses(tmp_path):
    cfg = load_config(_write_d(tmp_path, _flux_dict()))
    assert cfg.art_engine == "flux"
    assert cfg.flux_style.startswith("watercolour")
    assert cfg.flux_guidance == 2.4
    assert cfg.outfit == "a red sweater and blue overalls"
    assert len(cfg.characters) == 2
    hero = cfg.characters[0]
    assert hero.role == "hero" and hero.lora == "boy.safetensors"
    assert hero.trigger == "b1scuitboy boy" and hero.strength == 0.9
    comp = cfg.characters[1]
    assert comp.role == "companion" and comp.appears_on == "memory"
    assert cfg.upscale_model == ""        # WS3b: lanczos-only by default

def test_flux_config_loads_upscale_model(tmp_path):
    cfg = load_config(_write_d(tmp_path, _flux_dict(upscale_model="4x-UltraSharp.pth")))
    assert cfg.upscale_model == "4x-UltraSharp.pth"

def test_art_engine_defaults_to_sdxl(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "dog", "pet_name": "Sunny",
        "page_count": 22}))
    assert cfg.art_engine == "sdxl"
    assert cfg.characters == ()

def test_invalid_art_engine_rejected(tmp_path):
    with pytest.raises(ConfigError, match="art_engine"):
        load_config(_write_d(tmp_path, _flux_dict(art_engine="midjourney")))

def test_flux_requires_exactly_one_hero(tmp_path):
    with pytest.raises(ConfigError, match="hero"):
        load_config(_write_d(tmp_path, _flux_dict(characters=[
            {"role": "companion", "lora": "dog.safetensors", "trigger": "d",
             "appears_on": "memory"}])))

def test_flux_character_requires_lora_and_trigger(tmp_path):
    with pytest.raises(ConfigError, match="lora"):
        load_config(_write_d(tmp_path, _flux_dict(characters=[
            {"role": "hero", "trigger": "b1scuitboy boy"}])))

def test_flux_character_requires_trigger_when_lora_present(tmp_path):
    with pytest.raises(ConfigError, match="trigger"):
        load_config(_write_d(tmp_path, _flux_dict(characters=[
            {"role": "hero", "lora": "boy.safetensors"}])))

def test_flux_requires_flux_style(tmp_path):
    with pytest.raises(ConfigError, match="flux_style"):
        load_config(_write_d(tmp_path, _flux_dict(flux_style="")))

def test_picture_theme_defaults_to_grief(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "dog", "pet_name": "Sunny",
        "page_count": 22}))
    assert cfg.theme == "grief"

def test_picture_theme_comfort_parses(tmp_path):
    cfg = load_config(_write_d(tmp_path, {
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "cat", "pet_name": "Mango",
        "page_count": 22, "theme": "comfort"}))
    assert cfg.theme == "comfort"

def test_invalid_theme_rejected(tmp_path):
    with pytest.raises(ConfigError, match="theme"):
        load_config(_write_d(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
            "book_type": "picture", "pet_kind": "cat", "pet_name": "Mango",
            "page_count": 22, "theme": "spooky"}))


def test_where_does_mango_go_config_is_valid():
    p = Path(__file__).resolve().parent.parent / "books" / "where-does-mango-go.config.json"
    cfg = load_config(p)
    assert cfg.book_type == "picture" and cfg.art_engine == "flux"
    assert cfg.theme == "comfort" and cfg.pet_name == "Mango"
    assert cfg.trim_w == 8.5 and cfg.page_count >= 20 and cfg.page_count % 2 == 0
    assert len(cfg.characters) == 2
    assert cfg.characters[0].role == "hero"


def _concept_data(**over):
    data = {
        "slug": "tiny-creatures",
        "book_type": "concept",
        "art_engine": "flux",
        "title": "Tiny Creatures",
        "subtitle": "A First Look at Little Animals",
        "author": "Eleanor Hartley",
        "subject": "small animals and where they live",
        "flux_style": "soft storybook watercolour, warm natural palette, no text",
        "art_prompt": "a sunlit meadow full of small creatures, soft storybook watercolour, no text",
        "page_count": 22,
        "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }
    data.update(over)
    return data


def test_concept_config_loads(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data()), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.book_type == "concept"
    assert cfg.subject == "small animals and where they live"
    assert cfg.art_engine == "flux"
    assert cfg.makes_ebook is False


def test_concept_config_topics_parsed(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(topics=["a fox", "a snail"])), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.topics == ("a fox", "a snail")


def test_concept_requires_subject(tmp_path):
    p = tmp_path / "c.json"
    d = _concept_data(); d.pop("subject")
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ConfigError, match="subject"):
        load_config(p)


def test_concept_requires_flux_engine(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(art_engine="sdxl")), encoding="utf-8")
    with pytest.raises(ConfigError, match="flux"):
        load_config(p)


def test_concept_requires_flux_style(tmp_path):
    p = tmp_path / "c.json"
    d = _concept_data(); d.pop("flux_style")
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ConfigError, match="flux_style"):
        load_config(p)


def test_concept_page_count_floor(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(page_count=18)), encoding="utf-8")
    with pytest.raises(ConfigError, match="page_count"):
        load_config(p)


def test_illustrator_optional_and_parsed(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data()), encoding="utf-8")
    assert load_config(p).illustrator == ""          # optional, defaults empty
    p.write_text(json.dumps(_concept_data(illustrator="Grace Sullivan")), encoding="utf-8")
    assert load_config(p).illustrator == "Grace Sullivan"


def test_subject_fallback_flags_default_off_and_parse(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_concept_data()), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.subject_fallback is False          # default OFF
    assert cfg.max_fallbacks == 3                 # default cap

    p.write_text(json.dumps(_concept_data(subject_fallback=True, max_fallbacks=5)),
                 encoding="utf-8")
    cfg = load_config(p)
    assert cfg.subject_fallback is True
    assert cfg.max_fallbacks == 5

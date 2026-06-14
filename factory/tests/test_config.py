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

def test_flux_requires_flux_style(tmp_path):
    with pytest.raises(ConfigError, match="flux_style"):
        load_config(_write_d(tmp_path, _flux_dict(flux_style="")))

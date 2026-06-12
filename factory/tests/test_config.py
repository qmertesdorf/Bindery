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
        "pet_kind": "n/a", "art_prompt": "x", "book_type": "standard",
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.book_type == "standard"
    assert cfg.makes_ebook is True     # read-through books still get a Kindle edition


def test_invalid_book_type_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({
        "slug": "x", "title": "T", "subtitle": "S", "author": "A",
        "pet_kind": "dog", "art_prompt": "x", "book_type": "magazine",
    }), encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "book_type" in str(e.value)

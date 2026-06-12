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

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

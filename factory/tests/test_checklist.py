from pathlib import Path
from factory.config import BookConfig
from factory.checklist import make_checklist


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", price_usd=9.99)


def std_cfg():
    return BookConfig(slug="memoir", title="A Book", subtitle="Sub",
                      author="A", art_prompt="x", price_usd=14.99,
                      book_type="standard", synopsis="A gentle read about loss.",
                      chapter_count=18, blurb="A comforting companion read.",
                      trim_w=5.5, trim_h=8.5)


def test_make_checklist_has_disclosure_and_royalty(tmp_path):
    out = make_checklist(cfg(), pages=120, out_dir=tmp_path)
    text = Path(out).read_text(encoding="utf-8")
    assert "AI" in text and "disclos" in text.lower()
    assert "Text: AI-generated" in text
    assert "Images: AI-generated" in text
    assert "$9.99" in text
    assert "Death & Grief" in text
    assert "3.70" in text  # royalty 9.99*0.6 - 2.29


def test_journal_checklist_omits_ebook(tmp_path):
    # cfg() is a journal (default book_type) — paperback-only, no Kindle artifacts
    text = Path(make_checklist(cfg(), pages=120, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "interior.epub" not in text
    assert "cover-ebook.jpg" not in text
    assert "ASIN" not in text


def test_standard_checklist_includes_ebook(tmp_path):
    text = Path(make_checklist(std_cfg(), pages=120, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "interior.epub" in text
    assert "cover-ebook.jpg" in text


def test_standard_checklist_no_pet_kind_crash(tmp_path):
    # standard books have empty pet_kind; keywords/description must not break
    text = Path(make_checklist(std_cfg(), pages=120, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "A comforting companion read." in text   # standard description = blurb
    assert "{{" not in text                          # template fully rendered


def test_checklist_shows_configured_trim_and_resources_note(tmp_path):
    text = Path(make_checklist(std_cfg(), pages=150, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "5.5 x 8.5" in text
    assert "6x9" not in text and "6 x 9" not in text   # no hardcoded trim leaks through
    assert "verify" in text.lower() and "resource" in text.lower()


def test_picture_checklist_is_colour_and_juvenile(tmp_path):
    import json
    from factory.config import load_config
    cfgp = tmp_path / "k.config.json"
    cfgp.write_text(json.dumps({
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "dog", "pet_name": "Sunny",
        "page_count": 26, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99}),
        encoding="utf-8")
    cfg = load_config(cfgp)
    out = make_checklist(cfg, 26, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "Color" in text  # interior is colour, not "Black & white"
    assert "Juvenile" in text  # juvenile category, not Self-Help
    assert "cream" not in text.lower()  # colour books print on white stock

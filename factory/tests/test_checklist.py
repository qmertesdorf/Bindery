from pathlib import Path
from factory.config import BookConfig
from factory.checklist import make_checklist


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", price_usd=9.99)


def std_cfg():
    return BookConfig(slug="memoir", title="A Book", subtitle="Sub",
                      author="A", pet_kind="n/a", art_prompt="x",
                      price_usd=9.99, book_type="standard")


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

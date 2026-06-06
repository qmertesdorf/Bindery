from pathlib import Path
from factory.config import BookConfig
from factory.checklist import make_checklist


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", price_usd=9.99)


def test_make_checklist_has_disclosure_and_royalty(tmp_path):
    out = make_checklist(cfg(), pages=120, out_dir=tmp_path)
    text = Path(out).read_text(encoding="utf-8")
    assert "AI" in text and "disclos" in text.lower()
    assert "Text: AI-generated" in text
    assert "Images: AI-generated" in text
    assert "$9.99" in text
    assert "Death & Grief" in text
    assert "3.70" in text  # royalty 9.99*0.6 - 2.29

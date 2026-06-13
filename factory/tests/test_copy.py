from factory.config import BookConfig
from factory.copy import book_blurb


def journal_cfg():
    return BookConfig(slug="d", title="T", subtitle="S", author="A",
                      pet_kind="dog", art_prompt="x")


def standard_cfg(**over):
    base = dict(slug="c", title="T", subtitle="S", author="A", art_prompt="x",
                book_type="standard", synopsis="A gentle read about loss.",
                chapter_count=8)
    base.update(over)
    return BookConfig(**base)


def test_journal_blurb_mentions_pet():
    assert "dog" in book_blurb(journal_cfg())


def test_standard_blurb_uses_blurb_field():
    assert book_blurb(standard_cfg(blurb="Custom back cover.")) == "Custom back cover."


def test_standard_blurb_falls_back_to_synopsis():
    assert book_blurb(standard_cfg()) == "A gentle read about loss."


def test_picture_blurb_mentions_child_and_pet():
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="picture", pet_kind="dog", pet_name="Sunny",
                     page_count=22, trim_w=8.5, trim_h=8.5)
    b = book_blurb(cfg)
    assert "dog" in b.lower() and ("child" in b.lower() or "little" in b.lower())

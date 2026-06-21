import pytest
from factory.config import BookConfig
from factory.copy import (book_blurb, listing_description, listing_keywords,
                          verify_listing_copy, ListingCopyError, KDP_KEYWORD_MAX)


def concept_cfg(**over):
    base = dict(slug="wlw", title="Wild Little World", subtitle="S", author="A",
                art_prompt="x", book_type="concept", art_engine="flux",
                subject="ocean animals", flux_style="soft watercolour",
                page_count=24, trim_w=8.5, trim_h=8.5)
    base.update(over)
    return BookConfig(**base)


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


# ── WS6b: Rufus-era natural-language listing copy ──────────────────────────────

def test_listing_description_leads_with_blurb_then_expands():
    cfg = concept_cfg(blurb="Step into a wild little world.")
    desc = listing_description(cfg)
    # the back-cover hook leads, then the intent body expands it (longer than blurb)
    assert desc.startswith("Step into a wild little world.")
    assert len(desc) > len(book_blurb(cfg))
    # natural-language buyer intent woven in, not a keyword list
    assert "ocean animals" in desc
    assert any(w in desc.lower() for w in ("bedtime", "gift", "read aloud", "read-aloud"))


def test_listing_description_standard_is_just_synopsis():
    cfg = BookConfig(slug="c", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="standard", synopsis="A gentle read about loss.",
                     chapter_count=8)
    assert listing_description(cfg) == "A gentle read about loss."


def test_concept_keywords_derive_from_subject():
    kws = listing_keywords(concept_cfg(subject="ocean animals"))
    assert len(kws) == 7
    assert any("ocean animals" in k for k in kws)
    # not the old hardcoded animal stuffing
    assert "children's animal book" not in kws


def test_keywords_respect_kdp_length_limit():
    # a long subject must not push any keyword past KDP's 50-char field limit
    kws = listing_keywords(concept_cfg(subject="freshwater fish and pond creatures"))
    assert all(len(k) <= KDP_KEYWORD_MAX for k in kws)


def test_verify_listing_copy_passes_for_all_book_types():
    verify_listing_copy(concept_cfg())
    verify_listing_copy(BookConfig(slug="j", title="T", subtitle="S", author="A",
                                   art_prompt="x", pet_kind="dog"))   # journal
    verify_listing_copy(BookConfig(slug="p", title="T", subtitle="S", author="A",
                                   art_prompt="x", book_type="picture", pet_kind="cat",
                                   pet_name="Mango", page_count=24, trim_w=8.5, trim_h=8.5))
    verify_listing_copy(BookConfig(slug="s", title="A Quiet Year", subtitle="S",
                                   author="A", art_prompt="x", book_type="standard",
                                   synopsis="A gentle read about loss.", chapter_count=8))


def test_verify_listing_copy_rejects_stuffed_keywords(monkeypatch):
    import factory.copy as copymod
    monkeypatch.setattr(copymod, "listing_keywords",
                        lambda cfg: ["dog gift"] * 7)   # duplicates + no diversity
    with pytest.raises(ListingCopyError):
        verify_listing_copy(concept_cfg())


def test_long_subject_keywords_are_not_clipped_mid_phrase():
    # captions-style long subject must yield a compact head noun, not "...and the"
    cfg = concept_cfg(subject="ocean animals and the watery places they live")
    kws = listing_keywords(cfg)
    assert all(len(k) <= KDP_KEYWORD_MAX for k in kws)
    dangling = {"and", "the", "a", "an", "for", "of", "to", "with", "about", "or"}
    assert all(k.split()[-1].lower() not in dangling for k in kws)
    assert any("ocean animals" in k for k in kws)   # head noun preserved
    verify_listing_copy(cfg)                          # the guard accepts it


def test_verify_listing_copy_rejects_overlong_keyword(monkeypatch):
    import factory.copy as copymod
    long_kw = "a" * (KDP_KEYWORD_MAX + 5)
    monkeypatch.setattr(copymod, "listing_keywords",
                        lambda cfg: [long_kw] + [f"distinct phrase number {i}" for i in range(6)])
    with pytest.raises(ListingCopyError):
        verify_listing_copy(concept_cfg())

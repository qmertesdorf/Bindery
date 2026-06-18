from pathlib import Path
from factory.config import BookConfig
from factory.interior import render_interior_html, InteriorError, _verify_picture_page_count
import pytest

def _cfg():
    return BookConfig(slug="k", title="Sunny's Last Walk", subtitle="S", author="A",
                      art_prompt="x", book_type="picture", pet_kind="dog",
                      pet_name="Sunny", page_count=2, trim_w=8.5, trim_h=8.5)

def _content():
    return {"character_anchor": "a", "art_style": "s", "dedication": "For Sunny",
            "pages": [{"text": "We walked every morning.", "scene": "garden"},
                      {"text": "Now the leash hangs still.", "scene": "hallway"}],
            "closing": "Love stays."}

def test_picture_interior_has_image_per_page_and_text(tmp_path):
    html_path = render_interior_html(_cfg(), _content(), tmp_path)
    html = html_path.read_text(encoding="utf-8")
    assert 'page_01.png' in html and 'page_02.png' in html
    assert "We walked every morning." in html
    assert "For Sunny" in html and "Love stays." in html
    # no fill-in ruled lines in a picture book
    assert 'class="lines"' not in html

def test_picture_interior_feathers_all_four_edges(tmp_path):
    # Guards the "stapled photo box" defect: art must fade on all four straight
    # edges (crossed gradients intersected), not the old single radial that left
    # the side-centres hard.
    html = render_interior_html(_cfg(), _content(), tmp_path).read_text(encoding="utf-8")
    assert "mask-composite: intersect" in html
    assert "linear-gradient(to right" in html and "linear-gradient(to bottom" in html
    assert "radial-gradient" not in html  # the old hard-edged mask is gone

def test_picture_page_count_guard_rejects_under_24():
    with pytest.raises(InteriorError, match="24"):
        _verify_picture_page_count(20)

def test_picture_page_count_guard_rejects_odd():
    with pytest.raises(InteriorError, match="even"):
        _verify_picture_page_count(25)

def test_picture_page_count_guard_accepts_even_min():
    _verify_picture_page_count(24)  # no raise

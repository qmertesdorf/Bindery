from pathlib import Path
from factory.config import BookConfig
from factory.interior import render_interior_html


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", prompt_count=5)


def test_render_interior_html_contains_title_and_prompts(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "Paw Prints" in text
    assert "prompt 1" in text
    assert text.count('class="page"') >= 3  # paginated layout

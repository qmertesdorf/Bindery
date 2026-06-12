import pytest
from pathlib import Path
from factory import specs
from factory.config import BookConfig
from factory.interior import render_interior_html
from factory.interior import (count_pages, build_interior_pdf, build_epub,
                              _verify_interior_margins, InteriorError)


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


def test_count_pages(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    # title + intro + profile + memories-head + 5 prompts + milestones-head
    # + 3 milestones + 2 letters = 15
    assert count_pages(html_path) == 15


def test_build_interior_pdf_calls_browse(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    calls = []
    def runner(args):
        calls.append(args)
        (tmp_path / "interior.pdf").write_bytes(b"%PDF-1.4")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, pages = build_interior_pdf(html_path, tmp_path, runner=runner)
    assert Path(pdf).exists()
    assert pages == 15
    assert any(a[1] == "pdf" for a in calls)


def test_build_epub(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    out = build_epub(cfg(), sample_content, tmp_path)
    assert Path(out).exists()
    assert Path(out).suffix == ".epub"


def test_verify_interior_margins(tmp_path):
    import fitz
    W, H = specs.TRIM_W_IN * 72, specs.TRIM_H_IN * 72

    def page_with_text(x_in, y_in):
        p = tmp_path / f"i_{x_in}_{y_in}.pdf"
        d = fitz.open(); pg = d.new_page(width=W, height=H)
        pg.insert_text((x_in * 72, y_in * 72), "text", fontsize=12)
        d.save(str(p)); d.close()
        return p

    # text inside the margins -> passes
    _verify_interior_margins(page_with_text(1.0, 2.0))
    # text below the bottom margin (runs into the trim) -> hard failure
    with pytest.raises(InteriorError):
        _verify_interior_margins(page_with_text(1.0, 8.9))
    # non-PDF stub is skipped
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    _verify_interior_margins(stub)

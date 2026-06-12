import pytest
from pathlib import Path
from factory import specs
from factory.config import BookConfig
from factory.interior import render_interior_html
from factory.interior import (count_pages, build_interior_pdf, build_epub,
                              _verify_interior_margins, InteriorError, pdf_page_count)


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


def test_build_epub_standard_chapters(tmp_path):
    out = build_epub(std_cfg(), std_content(), tmp_path)
    assert Path(out).exists() and Path(out).suffix == ".epub"
    # the chapters are actually rendered into the package (not just the nav doc)
    import zipfile
    zf = zipfile.ZipFile(out)
    names = zf.namelist()
    assert any(n.endswith("chap1.xhtml") for n in names)
    assert any(n.endswith("chap2.xhtml") for n in names)
    # and the chapter title made it into the content
    chap1 = next(n for n in names if n.endswith("chap1.xhtml"))
    assert "First" in zf.read(chap1).decode("utf-8")


def std_cfg():
    return BookConfig(slug="comp", title="Gentle Goodbye", subtitle="Sub",
                      author="A", art_prompt="x", book_type="standard",
                      synopsis="Grieving a dog.", chapter_count=2,
                      words_per_chapter=40)


def std_content():
    return {"preface": "A short preface.",
            "chapters": [{"title": "First", "paragraphs": ["Para one.", "Para two."]},
                         {"title": "Second", "paragraphs": ["Para three."]}]}


def test_standard_interior_renders_chapters_no_fill_lines(tmp_path):
    html_path = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "Gentle Goodbye" in text
    assert "First" in text and "Para one." in text
    assert 'class="chapter"' in text
    assert 'class="lines"' not in text          # no journal fill-in ruled lines


def test_pdf_page_count(tmp_path):
    import fitz
    p = tmp_path / "doc.pdf"
    d = fitz.open()
    d.new_page(); d.new_page(); d.new_page()
    d.save(str(p)); d.close()
    assert pdf_page_count(p) == 3
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    assert pdf_page_count(stub) == 0            # non-PDF stub -> 0, no crash


def test_standard_build_rejects_zero_pages(tmp_path):
    # if the rendered PDF can't be opened (0 pages), a standard build must fail
    # loudly rather than feed a 0 page count into the cover spine math
    html_path = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    def runner(args):
        (tmp_path / "interior.pdf").write_bytes(b"not a pdf")   # fitz can't open -> 0 pages
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    with pytest.raises(InteriorError):
        build_interior_pdf(html_path, tmp_path, runner=runner, book_type="standard")


def test_standard_build_uses_pdf_page_count(tmp_path):
    # standard books must take the page count from the RENDERED PDF, not HTML sections
    html_path = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    import fitz
    def runner(args):
        p = tmp_path / "interior.pdf"
        d = fitz.open()
        for _ in range(5):
            d.new_page()
        d.save(str(p)); d.close()
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    _, pages = build_interior_pdf(html_path, tmp_path, runner=runner, book_type="standard")
    assert pages == 5   # 5 real PDF pages, not the HTML section count


def test_standard_interior_sets_nonzero_page_margin(tmp_path, sample_content):
    # Regression: standard prose flows across many pages, so the only thing that
    # keeps top/bottom insets on EVERY page is a real CSS `@page` margin (browse
    # renders without --prefer-css-page-size, so @page wins over the --margins
    # flag). A standard interior that left @page at 0 rendered edge-to-edge and
    # tripped the live margin guard. Journals deliberately keep @page margin 0
    # and inset via fixed .page padding.
    std_html = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    std_text = Path(std_html).read_text(encoding="utf-8")
    assert f"@page {{ margin: {specs.MARGIN_TOPBOTTOM_IN}in; }}" in std_text

    sample_content["prompts"] = sample_content["prompts"][:5]
    j_html = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    j_text = Path(j_html).read_text(encoding="utf-8")
    assert "@page" not in j_text          # journal page margin lives in interior.css (0)


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

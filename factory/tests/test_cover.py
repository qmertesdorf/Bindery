import pytest
from pathlib import Path
from factory.config import BookConfig
from factory.cover import render_cover_html, build_cover, _verify_cover_pdf, CoverError


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x")


def test_render_cover_html_has_dimensions_and_title(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    html = render_cover_html(cfg(), pages=120, art_path=art, out_dir=tmp_path)
    text = Path(html).read_text(encoding="utf-8")
    assert "Paw Prints" in text
    assert "12.55in" in text   # full wraparound width for 120pp
    assert "9.25in" in text


def test_build_cover_makes_pdf_and_jpg(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    calls = []
    def runner(args):
        calls.append(args)
        # create whatever output file browse was told to write
        target = args[2] if args[1] in ("pdf", "screenshot") else None
        if target:
            Path(target).write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, jpg = build_cover(cfg(), pages=120, art_path=art, out_dir=tmp_path, runner=runner)
    assert Path(pdf).exists() and Path(pdf).suffix == ".pdf"
    assert Path(jpg).exists() and Path(jpg).suffix == ".jpg"


def test_verify_cover_pdf_catches_dropped_text(tmp_path):
    import fitz
    p = tmp_path / "cover.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Paw Prints on My Heart")
    page.insert_text((72, 120), "Eleanor Hartley")
    doc.save(str(p))
    doc.close()
    # all present -> passes; wrapped/extra whitespace tolerated
    _verify_cover_pdf(p, ["Paw Prints on My   Heart", "Eleanor Hartley"])
    # a missing element (e.g. author dropped by the renderer) -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_pdf(p, ["Eleanor Hartley", "A Guided Grief Journal"])
    # a non-PDF stub (as produced by fake runners) is skipped, not an error
    stub = tmp_path / "stub.pdf"
    stub.write_bytes(b"x")
    _verify_cover_pdf(stub, ["anything"])

import pytest
from pathlib import Path
from factory.config import BookConfig
from factory import specs
from factory.cover import (render_cover_html, build_cover, _verify_cover_pdf,
                           _verify_cover_dimensions, _verify_cover_background,
                           _verify_cover_text_zones, _verify_cover_no_white_edge,
                           _verify_cover_art, CoverError)


def test_verify_cover_art_fails_on_missing(tmp_path):
    # a failed cover render leaves no art.png; the build must NOT silently fall back
    # to a stale cover_bg.png — fail loudly instead.
    with pytest.raises(CoverError):
        _verify_cover_art(tmp_path / "art.png")


def test_verify_cover_art_allows_test_stub(tmp_path):
    stub = tmp_path / "art.png"
    stub.write_bytes(b"\x89PNG stub")          # tiny non-image stub (test fake)
    _verify_cover_art(stub)                     # must not raise


def test_verify_cover_art_rejects_corrupt_real_file(tmp_path):
    bad = tmp_path / "art.png"
    bad.write_bytes(b"\x00" * 4096)            # >1KB but not a valid image
    with pytest.raises(CoverError):
        _verify_cover_art(bad)


def test_verify_cover_no_white_edge(tmp_path):
    import fitz
    def cover(white_strip):
        p = tmp_path / f"c_{white_strip}.pdf"
        d = fitz.open(); pg = d.new_page(width=400, height=600)
        pg.draw_rect(fitz.Rect(0, 0, 400, 600), fill=(0.12, 0.12, 0.12), color=(0.12, 0.12, 0.12))
        if white_strip:
            pg.draw_rect(fitz.Rect(397, 0, 400, 600), fill=(1, 1, 1), color=(1, 1, 1))
        d.save(str(p)); d.close()
        return p
    # a hair-thin white line at the right edge (full-bleed bg fell short) -> fail
    with pytest.raises(CoverError):
        _verify_cover_no_white_edge(cover(True))
    # a clean full-bleed (dark to every edge) -> passes
    _verify_cover_no_white_edge(cover(False))
    # a non-PDF stub is skipped, not an error
    stub = tmp_path / "stub.pdf"; stub.write_bytes(b"x")
    _verify_cover_no_white_edge(stub)


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


def test_build_cover_skips_ebook_when_disabled(tmp_path):
    # journals are paperback-only: build the wrap PDF but no ebook JPG
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            Path(args[2]).write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, jpg = build_cover(cfg(), pages=120, art_path=art, out_dir=tmp_path,
                           runner=runner, make_ebook_cover=False)
    assert Path(pdf).exists()
    assert jpg is None
    assert not (tmp_path / "cover-ebook.jpg").exists()


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


def test_verify_cover_back_balanced(tmp_path):
    import fitz
    from factory.cover import _verify_cover_back_balanced
    pages = 84
    W, H = specs.cover_dimensions_in(pages)
    br = specs.BLEED_IN + specs.TRIM_W_IN

    def make(dark_right):
        d = fitz.open(); pg = d.new_page(width=W * 72, height=H * 72)
        pg.draw_rect(fitz.Rect(0, 0, W * 72, H * 72), fill=(0.6, 0.6, 0.6))
        if dark_right:  # heavy dark mass on the back-right (foreground bleeding in)
            pg.draw_rect(fitz.Rect((br - 2.5) * 72, 0, br * 72, H * 72),
                         fill=(0.04, 0.04, 0.04))
        p = tmp_path / f"bal_{dark_right}.pdf"; d.save(str(p)); d.close()
        return p

    # balanced back -> passes
    _verify_cover_back_balanced(make(False), pages)
    # heavy dark mass on the back-right -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_back_balanced(make(True), pages)
    # non-PDF stub -> skipped
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    _verify_cover_back_balanced(stub, pages)


def test_audit_cover_composition(tmp_path):
    import fitz
    from factory.cover import _audit_cover_composition
    d = fitz.open(); pg = d.new_page(width=600, height=400)
    pg.draw_rect(fitz.Rect(0, 0, 600, 400), fill=(0.3, 0.5, 0.3))
    pg.insert_text((50, 200), "Cover")
    p = tmp_path / "c.pdf"; d.save(str(p)); d.close()

    class Aud:
        def __init__(self, ok): self.ok = ok; self.kinds = []
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            self.kinds.append(kind)
            return {"ok": self.ok, "issues": [] if self.ok else ["pale text, hard to read"]}

    # vision auditor flags a legibility problem -> hard failure
    with pytest.raises(CoverError):
        _audit_cover_composition(p, Aud(False))
    # auditor OK -> no raise, and it was asked with the cover prompt
    a = Aud(True); _audit_cover_composition(p, a); assert a.kinds == ["cover"]
    # no auditor injected -> skipped
    _audit_cover_composition(p, None)
    # non-PDF stub -> skipped
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    _audit_cover_composition(stub, Aud(False))


def test_flatten_cover_pdf_makes_single_image(tmp_path):
    import fitz
    from factory.cover import _flatten_cover_pdf
    d = fitz.open(); pg = d.new_page(width=600, height=400)
    pg.draw_rect(fitz.Rect(0, 0, 600, 400), fill=(0.2, 0.4, 0.2))
    pg.insert_text((100, 200), "Hello cover")
    p = tmp_path / "v.pdf"; d.save(str(p)); d.close()

    _flatten_cover_pdf(p, dpi=96)
    out = fitz.open(str(p))
    assert out.page_count == 1
    assert len(out[0].get_images()) == 1            # one embedded image
    assert out[0].get_text().strip() == ""          # text is now rasterised
    assert abs(out[0].rect.width - 600) < 1 and abs(out[0].rect.height - 400) < 1
    out.close()

    # non-PDF stub is skipped, not an error
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    _flatten_cover_pdf(stub)


def test_verify_cover_pdf_tolerates_linebreak_hyphenation(tmp_path):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    # simulate the renderer wrapping a hyphenated word across two lines
    page.insert_text((72, 72), "a soft read-")
    page.insert_text((72, 90), "aloud nature book")
    p = tmp_path / "hy.pdf"
    doc.save(str(p)); doc.close()
    # the verbatim blurb still matches despite the line-break hyphen
    _verify_cover_pdf(p, ["a soft read-aloud nature book"])


def _pdf_of_size(path, w_in, h_in):
    import fitz
    doc = fitz.open()
    doc.new_page(width=w_in * 72, height=h_in * 72)
    doc.save(str(path))
    doc.close()


def test_verify_cover_dimensions_matches_page_count(tmp_path):
    pages = 84
    exp_w, exp_h = specs.cover_dimensions_in(pages)
    good = tmp_path / "good.pdf"
    _pdf_of_size(good, exp_w, exp_h)
    _verify_cover_dimensions(good, pages)  # correct size -> passes

    # a cover sized for the wrong page count (spine off) -> hard failure
    wrong = tmp_path / "wrong.pdf"
    wrong_w, _ = specs.cover_dimensions_in(pages + 200)
    _pdf_of_size(wrong, wrong_w, exp_h)
    with pytest.raises(CoverError):
        _verify_cover_dimensions(wrong, pages)

    # non-PDF stub is skipped, not an error
    stub = tmp_path / "stub.pdf"
    stub.write_bytes(b"x")
    _verify_cover_dimensions(stub, pages)


def test_verify_cover_background(tmp_path):
    import fitz
    swatch = tmp_path / "s.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40))
    pix.set_rect(pix.irect, (120, 120, 120))
    pix.save(str(swatch))

    # one full-page (non-white) background -> passes
    good = tmp_path / "good.pdf"
    d = fitz.open(); p = d.new_page(width=600, height=400)
    p.insert_image(fitz.Rect(0, 0, 600, 400), filename=str(swatch))
    d.save(str(good)); d.close()
    _verify_cover_background(good)

    # two images (per-panel backgrounds) -> hard failure
    bad = tmp_path / "bad.pdf"
    d = fitz.open(); p = d.new_page(width=600, height=400)
    p.insert_image(fitz.Rect(0, 0, 300, 400), filename=str(swatch))
    p.insert_image(fitz.Rect(300, 0, 600, 400), filename=str(swatch))
    d.save(str(bad)); d.close()
    with pytest.raises(CoverError):
        _verify_cover_background(bad)

    # a blank/white page (background failed to render) -> hard failure
    blank = tmp_path / "blank.pdf"
    d = fitz.open(); d.new_page(width=600, height=400)
    d.save(str(blank)); d.close()
    with pytest.raises(CoverError):
        _verify_cover_background(blank)

    # non-PDF stub is skipped
    stub = tmp_path / "stub.pdf"; stub.write_bytes(b"x")
    _verify_cover_background(stub)


def test_verify_cover_back_text_centered(tmp_path):
    import fitz
    from factory.cover import _verify_cover_back_text_centered
    pages = 84
    W, H = specs.cover_dimensions_in(pages)
    back_cx = specs.BLEED_IN + specs.TRIM_W_IN / 2

    text = "A short back blurb."
    fs = 12
    tw_in = fitz.get_text_length(text, fontsize=fs) / 72  # rendered width in inches

    def pdf_back_text(cx_in, cy_in):
        p = tmp_path / f"c_{cx_in:.2f}_{cy_in:.2f}.pdf"
        d = fitz.open(); pg = d.new_page(width=W * 72, height=H * 72)
        # insert_text takes the LEFT/baseline; place the left so the bbox centre
        # lands at cx_in, baseline at cy_in (bbox centre ~ cy_in)
        pg.insert_text(((cx_in - tw_in / 2) * 72, cy_in * 72), text, fontsize=fs)
        d.save(str(p)); d.close()
        return p

    # blurb centred on the back panel -> passes
    _verify_cover_back_text_centered(pdf_back_text(back_cx, H / 2), pages)

    # blurb shoved high (the old asymmetric-padding defect) -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_back_text_centered(pdf_back_text(back_cx, H / 2 - 1.0), pages)

    # blurb off to one side -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_back_text_centered(pdf_back_text(back_cx - 1.5, H / 2), pages)

    # non-PDF stub is skipped, not an error
    stub = tmp_path / "stub.pdf"; stub.write_bytes(b"x")
    _verify_cover_back_text_centered(stub, pages)


def test_verify_cover_text_zones(tmp_path):
    import fitz
    pages = 84
    W, H = specs.cover_dimensions_in(pages)

    def pdf_with_text(x_in, y_in):
        p = tmp_path / f"t_{x_in}_{y_in}.pdf"
        d = fitz.open(); pg = d.new_page(width=W * 72, height=H * 72)
        pg.insert_text((x_in * 72, y_in * 72), "TITLE", fontsize=20)
        d.save(str(p)); d.close()
        return p

    # text centred on the front cover, well inside the trim -> passes
    front_cx = W - specs.BLEED_IN - specs.TRIM_W_IN / 2
    _verify_cover_text_zones(pdf_with_text(front_cx - 0.3, 1.0), pages)

    # text in the top-left bleed -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_text_zones(pdf_with_text(0.15, 0.2), pages)

    # text in the back cover's lower-right barcode keep-out -> hard failure
    with pytest.raises(CoverError):
        _verify_cover_text_zones(pdf_with_text(specs.BLEED_IN + specs.TRIM_W_IN - 1.0,
                                               H - specs.BLEED_IN - 0.3), pages)

    # non-PDF stub is skipped
    stub = tmp_path / "stub.pdf"; stub.write_bytes(b"x")
    _verify_cover_text_zones(stub, pages)


def std_cfg_5x8():
    return BookConfig(slug="comp", title="Gentle Goodbye", subtitle="Sub",
                      author="A", art_prompt="x", book_type="standard",
                      synopsis="s", chapter_count=8, trim_w=5.5, trim_h=8.5,
                      blurb="A gentle companion read.")


def test_cover_html_uses_configured_trim(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    # 150pp at 5.5x8.5 -> width 11.625, height 8.75
    html = render_cover_html(std_cfg_5x8(), pages=150, art_path=art, out_dir=tmp_path)
    text = Path(html).read_text(encoding="utf-8")
    assert "11.625in" in text
    assert "8.75in" in text


def test_verify_cover_dimensions_custom_trim(tmp_path):
    pages = 150
    exp_w, exp_h = specs.cover_dimensions_in(pages, 5.5, 8.5)
    good = tmp_path / "good.pdf"
    _pdf_of_size(good, exp_w, exp_h)
    _verify_cover_dimensions(good, pages, trim_w=5.5, trim_h=8.5)  # passes
    # a 6x9-sized cover is WRONG for a 5.5x8.5 book -> failure
    wrong = tmp_path / "wrong.pdf"
    w6, h6 = specs.cover_dimensions_in(pages)  # 6x9
    _pdf_of_size(wrong, w6, h6)
    with pytest.raises(CoverError):
        _verify_cover_dimensions(wrong, pages, trim_w=5.5, trim_h=8.5)


def test_picture_cover_dimensions_use_white_spine(tmp_path):
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A",
                     art_prompt="x", book_type="picture", pet_kind="dog",
                     pet_name="Sunny", page_count=26, trim_w=8.5, trim_h=8.5,
                     price_usd=10.99)
    (tmp_path / "art.png").write_bytes(b"\x89PNG")
    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            Path(args[2]).write_bytes(b"x")  # stub; guards skip non-PDF
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, jpg = build_cover(cfg, 26, tmp_path / "art.png", tmp_path,
                           runner=runner, make_ebook_cover=False)
    assert pdf.exists() and jpg is None

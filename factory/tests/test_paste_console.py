import json
from factory.config import load_config
from factory.paste_console import make_paste_console, build_steps


def _concept_cfg(tmp_path):
    p = tmp_path / "c.config.json"
    p.write_text(json.dumps({
        "slug": "wlw", "title": "Wild Little World", "subtitle": "A First Look",
        "author": "Eleanor Hartley", "art_prompt": "meadow, no text",
        "book_type": "concept", "art_engine": "flux", "subject": "animals and nature",
        "flux_style": "soft watercolour, no text", "page_count": 24,
        "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
        "blurb": "Step into a wild little world."}), encoding="utf-8")
    return load_config(p)


def test_build_steps_concept_fields(tmp_path):
    steps = build_steps(_concept_cfg(tmp_path), 24)
    fields = [s["field"] for s in steps]
    assert "Book Title" in fields
    assert sum(1 for s in steps if s["field"].startswith("Keyword")) == 7
    # author split into first/last
    first = next(s["value"] for s in steps if "First name" in s["field"])
    last = next(s["value"] for s in steps if "Last name" in s["field"])
    assert (first, last) == ("Eleanor", "Hartley")
    # concept = colour/white stock, NOT cream
    ink = next(s["value"] for s in steps if "Ink & paper" in s["field"])
    assert "Color" in ink and "White" in ink and "Cream" not in ink
    # description is the blurb as HTML
    desc = next(s["value"] for s in steps if s["field"] == "Description")
    assert desc == "<p>Step into a wild little world.</p>"


def test_illustrator_contributor_steps(tmp_path):
    p = tmp_path / "c.config.json"
    p.write_text(json.dumps({
        "slug": "wlw", "title": "Wild Little World", "subtitle": "A First Look",
        "author": "Hannah Whitfield", "illustrator": "Grace Sullivan",
        "art_prompt": "meadow, no text", "book_type": "concept", "art_engine": "flux",
        "subject": "animals and nature", "flux_style": "soft watercolour, no text",
        "page_count": 24, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99}),
        encoding="utf-8")
    steps = build_steps(load_config(p), 24)
    by = {s["field"]: s["value"] for s in steps}
    assert by["Author — First name"] == "Hannah" and by["Author — Last name"] == "Whitfield"
    assert by["Illustrator — First name"] == "Grace"
    assert by["Illustrator — Last name"] == "Sullivan"
    assert any("role: Illustrator" in s["field"] for s in steps)


def test_no_illustrator_steps_when_unset(tmp_path):
    steps = build_steps(_concept_cfg(tmp_path), 24)  # _concept_cfg has no illustrator
    assert not any("Illustrator" in s["field"] for s in steps)


def test_make_paste_console_writes_self_contained_html(tmp_path):
    out = make_paste_console(_concept_cfg(tmp_path), 24, tmp_path)
    html = out.read_text(encoding="utf-8")
    assert out.name == "paste-console.html"
    assert "Copy &amp; Next" in html and "navigator.clipboard" in html
    assert "execCommand('copy')" in html        # file:// fallback
    assert "localStorage" in html               # progress persistence
    assert "Wild Little World" in html
    # the steps are embedded as valid JSON the page can render
    start = html.index("const STEPS = ") + len("const STEPS = ")
    arr = json.loads(html[start:html.index(";\n", start)])
    assert any(s["field"] == "Book Title" for s in arr)
    assert "{{" not in html and "__STEPS__" not in html  # fully substituted

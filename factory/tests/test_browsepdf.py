from pathlib import Path
from factory.browsepdf import html_to_pdf, html_to_screenshot, BrowseError
import pytest


def make_runner(record):
    def run(args):
        record.append(args)
        class R: returncode = 0; stdout = "ok"; stderr = ""
        return R()
    return run


def test_html_to_pdf_invokes_goto_then_pdf(tmp_path):
    html = tmp_path / "in.html"; html.write_text("<h1>hi</h1>", encoding="utf-8")
    out = tmp_path / "out.pdf"
    calls = []
    html_to_pdf(html, out, width_in=6, height_in=9, runner=make_runner(calls))
    assert any(a[1] == "goto" and a[2].startswith("file://") for a in calls)
    pdf_call = [a for a in calls if a[1] == "pdf"][0]
    assert "--width" in pdf_call and "6in" in pdf_call
    assert "9in" in pdf_call


def test_runner_failure_raises(tmp_path):
    html = tmp_path / "in.html"; html.write_text("x", encoding="utf-8")
    def bad(args):
        class R: returncode = 1; stdout = ""; stderr = "boom"
        return R()
    with pytest.raises(BrowseError):
        html_to_pdf(html, tmp_path / "o.pdf", width_in=6, height_in=9, runner=bad)


def test_screenshot_invokes_viewport_and_screenshot(tmp_path):
    html = tmp_path / "c.html"; html.write_text("x", encoding="utf-8")
    calls = []
    html_to_screenshot(html, tmp_path / "o.jpg", width_px=1600, height_px=2560,
                       runner=make_runner(calls))
    assert any(a[1] == "viewport" for a in calls)
    assert any(a[1] == "screenshot" for a in calls)

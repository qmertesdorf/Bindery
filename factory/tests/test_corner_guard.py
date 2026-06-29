"""Corner guard: geometry + aggregation are exercised with a real (tiny) PIL image
and an injected probe, so no GPU or CLI is needed."""
from pathlib import Path

import pytest
from PIL import Image

from factory.qa.corner_guard import _corner_boxes, build_corner_prompt, CornerGuard
from factory.qa import EnsembleAuditor


def test_corner_boxes_cover_all_four_corners():
    boxes = dict(_corner_boxes(100, 200, 0.25))  # fw=25, fh=50
    assert boxes["top-left"] == (0, 0, 25, 50)
    assert boxes["top-right"] == (75, 0, 100, 50)
    assert boxes["bottom-left"] == (0, 150, 25, 200)
    assert boxes["bottom-right"] == (75, 150, 100, 200)


def test_corner_prompt_targets_text_and_blank_paper():
    p = build_corner_prompt("bottom-right", Path("/o/c.png"))
    low = p.lower()
    assert "bottom-right" in low and "c.png" in p
    assert "signature" in low or "watermark" in low
    assert "paper" in low and ("margin" in low or "blank" in low)
    assert "ok" in low  # asks for the JSON verdict


def _img(tmp_path, size=(64, 64)):
    p = tmp_path / "page.png"
    Image.new("RGB", size, (10, 20, 30)).save(p)
    return p


def test_guard_localises_a_flagged_corner(tmp_path):
    seen = []
    def probe(label, crop_path):
        seen.append(label)
        if label == "bottom-right":
            return {"ok": False, "issues": ["faint initials"]}
        return {"ok": True, "issues": []}
    issues = CornerGuard(probe_fn=probe).check(_img(tmp_path))
    assert len(seen) == 4  # all four corners probed
    assert issues == ["bottom-right corner: faint initials"]


def test_guard_clean_image_returns_no_issues(tmp_path):
    issues = CornerGuard(probe_fn=lambda label, p: {"ok": True, "issues": []}).check(
        _img(tmp_path))
    assert issues == []


def test_guard_crops_are_real_files_passed_to_probe(tmp_path):
    # the probe receives an actual cropped image file it could read
    sizes = []
    def probe(label, crop_path):
        with Image.open(crop_path) as c:
            sizes.append(c.size)
        return {"ok": True, "issues": []}
    CornerGuard(probe_fn=probe, frac=0.25).check(_img(tmp_path, size=(100, 100)))
    assert sizes == [(25, 25)] * 4


class _OkHolistic:
    def audit(self, image_path, **kw):
        return {"ok": True, "issues": []}


def test_ensemble_corner_guard_rejects(tmp_path):
    img = _img(tmp_path)
    guard = CornerGuard(probe_fn=lambda label, p: (
        {"ok": False, "issues": ["text"]} if label == "top-left"
        else {"ok": True, "issues": []}))
    ens = EnsembleAuditor(_OkHolistic(), corner_guard=guard)
    v = ens.audit(img, anchor="a fox", scene="a fox", kind="concept")
    assert v["ok"] is False
    assert any("top-left corner" in i for i in v["issues"])


def test_ensemble_corner_guard_skips_cover(tmp_path):
    # the cover legitimately carries title/blurb text, so the corner text-probe
    # must not run on it
    img = _img(tmp_path)
    guard = CornerGuard(probe_fn=lambda label, p: {"ok": False, "issues": ["text"]})
    ens = EnsembleAuditor(_OkHolistic(), corner_guard=guard)
    v = ens.audit(img, anchor="", scene=None, kind="cover", caption="blurb")
    assert v["ok"] is True

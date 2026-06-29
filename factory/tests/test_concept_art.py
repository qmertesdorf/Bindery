import json as _json
from pathlib import Path
import pytest
from factory.config import BookConfig
from factory.flux_art import (generate_concept_art, concept_page_prompt,
                              has_white_border)


def _cfg(**over):
    base = dict(slug="tiny", title="Tiny Creatures", subtitle="sub",
                author="Eleanor Hartley",
                art_prompt="a sunlit meadow, soft watercolour, no text",
                book_type="concept", art_engine="flux", subject="small animals",
                flux_style="soft storybook watercolour, no text", flux_guidance=2.4,
                page_count=2)
    base.update(over)
    return BookConfig(**base)


_CONTENT = {"art_style": "soft watercolour", "character_anchor": "",
            "dedication": "d",
            "pages": [{"subject": "a fox", "text": "A fox is red.",
                       "scene": "a fox in tall grass"},
                      {"subject": "a snail", "text": "A snail is slow.",
                       "scene": "a snail on a leaf"}],
            "closing": "bye"}


class _Comfy:
    """Records every submitted workflow and writes a stub PNG so the file exists."""
    def __init__(self):
        self.workflows = []
    def submit(self, workflow, *, out_path):
        self.workflows.append(workflow)
        Path(out_path).write_bytes(b"\x89PNG stub")


class _OKAuditor:
    def __init__(self):
        self.kinds = []
        self.refs = []
        self.captions = []
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character", caption=None):
        self.kinds.append(kind)
        self.refs.append(reference_path)
        self.captions.append(caption)
        return {"ok": True, "issues": []}


def test_concept_page_prompt_excludes_people_and_text():
    p = concept_page_prompt({"subject": "a fox", "scene": "a fox in grass"},
                            style="soft watercolour")
    assert "soft watercolour" in p
    assert "a fox in grass" in p
    assert "no people" in p.lower()
    assert "no text" in p.lower()
    # steer away from photoreal toward storybook illustration
    assert "not photorealistic" in p.lower() or "not a photograph" in p.lower()
    assert "storybook" in p.lower()


def test_concept_page_prompt_forces_full_bleed():
    # Flux vignettes some subjects onto white paper; the generation prompt must steer
    # hard for full-bleed, not just the post-hoc auditor ([[catch-defects-with-guards]]).
    low = concept_page_prompt({"subject": "a fox", "scene": "a fox"}, style="x").lower()
    assert "full-bleed" in low or "full bleed" in low
    assert "edge to edge" in low
    assert "no white" in low or "no blank margin" in low or "no framed vignette" in low


def test_concept_page_prompt_suppresses_signatures():
    # Flux scrawls fake artist signatures/watermarks on painterly styles — the prompt
    # must steer them away (a real defect on a pen-name title).
    low = concept_page_prompt({"subject": "a fox", "scene": "a fox"}, style="x").lower()
    assert "no signature" in low and "no watermark" in low


def test_concept_page_prompt_injects_stated_counts():
    # A stated body-part count must be steered AT GENERATION TIME (positive directive),
    # not left for the post-hoc count guard to reject and burn a reroll on
    # ([[catch-defects-with-guards]]). Uses the SAME extractor as the count guard so the
    # prompt and the guard can never disagree about what the claim is.
    p = concept_page_prompt(
        {"subject": "an octopus",
         "scene": "an octopus with eight curly arms among the rocks",
         "text": "An octopus is clever and free,\nwith eight soft arms beneath the sea."},
        style="soft watercolour")
    assert "exactly 8 arms" in p.lower()


def test_concept_page_prompt_no_count_when_none_stated():
    # No numeric claim in scene/caption ⇒ no count directive appended (don't invent one).
    p = concept_page_prompt({"subject": "a fox", "scene": "a fox in tall grass"},
                            style="x")
    assert "exactly" not in p.lower()


def test_generate_concept_art_reuses_existing_pages_and_cover(tmp_path):
    # an already-rendered page / cover is kept; only missing art re-renders, so a
    # targeted re-roll (delete one page) doesn't redo the whole book or the cover.
    (tmp_path / "page_01.png").write_bytes(b"\x89PNG kept")
    (tmp_path / "art.png").write_bytes(b"\x89PNG kept")
    comfy, auditor = _Comfy(), _OKAuditor()
    art = generate_concept_art(_cfg(), _CONTENT, tmp_path, comfy,
                               seed=99, auditor=auditor)
    assert [p.name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert art["cover"].name == "art.png"
    # only the MISSING page 2 rendered + audited; page 1 and cover were reused
    assert len(comfy.workflows) == 1
    assert auditor.kinds == ["concept"]
    # the reused page 1 still anchors the style for the re-rendered page 2
    assert auditor.refs[0] is not None and auditor.refs[0].name == "page_01.png"
    # reused art left byte-for-byte untouched
    assert (tmp_path / "page_01.png").read_bytes() == b"\x89PNG kept"
    assert (tmp_path / "art.png").read_bytes() == b"\x89PNG kept"


def test_generate_concept_art_uses_empty_lora_stack_and_concept_audit(tmp_path):
    comfy, auditor = _Comfy(), _OKAuditor()
    art = generate_concept_art(_cfg(), _CONTENT, tmp_path, comfy,
                               seed=99, auditor=auditor)
    assert [p.name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert art["cover"].name == "art.png"
    assert art["flagged"] == []
    # every page audited under the concept (character-free) bar
    assert set(auditor.kinds) == {"concept"}
    # style cohesion: page 1 is the anchor (no reference); later pages + cover are
    # audited AGAINST page_01.png so the whole book matches one style
    assert auditor.refs[0] is None
    later = [r for r in auditor.refs[1:] if r is not None]
    assert later and all(r.name == "page_01.png" for r in later)
    # empty LoRA stack => no LoraLoaderModelOnly nodes in any submitted graph
    for wf in comfy.workflows:
        assert not any(n.get("class_type") == "LoraLoaderModelOnly"
                       for n in wf.values())


def test_generate_concept_art_passes_page_caption_to_auditor(tmp_path):
    # each page's read-aloud caption (content["pages"][i]["text"]) is threaded to the
    # auditor so it can enforce caption fidelity (e.g. stated counts / actions)
    comfy, auditor = _Comfy(), _OKAuditor()
    generate_concept_art(_cfg(), _CONTENT, tmp_path, comfy, seed=99, auditor=auditor)
    # the two page audits carry their captions; the cover audit (last) carries none
    assert auditor.captions[0] == "A fox is red."
    assert auditor.captions[1] == "A snail is slow."
    assert auditor.captions[-1] is None  # cover has no caption


def _img(tmp_path, name, fill, *, size=200, border=0, border_fill=(255, 255, 255)):
    """Write a `size`x`size` test PNG: solid `fill`, optionally framed by a
    `border`-px band of `border_fill` (a stand-in for the white watercolour-paper
    vignette). `size` defaults small for the detector unit tests; the full build
    test uses a print-size image so the resolution guard is satisfied."""
    from PIL import Image
    im = Image.new("RGB", (size, size), border_fill)
    b = border
    Image.Image.paste(im, Image.new("RGB", (size - 2 * b, size - 2 * b), fill), (b, b))
    p = tmp_path / name
    im.save(p)
    return p


def test_has_white_border_detects_paper_vignette(tmp_path):
    # a scene framed by a white paper border is flagged; a full-bleed page is not
    bordered = _img(tmp_path, "bordered.png", (60, 120, 180), border=16)
    full = _img(tmp_path, "full.png", (60, 120, 180), border=0)
    assert has_white_border(bordered) is True
    assert has_white_border(full) is False


def test_has_white_border_ignores_bright_painted_sky(tmp_path):
    # a legitimately light/tinted edge (pale sky, snow) is NOT pure flat paper white,
    # so it must NOT be mistaken for a border (no false build flags on good pages)
    sky = _img(tmp_path, "sky.png", (60, 120, 180), border=16,
               border_fill=(228, 236, 245))  # tinted, below the pure-paper bar
    assert has_white_border(sky) is False


def test_has_white_border_skips_non_image_stub(tmp_path):
    stub = tmp_path / "stub.png"
    stub.write_bytes(b"\x89PNG stub")
    assert has_white_border(stub) is False


def test_has_white_border_handles_varied_corner_bytes(tmp_path):
    # Regression: real renders have noisy/gradient corners (not flat fills). The
    # population stdev over those bytes must compute without raising —
    # statistics.pstdev(bytes) hit a data-dependent Python 3.11 _ss TypeError on
    # some such corners and crashed the border check mid-build.
    from PIL import Image
    im = Image.new("RGB", (200, 200))
    px = im.load()
    for y in range(200):
        for x in range(200):
            px[x, y] = ((x * 7 + y * 3) % 200, (x * 3 + y * 11) % 200, (x + y) % 200)
    p = tmp_path / "varied.png"
    im.save(p)
    # must not raise; a dark, varied corner is not a flat white paper border
    assert has_white_border(p) is False


def test_generate_concept_art_flags_reused_page_with_white_border(tmp_path):
    # a REUSED page that ships a white paper border is no longer blindly trusted —
    # the deterministic full-bleed guard flags it for review
    # print-size so the resolution guard passes; border scaled to clear the corners
    _img(tmp_path, "page_01.png", (60, 120, 180), size=2800, border=200)
    (tmp_path / "art.png").write_bytes(b"\x89PNG stub")        # cover reused (stub)
    comfy, auditor = _Comfy(), _OKAuditor()
    art = generate_concept_art(_cfg(page_count=1), {
        "art_style": "x", "character_anchor": "", "dedication": "d",
        "pages": [{"subject": "a fox", "text": "t", "scene": "a fox"}],
        "closing": "c"}, tmp_path, comfy, seed=1, auditor=auditor)
    assert 1 in art["flagged"]


class _FailAuditor:
    """Auditor that fails every page — to prove reused pages get re-audited."""
    def __init__(self):
        self.calls = []
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character", caption=None):
        self.calls.append(Path(image_path).name)
        return {"ok": False, "issues": ["wrong body plan"]}


def _reuse_content():
    return {"art_style": "x", "character_anchor": "", "dedication": "d",
            "pages": [{"subject": "a fox", "text": "t", "scene": "a fox"}],
            "closing": "c"}


def test_reaudit_reused_flags_failing_page_when_enabled(tmp_path):
    # qa_reaudit_reused: a REUSED page is vision-re-audited and a failure is flagged
    # for review — closes the gap where kept pages rode through unchecked. It is NOT
    # re-rendered (reuse is preserved); deleting the PNG is how you force a re-roll.
    _img(tmp_path, "page_01.png", (60, 120, 180), size=2800, border=0)
    (tmp_path / "art.png").write_bytes(b"\x89PNG stub")        # cover reused (stub)
    comfy, auditor = _Comfy(), _FailAuditor()
    art = generate_concept_art(_cfg(page_count=1, qa_reaudit_reused=True),
                               _reuse_content(), tmp_path, comfy, seed=1,
                               auditor=auditor)
    assert "page_01.png" in auditor.calls   # the reused page WAS re-audited
    assert 1 in art["flagged"]              # and flagged on failure
    assert comfy.workflows == []            # but NOT re-rendered — still reuse


def test_reaudit_reused_skipped_by_default(tmp_path):
    # Default (flag off): reused pages are NOT re-audited — the fast reuse path is
    # unchanged, so existing builds keep their behaviour.
    _img(tmp_path, "page_01.png", (60, 120, 180), size=2800, border=0)
    (tmp_path / "art.png").write_bytes(b"\x89PNG stub")
    comfy, auditor = _Comfy(), _FailAuditor()
    art = generate_concept_art(_cfg(page_count=1), _reuse_content(), tmp_path,
                               comfy, seed=1, auditor=auditor)
    assert auditor.calls == []              # no re-audit of reused pages
    assert 1 not in art["flagged"]


def test_generate_concept_art_keeps_best_and_flags(tmp_path):
    comfy = _Comfy()

    class _NeverPasses:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": False, "issues": ["stub never passes"]}

    art = generate_concept_art(_cfg(page_count=1), {
        "art_style": "x", "character_anchor": "", "dedication": "d",
        "pages": [{"subject": "a fox", "text": "t", "scene": "a fox"}],
        "closing": "c"}, tmp_path, comfy, seed=1, auditor=_NeverPasses(),
        max_tries=2)
    assert 1 in art["flagged"]
    assert art["pages"][0].name == "page_01.png"
    assert art["pages"][0].exists()


def test_subject_fallback_swaps_stubborn_page(tmp_path):
    # A page whose subject the auditor keeps rejecting is swapped to a new subject,
    # its content regenerated, and re-rolled — rescuing the page (no flag).
    comfy = _Comfy()

    class _ManateeFails:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            ok = "manatee" not in anchor.lower()
            return {"ok": ok, "issues": [] if ok else ["forked/notched tail"]}

    def fake_generate(prompt):
        return _json.dumps({"subject": "a sea turtle",
                            "text": "A turtle swims by,\nunder the sky.",
                            "scene": "a green sea turtle in clear blue water"})

    seen = {}

    def fake_suggest(*, theme, used, failed):
        seen["theme"] = theme
        seen["used"] = used
        seen["failed"] = failed
        return "a sea turtle"

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t",
                          "scene": "a manatee with a paddle tail"}],
               "closing": "c"}
    art = generate_concept_art(
        _cfg(page_count=1, subject_fallback=True, max_fallbacks=2,
             max_reading_grade=0),
        content, tmp_path, comfy, seed=1, auditor=_ManateeFails(), max_tries=2,
        generate_fn=fake_generate, suggest_fn=fake_suggest)

    assert art["flagged"] == []                                   # swap rescued it
    assert content["pages"][0]["subject"] == "a sea turtle"       # mutated in place
    assert content["pages"][0]["scene"] == "a green sea turtle in clear blue water"
    assert content["pages"][0]["text"] == "A turtle swims by,\nunder the sky."
    assert seen["failed"] == "a manatee"
    assert "a manatee" in seen["used"]                            # old subject blocked


def test_subject_fallback_off_keeps_best_and_flags(tmp_path):
    # Default (flag off): a stubborn page is kept-best + flagged, content untouched,
    # and NO suggest/regenerate LLM calls happen.
    comfy = _Comfy()

    class _AllFail:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": False, "issues": ["bad"]}

    def boom(*a, **k):
        raise AssertionError("must not call the LLM when subject_fallback is off")

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t",
                          "scene": "a manatee"}], "closing": "c"}
    art = generate_concept_art(_cfg(page_count=1), content, tmp_path, comfy,
                               seed=1, auditor=_AllFail(), max_tries=2,
                               generate_fn=boom, suggest_fn=boom)
    assert 1 in art["flagged"]
    assert content["pages"][0]["subject"] == "a manatee"          # unchanged


def test_subject_fallback_respects_cap(tmp_path):
    # The auditor rejects every subject; the loop swaps exactly max_fallbacks times
    # then keeps-best + flags (does not loop forever).
    comfy = _Comfy()

    class _AllFail:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": False, "issues": ["bad"]}

    n = {"suggest": 0}

    def fake_suggest(*, theme, used, failed):
        n["suggest"] += 1
        return f"creature {n['suggest']}"

    def fake_generate(prompt):
        return _json.dumps({"subject": "creature X", "text": "a\nb",
                            "scene": "a creature in water"})

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t",
                          "scene": "a manatee"}], "closing": "c"}
    art = generate_concept_art(
        _cfg(page_count=1, subject_fallback=True, max_fallbacks=3,
             max_reading_grade=0),
        content, tmp_path, comfy, seed=1, auditor=_AllFail(), max_tries=1,
        generate_fn=fake_generate, suggest_fn=fake_suggest)
    assert n["suggest"] == 3            # exactly max_fallbacks swaps attempted
    assert 1 in art["flagged"]          # then gave up and flagged


def test_subject_fallback_content_regen_failure_flags_not_crashes(tmp_path):
    # If the swapped subject's content can't be regenerated (LLM returns junk →
    # ContentError), the build must keep-best + FLAG, not crash — preserving the
    # flag-don't-fail contract for the whole book.
    comfy = _Comfy()

    class _AllFail:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": False, "issues": ["bad"]}

    def fake_suggest(*, theme, used, failed):
        return "a sea turtle"

    def junk_generate(prompt):
        return "not json at all"        # regenerate_concept_page raises ContentError

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t",
                          "scene": "a manatee"}], "closing": "c"}
    art = generate_concept_art(
        _cfg(page_count=1, subject_fallback=True, max_fallbacks=2,
             max_reading_grade=0),
        content, tmp_path, comfy, seed=1, auditor=_AllFail(), max_tries=1,
        generate_fn=junk_generate, suggest_fn=fake_suggest)
    assert 1 in art["flagged"]                          # flagged, build survived
    assert content["pages"][0]["subject"] == "a manatee"  # no usable swap applied


def test_subject_fallback_flags_overhard_swapped_caption(tmp_path):
    # A swapped page bypasses build.py's pre-art readability gate. If the regenerated
    # couplet still reads above the ceiling, the page must be FLAGGED — the picture is
    # rescued but the over-grade caption is surfaced for review (no silent defect).
    comfy = _Comfy()

    class _ManateeFails:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            ok = "manatee" not in anchor.lower()
            return {"ok": ok, "issues": [] if ok else ["forked tail"]}

    def fake_generate(prompt):
        # parseable, but far too hard for an early reader (every retry returns hard)
        return _json.dumps({
            "subject": "a sea turtle",
            "text": "The magnificent leatherback navigates extraordinary "
                    "transoceanic currents relentlessly.",
            "scene": "a green sea turtle in clear blue water"})

    def fake_suggest(*, theme, used, failed):
        return "a sea turtle"

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t",
                          "scene": "a manatee"}], "closing": "c"}
    art = generate_concept_art(
        _cfg(page_count=1, subject_fallback=True, max_fallbacks=2,
             max_reading_grade=3.0),
        content, tmp_path, comfy, seed=1, auditor=_ManateeFails(), max_tries=1,
        generate_fn=fake_generate, suggest_fn=fake_suggest)
    assert content["pages"][0]["subject"] == "a sea turtle"   # swap rendered (audit ok)
    assert 1 in art["flagged"]                                # but caption-flagged


def test_subject_fallback_dedup_spans_all_pages(tmp_path):
    # The replacement chooser must see EVERY page's subject in `used`, so a swap on
    # one page can't collide with another spread's subject (shared used_subjects).
    comfy = _Comfy()

    class _ManateeFails:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            ok = "manatee" not in anchor.lower()
            return {"ok": ok, "issues": [] if ok else ["forked tail"]}

    seen = {}

    def fake_suggest(*, theme, used, failed):
        seen["used"] = list(used)
        return "a sea turtle"

    def fake_generate(prompt):
        return _json.dumps({"subject": "a sea turtle", "text": "a\nb",
                            "scene": "a green sea turtle in clear blue water"})

    content = {"art_style": "x", "character_anchor": "", "dedication": "d",
               "pages": [{"subject": "a manatee", "text": "t", "scene": "a manatee"},
                         {"subject": "a dolphin", "text": "t2",
                          "scene": "a dolphin leaping"}],
               "closing": "c"}
    generate_concept_art(
        _cfg(page_count=2, subject_fallback=True, max_fallbacks=2,
             max_reading_grade=0),
        content, tmp_path, comfy, seed=1, auditor=_ManateeFails(), max_tries=1,
        generate_fn=fake_generate, suggest_fn=fake_suggest)
    # both the failing page's own subject AND the other spread's subject are blocked
    assert "a manatee" in seen["used"]
    assert "a dolphin" in seen["used"]

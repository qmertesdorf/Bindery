from pathlib import Path
import pytest
from factory.config import BookConfig
from factory.flux_art import generate_concept_art, concept_page_prompt


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


def test_concept_page_prompt_suppresses_signatures():
    # Flux scrawls fake artist signatures/watermarks on painterly styles — the prompt
    # must steer them away (a real defect on a pen-name title).
    low = concept_page_prompt({"subject": "a fox", "scene": "a fox"}, style="x").lower()
    assert "no signature" in low and "no watermark" in low


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

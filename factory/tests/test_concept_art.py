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
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character"):
        self.kinds.append(kind)
        return {"ok": True, "issues": []}


def test_concept_page_prompt_excludes_people_and_text():
    p = concept_page_prompt({"subject": "a fox", "scene": "a fox in grass"},
                            style="soft watercolour")
    assert "soft watercolour" in p
    assert "a fox in grass" in p
    assert "no people" in p.lower()
    assert "no text" in p.lower()


def test_generate_concept_art_uses_empty_lora_stack_and_concept_audit(tmp_path):
    comfy, auditor = _Comfy(), _OKAuditor()
    art = generate_concept_art(_cfg(), _CONTENT, tmp_path, comfy,
                               seed=99, auditor=auditor)
    assert [p.name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert art["cover"].name == "art.png"
    assert art["flagged"] == []
    # every page audited under the concept (character-free) bar
    assert set(auditor.kinds) == {"concept"}
    # empty LoRA stack => no LoraLoaderModelOnly nodes in any submitted graph
    for wf in comfy.workflows:
        assert not any(n.get("class_type") == "LoraLoaderModelOnly"
                       for n in wf.values())


def test_generate_concept_art_keeps_best_and_flags(tmp_path):
    comfy = _Comfy()

    class _NeverPasses:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character"):
            return {"ok": False, "issues": ["stub never passes"]}

    art = generate_concept_art(_cfg(page_count=1), {
        "art_style": "x", "character_anchor": "", "dedication": "d",
        "pages": [{"subject": "a fox", "text": "t", "scene": "a fox"}],
        "closing": "c"}, tmp_path, comfy, seed=1, auditor=_NeverPasses(),
        max_tries=2)
    assert 1 in art["flagged"]
    assert art["pages"][0].name == "page_01.png"
    assert art["pages"][0].exists()

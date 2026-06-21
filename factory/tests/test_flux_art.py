from factory.flux_art import flux_lora_workflow
from factory.config import Character
from factory.flux_art import page_plan
from pathlib import Path
import pytest
from factory.config import BookConfig
from factory.art import ComfyClient, ArtError
from factory.flux_art import generate_flux_art

HERO = Character(role="hero", lora="boy.safetensors", trigger="b1scuitboy boy",
                 strength=0.9)
DOG = Character(role="companion", lora="dog.safetensors", trigger="b1scuitdog dog",
                strength=0.85, appears_on="memory")


def test_page_plan_child_and_pet_uses_both_loras_and_triggers():
    page = {"scene": "a sunny field", "cast": "child_and_pet", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9), ("dog.safetensors", 0.85)]
    assert "b1scuitboy boy" in prompt and "b1scuitdog dog" in prompt
    assert "a red sweater" in prompt
    assert "warm gentle smile" in prompt          # happy mood -> smiling

def test_page_plan_child_uses_hero_only_and_excludes_animals():
    page = {"scene": "an empty hallway", "cast": "child", "mood": "sad"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("boy.safetensors", 0.9)]
    assert "b1scuitdog dog" not in prompt
    assert "no animals" in prompt
    assert "not smiling" in prompt                # sad mood (in GRIEF) -> no smile

def test_page_plan_no_companion_treats_child_and_pet_as_hero_only():
    page = {"scene": "a field", "cast": "child_and_pet", "mood": "happy"}
    prompt, loras = page_plan(page, hero=HERO, companion=None,
                              style="w", outfit="o")
    assert loras == [("boy.safetensors", 0.9)]

def test_page_plan_pet_renders_companion_alone():
    page = {"scene": "a luminous meadow", "cast": "pet", "mood": "peaceful"}
    prompt, loras = page_plan(page, hero=HERO, companion=DOG,
                              style="watercolour", outfit="a red sweater")
    assert loras == [("dog.safetensors", 0.85)]      # companion only
    assert "b1scuitdog dog" in prompt
    assert "b1scuitboy boy" not in prompt            # no child
    assert "a red sweater" not in prompt             # no outfit (no child)
    assert "No people" in prompt


def test_flux_workflow_puts_seed_on_noise_not_sampler():
    wf = flux_lora_workflow("a boy", 777, loras=[("boy.safetensors", 0.9)],
                            guidance=2.4)
    # Flux seeds the RandomNoise node, NOT a KSampler
    assert wf["noise"]["class_type"] == "RandomNoise"
    assert wf["noise"]["inputs"]["noise_seed"] == 777
    assert "KSampler" not in [n["class_type"] for n in wf.values()]
    assert wf["pos"]["inputs"]["text"] == "a boy"
    assert wf["fg"]["inputs"]["guidance"] == 2.4

def test_flux_workflow_single_lora_chain():
    wf = flux_lora_workflow("x", 1, loras=[("boy.safetensors", 0.9)], guidance=2.4)
    loras = {k: v for k, v in wf.items() if v["class_type"] == "LoraLoaderModelOnly"}
    assert len(loras) == 1
    assert wf["lora0"]["inputs"]["model"] == ["u", 0]       # first lora on the UNET
    assert wf["lora0"]["inputs"]["lora_name"] == "boy.safetensors"
    assert wf["lora0"]["inputs"]["strength_model"] == 0.9
    # the sampler chain reads from the LAST lora in the stack
    assert wf["sch"]["inputs"]["model"] == ["lora0", 0]
    assert wf["gd"]["inputs"]["model"] == ["lora0", 0]

def test_flux_workflow_stacks_two_loras_in_series():
    wf = flux_lora_workflow("x", 1, guidance=2.4,
                            loras=[("boy.safetensors", 0.9), ("dog.safetensors", 0.85)])
    assert wf["lora0"]["inputs"]["model"] == ["u", 0]          # boy on UNET
    assert wf["lora1"]["inputs"]["model"] == ["lora0", 0]      # dog on boy output
    assert wf["lora1"]["inputs"]["lora_name"] == "dog.safetensors"
    assert wf["lora1"]["inputs"]["strength_model"] == 0.85
    assert wf["sch"]["inputs"]["model"] == ["lora1", 0]        # chain head = last lora
    assert wf["gd"]["inputs"]["model"] == ["lora1", 0]


def _flux_cfg():
    return BookConfig(slug="k", title="T", subtitle="S", author="A",
                      art_prompt="a boy and a dog on a sunset hill",
                      book_type="picture", pet_kind="dog", pet_name="Biscuit",
                      page_count=4, trim_w=8.5, trim_h=8.5, art_engine="flux",
                      flux_style="watercolour storybook, no text",
                      flux_guidance=2.4, outfit="a red sweater and blue overalls",
                      characters=(HERO, DOG))

def _flux_content():
    return {"character_anchor": "a boy named Biscuit's friend; Biscuit is a golden dog",
            "art_style": "soft watercolour",
            "dedication": "For Biscuit",
            "pages": [
                {"text": "t1", "scene": "the field", "cast": "child_and_pet", "mood": "happy"},
                {"text": "t2", "scene": "the hallway", "cast": "child", "mood": "sad"}],
            "closing": "c"}

def _fake_comfy():
    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    return ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

class _Auditor:
    def __init__(self, fail_first=0):
        self.calls = 0; self.fail_first = fail_first; self.anchors = []
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character", caption=None):
        self.calls += 1; self.anchors.append(anchor)
        ok = self.calls > self.fail_first
        return {"ok": ok, "issues": [] if ok else ["dog colour off"]}

def test_generate_flux_art_writes_pages_and_cover(tmp_path):
    art = generate_flux_art(_flux_cfg(), _flux_content(), tmp_path, _fake_comfy(),
                            seed=7, auditor=_Auditor())
    assert [Path(p).name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert Path(art["cover"]).name == "art.png"
    for p in [*art["pages"], art["cover"]]:
        assert Path(p).exists()
    # flux books need NO SDXL-style reference sheet (the LoRA carries identity)
    assert not (tmp_path / "reference.png").exists()

def test_generate_flux_art_audits_present_page_against_boy_only_anchor(tmp_path):
    aud = _Auditor()
    generate_flux_art(_flux_cfg(), _flux_content(), tmp_path, _fake_comfy(),
                      seed=7, auditor=aud)
    # page 1 is memory -> full anchor (mentions the dog); page 2 is present ->
    # the anchor is trimmed before the pet name so the auditor won't demand a dog
    assert "golden dog" in aud.anchors[0]
    assert "golden dog" not in aud.anchors[1]

def test_generate_flux_art_audits_pet_page_against_pet_only_anchor(tmp_path):
    content = {"character_anchor": "a little girl Posy. Mango is a ginger tabby cat",
               "art_style": "soft watercolour", "dedication": "d",
               "pages": [{"text": "t", "scene": "a meadow", "cast": "pet",
                          "mood": "peaceful"}],
               "closing": "c"}
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A",
                     art_prompt="cover", book_type="picture", pet_kind="cat",
                     pet_name="Mango", page_count=4, trim_w=8.5, trim_h=8.5,
                     art_engine="flux", flux_style="ws", flux_guidance=2.4,
                     outfit="a blue dress", characters=(
                         Character(role="hero", lora="posy.safetensors",
                                   trigger="p0sygirl girl"),
                         Character(role="companion", lora="mango.safetensors",
                                   trigger="mang0cat cat", strength=0.85)))
    aud = _Auditor()
    generate_flux_art(cfg, content, tmp_path, _fake_comfy(), seed=7, auditor=aud)
    # the pet page audits against the pet's part of the anchor, not the child's
    assert "ginger tabby" in aud.anchors[0]
    assert "Posy" not in aud.anchors[0]

def test_generate_flux_art_regenerates_until_consistent(tmp_path):
    aud = _Auditor(fail_first=1)  # first page's first audit fails, then all pass
    generate_flux_art(_flux_cfg(), _flux_content(), tmp_path, _fake_comfy(),
                      seed=7, auditor=aud)
    assert aud.calls >= 4  # page1 (fail+pass) + page2 + cover

def test_generate_flux_art_keeps_best_and_flags_when_inconsistent(tmp_path):
    # a never-consistent run keeps each page's best attempt and flags it for review,
    # rather than raising and killing the whole book on one stubborn page
    art = generate_flux_art(_flux_cfg(), _flux_content(), tmp_path, _fake_comfy(),
                            seed=7, auditor=_Auditor(fail_first=999), max_tries=3)
    assert [Path(p).name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    for p in art["pages"]:
        assert Path(p).exists()
    assert art["flagged"] == [1, 2, "cover"]

def test_generate_flux_art_threads_seed_into_graph(tmp_path):
    seeds = []
    def http_post(url, json):
        seeds.append(json["prompt"]["noise"]["inputs"]["noise_seed"])
        return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)
    generate_flux_art(_flux_cfg(), _flux_content(), tmp_path, comfy,
                      seed=1000, auditor=_Auditor())
    # the caller's seed actually drives the graph (not a hardcoded constant)
    assert 1000 + 1 * 17 in seeds   # page 1 seed = seed + i*17
    assert 1000 + 42 in seeds       # cover seed = seed + 42
    assert all(s >= 1000 for s in seeds)

def test_generate_flux_art_routes_all_three_casts_to_correct_anchors(tmp_path):
    content = {"character_anchor": "a little girl Posy. Mango is a ginger tabby cat",
               "art_style": "soft watercolour", "dedication": "d",
               "pages": [
                   {"text": "t", "scene": "alone in the kitchen",
                    "cast": "child", "mood": "wistful"},
                   {"text": "t", "scene": "together in a meadow",
                    "cast": "child_and_pet", "mood": "happy"},
                   {"text": "t", "scene": "a luminous field",
                    "cast": "pet", "mood": "peaceful"}],
               "closing": "c"}
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A",
                     art_prompt="cover", book_type="picture", pet_kind="cat",
                     pet_name="Mango", page_count=4, trim_w=8.5, trim_h=8.5,
                     art_engine="flux", theme="comfort", flux_style="ws",
                     flux_guidance=2.4, outfit="a blue dress", characters=(
                         Character(role="hero", lora="posy.safetensors",
                                   trigger="p0sygirl girl"),
                         Character(role="companion", lora="mango.safetensors",
                                   trigger="mang0cat cat", strength=0.85)))
    aud = _Auditor()
    generate_flux_art(cfg, content, tmp_path, _fake_comfy(), seed=7, auditor=aud)
    # page 1 (child)         -> hero-only anchor (no pet description)
    assert "ginger tabby" not in aud.anchors[0] and "Posy" in aud.anchors[0]
    # page 2 (child_and_pet) -> full anchor (both)
    assert "ginger tabby" in aud.anchors[1] and "Posy" in aud.anchors[1]
    # page 3 (pet)           -> pet-only anchor (no child)
    assert "ginger tabby" in aud.anchors[2] and "Posy" not in aud.anchors[2]

import json
from pathlib import Path
from factory.config import BookConfig
from factory.art import inject_prompt, ComfyClient, square_workflow, generate_picture_art, ArtError
import pytest


def test_square_workflow_sets_square_dims_by_class_type():
    wf = {
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1536, "height": 768}},
        "10": {"class_type": "LatentUpscale", "inputs": {"width": 3072, "height": 1536}},
        "12": {"class_type": "ImageScale", "inputs": {"width": 5568, "height": 2784}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
    }
    sq = square_workflow(wf, base=1024, final=2048)
    assert sq["5"]["inputs"]["width"] == sq["5"]["inputs"]["height"] == 1024
    assert sq["10"]["inputs"]["width"] == sq["10"]["inputs"]["height"] == 2048
    assert sq["12"]["inputs"]["width"] == sq["12"]["inputs"]["height"] == 2048
    # original untouched (deep copy) and unrelated nodes preserved
    assert wf["5"]["inputs"]["width"] == 1536
    assert sq["6"]["inputs"]["text"] == "x"

def test_square_workflow_tolerates_missing_nodes():
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
    assert square_workflow(wf) == wf  # nothing to change, equal content


def test_inject_prompt_sets_text_and_seed():
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER"}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    out = inject_prompt(wf, positive_node="6", sampler_node="3",
                        prompt="watercolor dog", seed=42)
    assert out["6"]["inputs"]["text"] == "watercolor dog"
    assert out["3"]["inputs"]["seed"] == 42


def test_comfy_generate_downloads_image(tmp_path):
    posts, gets = [], []
    def http_post(url, json):
        posts.append(url)
        return {"prompt_id": "abc"}
    def http_get(url):
        gets.append(url)
        if "/history/" in url:
            return {"abc": {"outputs": {"9": {"images": [
                {"filename": "img.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG\r\n"  # /view raw bytes
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    client = ComfyClient(http_post=http_post, http_get=http_get)
    out = client.generate(wf, positive_node="6", sampler_node="3",
                          prompt="dog", seed=1, out_path=tmp_path / "art.png")
    assert Path(out).exists()
    assert Path(out).read_bytes().startswith(b"\x89PNG")
    assert any("/prompt" in u for u in posts)
    assert any("/view" in u for u in gets)


def _picture_cfg():
    return BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                      book_type="picture", pet_kind="dog", pet_name="Sunny",
                      page_count=2, trim_w=8.5, trim_h=8.5)

def _content():
    return {"character_anchor": "a girl and a golden dog",
            "art_style": "soft watercolor",
            "dedication": "For Sunny",
            "pages": [{"text": "t1", "scene": "garden"},
                      {"text": "t2", "scene": "window"}],
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
    """Fail the first `fail_first` audits, then pass."""
    def __init__(self, fail_first=0): self.calls = 0; self.fail_first = fail_first
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character"):
        self.calls += 1
        ok = self.calls > self.fail_first
        return {"ok": ok, "issues": [] if ok else ["dog colour off"]}

def test_generate_picture_art_writes_ref_pages_and_cover(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    art = generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                               wf, positive_node="6", sampler_node="3", seed=7,
                               auditor=_Auditor())
    assert Path(art["reference"]).name == "reference.png"
    assert [Path(p).name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert Path(art["cover"]).name == "art.png"
    for p in [art["reference"], *art["pages"], art["cover"]]:
        assert Path(p).exists()

def test_generate_picture_art_regenerates_until_consistent(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    auditor = _Auditor(fail_first=1)  # first audit (reference) fails, then all pass
    art = generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                               wf, positive_node="6", sampler_node="3", seed=7,
                               auditor=auditor)
    assert Path(art["reference"]).exists()
    assert auditor.calls >= 4  # 2 for ref (1 fail + 1 pass) + 2 pages

def test_generate_picture_art_fails_when_never_consistent(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    auditor = _Auditor(fail_first=999)  # never passes
    with pytest.raises(ArtError, match="consistent"):
        generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                             wf, positive_node="6", sampler_node="3", seed=7,
                             auditor=auditor, max_tries=3)


def test_comfy_submit_posts_workflow_and_downloads(tmp_path):
    posts, gets = [], []
    def http_post(url, json):
        posts.append((url, json))
        return {"prompt_id": "z"}
    def http_get(url):
        gets.append(url)
        if "/history/" in url:
            return {"z": {"outputs": {"9": {"images": [
                {"filename": "img.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG\r\n"
    client = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)
    wf = {"noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": 9}}}
    out = client.submit(wf, out_path=tmp_path / "flux.png")
    assert Path(out).exists()
    assert Path(out).read_bytes().startswith(b"\x89PNG")
    # submit posts the workflow VERBATIM (no prompt/seed injection)
    assert posts[0][1] == {"prompt": wf}
    assert any("/view" in u for u in gets)


def test_run_audited_render_retries_with_fresh_seed_and_hints(tmp_path):
    from factory.art import run_audited_render
    seeds, prompts = [], []
    def render(prompt, seed, out_path):
        seeds.append(seed); prompts.append(prompt)
        Path(out_path).write_bytes(b"x")
    auditor = _Auditor(fail_first=2)  # first two audits fail, third passes
    out = run_audited_render(render, "base prompt", out_path=tmp_path / "p.png",
                             auditor=auditor, anchor="a", scene="s", seed=100,
                             max_tries=4)
    assert Path(out).exists()
    assert seeds == [100, 1109, 2118]          # seed + attempt*1009
    assert "Fix these problems" in prompts[1]  # corrective hint appended on retry
    assert prompts[0] == "base prompt"         # first attempt is the clean prompt

def test_run_audited_render_raises_after_budget(tmp_path):
    from factory.art import run_audited_render
    def render(prompt, seed, out_path):
        Path(out_path).write_bytes(b"x")
    with pytest.raises(ArtError, match="consistent"):
        run_audited_render(render, "p", out_path=tmp_path / "p.png",
                           auditor=_Auditor(fail_first=999), anchor="a",
                           scene="s", seed=0, max_tries=3)

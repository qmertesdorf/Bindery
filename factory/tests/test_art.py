import json
from pathlib import Path
from factory.art import inject_prompt, ComfyClient, square_workflow


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

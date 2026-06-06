import json
from pathlib import Path
from factory.art import inject_prompt, ComfyClient


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

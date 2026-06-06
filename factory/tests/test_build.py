import json
from pathlib import Path
from factory.art import ComfyClient
from build import run_build


def test_end_to_end_with_fakes(tmp_path, sample_config_dict, sample_content):
    cfgp = tmp_path / "dog-loss.config.json"
    sample_config_dict["prompt_count"] = 5
    cfgp.write_text(json.dumps(sample_config_dict), encoding="utf-8")

    fake_llm = lambda prompt: json.dumps({**sample_content, "prompts": sample_content["prompts"][:5]})

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            Path(args[2]).write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    workflow = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}

    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, workflow=workflow,
                        positive_node="6", sampler_node="3", runner=runner)
    for f in ["interior.pdf", "interior.epub", "cover-paperback.pdf",
              "cover-ebook.jpg", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"

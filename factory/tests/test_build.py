import json
from pathlib import Path
from factory.art import ComfyClient
from build import run_build


def _build(tmp_path, config_dict, content):
    """Run the full pipeline with fakes (no LLM / ComfyUI / browser)."""
    cfgp = tmp_path / "book.config.json"
    config_dict = {**config_dict, "prompt_count": 5}
    cfgp.write_text(json.dumps(config_dict), encoding="utf-8")

    fake_llm = lambda prompt: json.dumps({**content, "prompts": content["prompts"][:5]})

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

    return run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                     comfy=comfy, workflow=workflow,
                     positive_node="6", sampler_node="3", runner=runner)


def test_journal_build_is_paperback_only(tmp_path, sample_config_dict, sample_content):
    # default book_type is "journal" — you can't fill in a Kindle book
    out_dir = _build(tmp_path, sample_config_dict, sample_content)
    for f in ["interior.pdf", "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
    assert not (Path(out_dir) / "interior.epub").exists(), "journal should not produce an EPUB"
    assert not (Path(out_dir) / "cover-ebook.jpg").exists(), "journal should not produce an ebook cover"


def test_standard_book_build_includes_ebook(tmp_path, sample_config_dict, sample_content):
    cfg_dict = {**sample_config_dict, "book_type": "standard"}
    out_dir = _build(tmp_path, cfg_dict, sample_content)
    for f in ["interior.pdf", "cover-paperback.pdf", "upload-checklist.md",
              "interior.epub", "cover-ebook.jpg"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"

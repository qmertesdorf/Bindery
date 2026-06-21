import json
from pathlib import Path
from factory.art import ComfyClient
from factory.audit import ClaudeVisionAuditor  # noqa: F401 (import sanity)
from build import run_build


def _build(tmp_path, config_dict, content, fake_llm=None):
    """Run the full pipeline with fakes (no LLM / ComfyUI / browser)."""
    cfgp = tmp_path / "book.config.json"
    config_dict = {**config_dict, "prompt_count": 5}
    cfgp.write_text(json.dumps(config_dict), encoding="utf-8")

    if fake_llm is None:
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
            target = Path(args[2])
            if target.name == "interior.pdf":
                # a real (blank) PDF so the standard path's pdf_page_count > 0;
                # the journal path ignores this and counts HTML sections instead
                import fitz
                d = fitz.open()
                for _ in range(12):
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
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


def test_standard_book_build_includes_ebook(tmp_path, sample_config_dict):
    cfg_dict = {**sample_config_dict, "book_type": "standard",
                "synopsis": "A comforting read on grieving a dog.",
                "chapter_count": 3, "words_per_chapter": 40,
                "blurb": "A comforting companion read."}

    outline = {"preface": "A short preface.",
               "chapters": [{"title": f"Chapter {i}", "synopsis": "s"} for i in range(1, 4)]}

    def fake_llm(prompt):
        if "OUTLINE" in prompt:                       # outline pass
            return json.dumps(outline)
        if "MATTER" in prompt:                        # front/back matter pass
            return json.dumps({"epigraph": "Gentle lines.",
                               "readings": ["r1", "r2", "r3"],
                               "closing_letter": "Dear friend, be gentle."})
        return json.dumps({"paragraphs": [" ".join(["word"] * 30)] * 2})  # chapter pass

    out_dir = _build(tmp_path, cfg_dict, content=None, fake_llm=fake_llm)
    for f in ["interior.pdf", "cover-paperback.pdf", "upload-checklist.md",
              "interior.epub", "cover-ebook.jpg"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"


def test_picture_build_paperback_only_with_pages(tmp_path, picture_config_dict, picture_content):
    cfgp = tmp_path / "book.config.json"
    cfgp.write_text(json.dumps(picture_config_dict), encoding="utf-8")

    bible = {"character_anchor": picture_content["character_anchor"],
             "art_style": picture_content["art_style"],
             "dedication": picture_content["dedication"]}
    story = {"pages": picture_content["pages"], "closing": picture_content["closing"]}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    class FakeAuditor:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": True, "issues": []}

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            target = Path(args[2])
            if target.name == "interior.pdf":
                import fitz
                d = fitz.open()
                for _ in range(26):   # >= 24, even, for the picture page guard
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    workflow = {"5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1536, "height": 768}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}

    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, workflow=workflow, positive_node="6",
                        sampler_node="3", runner=runner, auditor=FakeAuditor())
    for f in ["content.json", "reference.png", "page_01.png", "page_02.png",
              "art.png", "interior.pdf", "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
    assert not (Path(out_dir) / "interior.epub").exists()
    assert not (Path(out_dir) / "cover-ebook.jpg").exists()


def test_picture_build_routes_to_flux_engine(tmp_path, picture_config_dict, picture_content):
    # keep picture_config_dict's page_count (20) so it matches the 20-page
    # picture_content fixture — content validation requires an exact match.
    cfg_dict = {**picture_config_dict, "art_engine": "flux",
                "flux_style": "watercolour storybook, no text",
                "flux_guidance": 2.4,
                "outfit": "a red sweater and blue overalls",
                "characters": [
                    {"role": "hero", "lora": "boy.safetensors",
                     "trigger": "b1scuitboy boy", "strength": 0.9},
                    {"role": "companion", "lora": "dog.safetensors",
                     "trigger": "b1scuitdog dog", "strength": 0.85,
                     "appears_on": "memory"}]}
    cfgp = tmp_path / "book.config.json"
    cfgp.write_text(json.dumps(cfg_dict), encoding="utf-8")

    bible = {"character_anchor": picture_content["character_anchor"],
             "art_style": picture_content["art_style"],
             "dedication": picture_content["dedication"]}
    story = {"pages": picture_content["pages"], "closing": picture_content["closing"]}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    class FakeAuditor:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": True, "issues": []}

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            target = Path(args[2])
            if target.name == "interior.pdf":
                import fitz
                d = fitz.open()
                for _ in range(26):
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    # NOTE: no workflow passed — the flux path must not need the SDXL template.
    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, runner=runner, auditor=FakeAuditor())
    for f in ["content.json", "page_01.png", "page_02.png", "art.png",
              "interior.pdf", "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
    # flux path produces NO reference sheet
    assert not (Path(out_dir) / "reference.png").exists()


def test_run_build_concept_end_to_end(tmp_path):
    cfg_dict = {
        "slug": "tiny", "book_type": "concept", "art_engine": "flux",
        "title": "Tiny Creatures", "subtitle": "sub", "author": "Eleanor Hartley",
        "subject": "small animals", "flux_style": "soft watercolour, no text",
        "art_prompt": "a meadow, soft watercolour, no text",
        "page_count": 20, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }
    cfgp = tmp_path / "tiny.config.json"
    cfgp.write_text(json.dumps(cfg_dict), encoding="utf-8")

    pages = [{"subject": f"animal {i}", "text": f"line {i}",
              "scene": f"animal {i} in a meadow"} for i in range(20)]
    bible = {"art_style": "soft watercolour", "dedication": "d"}
    story = {"pages": pages, "closing": "bye"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STYLE BIBLE" in prompt else json.dumps(story)

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    class FakeAuditor:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            return {"ok": True, "issues": []}

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            target = Path(args[2])
            if target.name == "interior.pdf":
                import fitz
                d = fitz.open()
                for _ in range(26):
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    # concept must use the Flux submit path and need NO SDXL workflow template.
    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, runner=runner, auditor=FakeAuditor())
    for f in ["content.json", "page_01.png", "art.png", "interior.pdf",
              "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
    # paperback-only: no Kindle edition
    assert not (Path(out_dir) / "interior.epub").exists()


def test_run_build_reuses_existing_art(tmp_path):
    # A rerun must NOT re-render when every page + cover already exists (symmetric
    # to content.json reuse) — e.g. regenerating only the cover/checklist after a
    # metadata fix should preserve the reviewed illustrations.
    cfg_dict = {
        "slug": "tiny", "book_type": "concept", "art_engine": "flux",
        "title": "Tiny Creatures", "subtitle": "sub", "author": "Eleanor Hartley",
        "subject": "small animals", "flux_style": "soft watercolour, no text",
        "art_prompt": "a meadow, soft watercolour, no text",
        "page_count": 20, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }
    cfgp = tmp_path / "tiny.config.json"
    cfgp.write_text(json.dumps(cfg_dict), encoding="utf-8")

    # Pre-seed reviewed content + art so the build should reuse, not render.
    out = tmp_path / "out" / "tiny"
    out.mkdir(parents=True)
    pages = [{"subject": f"animal {i}", "text": f"line {i}",
              "scene": f"animal {i} in a meadow"} for i in range(20)]
    (out / "content.json").write_text(json.dumps({
        "art_style": "x", "character_anchor": "", "dedication": "d",
        "pages": pages, "closing": "bye"}), encoding="utf-8")
    for i in range(1, 21):
        (out / f"page_{i:02d}.png").write_bytes(b"\x89PNG")
    (out / "art.png").write_bytes(b"\x89PNG")

    class BoomComfy:
        def submit(self, *a, **k):
            raise AssertionError("must not render — existing art should be reused")
        def generate(self, *a, **k):
            raise AssertionError("must not render — existing art should be reused")

    def boom_llm(prompt):
        raise AssertionError("must not regenerate content — content.json exists")

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            target = Path(args[2])
            if target.name == "interior.pdf":
                import fitz
                d = fitz.open()
                for _ in range(26):
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=boom_llm,
                        comfy=BoomComfy(), runner=runner)
    for f in ["interior.pdf", "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"

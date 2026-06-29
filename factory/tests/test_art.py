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
              kind="character", caption=None):
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


def test_comfy_free_posts_unload_and_swallows_errors():
    posts = []
    def http_post(url, json):
        posts.append((url, json))
        return {}
    ComfyClient(http_post=http_post).free()
    assert posts[0][0].endswith("/free")
    assert posts[0][1] == {"unload_models": True, "free_memory": True}
    # best-effort: a transport failure must not propagate (freeing is an optimization)
    def boom(url, json):
        raise RuntimeError("comfy down")
    ComfyClient(http_post=boom).free()   # does not raise


def test_comfy_submit_restarts_backend_on_transport_death(tmp_path):
    # A native ComfyUI crash (Blackwell SIGILL at VAE decode) surfaces as a
    # connection error; submit() should relaunch via restart_fn and re-submit the
    # whole graph (the dead process's prompt_id is gone) rather than killing the build.
    import requests
    state = {"alive": False, "restarts": 0}
    def restart():
        state["restarts"] += 1
        state["alive"] = True
    def http_post(url, json):
        if not state["alive"]:
            raise requests.exceptions.ConnectionError("refused")
        return {"prompt_id": "z"}
    def http_get(url):
        if not state["alive"]:
            raise requests.exceptions.ConnectionError("refused")
        if "/history/" in url:
            return {"z": {"outputs": {"9": {"images": [
                {"filename": "img.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG\r\n"
    client = ComfyClient(http_post=http_post, http_get=http_get,
                         poll_interval=0, restart_fn=restart)
    out = client.submit({"n": {"class_type": "X", "inputs": {}}},
                        out_path=tmp_path / "f.png")
    assert Path(out).exists()
    assert state["restarts"] == 1  # restarted once, then the re-submit succeeded


def test_comfy_submit_propagates_transport_error_without_restart_fn(tmp_path):
    # Default (no restart_fn): unchanged behaviour — a transport death propagates.
    import requests
    def http_post(url, json):
        raise requests.exceptions.ConnectionError("refused")
    client = ComfyClient(http_post=http_post, poll_interval=0)
    with pytest.raises(requests.exceptions.ConnectionError):
        client.submit({"n": {}}, out_path=tmp_path / "f.png")


def test_comfy_submit_gives_up_after_max_restarts(tmp_path):
    import requests
    calls = {"restarts": 0}
    def restart():
        calls["restarts"] += 1  # backend never recovers
    def http_post(url, json):
        raise requests.exceptions.ConnectionError("refused")
    client = ComfyClient(http_post=http_post, poll_interval=0,
                         restart_fn=restart, max_restarts=2)
    with pytest.raises(requests.exceptions.ConnectionError):
        client.submit({"n": {}}, out_path=tmp_path / "f.png")
    assert calls["restarts"] == 2  # tried the budget, then re-raised


def test_comfy_submit_does_not_restart_on_graph_error(tmp_path):
    # A real ComfyUI/graph error (no prompt_id -> ArtError) is NOT a transport death;
    # restarting would just loop, so it must propagate immediately.
    calls = {"restarts": 0}
    def restart():
        calls["restarts"] += 1
    def http_post(url, json):
        return {}  # missing prompt_id -> ArtError
    client = ComfyClient(http_post=http_post, poll_interval=0, restart_fn=restart)
    with pytest.raises(ArtError):
        client.submit({"n": {}}, out_path=tmp_path / "f.png")
    assert calls["restarts"] == 0


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


def test_shape_reroll_hint_rewrites_count_issue_positively():
    from factory.art import _shape_reroll_hint
    # the count guard's negative report becomes a positive directive (no "image shows")
    out = _shape_reroll_hint(
        "wrong arms count: scene/caption says 8, image shows 6")
    assert out == "draw exactly 8 arms"
    # hyphenated parts survive
    assert _shape_reroll_hint(
        "wrong eye-stalks count: scene/caption says 2, image shows 3"
    ) == "draw exactly 2 eye-stalks"
    # unrecognised issues pass through unchanged
    assert _shape_reroll_hint("dog colour off") == "dog colour off"


class _CountIssueAuditor:
    """Fail once with a count-guard-style issue, then pass."""
    def __init__(self): self.calls = 0
    def audit(self, image_path, **kw):
        self.calls += 1
        if self.calls == 1:
            return {"ok": False,
                    "issues": ["wrong arms count: scene/caption says 8, image shows 6"]}
        return {"ok": True, "issues": []}


def test_reroll_prompt_feeds_positive_count_directive_not_the_wrong_number(tmp_path):
    from factory.art import run_audited_render
    prompts = []
    def render(prompt, seed, out_path):
        prompts.append(prompt); Path(out_path).write_bytes(b"x")
    run_audited_render(render, "an octopus", out_path=tmp_path / "p.png",
                       auditor=_CountIssueAuditor(), anchor="a", scene="s", seed=1,
                       max_tries=3)
    assert "draw exactly 8 arms" in prompts[1]   # positive directive on the reroll
    assert "image shows" not in prompts[1]        # the wrong number is NOT reinjected

def test_run_audited_render_raises_after_budget(tmp_path):
    from factory.art import run_audited_render
    def render(prompt, seed, out_path):
        Path(out_path).write_bytes(b"x")
    with pytest.raises(ArtError, match="consistent"):
        run_audited_render(render, "p", out_path=tmp_path / "p.png",
                           auditor=_Auditor(fail_first=999), anchor="a",
                           scene="s", seed=0, max_tries=3)


# ---- WS1b best-of-N selection ----

def test_run_audited_render_best_of_n_keeps_highest_score(tmp_path):
    from factory.art import run_audited_render
    from factory.qa import VQAScorer, BestOfNSelector
    # each candidate's bytes ARE its seed; score = that number so the highest
    # seed wins — lets us prove the selected candidate lands at out_path
    def render(prompt, seed, out_path):
        Path(out_path).write_bytes(str(seed).encode())
    vqa = VQAScorer(score_fn=lambda p, c: float(Path(p).read_bytes().decode()))
    out = run_audited_render(
        render, "p", out_path=tmp_path / "p.png", auditor=_Auditor(),
        anchor="a", scene="s", seed=100, max_tries=1, caption="a fox",
        n_candidates=3, selector=BestOfNSelector(vqa))
    assert Path(out).read_bytes() == b"15938"   # 100 + 2*7919, the top candidate
    assert not list(tmp_path.glob("*__cand*"))  # candidate temp files cleaned up

def test_run_audited_render_best_of_n_noop_without_caption(tmp_path):
    from factory.art import run_audited_render
    seeds = []
    def render(prompt, seed, out_path):
        seeds.append(seed); Path(out_path).write_bytes(b"x")
    run_audited_render(render, "p", out_path=tmp_path / "p.png",
                       auditor=_Auditor(), anchor="a", scene="s", seed=5,
                       max_tries=1, caption=None, n_candidates=3,
                       selector="unused")
    assert seeds == [5]   # no caption to rank on -> a single render, no waste


# ---- WS2 repair-before-reroll ----

class _DefectThenPass:
    """Reject the first audit WITH detector boxes, then pass."""
    def __init__(self): self.audits = 0
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character", caption=None):
        self.audits += 1
        if self.audits == 1:
            return {"ok": False, "issues": ["malformed hand"],
                    "defects": [("hand", (0, 0, 1, 1))]}
        return {"ok": True, "issues": []}

def test_repair_runs_before_reroll_on_localized_reject(tmp_path):
    from factory.art import run_audited_render
    class _Aud:  # rejects until the image is marked REPAIRED
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character", caption=None):
            if Path(image_path).read_bytes() == b"REPAIRED":
                return {"ok": True, "issues": []}
            return {"ok": False, "issues": ["bad hand"],
                    "defects": [("hand", (0, 0, 1, 1))]}
    renders, repaired = [], []
    def render(prompt, seed, out_path):
        renders.append(seed); Path(out_path).write_bytes(b"orig")
    def repair_fn(image_path, defects, *, prompt):
        repaired.append(defects); Path(image_path).write_bytes(b"REPAIRED")
    out = run_audited_render(render, "p", out_path=tmp_path / "p.png",
                             auditor=_Aud(), anchor="a", scene="s", seed=0,
                             max_tries=4, repair_fn=repair_fn)
    assert Path(out).read_bytes() == b"REPAIRED"
    assert len(renders) == 1 and len(repaired) == 1  # repaired without a reroll

def test_repair_failure_falls_back_to_reroll(tmp_path):
    from factory.art import run_audited_render
    renders = []
    def render(prompt, seed, out_path):
        renders.append(seed); Path(out_path).write_bytes(b"orig")
    def repair_fn(image_path, defects, *, prompt):
        raise RuntimeError("no fill model")
    out = run_audited_render(render, "p", out_path=tmp_path / "p.png",
                             auditor=_DefectThenPass(), anchor="a", scene="s",
                             seed=0, max_tries=4, repair_fn=repair_fn)
    assert Path(out).exists() and len(renders) == 2  # repair failed -> rerolled

def test_repair_skipped_when_reject_has_no_defects(tmp_path):
    from factory.art import run_audited_render
    called = []
    def render(prompt, seed, out_path): Path(out_path).write_bytes(b"x")
    def repair_fn(image_path, defects, *, prompt): called.append(1)
    run_audited_render(render, "p", out_path=tmp_path / "p.png",
                       auditor=_Auditor(fail_first=1), anchor="a", scene="s",
                       seed=0, max_tries=4, repair_fn=repair_fn)
    assert called == []   # holistic reject with no boxes -> straight to reroll

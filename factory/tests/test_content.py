import json
import pytest
from factory.config import BookConfig
from factory.content import (build_prompt, generate_content, ContentError,
                             validate_content, generate_json, run_claude_cli)


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_claude_cli_retries_transient_failure(monkeypatch):
    # A lone exit-1 blip must NOT abort: the helper retries and returns the later
    # success, so one transient CLI hiccup can't kill a multi-hour build.
    calls = []
    seq = iter([_FakeProc(1, stderr="boom"), _FakeProc(0, stdout="OK\n")])

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return next(seq)

    monkeypatch.setattr("factory.content.subprocess.run", fake_run)
    monkeypatch.setattr("factory.content.time.sleep", lambda *_: None)
    assert run_claude_cli("claude -p", "hi") == "OK\n"
    assert len(calls) == 2


def test_run_claude_cli_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("factory.content.subprocess.run",
                        lambda cmd, **kw: _FakeProc(1, stderr="still down"))
    monkeypatch.setattr("factory.content.time.sleep", lambda *_: None)
    with pytest.raises(ContentError, match="after 3 attempts"):
        run_claude_cli("claude -p", "hi", attempts=3)


def test_run_claude_cli_empty_output_counts_as_failure(monkeypatch):
    # exit 0 but blank stdout is also transient (the build needs a real reply)
    seq = iter([_FakeProc(0, stdout="   \n"), _FakeProc(0, stdout="real\n")])
    monkeypatch.setattr("factory.content.subprocess.run", lambda cmd, **kw: next(seq))
    monkeypatch.setattr("factory.content.time.sleep", lambda *_: None)
    assert run_claude_cli("claude -p", "hi") == "real\n"


def test_generate_json_feeds_error_back_then_succeeds():
    # first response fails validation; the retry prompt must carry the rejection reason
    seen = []
    seq = iter(['{"n": 1}', '{"n": 2}'])
    def fn(prompt):
        seen.append(prompt)
        return next(seq)
    def pv(data):
        if data["n"] != 2:
            raise ContentError("n must be 2")
        return data
    out = generate_json(fn, lambda: "BASE", pv, label="thing")
    assert out == {"n": 2}
    assert seen[0] == "BASE"
    assert "REJECTED" in seen[1] and "n must be 2" in seen[1]


def test_generate_json_raises_after_attempts_exhausted():
    with pytest.raises(ContentError, match="after 2 attempts"):
        generate_json(lambda p: "not json", lambda: "BASE",
                      lambda d: d, label="thing")


@pytest.fixture
def cfg():
    return BookConfig(slug="dog-loss", title="T", subtitle="S", author="A",
                      pet_kind="dog", art_prompt="x", prompt_count=5)


def test_build_prompt_mentions_pet_and_count(cfg):
    p = build_prompt(cfg)
    assert "dog" in p
    assert "5" in p
    assert "JSON" in p


def test_generate_content_parses_fenced_json(cfg, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    fake = lambda prompt: "```json\n" + json.dumps(sample_content) + "\n```"
    out = generate_content(cfg, generate_fn=fake)
    assert len(out["prompts"]) == 5
    assert out["intro"]


def test_generate_content_rejects_bad_json(cfg):
    with pytest.raises(ContentError):
        generate_content(cfg, generate_fn=lambda p: "not json at all")


def test_validate_rejects_missing_key(sample_content):
    del sample_content["prompts"]
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=70)


def test_validate_rejects_wrong_prompt_count(sample_content):
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=999)


import json
from factory.config import BookConfig
from factory.content import generate_content

def test_generate_content_dispatches_picture():
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="picture", pet_kind="dog", pet_name="Sunny",
                     page_count=4, trim_w=8.5, trim_h=8.5)
    bible = {"character_anchor": "a child and a golden dog",
             "art_style": "soft watercolor", "dedication": "For Sunny"}
    story = {"pages": [{"text": f"t{i}", "scene": f"s{i}",
                        "cast": "child", "mood": "tender"} for i in range(4)],
             "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_content(cfg, generate_fn=fake_llm)
    assert len(out["pages"]) == 4 and out["character_anchor"].startswith("a child")

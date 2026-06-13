import json, pytest
from pathlib import Path
from factory.audit import (build_audit_prompt, parse_verdict, AuditError,
                           ClaudeVisionAuditor)

def test_build_audit_prompt_includes_image_anchor_scene():
    p = build_audit_prompt(anchor="a girl + golden dog", scene="by the window",
                           image_path=Path("/out/page_01.png"),
                           reference_path=Path("/out/reference.png"))
    assert "page_01.png" in p and "a girl + golden dog" in p
    assert "by the window" in p and "reference.png" in p

def test_parse_verdict_ok():
    v = parse_verdict('{"ok": true, "issues": []}')
    assert v == {"ok": True, "issues": []}

def test_parse_verdict_coerces_issues_and_strips_fences():
    v = parse_verdict('```json\n{"ok": false, "issues": ["dog colour wrong"]}\n```')
    assert v["ok"] is False and v["issues"] == ["dog colour wrong"]

def test_parse_verdict_rejects_missing_ok():
    with pytest.raises(AuditError):
        parse_verdict('{"issues": []}')

def test_auditor_uses_injected_judge_fn():
    seen = {}
    def fake_judge(prompt):
        seen["prompt"] = prompt
        return '{"ok": false, "issues": ["child hair differs"]}'
    auditor = ClaudeVisionAuditor(judge_fn=fake_judge)
    v = auditor.audit(Path("/out/page_02.png"), anchor="anchor",
                      reference_path=Path("/out/reference.png"), scene="garden")
    assert v["ok"] is False and v["issues"] == ["child hair differs"]
    assert "page_02.png" in seen["prompt"]

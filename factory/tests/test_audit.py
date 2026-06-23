import json, pytest
from pathlib import Path
from factory.audit import (build_audit_prompt, build_concept_audit_prompt,
                           build_cover_audit_prompt,
                           parse_verdict, AuditError, ClaudeVisionAuditor)


def test_cover_audit_prompt_checks_legibility():
    p = build_cover_audit_prompt(image_path=Path("/o/c.png")).lower()
    assert "legib" in p or "contrast" in p
    assert "c.png" in p
    assert "blurb" in p
    assert "centred" in p or "centered" in p or "balance" in p  # checks centering too

def test_build_audit_prompt_includes_image_anchor_scene():
    p = build_audit_prompt(anchor="a girl + golden dog", scene="by the window",
                           image_path=Path("/out/page_01.png"),
                           reference_path=Path("/out/reference.png"))
    assert "page_01.png" in p and "a girl + golden dog" in p
    assert "by the window" in p and "reference.png" in p

def test_build_audit_prompt_rejects_animal_features_on_child():
    # Guards the "boy with a dog's nose" defect: the auditor must be told to reject
    # animal features bleeding onto the human child (two-character attribute bleed).
    p = build_audit_prompt(anchor="a boy + golden dog", scene="cover",
                           image_path=Path("/out/art.png"), reference_path=None)
    low = p.lower()
    assert "snout" in low or "muzzle" in low
    assert "fully" in low and "human" in low


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


def test_concept_audit_prompt_is_character_free():
    prompt = build_concept_audit_prompt(
        anchor="a red fox in a meadow; no people, no text",
        scene="a fox sitting in tall grass at dawn",
        image_path=Path("/out/page_01.png"))
    assert "no people" in prompt.lower()
    assert "page_01.png" in prompt
    # concept books must not carry the character-identity rules
    assert "outfit" not in prompt.lower()
    # rejects AI-slop hybrid/malformed animals (the cover deer/rabbit/fox blend)
    assert "hybrid" in prompt.lower() and "species" in prompt.lower()
    # rejects artist signatures/watermarks (faint corner marks)
    assert "signature" in prompt.lower() and "corner" in prompt.lower()
    # rejects anatomical anomalies by counting features (the 3-eyed snail)
    assert "count" in prompt.lower() and "eyes" in prompt.lower()
    # demands correct, realistic per-species anatomy incl. feature PLACEMENT
    assert "anatomically correct" in prompt.lower()
    assert "eye-stalk" in prompt.lower()  # the snail eyes-on-stalks rule


def test_concept_audit_prompt_checks_body_plan_silhouette():
    # Vision review counts parts but waves through wrong BODY PLANS (round-body manta,
    # dolphin-tailed shark, 6-arm starfish); the prompt must name the silhouette tells
    # for the ocean animals that slipped through ([[catch-defects-with-guards]]).
    low = build_concept_audit_prompt(
        anchor="an ocean animal; no people, no text",
        scene="a manta ray gliding", image_path=Path("/out/page_09.png")).lower()
    assert "body plan" in low and "silhouette" in low
    # the specific failure modes are named so the model has concrete tells to check
    assert "diamond" in low                 # ray = flat disc, not round body + wings
    assert "vertical tail" in low           # shark, not a horizontal dolphin fluke
    assert "exactly five arms" in low       # starfish count
    assert "exactly eight arms" in low      # octopus count
    assert "paddle tail" in low             # manatee, not a forked fish tail


def test_concept_audit_prompt_rejects_photorealism():
    # the auditor must gate out photo-real renders so the regenerate loop
    # self-corrects toward the storybook illustration style
    prompt = build_concept_audit_prompt(
        anchor="a bee on a flower", scene="a bee",
        image_path=Path("/out/p.png")).lower()
    assert "photo" in prompt          # rejects photographic / photorealistic
    assert "storybook" in prompt      # must read as a storybook painting


def test_concept_audit_prompt_enforces_style_cohesion_vs_reference():
    # with a style reference, the auditor must require the new page to MATCH it
    prompt = build_concept_audit_prompt(
        anchor="a snail on a leaf", scene="a snail",
        image_path=Path("/out/page_11.png"),
        reference_path=Path("/out/page_01.png"))
    assert "page_01.png" in prompt          # the reference is named
    assert "reference" in prompt.lower()
    assert "cohesive" in prompt.lower() or "match" in prompt.lower()


def test_concept_audit_prompt_without_reference_has_no_cohesion_clause():
    prompt = build_concept_audit_prompt(
        anchor="a fox", scene="a fox", image_path=Path("/out/p.png")).lower()
    assert "style reference" not in prompt


def test_concept_audit_prompt_rejects_grain():
    # the auditor must gate out grainy/noisy renders (the speckled jellyfish bg) so
    # the regenerate loop self-corrects toward clean watercolour washes
    prompt = build_concept_audit_prompt(
        anchor="a jellyfish", scene="a jellyfish",
        image_path=Path("/out/p.png")).lower()
    assert "grain" in prompt and ("noisy" in prompt or "noise" in prompt)
    assert "speckle" in prompt or "speckled" in prompt


def test_concept_audit_prompt_rejects_white_paper_border():
    # the auditor must gate out pages that don't fill the trim — a ragged white
    # 'watercolour paper' vignette / blank background panel is a full-bleed print
    # defect (uneven white margins at the cut edge), not acceptable 'framing'
    prompt = build_concept_audit_prompt(
        anchor="a seahorse", scene="a seahorse",
        image_path=Path("/out/p.png")).lower()
    assert "fill the page" in prompt
    assert "border" in prompt and "paper" in prompt
    assert "full-bleed" in prompt or "edge to edge" in prompt
    # and 'framing' variation must NOT be a blanket licence for a blank-paper edge
    assert "still fills the page" in prompt


def test_concept_audit_prompt_includes_caption_fidelity():
    # the caption a child reads aloud must match the picture: stated counts/actions
    # (e.g. "eight curly arms", "wrapping its tail round the grass") are enforced
    prompt = build_concept_audit_prompt(
        anchor="an octopus", scene="an octopus on rocks",
        image_path=Path("/out/p.png"),
        caption="The octopus creeps with its eight curly arms.")
    low = prompt.lower()
    assert "The octopus creeps with its eight curly arms." in prompt  # caption quoted
    assert "caption" in low and "count" in low
    assert "caption mismatch" in low  # the reject rule is present


def test_concept_audit_prompt_without_caption_omits_caption_clause():
    prompt = build_concept_audit_prompt(
        anchor="a fox", scene="a fox", image_path=Path("/out/p.png")).lower()
    assert "caption fidelity" not in prompt
    assert "caption mismatch" not in prompt


def test_auditor_threads_caption_to_concept_prompt():
    captured = {}
    def judge(prompt):
        captured["prompt"] = prompt
        return '{"ok": true, "issues": []}'
    auditor = ClaudeVisionAuditor(judge_fn=judge)
    auditor.audit(Path("/out/page_18.png"), anchor="a seahorse", scene="a seahorse",
                  kind="concept", caption="It wraps its tail round the grass.")
    assert "It wraps its tail round the grass." in captured["prompt"]


def test_auditor_kind_selects_concept_prompt():
    captured = {}
    def judge(prompt):
        captured["prompt"] = prompt
        return '{"ok": true, "issues": []}'
    auditor = ClaudeVisionAuditor(judge_fn=judge)
    v = auditor.audit(Path("/out/page_01.png"), anchor="a red fox", scene="a fox",
                      kind="concept")
    assert v["ok"] is True
    assert "no people" in captured["prompt"].lower()

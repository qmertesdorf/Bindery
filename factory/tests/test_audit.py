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


def test_cover_audit_prompt_checks_front_art_defects():
    # The cover composition audit must also scrutinise the FRONT-COVER ART for defects
    # (the gap that let a whale ship with a coral sprig growing from its blowhole) —
    # not only text/layout.
    p = build_cover_audit_prompt(image_path=Path("/o/c.png")).lower()
    assert "front" in p and "art" in p
    # growths / sprigs / antennae from an animal's head/body
    assert "sprig" in p or "growth" in p or "antennae" in p or "blowhole" in p
    # malformed/duplicated anatomy
    assert "malformed" in p or "duplicated" in p or "fused" in p

def test_concept_audit_prompt_requires_species_recognizability():
    # The concept auditor must reject an animal that's missing its species' SIGNATURE
    # feature so it reads generic (the gap that passed a spineless 'pufferfish'),
    # using knowledge of the real animal — not only the scene's stated claims.
    p = build_concept_audit_prompt(
        anchor="a pufferfish in its natural setting", scene="a round pufferfish",
        image_path=Path("/o/p.png")).lower()
    assert "recogniz" in p and "signature" in p
    assert "generic" in p
    assert "pufferfish" in p and ("spine" in p or "prickle" in p)  # illustrative example


def test_concept_audit_prompt_rejects_unrequested_extra_animals():
    # Stray background creatures the scene didn't ask for (the 'ducks' behind the
    # pufferfish) must be rejected — but legitimate multi-animal scenes still pass.
    p = build_concept_audit_prompt(
        anchor="a pufferfish in its natural setting", scene="a round pufferfish",
        image_path=Path("/o/p.png")).lower()
    assert "extra" in p and ("background" in p or "stray" in p)
    assert "pod of dolphins" in p or "family of penguins" in p  # allowed groups
    assert "scenery" in p  # non-animal scenery still fine


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


def test_focused_fidelity_check_is_general_not_per_species():
    # The vision judge passed a dolphin-tailed shark, a bilobed-tail manatee and a
    # 6-arm starfish because the body-plan tells were buried. The fix must be
    # book-agnostic: force the judge to verify the concrete claims already written in
    # THIS page's scene + caption, with no hardcoded per-species checklist that every
    # new book would outgrow ([[catch-defects-with-guards]]).
    low = build_concept_audit_prompt(
        anchor="a shark in its natural setting; no people, no text",
        scene="a grey shark with a vertical tail, top lobe taller, cruising in blue",
        image_path=Path("/out/page_08.png"),
        caption="The friendly grey shark gives a swish of his tail.").lower()
    assert "focused fidelity check" in low
    assert "ground truth" in low                       # leans on scene+caption
    assert "count" in low and "literally" in low       # demands literal verification
    # the focused block itself must be species-agnostic: it works off the page's own
    # scene/caption, so the same wording appears whatever the subject is
    other = build_concept_audit_prompt(
        anchor="a hedgehog in a hedge", scene="a hedgehog among leaves",
        image_path=Path("/out/p.png"), caption="The hedgehog snuffles by.").lower()
    block = "focused fidelity check"
    assert low[low.index(block):low.index(block) + 600] == \
           other[other.index(block):other.index(block) + 600]


def test_focused_fidelity_check_omitted_without_scene_or_caption():
    # with nothing to verify against, the focused block must not appear
    p = build_concept_audit_prompt(
        anchor="a red fox", scene=None, image_path=Path("/out/p.png")).lower()
    assert "focused fidelity check" not in p


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


def test_audit_ensemble_rejects_on_any_failing_pass():
    # A single vision pass is stochastic (it caught the dolphin-tailed shark one run,
    # missed it the next). With passes>1 the any-fail ensemble must reject if ANY pass
    # flags a defect, and union the issues ([[catch-defects-with-guards]]).
    seq = iter([
        '{"ok": true, "issues": []}',
        '{"ok": false, "issues": ["shark tail is a symmetric fluke"]}',
        '{"ok": true, "issues": []}',
    ])
    auditor = ClaudeVisionAuditor(judge_fn=lambda _p: next(seq), passes=3)
    v = auditor.audit(Path("/out/page_08.png"), anchor="a shark", scene="a shark",
                      kind="concept")
    assert v["ok"] is False
    assert v["issues"] == ["shark tail is a symmetric fluke"]


def test_audit_ensemble_passes_when_every_pass_clean_and_dedupes():
    calls = {"n": 0}
    def judge(_p):
        calls["n"] += 1
        return '{"ok": true, "issues": []}'
    auditor = ClaudeVisionAuditor(judge_fn=judge, passes=3)
    v = auditor.audit(Path("/out/p.png"), anchor="a fox", scene="a fox", kind="concept")
    assert v == {"ok": True, "issues": []}
    assert calls["n"] == 3  # ran the configured number of passes

    # repeated identical complaints across passes collapse to one issue
    seq = iter(['{"ok": false, "issues": ["six arms"]}',
                '{"ok": false, "issues": ["six arms"]}'])
    a2 = ClaudeVisionAuditor(judge_fn=lambda _p: next(seq), passes=2)
    v2 = a2.audit(Path("/out/p.png"), anchor="a starfish", scene="a starfish",
                  kind="concept")
    assert v2 == {"ok": False, "issues": ["six arms"]}


def test_describe_prompt_is_spec_free_and_objective():
    from factory.audit import build_describe_prompt
    p = build_describe_prompt(Path("/o/p.png"))
    low = p.lower()
    assert "p.png" in p
    assert "describe" in low and "count" in low
    # it must NOT smuggle in the verdict task or the spec
    assert "reject" not in low and "ok=" not in low


def test_describe_first_injects_independent_observation():
    calls = []
    def judge(prompt):
        calls.append(prompt)
        if len(calls) == 1:  # the describe pass comes first
            return "A round orange fish with two eyes, no text, fills the frame."
        return '{"ok": true, "issues": []}'
    a = ClaudeVisionAuditor(judge_fn=judge, passes=2, describe_first=True)
    v = a.audit(Path("/o/p.png"), anchor="a fox", scene="a fox", kind="concept")
    assert v["ok"] is True
    assert len(calls) == 3  # 1 describe + 2 judge passes
    # both judge passes carry the independent observation
    assert "round orange fish" in calls[1].lower()
    assert "round orange fish" in calls[2].lower()
    # and the judge prompt tells it to trust the pixels over the observation
    assert "trust the pixels" in calls[1].lower() or "trust your own" in calls[1].lower()


def test_describe_first_off_by_default_no_extra_call():
    calls = {"n": 0}
    def judge(_p):
        calls["n"] += 1
        return '{"ok": true, "issues": []}'
    ClaudeVisionAuditor(judge_fn=judge, passes=2).audit(
        Path("/o/p.png"), anchor="a fox", scene="a fox", kind="concept")
    assert calls["n"] == 2  # no describe call


def test_merge_verdicts_majority_passes_on_minority_fail():
    # Majority vote trades the any-fail recall for precision: a lone dissenting pass
    # no longer sinks the page, but its issue is still surfaced for provenance.
    from factory.audit import _merge_verdicts
    v = _merge_verdicts([
        {"ok": True, "issues": []},
        {"ok": False, "issues": ["six arms"]},
        {"ok": True, "issues": []},
    ], mode="majority")
    assert v["ok"] is True
    assert v["issues"] == ["six arms"]


def test_merge_verdicts_majority_rejects_on_majority_fail_and_ties():
    from factory.audit import _merge_verdicts
    assert _merge_verdicts([
        {"ok": False, "issues": ["a"]},
        {"ok": False, "issues": ["b"]},
        {"ok": True, "issues": []},
    ], mode="majority")["ok"] is False
    # an even split errs safe → reject (this is a defect auditor)
    assert _merge_verdicts([
        {"ok": True, "issues": []},
        {"ok": False, "issues": ["a"]},
    ], mode="majority")["ok"] is False


def test_auditor_majority_aggregate_end_to_end():
    seq = iter(['{"ok": true, "issues": []}',
                '{"ok": false, "issues": ["x"]}',
                '{"ok": true, "issues": []}'])
    a = ClaudeVisionAuditor(judge_fn=lambda _p: next(seq), passes=3,
                            aggregate="majority")
    v = a.audit(Path("/o/p.png"), anchor="a fox", scene="a fox", kind="concept")
    assert v["ok"] is True  # any-fail would reject; majority passes (2 of 3 clean)


def test_auditor_default_aggregate_is_any_fail():
    seq = iter(['{"ok": true, "issues": []}',
                '{"ok": false, "issues": ["x"]}',
                '{"ok": true, "issues": []}'])
    a = ClaudeVisionAuditor(judge_fn=lambda _p: next(seq), passes=3)
    assert a.audit(Path("/o/p.png"), anchor="a fox", scene="a fox",
                   kind="concept")["ok"] is False  # default unchanged


def test_audit_default_is_single_pass():
    calls = {"n": 0}
    def judge(_p):
        calls["n"] += 1
        return '{"ok": true, "issues": []}'
    ClaudeVisionAuditor(judge_fn=judge).audit(
        Path("/out/p.png"), anchor="a fox", scene="a fox", kind="concept")
    assert calls["n"] == 1  # default unchanged: exactly one vision call


def _all_three_prompts():
    return (
        build_concept_audit_prompt(anchor="a fox", scene="a fox",
                                   image_path=Path("/o/p.png")).lower(),
        build_audit_prompt(anchor="a boy + dog", scene="x",
                           image_path=Path("/o/p.png"), reference_path=None).lower(),
        build_cover_audit_prompt(image_path=Path("/o/c.png")).lower(),
    )


def test_prompts_force_pixels_first_describe_then_judge():
    # The dominant VLM-judge failure is trusting the text spec over the pixels; every
    # prompt must tell the judge to look at the image FIRST and let the pixels win.
    for low in _all_three_prompts():
        assert "actually see" in low
        assert "only from the pixels" in low


def test_prompts_bias_defect_list_toward_strict():
    # Leniency bias: judges over-accept. The defect list (only) must push "prove it's
    # clean" — no waving a borderline defect through — while staying generous on
    # incidental variation.
    for low in _all_three_prompts():
        assert "borderline" in low


def test_prompts_require_evidence_location_per_issue():
    # Evidence-grounding: each issue must localize itself (corner / edge / body part),
    # which both steadies the judge and makes the reroll/repair targeted.
    for low in _all_three_prompts():
        assert "name where" in low


def test_concept_and_cover_check_physics_consistency():
    # Groh taxonomy: inconsistent light/shadow/reflection/perspective is a common AI
    # render tell the prompts didn't previously cover.
    for low in (
        build_concept_audit_prompt(anchor="a fox", scene="a fox",
                                   image_path=Path("/o/p.png")).lower(),
        build_cover_audit_prompt(image_path=Path("/o/c.png")).lower(),
    ):
        assert "shadow" in low
        assert "reflection" in low or "perspective" in low


def test_claude_vision_pins_the_judge_model(monkeypatch):
    # The vision judge must NOT inherit the box's default CLI model: every audit
    # prompt was tuned/validated against Opus, and the default can change any day
    # (it just did — the box default moved to a different model family). The real
    # adapter must pin the model exactly like content generation does.
    seen = {}
    def fake_run(shell_cmd, prompt, **kw):
        seen["cmd"] = shell_cmd
        return '{"ok": true, "issues": []}'
    monkeypatch.setattr("factory.audit.run_claude_cli", fake_run)
    monkeypatch.delenv("BOOKGEN_VISION_MODEL", raising=False)
    from factory.audit import _claude_vision
    _claude_vision("judge this")
    assert "--model claude-opus-4-8" in seen["cmd"]


def test_claude_vision_model_env_override(monkeypatch):
    # Per-environment override mirrors BOOKGEN_CONTENT_MODEL (read at call time so
    # a build script can set it without re-importing the world).
    seen = {}
    def fake_run(shell_cmd, prompt, **kw):
        seen["cmd"] = shell_cmd
        return '{"ok": true, "issues": []}'
    monkeypatch.setattr("factory.audit.run_claude_cli", fake_run)
    monkeypatch.setenv("BOOKGEN_VISION_MODEL", "claude-sonnet-4-6")
    from factory.audit import _claude_vision
    _claude_vision("judge this")
    assert "--model claude-sonnet-4-6" in seen["cmd"]


def test_claude_vision_rejects_unsafe_model_token(monkeypatch):
    # The model id is interpolated into a shell string; keep the no-injection
    # property by refusing anything outside [A-Za-z0-9._-]. run_claude_cli is
    # faked as a belt so a validation regression can never shell out for real
    # from this test — the fake's reply parses, so reaching it fails the raises.
    monkeypatch.setattr("factory.audit.run_claude_cli",
                        lambda cmd, prompt, **kw: '{"ok": true, "issues": []}')
    monkeypatch.setenv("BOOKGEN_VISION_MODEL", "opus; rm -rf /")
    from factory.audit import _claude_vision
    with pytest.raises(AuditError, match="model"):
        _claude_vision("judge this")


def _tag_spans(prompt: str, tag: str) -> tuple[int, int]:
    """Assert <tag>...</tag> appears exactly once and well-ordered; return span."""
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    assert prompt.count(open_t) == 1, f"{open_t} must appear exactly once"
    assert prompt.count(close_t) == 1, f"{close_t} must appear exactly once"
    s, e = prompt.index(open_t), prompt.index(close_t)
    assert s < e, f"{open_t} must open before it closes"
    return s, e


def test_audit_prompts_are_xml_sectioned_for_the_judge():
    # Claude judges attend to XML-delimited sections far more reliably than to a
    # 1,200-word wall of prose — the reject list and the accept list in particular
    # must be structurally separated so 'generous on variation' can never bleed
    # into 'strict on defects'. Wrap the battle-tested wording; do not reword it.
    concept = build_concept_audit_prompt(
        anchor="a fox", scene="a fox in grass", image_path=Path("/o/p.png"),
        caption="The fox sits.")
    character = build_audit_prompt(anchor="a boy + dog", scene="x",
                                   image_path=Path("/o/p.png"),
                                   reference_path=Path("/o/r.png"))
    cover = build_cover_audit_prompt(image_path=Path("/o/c.png"))

    for prompt in (concept, character):
        spec_s, spec_e = _tag_spans(prompt, "page_spec")
        rej_s, rej_e = _tag_spans(prompt, "reject_defects")
        acc_s, acc_e = _tag_spans(prompt, "accept_variation")
        out_s, _ = _tag_spans(prompt, "output_format")
        # spec -> reject -> accept -> output, in that order
        assert spec_e < rej_s < rej_e < acc_s < acc_e < out_s

    # the cover prompt has no per-page spec, but shares the other three sections
    rej_s, rej_e = _tag_spans(cover, "reject_defects")
    acc_s, acc_e = _tag_spans(cover, "accept_variation")
    out_s, _ = _tag_spans(cover, "output_format")
    assert rej_e < acc_s and acc_e < out_s

    # the content lives INSIDE its section (concept prompt's own spans)
    c_rej_s, c_rej_e = _tag_spans(concept, "reject_defects")
    c_acc_s, c_acc_e = _tag_spans(concept, "accept_variation")
    assert c_rej_s < concept.index("WRONG subject") < c_rej_e
    assert c_acc_s < concept.index("different pose") < c_acc_e
    assert concept.index("This page should show") > concept.index("<page_spec>")
    assert concept.index("Return ONLY JSON") > concept.index("<output_format>")


def test_xml_sections_do_not_reword_the_tuned_contracts():
    # Tagging must be purely structural: every battle-tested clause the older
    # contract tests pin down still appears verbatim (spot-check the critical ones).
    low = build_concept_audit_prompt(
        anchor="a fox", scene="a fox", image_path=Path("/o/p.png"),
        caption="The fox sits.").lower()
    for clause in ("focused fidelity check", "caption mismatch", "body plan",
                   "exactly five arms", "exactly eight arms", "paddle tail",
                   "anatomically correct", "fill the page", "actually see",
                   "only from the pixels", "borderline", "name where"):
        assert clause in low, f"tuned clause lost in restructure: {clause!r}"


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

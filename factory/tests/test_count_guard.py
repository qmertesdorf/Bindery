"""Deterministic exact-count guard: extraction is pure code; the count probe is
isolated + injectable so the suite needs no GPU or CLI."""
from pathlib import Path

from factory.qa.count_guard import (extract_count_claims, build_count_prompt,
                                     CountGuard, _parse_int)
from factory.qa import EnsembleAuditor


# ---- claim extraction (pure code) ----

def test_extract_number_words_and_digits_agree():
    claims = dict(extract_count_claims(
        "a starfish with exactly five arms, not a sixth",
        "It waves all 5 arms."))
    assert claims["arms"] == 5

def test_extract_conflicting_counts_are_dropped():
    # same part, two different numbers -> ambiguous -> no claim (never a false reject)
    assert "arms" not in dict(extract_count_claims("five arms and six arms"))

def test_extract_single_means_one_and_skips_unnumbered():
    claims = dict(extract_count_claims("a single paddle tail on a manatee"))
    assert claims["tails"] == 1
    # a bare plural with no number is not a count claim
    assert "legs" not in dict(extract_count_claims("a dog with legs"))

def test_extract_eye_stalks_with_adjective_and_canonicalises():
    claims = dict(extract_count_claims("two upper eye-stalks, each with one eye"))
    assert claims["eye-stalks"] == 2
    assert claims["eyes"] == 1  # 'one eye' -> eyes:1

def test_extract_reads_scene_and_caption_together():
    claims = dict(extract_count_claims("an octopus on rocks",
                                       "it creeps on eight curly arms"))
    assert claims["arms"] == 8

def test_extract_ignores_numbers_without_a_body_part():
    assert extract_count_claims("five minutes before two o'clock") == []


# ---- count probe wording ----

def test_count_prompt_enumerates_and_states_no_expected_number():
    p = build_count_prompt("arms", Path("/o/p.png"))
    low = p.lower()
    assert "p.png" in p
    assert "count" in low and "number each one" in low
    assert "only the final integer" in low
    # must not leak an expected count to anchor on
    assert "five" not in low and "eight" not in low

def test_parse_int_pulls_the_integer_from_chatty_replies():
    assert _parse_int("I count 6 arms.") == 6
    assert _parse_int("8") == 8
    assert _parse_int("none visible") is None


# ---- guard decision ----

def test_guard_rejects_only_on_mismatch():
    g = CountGuard(count_fn=lambda part, path: 6)  # image shows 6
    issues = g.check(Path("/o/p.png"), scene="a starfish with five arms")
    assert len(issues) == 1
    assert "arms" in issues[0] and "5" in issues[0] and "6" in issues[0]

def test_guard_passes_when_counts_match():
    g = CountGuard(count_fn=lambda part, path: 8)
    assert g.check(Path("/o/p.png"), scene="an octopus with eight arms") == []

def test_guard_does_not_fabricate_reject_when_count_unknown():
    g = CountGuard(count_fn=lambda part, path: None)
    assert g.check(Path("/o/p.png"), scene="five arms") == []

def test_guard_only_probes_extracted_parts():
    seen = []
    def count_fn(part, path):
        seen.append(part)
        return 5
    CountGuard(count_fn=count_fn).check(
        Path("/o/p.png"), scene="a starfish with five arms", caption="so pretty")
    assert seen == ["arms"]  # no probe for parts that were never claimed


# ---- ensemble integration ----

class _OkHolistic:
    def audit(self, image_path, **kw):
        return {"ok": True, "issues": []}

def test_ensemble_count_guard_rejects_wrong_count():
    ens = EnsembleAuditor(_OkHolistic(),
                          count_guard=CountGuard(count_fn=lambda part, path: 6))
    v = ens.audit("/o/p.png", anchor="a starfish", scene="a starfish with five arms",
                  kind="concept", caption=None)
    assert v["ok"] is False
    assert any("arms" in i for i in v["issues"])

def test_ensemble_count_guard_skips_cover():
    ens = EnsembleAuditor(_OkHolistic(),
                          count_guard=CountGuard(count_fn=lambda part, path: 99))
    v = ens.audit("/o/c.png", anchor="", scene="five arms", kind="cover",
                  caption="blurb")
    assert v["ok"] is True

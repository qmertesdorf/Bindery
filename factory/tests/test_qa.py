"""WS1 layered-QA ensemble: VQAScore gate, HADM anatomy stage, best-of-N
selection, and the EnsembleAuditor that combines them with the holistic auditor.
Every stage is exercised with injected fakes — no GPU, no model weights."""
import pytest
from pathlib import Path

from factory.audit import ClaudeVisionAuditor
from factory.qa import (VQAScorer, AnatomyDetector, Defect, BestOfNSelector,
                        EnsembleAuditor, build_ensemble_auditor)
from factory.qa.vqascore import VQAScoreError
from factory.qa.hadm import AnatomyError


# ---- VQAScorer ----

def test_vqascorer_scores_via_injected_fn():
    vqa = VQAScorer(score_fn=lambda p, c: 0.83, threshold=0.6)
    assert vqa.score(Path("/o/p.png"), "an octopus") == 0.83

def test_vqascorer_passes_reports_bool_and_score():
    vqa = VQAScorer(score_fn=lambda p, c: 0.42, threshold=0.6)
    ok, score = vqa.passes(Path("/o/p.png"), "a seahorse")
    assert ok is False and score == 0.42
    ok2, _ = VQAScorer(score_fn=lambda p, c: 0.7, threshold=0.6).passes("x", "y")
    assert ok2 is True

def test_vqascore_real_adapter_errors_without_dep():
    # The default adapter must fail loudly with install guidance, never silently
    # pass, when t2v_metrics is absent.
    from factory.qa import vqascore
    vqascore._MODEL = None
    with pytest.raises(VQAScoreError):
        vqascore._load_model()


# ---- AnatomyDetector ----

def test_anatomy_detector_filters_low_confidence():
    defs = [Defect("malformed hand", (0, 0, 10, 10), 0.9),
            Defect("extra limb", (5, 5, 9, 9), 0.3)]
    det = AnatomyDetector(detect_fn=lambda p: defs, min_score=0.5)
    kept = det.detect(Path("/o/p.png"))
    assert [d.label for d in kept] == ["malformed hand"]
    assert det.is_clean(Path("/o/p.png")) is False

def test_anatomy_detector_clean_image():
    det = AnatomyDetector(detect_fn=lambda p: [])
    assert det.is_clean("/o/p.png") is True

def test_anatomy_real_adapter_errors_until_wired():
    from factory.qa import hadm
    hadm._MODEL = None
    with pytest.raises(AnatomyError):
        hadm._load_model()


# ---- BestOfNSelector ----

def test_best_of_n_picks_highest_vqascore():
    scores = {"a.png": 0.4, "b.png": 0.9, "c.png": 0.7}
    vqa = VQAScorer(score_fn=lambda p, c: scores[Path(p).name])
    sel = BestOfNSelector(vqa)
    chosen = sel.select(["a.png", "b.png", "c.png"], caption="a fox")
    assert Path(chosen).name == "b.png"

def test_best_of_n_no_caption_returns_first():
    # nothing to score against -> stable first candidate, no scorer call
    def boom(p, c):  # must not be called
        raise AssertionError("scorer called without a caption")
    sel = BestOfNSelector(VQAScorer(score_fn=boom))
    assert Path(sel.select(["a.png", "b.png"], caption=None)).name == "a.png"

def test_best_of_n_single_candidate_skips_scoring():
    sel = BestOfNSelector(VQAScorer(score_fn=lambda p, c: 1 / 0))
    assert Path(sel.select(["only.png"], caption="a fox")).name == "only.png"


# ---- EnsembleAuditor ----

def _holistic(ok=True, issues=None):
    return ClaudeVisionAuditor(
        judge_fn=lambda prompt: '{"ok": %s, "issues": %s}'
        % ("true" if ok else "false",
           "[]" if not issues else "[" + ",".join(f'"{i}"' for i in issues) + "]"))

def test_ensemble_delegates_when_no_extra_stages():
    ens = EnsembleAuditor(_holistic(ok=False, issues=["wrong subject"]))
    v = ens.audit("/o/p.png", anchor="a fox", scene="a fox", kind="concept",
                  caption="a red fox")
    assert v["ok"] is False and v["issues"] == ["wrong subject"]
    assert "vqa_score" not in v and "defects" not in v

def test_ensemble_vqa_rejects_low_fidelity_and_reports_score():
    ens = EnsembleAuditor(_holistic(ok=True),
                          vqa=VQAScorer(score_fn=lambda p, c: 0.2, threshold=0.6))
    v = ens.audit("/o/p.png", anchor="an octopus", scene="octopus",
                  kind="concept", caption="eight curly arms")
    assert v["ok"] is False
    assert v["vqa_score"] == 0.2
    assert any("caption fidelity" in i.lower() for i in v["issues"])

def test_ensemble_vqa_passes_high_fidelity():
    ens = EnsembleAuditor(_holistic(ok=True),
                          vqa=VQAScorer(score_fn=lambda p, c: 0.95, threshold=0.6))
    v = ens.audit("/o/p.png", anchor="a fox", scene="fox", kind="concept",
                  caption="a red fox")
    assert v["ok"] is True and v["vqa_score"] == 0.95

def test_ensemble_anatomy_rejects_and_attaches_defects():
    defs = [Defect("malformed hand", (1, 2, 3, 4), 0.9)]
    ens = EnsembleAuditor(_holistic(ok=True),
                          anatomy=AnatomyDetector(detect_fn=lambda p: defs))
    v = ens.audit("/o/p.png", anchor="a child", scene="play", kind="concept")
    assert v["ok"] is False
    assert v["defects"] == defs
    assert any("malformed hand" in i for i in v["issues"])

def test_ensemble_skips_vqa_and_anatomy_on_cover():
    # The cover member judges layout, not subject/anatomy; the numeric gates must
    # not run (and reject) on the wraparound cover.
    ens = EnsembleAuditor(_holistic(ok=True),
                          vqa=VQAScorer(score_fn=lambda p, c: 0.0, threshold=0.6),
                          anatomy=AnatomyDetector(detect_fn=lambda p: [
                              Defect("x", (0, 0, 1, 1), 1.0)]))
    v = ens.audit("/o/c.png", anchor="", scene=None, kind="cover",
                  caption="a blurb")
    assert v["ok"] is True and "vqa_score" not in v and "defects" not in v

def test_ensemble_selector_from_vqa_member():
    ens = EnsembleAuditor(_holistic(), vqa=VQAScorer(score_fn=lambda p, c: 0.5))
    assert isinstance(ens.selector(), BestOfNSelector)
    assert EnsembleAuditor(_holistic()).selector() is None


# ---- build_ensemble_auditor factory ----

class _Cfg:
    def __init__(self, **kw):
        self.__dict__.update(kw)

def test_factory_returns_bare_holistic_when_disabled():
    cfg = _Cfg(qa_vqa=False, qa_anatomy=False)
    aud = build_ensemble_auditor(cfg, judge_fn=lambda p: '{"ok": true}')
    assert isinstance(aud, ClaudeVisionAuditor)

def test_factory_builds_ensemble_with_enabled_stages():
    cfg = _Cfg(qa_vqa=True, qa_vqa_threshold=0.7, qa_anatomy=True,
               qa_anatomy_min_score=0.4)
    aud = build_ensemble_auditor(
        cfg, judge_fn=lambda p: '{"ok": true}',
        vqa_score_fn=lambda p, c: 0.9, anatomy_detect_fn=lambda p: [])
    assert isinstance(aud, EnsembleAuditor)
    assert aud.vqa.threshold == 0.7 and aud.anatomy.min_score == 0.4

"""WS1 layered-QA ensemble: VQAScore gate, HADM anatomy stage, best-of-N
selection, and the EnsembleAuditor that combines them with the holistic auditor.
Every stage is exercised with injected fakes — no GPU, no model weights."""
import pytest
from pathlib import Path

from factory.audit import ClaudeVisionAuditor
from factory.qa import (VQAScorer, AnatomyDetector, Defect, BestOfNSelector,
                        ClaudeBestOfNSelector, build_select_prompt, parse_best,
                        EnsembleAuditor, build_ensemble_auditor,
                        TifaProbe, TifaDecomposer, TifaEvaluator)
from factory.qa.vqascore import VQAScoreError
from factory.qa.hadm import AnatomyError
from factory.qa.tifa import parse_probes, TifaError


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

def test_shutdown_daemon_is_safe_when_none():
    # idempotent / safe to call before the cover render even if VQA was never used
    from factory.qa import shutdown_daemon
    shutdown_daemon()
    shutdown_daemon()


def test_vqascore_real_adapter_errors_without_venv():
    # The default adapter must fail loudly with guidance — never silently pass —
    # when the isolated GPU venv python is missing.
    from factory.qa.vqascore import _VQADaemon
    d = _VQADaemon(python="/nonexistent/vqa/python.exe")
    with pytest.raises(VQAScoreError):
        d._ensure()


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

def test_best_of_n_frees_vram_before_scoring():
    # the VRAM-evict hook fires once, before the (separate-process) VQA model loads
    calls = []
    vqa = VQAScorer(score_fn=lambda p, c: (calls.append("score"), 0.5)[1])
    sel = BestOfNSelector(vqa, free_fn=lambda: calls.append("free"))
    sel.select(["a.png", "b.png"], caption="a fox")
    assert calls[0] == "free" and calls.count("free") == 1 and "score" in calls

def test_best_of_n_no_free_when_nothing_to_score():
    # single candidate / no caption short-circuits — don't pay a needless VRAM evict
    calls = []
    sel = BestOfNSelector(VQAScorer(score_fn=lambda p, c: 0.5),
                          free_fn=lambda: calls.append("free"))
    sel.select(["only.png"], caption="a fox")
    sel.select(["a.png", "b.png"], caption=None)
    assert calls == []


# ---- ClaudeBestOfNSelector (taste pick) ----

def test_parse_best_reads_1based_index_else_zero():
    assert parse_best("BEST: 2", 3) == 1
    assert parse_best("blah\nBEST:  3  \nok", 3) == 2
    assert parse_best("no answer", 3) == 0       # unparseable -> first
    assert parse_best("BEST: 9", 3) == 0         # out of range -> first

def test_claude_selector_picks_judge_choice_and_sees_all_candidates():
    seen = {}
    def judge(prompt):
        seen["prompt"] = prompt
        return "BEST: 3"
    sel = ClaudeBestOfNSelector(judge, subject="a penguin", anchor_path="anchor.png")
    chosen = sel.select(["a.png", "b.png", "c.png"], caption="penguins swim")
    assert Path(chosen).name == "c.png"               # the judged winner
    assert "a.png" in seen["prompt"] and "c.png" in seen["prompt"]  # all candidates named
    assert "anchor.png" in seen["prompt"]             # anchor passed to the rubric
    p = seen["prompt"].lower()
    assert "watercolour" in p                          # soft-style rubric present
    assert "full-bleed" in p and "trim" in p           # print-safe full-bleed requirement

def test_claude_selector_single_or_no_caption_skips_judge():
    def boom(prompt):
        raise AssertionError("judge called when there was nothing to choose")
    sel = ClaudeBestOfNSelector(boom)
    assert Path(sel.select(["only.png"], caption="x")).name == "only.png"
    assert Path(sel.select(["a.png", "b.png"], caption=None)).name == "a.png"

def test_hybrid_drops_wrong_subject_duds_then_judge_picks():
    # VQA floor removes the dud (0.02), Claude then picks among the survivors
    scores = {"dud.png": 0.02, "good1.png": 0.6, "good2.png": 0.8}
    vqa = VQAScorer(score_fn=lambda p, c: scores[Path(p).name])
    judged = {}
    def judge(prompt):
        judged["prompt"] = prompt
        return "BEST: 2"            # 2nd of the survivors
    sel = ClaudeBestOfNSelector(judge, vqa=vqa, vqa_floor=0.10)
    chosen = sel.select(["dud.png", "good1.png", "good2.png"], caption="a penguin")
    assert Path(chosen).name == "good2.png"           # survivor #2
    assert "dud.png" not in judged["prompt"]          # dud never reached the judge

def test_hybrid_keeps_best_when_all_below_floor():
    # everything is a dud -> never empty: fall back to the single highest VQA
    scores = {"a.png": 0.02, "b.png": 0.05}
    vqa = VQAScorer(score_fn=lambda p, c: scores[Path(p).name])
    sel = ClaudeBestOfNSelector(lambda prompt: "BEST: 1", vqa=vqa, vqa_floor=0.10)
    assert Path(sel.select(["a.png", "b.png"], caption="a penguin")).name == "b.png"


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

def test_ensemble_selector_modes():
    vqa = VQAScorer(score_fn=lambda p, c: 0.5)
    # "claude": a taste selector with NO vqa member needed (uses the holistic judge_fn)
    claude_sel = EnsembleAuditor(_holistic(), select_mode="claude").selector()
    assert isinstance(claude_sel, ClaudeBestOfNSelector) and claude_sel.vqa is None
    # "hybrid": taste selector pre-filtered by the VQA member
    hybrid_sel = EnsembleAuditor(_holistic(), vqa=vqa, select_mode="hybrid").selector()
    assert isinstance(hybrid_sel, ClaudeBestOfNSelector) and hybrid_sel.vqa is vqa
    # "vqa" (default) stays the fidelity selector
    assert isinstance(
        EnsembleAuditor(_holistic(), vqa=vqa, select_mode="vqa").selector(),
        BestOfNSelector)
    # the configured VQA dud-floor reaches the hybrid selector
    sel = EnsembleAuditor(_holistic(), vqa=vqa, select_mode="hybrid",
                          select_floor=0.25).selector()
    assert sel.vqa_floor == 0.25

def test_factory_builds_claude_selector_without_vqa():
    # qa_select=claude WITH best-of-N must build an ensemble that exposes a Claude
    # taste selector even when every other QA stage (incl. VQA) is off.
    cfg = _Cfg(qa_vqa=False, qa_anatomy=False, qa_tifa=False, qa_count_guard=False,
               qa_corner_crops=False, qa_select="claude", qa_candidates=3)
    aud = build_ensemble_auditor(cfg, judge_fn=lambda p: '{"ok": true}')
    assert isinstance(aud, EnsembleAuditor)
    assert isinstance(aud.selector(), ClaudeBestOfNSelector)

def test_factory_stays_bare_holistic_for_single_candidate_claude_default():
    # The default flip to qa_select="claude" must NOT pull single-candidate books off
    # the bare-holistic path — the selector only matters when qa_candidates>1.
    cfg = _Cfg(qa_vqa=False, qa_anatomy=False, qa_tifa=False, qa_count_guard=False,
               qa_corner_crops=False, qa_select="claude", qa_candidates=1)
    aud = build_ensemble_auditor(cfg, judge_fn=lambda p: '{"ok": true}')
    assert isinstance(aud, ClaudeVisionAuditor)


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


# ---- TIFA decomposition (WS1e) ----

def test_tifa_decomposer_via_injected_fn():
    probes = [TifaProbe("eight arms", "count"), TifaProbe("an octopus", "object")]
    dec = TifaDecomposer(decompose_fn=lambda c: probes)
    assert dec.decompose("an octopus with eight arms") == probes

def test_tifa_parse_probes_reads_llm_json():
    raw = ('```json\n[{"category":"count","element":"eight arms"},'
           '{"category":"object","element":"an octopus"}]\n```')
    probes = parse_probes(raw)
    assert [(p.element, p.category) for p in probes] == [
        ("eight arms", "count"), ("an octopus", "object")]

def test_tifa_parse_probes_skips_malformed_entries():
    raw = '[{"category":"object","element":"a fox"}, {"category":"color"}, "junk"]'
    probes = parse_probes(raw)
    assert [(p.element, p.category) for p in probes] == [("a fox", "object")]

def test_tifa_parse_probes_rejects_non_json():
    with pytest.raises(TifaError):
        parse_probes("the caption shows a fox")

def test_tifa_decomposer_caches_per_caption():
    # a caption is re-audited across reroll attempts; decompose it (a real LLM
    # call) only once per distinct caption.
    calls = []
    dec = TifaDecomposer(decompose_fn=lambda c: calls.append(c) or [TifaProbe(c, "object")])
    dec.decompose("a fox")
    dec.decompose("a fox")
    dec.decompose("a hare")
    assert calls == ["a fox", "a hare"]

def _evaluator(scores, probes, threshold=0.5):
    """TifaEvaluator with a fake decomposer + fake per-element VQA scorer."""
    dec = TifaDecomposer(decompose_fn=lambda c: probes)
    vqa = VQAScorer(score_fn=lambda p, element: scores[element])
    return TifaEvaluator(dec, vqa, threshold=threshold)

def test_tifa_evaluate_passes_when_all_probes_strong():
    probes = [TifaProbe("a red fox", "color"), TifaProbe("a fox", "object")]
    rep = _evaluator({"a red fox": 0.8, "a fox": 0.9}, probes).evaluate(
        "/o/p.png", "a red fox runs")
    assert rep["ok"] is True
    assert rep["score"] == pytest.approx(0.85)
    assert rep["hints"] == [] and rep["failing"] == []

def test_tifa_evaluate_flags_weak_probe_with_targeted_hint():
    probes = [TifaProbe("eight arms", "count"), TifaProbe("an octopus", "object")]
    rep = _evaluator({"eight arms": 0.05, "an octopus": 0.8}, probes,
                     threshold=0.5).evaluate("/o/p.png", "an octopus with eight arms")
    assert rep["ok"] is False
    assert rep["failing"] == ["count"]
    assert len(rep["hints"]) == 1
    assert "eight arms" in rep["hints"][0] and "count" in rep["hints"][0].lower()
    by = {p["element"]: p for p in rep["probes"]}
    assert by["eight arms"]["passed"] is False and by["an octopus"]["passed"] is True

def test_tifa_evaluate_no_probes_is_clean_pass():
    # a fully figurative caption decomposes to nothing depictable
    rep = _evaluator({}, [], threshold=0.5).evaluate("/o/p.png", "as proud as can be")
    assert rep["ok"] is True and rep["score"] == 1.0
    assert rep["probes"] == [] and rep["hints"] == []

def test_ensemble_tifa_attaches_report_and_targeted_hints():
    probes = [TifaProbe("eight arms", "count")]
    ens = EnsembleAuditor(_holistic(ok=True),
                          tifa=_evaluator({"eight arms": 0.05}, probes, threshold=0.5))
    v = ens.audit("/o/p.png", anchor="octopus", scene="reef", kind="concept",
                  caption="an octopus with eight arms")
    assert v["ok"] is False
    assert v["tifa"]["score"] == pytest.approx(0.05)
    assert any("eight arms" in i for i in v["issues"])

def test_ensemble_tifa_pass_keeps_ok_and_reports():
    probes = [TifaProbe("a fox", "object")]
    ens = EnsembleAuditor(_holistic(ok=True),
                          tifa=_evaluator({"a fox": 0.9}, probes, threshold=0.5))
    v = ens.audit("/o/p.png", anchor="fox", scene="forest", kind="concept",
                  caption="a fox")
    assert v["ok"] is True and v["tifa"]["score"] == pytest.approx(0.9)

def test_ensemble_tifa_skips_on_cover():
    probes = [TifaProbe("x", "object")]
    ens = EnsembleAuditor(_holistic(ok=True),
                          tifa=_evaluator({"x": 0.0}, probes, threshold=0.5))
    v = ens.audit("/o/c.png", anchor="", scene=None, kind="cover", caption="blurb")
    assert v["ok"] is True and "tifa" not in v

def test_factory_builds_tifa_member_and_reuses_vqa_scorer():
    cfg = _Cfg(qa_vqa=True, qa_vqa_threshold=0.15, qa_anatomy=False,
               qa_tifa=True, qa_tifa_threshold=0.4)
    aud = build_ensemble_auditor(
        cfg, judge_fn=lambda p: '{"ok": true}', vqa_score_fn=lambda p, c: 0.9,
        tifa_decompose_fn=lambda c: [TifaProbe("a fox", "object")])
    assert isinstance(aud, EnsembleAuditor)
    assert aud.tifa is not None and aud.tifa.threshold == 0.4
    # TIFA reuses the SAME VQA scorer instance — one daemon/model load, not two
    assert aud.tifa.scorer is aud.vqa

def test_factory_tifa_without_vqa_gate_still_gets_scorer():
    cfg = _Cfg(qa_vqa=False, qa_anatomy=False, qa_tifa=True, qa_tifa_threshold=0.4)
    aud = build_ensemble_auditor(
        cfg, judge_fn=lambda p: '{"ok": true}', vqa_score_fn=lambda p, c: 0.9,
        tifa_decompose_fn=lambda c: [TifaProbe("a fox", "object")])
    assert isinstance(aud, EnsembleAuditor)
    assert aud.tifa is not None and aud.vqa is None

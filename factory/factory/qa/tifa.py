"""TIFA-style caption decomposition for interpretability (research §WS1e).

VQAScore (§WS1a) gives ONE faithfulness number for a whole caption; when it is
low it cannot say *why*. TIFA (arXiv 2303.11897) instead breaks the caption into
per-fact probes — object / count / color / spatial / action — and checks each
one, so a reject can name the failing fact. Those failing facts become TARGETED
reroll hints (the art loop already appends `issues` to the next prompt) instead
of a vague "low fidelity", which is what makes TIFA worth running on top of the
scalar gate: it explains the rejection and steers the redraw.

Two injected pieces, both following the project's fake-able pattern so the unit
suite needs no LLM and no GPU:
  * a `decompose_fn(caption) -> [TifaProbe]` — the default shells to the Claude
    CLI to pull out the concrete, depictable facts (figurative phrases dropped);
  * a VQA `scorer` (the §WS1a `VQAScorer`, reused so only one model loads) that
    answers "Does this figure show {element}?" per probe.

The evaluator returns a report (mean score, per-probe pass/fail, failing
categories, targeted hints) — never raising on a weak page — so the ensemble can
both gate on the mean and surface the per-fact hints for the reroll and the
per-book provenance log.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# The canonical TIFA fact categories (arXiv 2303.11897). Free-form strings are
# tolerated from the decomposer, but these are what the prompt asks for.
CATEGORIES = ("object", "count", "color", "spatial", "action")


class TifaError(RuntimeError):
    pass


@dataclass(frozen=True)
class TifaProbe:
    """One concrete, depictable fact pulled from a caption. `element` is a short
    noun phrase scored as "Does this figure show {element}?"; `category` is one of
    CATEGORIES (kept verbatim even if the LLM returns something off-list)."""
    element: str
    category: str


def build_decompose_prompt(caption: str) -> str:
    cats = ", ".join(CATEGORIES)
    return f"""Break this children's picture-book caption into the CONCRETE,
DEPICTABLE facts a reader should be able to SEE in the illustration:

  "{caption}"

For each fact output a short noun phrase ("element") and its category, one of:
{cats}. Examples: an octopus -> object; eight arms -> count; a red fox -> color;
a fish under a rock -> spatial; wrapping its tail round the grass -> action.

Include ONLY facts that are visually checkable in a single still image. IGNORE
figurative, mood, or non-visual phrases ("as proud as can be", "never to roam",
"out of sight", "the largest of all") and incidental background scenery. If the
caption states nothing concretely depictable, return an empty list.

Return ONLY a JSON array of {{"category": "...", "element": "..."}} objects and
nothing else."""


def _strip_to_array(text: str) -> str:
    """Pull the JSON array out of an LLM reply — unwrap a ```/```json fence, else
    take the first '[' to the last ']' (the §WS1a `_strip_fences` is object-only)."""
    m = re.search(r"```(?:json)?\s*(\[.*\])\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    s, e = text.find("["), text.rfind("]")
    if s != -1 and e > s:
        return text[s:e + 1]
    return text


def parse_probes(raw: str) -> list[TifaProbe]:
    """Parse the decomposer's JSON array into probes, skipping malformed entries
    (missing keys / non-objects) so one bad row never sinks the whole page."""
    try:
        data = json.loads(_strip_to_array(raw))
    except json.JSONDecodeError as e:
        raise TifaError(f"TIFA decomposer did not return valid JSON: {e}") from e
    if not isinstance(data, list):
        raise TifaError(f"TIFA decomposer did not return a JSON array: {data!r}")
    probes: list[TifaProbe] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        element = item.get("element")
        category = item.get("category")
        if not element or not category:
            continue
        probes.append(TifaProbe(str(element).strip(), str(category).strip()))
    return probes


def _claude_decompose(caption: str) -> list[TifaProbe]:
    """Default adapter: decompose the caption via audit's Claude adapter, so it
    shares the pinned judge model (BOOKGEN_VISION_MODEL, Opus by default — the
    prompt was tuned against it), the transient-failure retries, and the
    usage-limit waits of every other build-critical Claude call."""
    from ..audit import _claude_vision, AuditError
    try:
        raw = _claude_vision(build_decompose_prompt(caption))
    except AuditError as e:
        raise TifaError(f"claude decompose failed: {e}") from e
    return parse_probes(raw)


class TifaDecomposer:
    """Caption -> [TifaProbe]. `decompose_fn` is injectable for tests; the default
    asks the Claude CLI for the concrete depictable facts."""

    def __init__(self, decompose_fn: Callable[[str], list[TifaProbe]] | None = None):
        self.decompose_fn = decompose_fn or _claude_decompose
        self._cache: dict[str, list[TifaProbe]] = {}

    def decompose(self, caption: str) -> list[TifaProbe]:
        # A page's caption is re-audited across reroll attempts; decomposition
        # depends only on the caption, so cache it to avoid redundant LLM calls.
        if caption not in self._cache:
            self._cache[caption] = list(self.decompose_fn(caption))
        return list(self._cache[caption])


class TifaEvaluator:
    """Score each decomposed probe with the VQA model and report per-fact results.

    A probe passes when its VQA score >= `threshold`; the overall verdict gates on
    the MEAN probe score (so one stubborn fact does not sink an otherwise-faithful
    page, matching the pipeline's "flag best & continue" stance). A caption with no
    depictable facts is a clean pass (score 1.0, no hints)."""

    def __init__(self, decomposer: TifaDecomposer, scorer, *, threshold: float = 0.4):
        self.decomposer = decomposer
        self.scorer = scorer
        self.threshold = threshold

    def _hint(self, probe: TifaProbe) -> str:
        return (f"unclear {probe.category}: the picture does not clearly show "
                f"\"{probe.element}\" — make it unmistakable")

    def evaluate(self, image_path, caption: str) -> dict:
        probes = self.decomposer.decompose(caption)
        if not probes:
            return {"ok": True, "score": 1.0, "probes": [], "failing": [],
                    "hints": []}
        results, hints, failing = [], [], []
        total = 0.0
        for probe in probes:
            s = float(self.scorer.score(image_path, probe.element))
            passed = s >= self.threshold
            total += s
            results.append({"element": probe.element, "category": probe.category,
                            "score": s, "passed": passed})
            if not passed:
                hints.append(self._hint(probe))
                if probe.category not in failing:
                    failing.append(probe.category)
        score = total / len(probes)
        return {"ok": score >= self.threshold, "score": score, "probes": results,
                "failing": failing, "hints": hints}

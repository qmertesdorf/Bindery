"""Best-of-N candidate selection (research §WS1b).

Generating 3-9 candidates per page and picking the best one raises the floor
quality and bounds reroll cost — a weak first draw no longer forces a fresh-seed
reroll if a sibling candidate is good. N is configured per book (default 1 =
today's single-candidate path).

Two selectors:
- `BestOfNSelector` ranks by **VQAScore** (image↔caption FIDELITY). It reliably
  finds the candidate that most clearly depicts the caption — but fidelity is not
  taste: it over-rewards the boldest, highest-contrast, most literal render and
  quietly drifts a soft watercolour book glossy/hard.
- `ClaudeBestOfNSelector` picks the **literal best** by a Claude-vision comparative
  judgement against a house-style rubric (soft fuzzy watercolour, charming face +
  TRUE-species body, cohesion with an anchor image). Optionally pre-filtered by a
  VQA floor (hybrid) so the taste-judge never wastes a look on a wrong-subject dud.
  ([[concept-scenes-underwater-fullbleed]])
"""
from __future__ import annotations
import re
from pathlib import Path


class BestOfNSelector:
    """Pick the highest-VQAScore candidate. Wraps a VQAScorer; with no caption
    (or a single candidate) there is nothing to score, so it returns the first
    candidate unchanged — keeping caption-free pages on today's behaviour."""

    def __init__(self, vqa, free_fn=None):
        self.vqa = vqa
        # Optional callback invoked once before scoring a batch — used to evict the
        # renderer's VRAM (ComfyUI /free) so the separate-process VQA model fits on
        # a 16GB card. None = no-op (tests, or when renderer/scorer don't contend).
        self.free_fn = free_fn

    def select(self, candidates, caption: str | None):
        candidates = [Path(c) for c in candidates]
        if not candidates:
            raise ValueError("BestOfNSelector.select needs at least one candidate")
        if len(candidates) == 1 or not caption:
            return candidates[0]
        if self.free_fn is not None:
            self.free_fn()   # free the renderer's VRAM before the VQA model loads
        scored = [(self.vqa.score(c, caption), c) for c in candidates]
        # Highest score wins; ties keep the earlier (lower-seed) candidate stable.
        best = max(range(len(scored)), key=lambda i: scored[i][0])
        return scored[best][1]


def build_select_prompt(candidates, caption, *, subject=None, anchor_path=None) -> str:
    """Comparative art-director prompt: name every candidate image by path and ask
    for the single best PICTURE-BOOK illustration on a SOFT-WATERCOLOUR rubric that
    deliberately down-weights the glossy/hard look a fidelity scorer over-rewards."""
    lines = "\n".join(f"  {i + 1}. {Path(c).resolve()}"
                      for i, c in enumerate(candidates))
    subj = subject or "the described subject"
    anchor = ""
    if anchor_path:
        anchor = (f"\n\nHOUSE-STYLE ANCHOR (the look + quality to match — this is NOT a "
                  f"candidate): {Path(anchor_path).resolve()}\nThe winner must read as the "
                  f"SAME illustrator / same book as this anchor.")
    return f"""You are the ART DIRECTOR choosing the single BEST illustration for ONE \
spread of a soft, hand-painted WATERCOLOUR children's picture book. The spread should \
depict: "{caption}".

OPEN AND LOOK AT each candidate image:
{lines}{anchor}

STEP 1 — DISQUALIFY FOR PRINT (this is a hard gate, apply it FIRST). A full-bleed page
must run its painting off ALL FOUR edges. RULE OUT any candidate whose painting fades to
a white/cream unpainted-paper border, a feathered or soft vignette, or sits on a blank
margin — these print as ugly white slivers at the trim cut. Soft BRUSHWORK inside the
picture is good; a soft unpainted EDGE that fades to paper is a DISQUALIFIER. Be strict:
if you can see paper/white at any edge or corner, it is disqualified.

STEP 2 — Among ONLY the candidates that survive Step 1, pick the single best picture-book
illustration, in this priority:
  a. CORRECT SUBJECT — clearly a {subj} with its TRUE-species body shape and proportions
     (NOT a generic chubby round ball/blob) and a sweet, friendly, gently-smiling face.
  b. HOUSE STYLE — soft, loose, hand-painted watercolour with gentle visible brushwork,
     cohesive with the anchor. STRONGLY prefer this over any glossy, hard-outlined,
     high-contrast, over-saturated, airbrushed, or CGI/3D-looking candidate.
  c. CLEAN — no text/letters/signature/watermark; no anatomy errors; no stray creatures.
  d. APPEAL — warm, charming, well-composed; the one a parent would pick off the shelf.
  Tie-break toward the SOFTER, gentler, more painterly one.

If (and only if) EVERY candidate is disqualified in Step 1, pick the one with the
SMALLEST, least-noticeable paper border.

Reply with ONLY one line, no other text: BEST: <number>"""


def parse_best(raw: str, n: int) -> int:
    """Parse 'BEST: <1-based number>' into a 0-based index; default 0 on anything
    unparseable or out of range (so a flaky judge reply never crashes a build)."""
    m = re.search(r"BEST:\s*(\d+)", raw or "", re.IGNORECASE)
    if m:
        i = int(m.group(1)) - 1
        if 0 <= i < n:
            return i
    return 0


class ClaudeBestOfNSelector:
    """Pick the LITERAL best candidate by Claude-vision comparative judgement (taste),
    not a fidelity metric. `judge_fn(prompt)->str` is the vision call (real = `claude
    -p`, reads the image paths named in the prompt). Optional `vqa` enables a HYBRID
    pre-filter: drop candidates below `vqa_floor` (wrong-subject duds) before the
    taste pick, so the judge only chooses among faithful candidates. `anchor_path`
    and `subject` are set per-page by the caller to sharpen the rubric."""

    def __init__(self, judge_fn, *, vqa=None, vqa_floor: float = 0.10,
                 anchor_path=None, subject=None, free_fn=None):
        self.judge_fn = judge_fn
        self.vqa = vqa
        self.vqa_floor = vqa_floor
        self.anchor_path = anchor_path
        self.subject = subject
        self.free_fn = free_fn

    def select(self, candidates, caption: str | None):
        candidates = [Path(c) for c in candidates]
        if not candidates:
            raise ValueError("ClaudeBestOfNSelector.select needs at least one candidate")
        if len(candidates) == 1 or not caption:
            return candidates[0]
        pool = candidates
        if self.vqa is not None:   # HYBRID: drop wrong-subject duds before the taste pick
            if self.free_fn is not None:
                self.free_fn()
            scored = [(self.vqa.score(c, caption), c) for c in pool]
            survivors = [c for s, c in scored if s >= self.vqa_floor]
            # never empty — if everything is below the floor, keep the single best
            pool = survivors or [max(scored, key=lambda sc: sc[0])[1]]
        if len(pool) == 1:
            return pool[0]
        raw = self.judge_fn(build_select_prompt(
            pool, caption, subject=self.subject, anchor_path=self.anchor_path))
        return pool[parse_best(raw, len(pool))]

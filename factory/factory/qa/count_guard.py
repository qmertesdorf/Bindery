"""Deterministic exact-count guard (research §WS-count).

VLMs cannot count reliably — and worse, when an animal is drawn with the WRONG
number of parts (a six-arm starfish, a five-legged mammal) the judge tends to
report the CANONICAL count it *expects* rather than what is actually on the page
(animals-with-extra-legs accuracy ~2%; arXiv "VLMs are Biased"). So the holistic
auditor's "count the arms" instruction, even ensembled over several passes, lets
wrong counts slip through — exactly the 6-arm starfish that survived 3x vision
([[next-pipeline-improvements]] [[catch-defects-with-guards]]).

This guard moves the DECISION into deterministic code. It extracts every explicit
count claim already written in the page's scene/caption (the author writes them
species-correct), then for each one runs an ISOLATED, forced-enumeration count
probe — one part at a time, with NO expected number stated so the model cannot
anchor — and compares the returned integer EXACTLY. A mismatch is a hard reject.
Perception still needs a vision call, but the claim extraction and the integer
comparison are pure code, and isolating + enumerating a single part is the
documented way to get the most reliable count out of a VLM.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Callable

from ..audit import _claude_vision

# Anatomy-defining nouns worth counting. Spots/stripes are deliberately excluded:
# uncountable in practice and not defect-critical, so probing them only invites
# false rejects.
# NOTE: longer/compound nouns must precede their prefixes in the alternation, or
# 'eyes?' would match inside 'eye-stalks' and mislabel the claim.
_PART_PATTERN = (
    r"eye-?stalks?|arms?|legs?|eyes?|fins?|tails?|wings?|"
    r"antennae|antennas?|antenna|tentacles?|ears?|horns?|tusks?|flippers?|points?")

# Parts that anatomically come in pairs or more, so a stated count of exactly 1 is a
# pose ("one leg lifted"), not an anatomical total. 'eyes' is deliberately EXCLUDED:
# a profile view legitimately shows one eye, and a crab's eye-stalk carries one eye
# each — both real count-of-one claims. 'fins'/'horns'/'tusks'/'tails' are excluded
# too (one dorsal fin, one horn, a narwhal's single tusk, one tail are valid totals).
_PAIRED_PARTS = {"arms", "legs", "wings", "ears", "flippers", "tentacles"}

_NUMBER_WORDS = {
    "one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}

# <number> [up to 2 adjectives] <part-noun>, e.g. "eight curly arms",
# "two upper eye-stalks", "5 arms", "a single paddle tail".
_CLAIM_RE = re.compile(
    r"\b(?P<num>\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\b"
    r"(?:\s+\w+){0,2}?\s+"
    r"(?P<part>" + _PART_PATTERN + r")\b",
    re.IGNORECASE)


def _canon(noun: str) -> str:
    """Normalise a matched part noun to a single canonical plural label so
    'tail'/'tails', 'eyestalk'/'eye-stalks', 'antenna'/'antennae' collapse."""
    n = noun.lower().replace("eyestalk", "eye-stalk")
    if n.startswith("antenna"):
        return "antennae"
    if n.endswith("ae"):
        return n
    return n if n.endswith("s") else n + "s"


def extract_count_claims(scene: str | None,
                         caption: str | None = None) -> list[tuple[str, int]]:
    """Pull explicit <count, body-part> claims out of the page's scene + caption.

    Pure code. If the SAME part is given two different numbers (e.g. an author's
    'five arms, not six arms'), it is AMBIGUOUS and dropped — never a false reject.
    Returns a sorted list so the probe order is deterministic."""
    text = " ".join(t for t in (scene, caption) if t)
    found: dict[str, int] = {}
    conflict: set[str] = set()
    for m in _CLAIM_RE.finditer(text):
        part = _canon(m.group("part"))
        num = m.group("num").lower()
        n = _NUMBER_WORDS.get(num)
        if n is None:
            n = int(num)
        if part in found and found[part] != n:
            conflict.add(part)
        else:
            found.setdefault(part, n)
    for p in conflict:
        found.pop(p, None)
    # A count of 1 for a part that anatomically comes in pairs or more is never a
    # total — it is a POSE reference ("one leg lifted", "one wing spread", "one paw
    # raised") that would false-reject every correct render (live defect: the
    # one-legged-flamingo pose, wild-golden-world 2026-07-07). Drop it. Genuinely-
    # singular parts (a tail, a horn, a narwhal's one tusk) keep their count of 1.
    for p in _PAIRED_PARTS:
        if found.get(p) == 1:
            found.pop(p, None)
    return sorted(found.items())


def build_count_prompt(part: str, image_path: Path) -> str:
    """Isolated, forced-enumeration count probe for ONE part. States no expected
    number (anchoring on the canonical count is the very bias we are dodging)."""
    return f"""Read the image at {image_path}. Look ONLY at the main subject.
Count its {part}: point to and NUMBER each one (1, 2, 3, ...) as you go right
around the subject. Do NOT assume the usual number for this kind of creature —
count exactly what is drawn, including any extra, missing, or malformed ones.
Reply with ONLY the final integer, and nothing else."""


def _parse_int(raw: str) -> int | None:
    m = re.search(r"-?\d+", raw)
    return int(m.group()) if m else None


def _claude_count(part: str, image_path: Path) -> int | None:
    return _parse_int(_claude_vision(build_count_prompt(part, Path(image_path))))


class CountGuard:
    """Deterministic exact-count gate. `count_fn(part, image_path) -> int | None`
    returns how many of `part` are visible (None when it can't tell — which never
    fabricates a reject). Defaults to an isolated Claude vision probe."""

    def __init__(self, count_fn: Callable[[str, Path], int | None] | None = None):
        self.count_fn = count_fn or _claude_count

    def check(self, image_path, *, scene: str | None,
              caption: str | None = None) -> list[str]:
        issues: list[str] = []
        for part, expected in extract_count_claims(scene, caption):
            got = self.count_fn(part, Path(image_path))
            if got is not None and int(got) != expected:
                issues.append(
                    f"wrong {part} count: scene/caption says {expected}, "
                    f"image shows {got}")
        return issues

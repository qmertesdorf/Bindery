"""WS6a — dependency-free readability scoring + a build-time guard for kids' text.

Verified research (2026-06-21): LLMs are unreliable at hitting a target grade/Lexile
on their own, so we do NOT trust the model's self-leveling — we measure the generated
kids' text with an external Flesch–Kincaid check and fail the build if it reads too
hard for an early reader. Pure functions, no I/O, no third-party deps (a tiny syllable
heuristic), so it runs in the GPU-free test venv.

Caveat: Flesch–Kincaid is noisy on very short, rhyming text; we aggregate the whole
book into one corpus and use a generous, configurable grade ceiling so normal whimsy
passes and only genuinely over-complex text trips the guard."""
from __future__ import annotations
import re

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_VOWELS = "aeiouy"


class ReadabilityError(ValueError):
    pass


def count_syllables(word: str) -> int:
    """Heuristic syllable count: vowel groups, minus a silent trailing 'e', floor 1.
    Not perfect, but stable and good enough to flag too-complex kids' text."""
    w = word.lower().strip("'’-")
    if not w:
        return 0
    groups = 0
    prev_vowel = False
    for ch in w:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            groups += 1
        prev_vowel = is_vowel
    # Drop a silent trailing 'e' (e.g. "make"→1), but NOT a consonant+"le" ending
    # where the "le" is its own syllable (e.g. "apple"→2, "table"→2).
    if w.endswith("e") and groups > 1:
        consonant_le = w.endswith("le") and len(w) >= 3 and w[-3] not in _VOWELS
        if not consonant_le:
            groups -= 1
    return max(1, groups)


def _counts(text: str) -> tuple[int, int, int]:
    """Return (sentences, words, syllables) for `text`. Sentences = terminal
    punctuation count, falling back to non-empty lines (kids' couplets rarely end
    in a period), then to 1 — never zero, so the formulas don't divide by zero."""
    words = _WORD.findall(text)
    n_words = len(words)
    n_syll = sum(count_syllables(w) for w in words)
    terminals = len(re.findall(r"[.!?]+", text))
    if terminals == 0:
        terminals = len([ln for ln in text.splitlines() if ln.strip()])
    n_sent = max(1, terminals)
    return n_sent, n_words, n_syll


def flesch_reading_ease(text: str) -> float:
    """Higher = easier (90–100 ≈ very easy / 5th grade). Empty text → 100.0."""
    s, w, syl = _counts(text)
    if w == 0:
        return 100.0
    return round(206.835 - 1.015 * (w / s) - 84.6 * (syl / w), 2)


def flesch_kincaid_grade(text: str) -> float:
    """US grade level needed to read `text`. Empty text → 0.0."""
    s, w, syl = _counts(text)
    if w == 0:
        return 0.0
    return round(0.39 * (w / s) + 11.8 * (syl / w) - 15.59, 2)


def kids_text(content: dict) -> list[tuple[str, str]]:
    """The child-facing strings of a picture/concept book as (label, text) pairs:
    each page's read-aloud `text`, plus the dedication and closing. Skips empties."""
    out = []
    for i, pg in enumerate(content.get("pages", []), 1):
        t = str(pg.get("text", "")).strip()
        if t:
            out.append((f"page {i}", t))
    for key in ("dedication", "closing"):
        v = str(content.get(key, "")).strip()
        if v:
            out.append((key, v))
    return out


def readability_report(content: dict) -> dict:
    """Aggregate FK grade + reading ease over the whole book's kids' text, plus the
    single hardest page (the one a fix should target)."""
    pairs = kids_text(content)
    corpus = "\n".join(t for _, t in pairs)
    per = [(label, flesch_kincaid_grade(t)) for label, t in pairs]
    hardest = max(per, key=lambda lt: lt[1], default=(None, 0.0))
    return {
        "grade": flesch_kincaid_grade(corpus),
        "reading_ease": flesch_reading_ease(corpus),
        "hardest": {"where": hardest[0], "grade": hardest[1]},
        "per_item": per,
    }


def verify_readability(content: dict, max_grade: float) -> dict:
    """Build-time guard: fail if the book's kids' text reads above `max_grade`
    (US grade level). Returns the report on success so callers can log it. A
    non-positive `max_grade` disables the gate (returns the report, never raises)."""
    report = readability_report(content)
    if max_grade and max_grade > 0 and report["grade"] > max_grade:
        h = report["hardest"]
        raise ReadabilityError(
            f"Kids' text reads at grade {report['grade']} (Flesch–Kincaid), above "
            f"the grade {max_grade:g} ceiling for early readers; hardest is "
            f"{h['where']} at grade {h['grade']}. Simplify the wording (shorter "
            f"words/sentences) or raise max_reading_grade if intentional.")
    return report

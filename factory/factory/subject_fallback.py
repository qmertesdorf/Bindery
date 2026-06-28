"""Auto-subject-fallback for the concept line: when a page's subject can't be
rendered cleanly within the audit budget, pick a NEW on-theme subject to draw
instead. Interchangeable-by-design (the book is "ocean animals", not "this animal"),
so a stubborn subject (the manatee's single paddle tail, ~24 gated attempts) is
swapped rather than shipped flagged ([[catch-defects-with-guards]]).

The chooser is an injected `generate_fn(prompt) -> str` (real impl shells `claude -p`,
mirroring content generation), so this is unit-testable with no LLM."""
from __future__ import annotations
from typing import Callable


class SubjectFallbackError(Exception):
    """The LLM could not offer a NEW, non-duplicate subject within the retry budget;
    the caller should flag the page and stop trying to swap it."""


def _norm(s: str) -> str:
    """Normalise a subject for duplicate comparison: lowercase, trim, drop wrapping
    quotes and a trailing period."""
    return s.strip().strip('"').strip("'").rstrip(".").strip().lower()


def build_subject_prompt(theme: str, used: list[str], failed: str) -> str:
    used_str = ", ".join(used) if used else "(none yet)"
    return f"""You are choosing ONE replacement subject for a single spread of a \
character-free children's picture book about {theme}, for early readers (around age 5).

The previous subject "{failed}" could not be illustrated cleanly and must be replaced.

Pick a NEW subject that is:
- clearly on-theme for "{theme}";
- simple and clean to draw in a soft kawaii storybook style — a single clear subject
  with a simple, rounded, friendly body;
- NOT already used in this book. Already used (do NOT repeat any of these): {used_str};
- NOT "{failed}".
Use your best judgment to AVOID subjects that are hard to render correctly: avoid
flat / ray-like bodies (rays, skates, flatfish), long eel-like bodies, and animals
with odd or easily-mangled tails or limb counts. Prefer simple, rounded, friendly
animals.

Return ONLY the subject as a short noun phrase (for example: "a sea turtle"), and
nothing else."""


def suggest_subject(generate_fn: Callable[[str], str], theme: str,
                    used: list[str], failed: str, *, max_retries: int = 2) -> str:
    """Ask `generate_fn` for a replacement subject on `theme`, not in `used` and not
    `failed`. Re-asks up to `max_retries` extra times if it returns a duplicate;
    raises SubjectFallbackError if it never offers something new."""
    blocked = {_norm(u) for u in used} | {_norm(failed)}
    for _ in range(max_retries + 1):
        raw = generate_fn(build_subject_prompt(theme, used, failed))
        first = next((ln.strip() for ln in (raw or "").splitlines() if ln.strip()), "")
        cand = first.strip().strip('"').strip("'").rstrip(".").strip()
        if cand and _norm(cand) not in blocked:
            return cand
    raise SubjectFallbackError(
        f"no new subject offered for theme {theme!r} (failed={failed!r})")

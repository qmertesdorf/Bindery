"""Auto-subject-fallback for the concept line: when a page's subject can't be
rendered cleanly within the audit budget, pick a NEW on-theme subject to draw
instead. Interchangeable-by-design (the book is "ocean animals", not "this animal"),
so a stubborn subject (the manatee's single paddle tail, ~24 gated attempts) is
swapped rather than shipped flagged ([[catch-defects-with-guards]]).

The chooser is an injected `generate_fn(prompt) -> str` (real impl shells `claude -p`,
mirroring content generation), so this is unit-testable with no LLM."""
from __future__ import annotations
import re
from typing import Callable


class SubjectFallbackError(Exception):
    """The LLM could not offer a NEW, non-duplicate subject within the retry budget;
    the caller should flag the page and stop trying to swap it."""


# Words that describe an animal but don't IDENTIFY a distinct species — colours,
# sizes, shapes, textures, life-stages, habitats, articles. They're stripped before
# comparing a candidate against the book's existing subjects, so a near-duplicate is
# caught by its shared animal word: "a round smooth-bodied harbor seal" vs a "harbor
# seal pup", or "a sea turtle hatchling" vs a "green sea turtle". The LLM keeps
# proposing these despite the prompt, so we GUARD it in code ([[catch-defects-with-guards]]).
_GENERIC = {
    "the", "and", "with", "for", "its", "his", "her", "one", "single",
    "baby", "juvenile", "young", "little", "tiny", "small", "big", "large", "giant",
    "round", "smooth", "bodied", "body", "soft", "gentle", "friendly", "fluffy",
    "plump", "cute", "adorable", "sweet", "bright", "happy", "playful", "curious",
    "calm", "fat", "chubby", "long", "short", "tall", "old",
    "pup", "pups", "calf", "calves", "hatchling", "chick", "fry", "juvenile",
    "blue", "green", "grey", "gray", "red", "orange", "yellow", "white", "black",
    "brown", "silver", "silvery", "golden", "pink", "purple", "pale", "dark",
    "spotted", "striped", "patterned", "colourful", "colorful",
    "sea", "ocean", "oceanic", "water", "watery", "deep", "shallow", "marine",
    "aquatic", "harbor", "harbour", "reef", "coral", "tide", "tidal", "pool",
    "arctic", "polar", "shore", "shallows", "sandy", "rocky", "fish",
}


# Species the chooser keeps proposing despite the prompt that either (a) are
# obscure/subspecies whose signature features the image model collapses into a
# common look-alike, so they fail the audit (a pangolin's scales, a serval's short
# tail, a secretary bird's quill crest — all seen 8/8-rejected), or (b) read as
# scary/menacing and break the gentle "never scary" brand. Enforced in code because
# prompt guidance alone did not stop them ([[catch-defects-with-guards]]). Matched by
# the candidate's species-identifying tokens, so "a giant pangolin" is still caught.
_HARD_OR_OFFBRAND = {
    # obscure / Flux-hard (signature collapses to a look-alike)
    "pangolin", "serval", "genet", "okapi", "aardvark", "aardwolf", "caracal",
    "civet", "hyrax", "gerenuk", "klipspringer", "oribi", "bushbaby", "galago",
    "colobus", "springhare", "dik", "duiker", "bongo", "sitatunga", "quagga",
    # menacing / off-brand for a gentle picture book
    "hyena", "jackal", "vulture", "marabou",
}


def _singular(t: str) -> str:
    """Crude singulariser so a plural subject and its singular match ("dolphins" vs
    "a dolphin", "penguins" vs "a penguin"). Leaves Latin-ish -us/-is/-ss words alone
    (walrus, octopus) and only trims a plain trailing -s."""
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith(("ss", "us", "is")) and len(t) > 3:
        return t[:-1]
    return t


def _content_tokens(s: str) -> set[str]:
    """The species-identifying words of a subject phrase (lowercased alpha tokens of
    length >= 3, minus the generic descriptors above, singularised). Two subjects that
    share any of these are treated as the same/related animal."""
    return {_singular(t) for t in re.findall(r"[a-z]+", s.lower())
            if len(t) >= 3 and t not in _GENERIC}


def _norm(s: str) -> str:
    """Normalise a subject for duplicate comparison: lowercase, trim, drop wrapping
    quotes and a trailing period."""
    return s.strip().strip('"').strip("'").rstrip(".").strip().lower()


# A real subject is a short noun phrase ("a green sea turtle" = 4 words). The chooser
# (claude -p) sometimes reasons out loud or adds preamble despite the prompt; cap the
# length so a rambling sentence is never accepted as a "subject".
_MAX_SUBJECT_WORDS = 6


def _extract_subject(raw: str) -> str:
    """Pull a clean short subject phrase from the LLM reply, robust to reasoning/
    preamble: prefer the LAST line that looks like a short noun phrase (the actual
    answer usually comes last), stripping wrapping quotes/bullets/punctuation. Falls
    back to the last non-empty line (which the caller's word-count guard then rejects
    if it's a paragraph)."""
    lines = [ln.strip().strip('"').strip("'").lstrip("-*•").strip().rstrip(".").strip()
             for ln in (raw or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln and not ln.endswith(":") and 1 <= len(ln.split()) <= _MAX_SUBJECT_WORDS:
            return ln
    return lines[-1] if lines else ""


def build_subject_prompt(theme: str, used: list[str], failed: str) -> str:
    used_str = ", ".join(used) if used else "(none yet)"
    return f"""You are choosing ONE replacement subject for a single spread of a \
character-free children's picture book about {theme}, for early readers (around age 5).

The previous subject "{failed}" could not be illustrated cleanly and must be replaced.

Pick a NEW subject that is:
- clearly on-theme for "{theme}";
- simple and clean to draw in a soft kawaii storybook style — a single clear subject
  with a simple, rounded, friendly body;
- a DIFFERENT KIND of animal from every one already in the book — NOT the same species,
  NOT a baby / juvenile / life-stage or variety of one already used, and NOT a close
  relative or look-alike cousin of one already used (e.g. if a sea turtle is already in
  the book, do NOT pick a turtle hatchling or another turtle; if several whales or
  dolphins are used, prefer a non-cetacean). This book is a tour of DISTINCT animals, so
  each spread must teach a genuinely new one. Already used — avoid these AND anything
  closely related to them: {used_str};
- NOT "{failed}";
- a natural fit for the book's established look and setting: the same bright, friendly,
  sunlit daytime palette as the rest of the book. Do NOT pick an animal whose natural
  scene would force a night-time, dark, gloomy or strongly off-palette setting.
- GENTLE and friendly, never a scary, menacing, fearsome or intimidating animal: this
  is a soft, sweet, "never scary" picture book, so avoid animals a young child would
  find frightening (a hyena, a jackal, a vulture, a wild dog and the like), even if
  they are iconic. A cute baby of a big animal is fine; a fearsome-looking one is not.
Use your best judgment to AVOID subjects that are hard to render correctly: avoid
flat / ray-like bodies (rays, skates, flatfish), long eel-like bodies (eels), animals
with curling or prehensile tails (seahorses, pipefish), hard-shelled crustaceans
(crabs, lobsters, shrimp), snails and slugs, and any animal with odd or easily-mangled
tails or limb counts. Pick a WELL-KNOWN, iconic animal that every child recognizes
and that illustrators draw constantly — NEVER an obscure or lesser-known species
(a serval, a genet, an okapi, a dik-dik and the like): the image model barely knows
those and paints a generic look-alike whose signature features fail the audit.
Prefer simple, plump, rounded, friendly animals (a seal, a penguin, a puffin, an
otter and the like).

Output ONLY the subject as a short noun phrase of 2 to 5 words on a SINGLE line — no
explanation, no reasoning, no preamble, no extra words and no punctuation. For example:
a sea turtle"""


def suggest_subject(generate_fn: Callable[[str], str], theme: str,
                    used: list[str], failed: str, *, max_retries: int = 2) -> str:
    """Ask `generate_fn` for a replacement subject on `theme`, distinct from every
    subject in `used` and from `failed`. Re-asks up to `max_retries` extra times if it
    returns an exact OR near duplicate (shares a species-identifying word with an
    existing subject — the LLM keeps proposing relatives/life-stages despite the
    prompt, so we reject them in code); raises SubjectFallbackError if it never offers
    a genuinely new animal."""
    blocked = {_norm(u) for u in used} | {_norm(failed)}
    # Species words already spoken for (each used subject + the failed one), so a
    # candidate that reuses any of them is a near-duplicate and gets re-asked.
    taken_tokens = [_content_tokens(s) for s in list(used) + [failed]]
    for _ in range(max_retries + 1):
        raw = generate_fn(build_subject_prompt(theme, used, failed))
        cand = _extract_subject(raw)
        # Reject empties, a rambling paragraph (the model reasoned instead of
        # answering), or an exact duplicate — and re-ask.
        if not cand or len(cand.split()) > _MAX_SUBJECT_WORDS or _norm(cand) in blocked:
            continue
        cand_tokens = _content_tokens(cand)
        if cand_tokens and any(cand_tokens & t for t in taken_tokens):
            continue  # near-duplicate: shares an animal word with an existing subject
        if cand_tokens & _HARD_OR_OFFBRAND:
            continue  # obscure/Flux-hard or menacing: re-ask (prompt alone didn't stop it)
        return cand
    raise SubjectFallbackError(
        f"no new subject offered for theme {theme!r} (failed={failed!r})")

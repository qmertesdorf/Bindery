"""Marketing copy derived from a BookConfig — back-cover blurb, Amazon listing
description, and KDP keywords.

Two audiences, two lengths (WS6b):

* ``book_blurb`` — the SHORT back-cover line. It must fit the printed cover, so
  the cover-layout guards in ``cover.py`` constrain its length. Keep it tight.
* ``listing_description`` / ``listing_keywords`` — the Amazon listing. Amazon's
  Rufus shopping assistant is a semantic LLM/RAG layer, so this copy is written
  for natural-language buyer *intent* (who it's for, the occasion, the questions
  a shopper asks Rufus) — NOT keyword stuffing. ``verify_listing_copy`` guards
  against regressing into a stuffed, KDP-invalid listing.
"""
from __future__ import annotations
from .config import BookConfig

KDP_KEYWORD_MAX = 50   # KDP hard limit: each of the 7 keyword fields ≤ 50 chars
KDP_KEYWORD_SLOTS = 7


class ListingCopyError(ValueError):
    """Raised when generated listing copy would be invalid or keyword-stuffed."""


def book_blurb(cfg: BookConfig) -> str:
    """One-paragraph back-cover / cover blurb. SHORT — it prints on the cover."""
    if cfg.book_type == "standard":
        return cfg.blurb or cfg.synopsis
    if cfg.book_type == "picture":
        return cfg.blurb or (
            f"A gentle, beautifully illustrated picture book for a little one saying "
            f"goodbye to a beloved {cfg.pet_kind}. Through a child's eyes and soft, "
            f"tender pictures, it holds space for big feelings and helps a family "
            f"remember {cfg.pet_name} with love. A comforting read-aloud and a "
            f"caring gift.")
    if cfg.book_type == "concept":
        return cfg.blurb or (
            f"A gentle, beautifully illustrated picture book that takes early readers "
            f"on a tour of {cfg.subject}. Soft watercolours and simple, read-aloud "
            f"lines make every page a warm discovery for curious little ones.")
    return (f"A gentle, guided journal to help you grieve and remember your beloved "
            f"{cfg.pet_kind}. Undated reflective prompts, memory pages, and milestone "
            f"reflections give you a private space to process loss at your own pace. "
            f"A comforting keepsake and a thoughtful gift.")


def _intent_paragraph(cfg: BookConfig) -> str:
    """The Rufus-era body: natural-language sentences that answer the questions a
    shopper would ask ("a first book about X?", "a gift for a grieving child?",
    "a calming bedtime read?"). Buyer intent woven into prose, not a keyword list."""
    if cfg.book_type == "concept":
        subj = cfg.subject
        return (
            f"Perfect for toddlers, preschoolers, and early readers, it's a calming "
            f"book to share at bedtime or quiet time and a thoughtful gift for any "
            f"child who is curious about {subj}. The simple, read-aloud rhythm makes "
            f"it easy for grown-ups and little ones to enjoy together, while the soft "
            f"watercolour illustrations hold a young child's attention without "
            f"overwhelming detail. If you're looking for a gentle first book about "
            f"{subj} — one that builds early curiosity about the natural world and a "
            f"love of reading — this is made to be read again and again.")
    if cfg.book_type == "picture":
        return (
            f"Written for families saying goodbye to a beloved {cfg.pet_kind}, it's a "
            f"gentle, read-aloud story to share with a grieving child — whether you "
            f"are explaining the loss of a pet for the first time or looking for a "
            f"comforting way to remember {cfg.pet_name} together. The tender pictures "
            f"and simple words help a little one name big feelings, making this a "
            f"caring sympathy gift for a child or family coping with the death of a "
            f"pet.")
    if cfg.book_type == "journal":
        return (
            f"Whether you have just lost your {cfg.pet_kind} or are working through "
            f"grief weeks or months later, the undated, reflective prompts give you a "
            f"private space to remember, cry, and heal at your own pace. It makes a "
            f"heartfelt sympathy gift for someone grieving a pet and a lasting "
            f"keepsake for the memories of a companion who meant the world to you.")
    return ""   # standard: the author's synopsis is the listing copy on its own


def listing_description(cfg: BookConfig) -> str:
    """The Amazon listing description (Rufus-optimised). Leads with the back-cover
    hook, then expands into natural-language buyer intent. Standard read-through
    books keep the author-supplied synopsis/blurb verbatim."""
    hook = book_blurb(cfg)
    body = _intent_paragraph(cfg)
    return f"{hook}\n\n{body}".strip() if body else hook


def _keyword_subject(cfg: BookConfig) -> str:
    """A compact noun phrase for keyword slots. Concept subjects are written for the
    page captions ("ocean animals and the watery places they live") and are too long
    for a 50-char KDP keyword field — clipping them leaves a dangling "...and the".
    Truncate at the first grammatical connector to keep the searchable head noun."""
    subj = cfg.subject
    for sep in (" and ", " — ", " - ", ", ", " that ", " which ", " they ", " with "):
        i = subj.find(sep)
        if i != -1:
            subj = subj[:i]
    return subj.strip()


def listing_keywords(cfg: BookConfig) -> list[str]:
    """The 7 KDP keyword phrases — written as natural-language shopper intents
    ("calming bedtime book about ocean animals") rather than stuffed nouns. The
    publisher still refines these against live Amazon search before upload."""
    if cfg.book_type == "concept":
        subj = _keyword_subject(cfg)
        kws = [f"picture book about {subj} for kids",
               f"toddler book about {subj}",
               f"calming bedtime book about {subj}",
               "read aloud book for preschoolers",
               "first nature book for curious toddlers",
               "early learning gift for young children",
               "soft illustrated story for quiet time"]
    elif cfg.book_type == "picture":
        kind = cfg.pet_kind
        kws = [f"book to help a child with {kind} loss",
               f"explaining the death of a pet to kids",
               "comforting story about losing a pet",
               "grief picture book for young children",
               "sympathy gift for a grieving child",
               f"saying goodbye to a {kind} for kids",
               "rainbow bridge book for children"]
    elif cfg.book_type == "standard":
        # Seed from the title + grief intents; refined against live search pre-upload.
        kws = [cfg.title.lower(),
               "comforting book about grief and loss",
               "support for coping with the loss",
               "book to read while grieving",
               "thoughtful sympathy and memorial gift",
               "gentle companion through bereavement",
               "finding peace after a loss"]
    else:   # journal
        kind = cfg.pet_kind
        kws = [f"grief journal for the loss of a {kind}",
               f"memorial keepsake for a beloved {kind}",
               "guided pet bereavement journal",
               "sympathy gift for someone grieving a pet",
               f"remembering a {kind} who passed away",
               "undated prompts for coping with pet loss",
               "rainbow bridge memory keepsake"]
    # KDP allows 50 chars/slot; trim defensively without splitting a word mid-token.
    return [_clip(k, KDP_KEYWORD_MAX) for k in kws[:KDP_KEYWORD_SLOTS]]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut or text[:limit]


def verify_listing_copy(cfg: BookConfig) -> None:
    """Build-time guard (WS6b): the Amazon listing must be valid for KDP and read
    as natural language, not keyword stuffing. Fails the build on regression so
    every future title is checked — see [[catch-defects-with-guards]]."""
    kws = listing_keywords(cfg)
    if len(kws) != KDP_KEYWORD_SLOTS:
        raise ListingCopyError(
            f"{cfg.slug}: expected {KDP_KEYWORD_SLOTS} keywords, got {len(kws)}")
    for k in kws:
        if not k.strip():
            raise ListingCopyError(f"{cfg.slug}: empty keyword in listing")
        if len(k) > KDP_KEYWORD_MAX:
            raise ListingCopyError(
                f"{cfg.slug}: keyword exceeds KDP's {KDP_KEYWORD_MAX}-char limit: {k!r}")
    lower = [k.lower() for k in kws]
    if len(set(lower)) != len(lower):
        raise ListingCopyError(f"{cfg.slug}: duplicate keywords in listing: {kws}")
    # A keyword ending in an article/conjunction is a phrase clipped mid-thought
    # (e.g. a long subject truncated to "...book about ocean animals and the").
    dangling = {"and", "the", "a", "an", "for", "of", "to", "with", "about", "or"}
    for k in kws:
        if k.split()[-1].lower() in dangling:
            raise ListingCopyError(
                f"{cfg.slug}: keyword looks clipped mid-phrase: {k!r}")
    # Anti-stuffing: the 7 slots should not be the same one or two words rephrased.
    stop = {"a", "an", "the", "for", "to", "of", "and", "with", "about", "in",
            "on", "who", "your", "you"}
    words = {w for k in lower for w in k.split() if len(w) > 2 and w not in stop}
    if len(words) < 10:
        raise ListingCopyError(
            f"{cfg.slug}: keywords look stuffed/repetitive (only {len(words)} "
            f"distinct content words across 7 slots): {kws}")
    # Description must read as prose, not a comma-jammed keyword string. Standard
    # books carry the author's own synopsis verbatim (may be a single short line),
    # so only hold the generated copy to the natural-length floor.
    desc = listing_description(cfg)
    if cfg.book_type != "standard" and len(desc.split()) < 12:
        raise ListingCopyError(
            f"{cfg.slug}: listing description is too thin to read as natural copy")
    if not desc.strip():
        raise ListingCopyError(f"{cfg.slug}: empty listing description")
    if sum(desc.count(p) for p in ".!?") < 1:
        raise ListingCopyError(
            f"{cfg.slug}: listing description has no sentence structure: {desc!r}")

"""Load and validate a book.config.json into a BookConfig."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["slug", "title", "subtitle", "author", "art_prompt"]
BOOK_TYPES = ("journal", "standard", "picture", "concept")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Character:
    """A LoRA-backed character in a Flux picture book. `appears_on` is "all"
    (hero, every page) or "memory" (companion, only on flashback pages)."""
    role: str            # "hero" or "companion"
    lora: str            # LoRA filename in ComfyUI/models/loras
    trigger: str         # the trained trigger phrase, e.g. "b1scuitboy boy"
    strength: float = 0.9
    appears_on: str = "all"


@dataclass(frozen=True)
class BookConfig:
    slug: str
    title: str
    subtitle: str
    author: str
    art_prompt: str
    pet_kind: str = ""                # journals only
    prompt_count: int = 70           # journals only
    price_usd: float = 9.99
    book_type: str = "journal"
    synopsis: str = ""               # standard only
    chapter_count: int = 0           # standard only
    words_per_chapter: int = 0       # standard only
    blurb: str = ""                  # standard back-cover/listing copy
    trim_w: float = 6.0              # paperback trim width (in)
    trim_h: float = 9.0              # paperback trim height (in)
    pet_name: str = ""               # picture only — the remembered pet's name
    page_count: int = 0              # picture only — number of story pages
    art_style: str = ""              # picture only — locked illustration style (optional)
    character_anchor: str = ""       # picture only — pin the character design (optional)
    art_engine: str = "sdxl"              # picture only — "sdxl" (default) or "flux"
    flux_style: str = ""                  # flux only — the rich style/look prompt
    flux_guidance: float = 2.4            # flux only — FluxGuidance value
    outfit: str = ""                      # flux only — locked character wardrobe
    characters: tuple = ()                # flux only — tuple[Character, ...]
    theme: str = "grief"                  # picture only — content arc: "grief" or "comfort"
    subject: str = ""                     # concept only — the book's subject
    topics: tuple = ()                    # concept only — explicit per-spread subjects
    illustrator: str = ""                 # optional — "Illustrated by" credit (≠ author)
    # WS1 layered-QA ensemble (all default OFF → today's Claude-only path). Enable
    # per book once the GPU stages (VQAScore / HADM weights) are provisioned.
    qa_vqa: bool = False                  # VQAScore caption-fidelity gate (WS1a)
    qa_vqa_threshold: float = 0.6         # min P("does this show the caption?")
    qa_anatomy: bool = False              # HADM anatomy-defect detector (WS1c)
    qa_anatomy_min_score: float = 0.5     # min detector confidence to count a defect
    qa_candidates: int = 1                # best-of-N candidates per render (WS1b; 1 = off)
    qa_repair: bool = False               # localized inpaint repair before reroll (WS2)

    @property
    def makes_ebook(self) -> bool:
        """Whether this title gets a Kindle/EPUB edition.

        Journals are paperback-only — a fill-in journal is useless as a
        reflowable Kindle book (you can't write in it) — so only standard
        read-through books produce an EPUB + ebook cover.
        """
        return self.book_type == "standard"


def load_config(path: str | Path) -> BookConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON: {e}") from e
    missing = [k for k in REQUIRED if k not in data or data[k] in (None, "")]
    if missing:
        raise ConfigError(f"{path}: missing required field(s): {', '.join(missing)}")
    book_type = str(data.get("book_type", "journal"))
    art_engine = str(data.get("art_engine", "sdxl"))
    theme = str(data.get("theme", "grief"))
    if book_type not in BOOK_TYPES:
        raise ConfigError(
            f"{path}: book_type must be one of {BOOK_TYPES}, got {book_type!r}")
    if book_type == "journal" and not data.get("pet_kind"):
        raise ConfigError(f"{path}: journal books require 'pet_kind'")
    if book_type == "standard":
        miss = [k for k in ("synopsis", "chapter_count")
                if not data.get(k)]
        if miss:
            raise ConfigError(
                f"{path}: standard books require: {', '.join(miss)}")
    if book_type == "picture":
        if not data.get("pet_kind"):
            raise ConfigError(f"{path}: picture books require 'pet_kind'")
        if not data.get("pet_name"):
            raise ConfigError(f"{path}: picture books require 'pet_name'")
        pc = int(data.get("page_count", 0))
        if pc < 20 or pc % 2 != 0:
            raise ConfigError(
                f"{path}: picture 'page_count' must be even and >= 20 "
                f"(with fixed matter this clears KDP's 24-page floor); got {pc}")
        if theme not in ("grief", "comfort"):
            raise ConfigError(
                f"{path}: picture 'theme' must be 'grief' or 'comfort', "
                f"got {theme!r}")
        if art_engine not in ("sdxl", "flux"):
            raise ConfigError(
                f"{path}: picture 'art_engine' must be 'sdxl' or 'flux', "
                f"got {art_engine!r}")
        if art_engine == "flux":
            chars = data.get("characters", []) or []
            heroes = [c for c in chars if c.get("role") == "hero"]
            if len(heroes) != 1:
                raise ConfigError(
                    f"{path}: flux picture books require exactly one 'hero' "
                    f"character (got {len(heroes)})")
            for c in chars:
                if not c.get("lora") or not c.get("trigger"):
                    raise ConfigError(
                        f"{path}: each flux character needs a 'lora' and a 'trigger'")
            if not data.get("flux_style"):
                raise ConfigError(f"{path}: flux picture books require 'flux_style'")
    if book_type == "concept":
        if not data.get("subject"):
            raise ConfigError(f"{path}: concept books require 'subject'")
        if art_engine != "flux":
            raise ConfigError(
                f"{path}: concept books require art_engine 'flux', got {art_engine!r}")
        if not data.get("flux_style"):
            raise ConfigError(f"{path}: concept books require 'flux_style'")
        pc = int(data.get("page_count", 0))
        if pc < 20 or pc % 2 != 0:
            raise ConfigError(
                f"{path}: concept 'page_count' must be even and >= 20; got {pc}")
    trim_w = float(data.get("trim_w", 6.0))
    trim_h = float(data.get("trim_h", 9.0))
    if trim_w <= 0 or trim_h <= 0:
        raise ConfigError(f"{path}: trim_w/trim_h must be positive")
    return BookConfig(
        slug=data["slug"],
        title=data["title"],
        subtitle=data["subtitle"],
        author=data["author"],
        art_prompt=data["art_prompt"],
        pet_kind=str(data.get("pet_kind", "")),
        prompt_count=int(data.get("prompt_count", 70)),
        price_usd=float(data.get("price_usd", 9.99)),
        book_type=book_type,
        synopsis=str(data.get("synopsis", "")),
        chapter_count=int(data.get("chapter_count", 0)),
        words_per_chapter=int(data.get("words_per_chapter", 0)),
        blurb=str(data.get("blurb", "")),
        trim_w=trim_w,
        trim_h=trim_h,
        pet_name=str(data.get("pet_name", "")),
        page_count=int(data.get("page_count", 0)),
        art_style=str(data.get("art_style", "")),
        character_anchor=str(data.get("character_anchor", "")),
        art_engine=art_engine,
        flux_style=str(data.get("flux_style", "")),
        flux_guidance=float(data.get("flux_guidance", 2.4)),
        outfit=str(data.get("outfit", "")),
        characters=tuple(
            Character(role=str(c.get("role", "")), lora=str(c.get("lora", "")),
                      trigger=str(c.get("trigger", "")),
                      strength=float(c.get("strength", 0.9)),
                      appears_on=str(c.get("appears_on", "all")))
            for c in (data.get("characters", []) or [])),
        theme=theme,
        subject=str(data.get("subject", "")),
        topics=tuple(str(t) for t in (data.get("topics", []) or [])),
        illustrator=str(data.get("illustrator", "")),
        qa_vqa=bool(data.get("qa_vqa", False)),
        qa_vqa_threshold=float(data.get("qa_vqa_threshold", 0.6)),
        qa_anatomy=bool(data.get("qa_anatomy", False)),
        qa_anatomy_min_score=float(data.get("qa_anatomy_min_score", 0.5)),
        qa_candidates=int(data.get("qa_candidates", 1)),
        qa_repair=bool(data.get("qa_repair", False)),
    )

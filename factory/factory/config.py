"""Load and validate a book.config.json into a BookConfig."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["slug", "title", "subtitle", "author", "art_prompt"]
BOOK_TYPES = ("journal", "standard", "picture")


class ConfigError(ValueError):
    pass


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
    )

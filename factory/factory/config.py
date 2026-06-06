"""Load and validate a book.config.json into a BookConfig."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["slug", "title", "subtitle", "author", "pet_kind", "art_prompt"]


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BookConfig:
    slug: str
    title: str
    subtitle: str
    author: str
    pet_kind: str
    art_prompt: str
    prompt_count: int = 70
    price_usd: float = 9.99


def load_config(path: str | Path) -> BookConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON: {e}") from e
    missing = [k for k in REQUIRED if k not in data or data[k] in (None, "")]
    if missing:
        raise ConfigError(f"{path}: missing required field(s): {', '.join(missing)}")
    return BookConfig(
        slug=data["slug"],
        title=data["title"],
        subtitle=data["subtitle"],
        author=data["author"],
        pet_kind=data["pet_kind"],
        art_prompt=data["art_prompt"],
        prompt_count=int(data.get("prompt_count", 70)),
        price_usd=float(data.get("price_usd", 9.99)),
    )

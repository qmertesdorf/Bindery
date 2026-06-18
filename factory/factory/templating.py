"""Shared Jinja2 environment."""
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _autoescape(template_name: str | None) -> bool:
    """Escape only genuine HTML/XML templates. Every template here ends in `.j2`,
    so a by-final-extension rule can't tell HTML from markdown — and HTML-escaping
    a markdown/text template (e.g. checklist.md.j2) mangles apostrophes/&/< in copy
    the user pastes into KDP. Match on the markup type before the `.j2` suffix."""
    if not template_name:
        return False
    return template_name.endswith((".html", ".html.j2", ".xml", ".xml.j2"))


def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=_autoescape,
    )


def render(template_name: str, **ctx) -> str:
    return env().get_template(template_name).render(**ctx)

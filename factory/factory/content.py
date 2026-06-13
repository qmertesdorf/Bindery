"""Stage 1: generate interior content via an injected LLM callable."""
from __future__ import annotations
import json
import re
import subprocess
from typing import Callable
from .config import BookConfig

REQUIRED_KEYS = ["intro", "how_to_use", "pet_profile_fields", "prompts",
                 "milestones", "section_microcopy", "letter_pages"]


class ContentError(ValueError):
    pass


def build_prompt(cfg: BookConfig) -> str:
    return f"""You are writing the interior content for a print grief journal for someone \
who has lost their {cfg.pet_kind}. The tone is warm, tender, and gentle. Never clinical.

Return ONLY valid JSON (no markdown, no commentary) with exactly these keys:
- "intro": 2-4 warm sentences welcoming the griever (string)
- "how_to_use": 2-3 sentences on using the journal at their own pace (string)
- "pet_profile_fields": list of 5-7 short fill-in labels about the {cfg.pet_kind} \
(e.g. "Name", "Breed", "The day we met")
- "prompts": exactly {cfg.prompt_count} distinct, undated reflective grief prompts \
(strings), e.g. "Today I miss you because...", "What I wish I had said...". Vary them.
- "milestones": 4-6 milestone reflection headings (e.g. "The first week without you")
- "section_microcopy": object with short supportive lines, keys "prompts" and "milestones"
- "letter_pages": 2-3 headings for letter-to-pet pages

Output the JSON object and nothing else."""


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # fall back: first { to last }
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        return text[s:e + 1]
    return text


def validate_content(data: dict, expected_prompts: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("content is not a JSON object")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ContentError(f"content missing keys: {', '.join(missing)}")
    if not isinstance(data["prompts"], list) or len(data["prompts"]) != expected_prompts:
        raise ContentError(
            f"expected {expected_prompts} prompts, got "
            f"{len(data['prompts']) if isinstance(data['prompts'], list) else 'non-list'}")


def generate_content(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    if cfg.book_type == "standard":
        from .standard_content import generate_standard_content
        return generate_standard_content(cfg, generate_fn)
    if cfg.book_type == "picture":
        from .picture_content import generate_picture_content
        return generate_picture_content(cfg, generate_fn)
    raw = generate_fn(build_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"LLM did not return valid JSON: {e}") from e
    validate_content(data, cfg.prompt_count)
    return data


def claude_generate(prompt: str) -> str:
    """Real adapter: shell out to the installed Claude Code CLI in print mode.

    Uses shell=True so the Windows `claude.cmd`/Unix shim resolves, and pipes the
    prompt via stdin so the multi-line text never needs shell quoting. The shell
    string is the constant "claude -p" (no interpolated data), so there is no
    injection surface.
    """
    proc = subprocess.run(
        "claude -p",
        input=prompt,
        capture_output=True, text=True, timeout=300,
        shell=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise ContentError(f"claude CLI failed (exit {proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout

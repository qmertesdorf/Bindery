"""Stage 1: generate interior content via an injected LLM callable."""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from typing import Callable
from .config import BookConfig

# Pin the content-generation model so builds are REPRODUCIBLE: without a pin,
# claude_generate inherits whatever the box's default Claude model happens to be
# that day, so the same config could yield different prose on a re-run. Override
# per-environment with BOOKGEN_CONTENT_MODEL (e.g. a cheaper model for bulk
# standard-book chapters). Validated below so it stays a safe shell token.
CONTENT_MODEL = os.environ.get("BOOKGEN_CONTENT_MODEL", "claude-opus-4-8")

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


def _retry_feedback(error: str) -> str:
    """Suffix appended to a regenerated prompt telling the model exactly why its
    last response was rejected — so a SYSTEMATIC contract/formatting miss isn't
    repeated identically on the retry (the old retries re-rolled the same prompt
    blind)."""
    return (f"\n\nIMPORTANT: your previous response was REJECTED for this reason: "
            f"{error}\nReturn a corrected response that fixes exactly this problem. "
            f"Output ONLY the JSON and nothing else.")


def generate_json(generate_fn: Callable[[str], str], build_prompt: Callable[[], str],
                  parse_validate: Callable[[dict], object], *,
                  attempts: int = 2, label: str = "content") -> object:
    """Generate → strip fences → JSON-parse → ``parse_validate``, retrying on any
    ContentError/JSON error while FEEDING the rejection reason back into the prompt.

    ``build_prompt()`` returns the base prompt (no args); the feedback is appended
    here on retries. ``parse_validate(data)`` validates and returns the usable
    result (it may raise ContentError). Raises ContentError if every attempt fails."""
    base = build_prompt()
    last = None
    for _ in range(attempts):
        prompt = base if last is None else base + _retry_feedback(last)
        raw = generate_fn(prompt)
        try:
            data = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            last = f"{label} is not valid JSON: {e}"
            continue
        try:
            return parse_validate(data)
        except ContentError as e:
            last = str(e)
    raise ContentError(f"{label}: failed after {attempts} attempts; last error: {last}")


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
    if cfg.book_type == "concept":
        from .concept_content import generate_concept_content
        return generate_concept_content(cfg, generate_fn)
    raw = generate_fn(build_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"LLM did not return valid JSON: {e}") from e
    validate_content(data, cfg.prompt_count)
    return data


_USAGE_LIMIT_RE = re.compile(r"(session|usage|rate)\s+limit", re.IGNORECASE)


def run_claude_cli(shell_cmd: str, prompt: str, *, timeout: int = 300,
                   attempts: int = 3, backoff: float = 3.0,
                   limit_poll: float = 300.0,
                   limit_wait_max: float | None = None) -> str:
    """Run the Claude Code CLI in print mode, RETRYING transient failures.

    A single non-zero exit (or an empty reply) from the CLI is almost always a
    transient hiccup — a momentary network blip or 5xx. Without a retry, one such
    blip on ANY of the hundreds of content/vision calls a build makes would abort
    the whole multi-hour run (an AuditError propagating out of run_audited_render).
    Retry with linear backoff and only raise after the last attempt, so the build
    survives transient CLI errors but still fails loudly on a real outage
    ([[catch-defects-with-guards]]).

    A USAGE/SESSION-LIMIT error is a third case: not transient (backoff can't fix
    it) and not permanent (it lifts on a schedule — an overnight build died at
    3:30am on "You've hit your session limit — resets 4:10am", 2026-07-02). Those
    waits sleep `limit_poll` at a time WITHOUT consuming the normal attempts,
    bounded by `limit_wait_max` (default env BOOKGEN_LIMIT_WAIT_MAX or 5h) so a
    never-lifting limit still fails loudly.

    `shell_cmd` is a CONSTANT string at every call site (no interpolated user
    data), preserving the existing no-injection-surface property.
    """
    if limit_wait_max is None:
        limit_wait_max = float(os.environ.get("BOOKGEN_LIMIT_WAIT_MAX", 5 * 3600))
    last = ""
    rc = -1
    tries = 0
    limit_waited = 0.0
    while tries < attempts:
        proc = subprocess.run(
            shell_cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout, shell=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
        rc = proc.returncode
        last = (proc.stderr or proc.stdout or "").strip()[:500]
        if _USAGE_LIMIT_RE.search(last) and limit_waited < limit_wait_max:
            print(f"[claude-cli] usage limit hit — waiting {limit_poll:.0f}s "
                  f"({limit_waited:.0f}s/{limit_wait_max:.0f}s cap used): "
                  f"{last[:120]}", flush=True)
            time.sleep(limit_poll)
            limit_waited += limit_poll
            continue                     # limit waits don't burn attempts
        tries += 1
        if tries < attempts:
            time.sleep(backoff * tries)
    raise ContentError(
        f"claude CLI failed after {attempts} attempts (exit {rc}): {last}")


def safe_model_token(model: str) -> str:
    """Validate a model id for interpolation into the constant `claude -p` shell
    string: anything outside `[A-Za-z0-9._-]` is refused, so a pinned command
    stays free of interpolated user data (no injection surface)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ContentError(f"{model!r} is not a safe model token")
    return model


def claude_generate(prompt: str) -> str:
    """Real adapter: shell out to the installed Claude Code CLI in print mode.

    Uses shell=True so the Windows `claude.cmd`/Unix shim resolves, and pipes the
    prompt via stdin so the multi-line text never needs shell quoting. The shell
    string is the constant "claude -p --model <pinned>" — the model id is validated
    to a safe `[A-Za-z0-9._-]` token, so there is still no interpolated user data
    and no injection surface. Pinning the model keeps builds reproducible.
    """
    return run_claude_cli(
        f"claude -p --model {safe_model_token(CONTENT_MODEL)}", prompt)

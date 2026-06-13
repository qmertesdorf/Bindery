"""Vision auditor: judge an illustration for character consistency & cleanliness.

Injected exactly like generate_fn / ComfyClient so the art loop is testable with
a fake. The real adapter shells to the `claude` CLI, which can Read local image
files in print mode and return a JSON verdict.
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Callable
from .content import _strip_fences


class AuditError(RuntimeError):
    pass


def build_audit_prompt(*, anchor: str, scene: str | None,
                       image_path: Path, reference_path: Path | None) -> str:
    ref = (f"\nRead the reference character sheet at {reference_path} — the child "
           f"and pet in the new image MUST match it." if reference_path else "")
    scene_line = f"\nIntended scene for this page: {scene}." if scene else ""
    return f"""Read the image file at {image_path} and judge it strictly.{ref}

The recurring characters must look like: {anchor}.{scene_line}

Reject (ok=false) if ANY of these is true:
- the child or the pet is NOT visually consistent with the reference/anchor
  (different hair, skin, age, breed, colour, or markings);
- any text, letters, words, or numbers are baked into the artwork;
- anatomy is deformed (bad faces, extra/missing limbs);
- the picture does not match the intended scene.
Be strict — if you are unsure, set ok=false.

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""


def parse_verdict(raw: str) -> dict:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise AuditError(f"auditor did not return valid JSON: {e}") from e
    if not isinstance(data, dict) or "ok" not in data:
        raise AuditError(f"auditor verdict missing 'ok': {data!r}")
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return {"ok": bool(data["ok"]), "issues": [str(i) for i in issues]}


def _claude_vision(prompt: str) -> str:
    """Real adapter: shell to the Claude CLI in print mode (it can Read the image
    path in the prompt). Constant shell string 'claude -p' — no injection surface."""
    proc = subprocess.run(
        "claude -p", input=prompt, capture_output=True, text=True, timeout=300,
        shell=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise AuditError(f"claude vision failed (exit {proc.returncode}): "
                         f"{proc.stderr[:500]}")
    return proc.stdout


class ClaudeVisionAuditor:
    def __init__(self, judge_fn: Callable[[str], str] | None = None):
        self.judge_fn = judge_fn or _claude_vision

    def audit(self, image_path, *, anchor: str, reference_path=None,
              scene: str | None = None) -> dict:
        prompt = build_audit_prompt(
            anchor=anchor, scene=scene, image_path=Path(image_path),
            reference_path=Path(reference_path) if reference_path else None)
        return parse_verdict(self.judge_fn(prompt))

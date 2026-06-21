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
    ref = (f"\nA reference image of the recurring character(s) is at {reference_path}. "
           f"Read it: the character in the new image must be RECOGNISABLY THE SAME "
           f"character (same kind of person/animal, same defining features and outfit "
           f"colours) — it need NOT match the reference pose, angle, or background."
           if reference_path else "")
    scene_line = f"\nThis page is meant to depict, roughly: {scene}." if scene else ""
    return f"""Read the image file at {image_path} and judge it for a children's
picture book.{ref}

The recurring character(s) should look like: {anchor}.{scene_line}

This is a soft, stylised storybook, so judge GENEROUSLY. Apply a two-tier bar.

REJECT (set ok=false) ONLY for a real defect that would break the book:
- the character is the WRONG character, or characters are CONFLATED (e.g. a
  different person/animal, an animal wearing the child's clothes, or an extra
  subject/animal that should not be present);
- the CHILD has any animal features bleeding onto its face or body — a dog or
  animal nose/snout/muzzle, fur, whiskers, paws, a tail, or animal ears in place
  of human ones. The child must be fully, recognisably human;
- any text, letters, words, or numbers are rendered in the artwork;
- broken anatomy (malformed faces, extra or missing limbs/eyes);
- the character's DEFINING outfit is clearly wrong — wrong colours, OR a clearly
  different GARMENT than the one described above for this character, OR a
  described key piece is missing or replaced. The described outfit (whatever it
  is) must be recognisably present;
- the child's expression clearly CONTRADICTS the mood the scene calls for — in
  particular a smiling, grinning, or visibly happy child on a sad, lonely,
  wistful, or grieving page (the face must read at least quiet/subdued there).

ACCEPT (set ok=true) — do NOT reject — for natural variation that keeps the
character recognisable:
- different hairstyle detail, pose, camera angle, or framing;
- a quiet/neutral expression on a somber page (it need not be tearful — gentle is
  fine), or a warm one on a happy page;
- a different or simpler background, lighting, or time of day;
- missing or rearranged minor scene props; the scene only needs to be roughly right.

When the character is recognisable and the art is clean, set ok=true even if such
details differ. Reserve issues for genuine defects.

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""


def build_concept_audit_prompt(*, anchor: str, scene: str | None,
                               image_path: Path,
                               reference_path: Path | None = None) -> str:
    scene_line = f"\nThis page is meant to depict, roughly: {scene}." if scene else ""
    ref = (f"\nA STYLE REFERENCE image from this SAME book is at {reference_path}. "
           f"Read it. The new image must share the SAME illustration STYLE as the "
           f"reference — the same medium and finish (soft hand-painted storybook "
           f"watercolour), the same degree of stylisation vs realism, and a similar "
           f"brushwork/linework and palette feel — so every page looks like one "
           f"artist made one cohesive book. It need NOT match the reference's "
           f"subject, pose, composition, or colours; ONLY the style must match."
           if reference_path else "")
    cohesion_reject = (
        "\n- the illustration STYLE does NOT MATCH the style reference above "
        "(a different medium, finish, or level of realism — e.g. the reference is "
        "flat and painterly but this is glossy or photoreal): the book must look "
        "stylistically cohesive page to page;" if reference_path else "")
    return f"""Read the image file at {image_path} and judge it for a character-free
children's picture book.{ref}

This page should show: {anchor}.{scene_line}

This is a soft, stylised storybook, so judge GENEROUSLY. Apply a two-tier bar.

REJECT (set ok=false) ONLY for a real defect that would break the book:
- the WRONG subject (a clearly different animal or thing than described above);
- ANY people or human figures appear (this book has no people);
- any text, letters, words, or numbers are rendered in the artwork;
- broken anatomy (malformed faces, extra or missing limbs/eyes);
- a MALFORMED or HYBRID animal: anatomy that blends two species (e.g. a fox's body
  or colouring with a deer's or rabbit's tall ears/legs), mismatched or wrong body
  parts, or a creature that doesn't read clearly as ONE real animal. Every animal
  must be unmistakably a single, correct species;
- the picture looks PHOTOGRAPHIC or photorealistic — a real photo, a macro or
  close-up photograph, or a glossy 3D / CGI render — instead of a hand-painted,
  soft, simplified children's storybook illustration. It MUST clearly read as a
  storybook PAINTING (visible brushwork / drawn linework, stylised, not lifelike);
  realistic insects, fur, feathers, or water that look like a photo are a defect.{cohesion_reject}

ACCEPT (set ok=true) — do NOT reject — for natural variation:
- different pose, camera angle, framing, or composition;
- a different or simpler background, lighting, time of day, or season;
- extra incidental natural scenery (plants, sky, water) around the subject;
- loose, painterly, flat, or simplified rendering — that illustrated look is GOOD;
- stylistic differences that still read as the same soft storybook look.

When the subject is right and the art is clean, set ok=true even if such details
differ. Reserve issues for genuine defects.

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""


def build_cover_audit_prompt(*, image_path: Path) -> str:
    return f"""Read the image file at {image_path}. It is a wraparound children's
picture-book cover laid flat: the BACK cover is the LEFT half, a thin SPINE runs
down the middle, and the FRONT cover is the RIGHT half.

Judge it for defects a publisher would fix. REJECT (set ok=false) for any real
problem:
- TEXT LEGIBILITY: any text hard to read — low contrast against the art behind it
  (e.g. pale or white text over a bright, light, or busy area), washed out, or too
  faint. The back-cover blurb must be clearly readable from its first line to its
  last; the front title and author must be clearly legible.
- TEXT PLACEMENT: text cut off, running off the page, crossing onto the wrong
  panel / over the spine, or crammed into a corner.
- BACK BLURB BALANCE: the back-cover blurb must look CENTRED and balanced within
  the back cover (the left panel). Reject if it reads as off-centre — including
  when the background behind it is lopsided (e.g. a bright pool on one side, darker
  on the other) so the text appears pushed to one side even if technically centred.
- broken or garbled text, or obvious layout breakage.

ACCEPT (set ok=true) if the front title/author and the entire back blurb are
clearly legible and the layout is clean — natural art-style variation is fine.

Return ONLY JSON: {{"ok": true|false, "issues": ["short issue", ...]}}
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
              scene: str | None = None, kind: str = "character") -> dict:
        if kind == "cover":
            prompt = build_cover_audit_prompt(image_path=Path(image_path))
        elif kind == "concept":
            prompt = build_concept_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path),
                reference_path=Path(reference_path) if reference_path else None)
        else:
            prompt = build_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path),
                reference_path=Path(reference_path) if reference_path else None)
        return parse_verdict(self.judge_fn(prompt))

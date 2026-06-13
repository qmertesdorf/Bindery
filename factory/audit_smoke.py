"""Pre-flight smoke test for a picture-book build.

Validates the two real-world paths that the fakes-based unit tests cannot cover,
BEFORE committing to a full ~24-image build:

  1. the ComfyUI SQUARE render (square_workflow against the live API), and
  2. the `claude -p` VISION round-trip (does the real auditor read the image and
     return a usable {"ok", "issues"} verdict?).

It generates the story bible (real claude), renders ONE square reference image
(real ComfyUI), then runs the REAL ClaudeVisionAuditor on it and prints the
verdict. Cheap to run; fails fast if either path is broken.

Usage (from the `factory` dir, with the venv active):
    python audit_smoke.py [books/dog-loss-kids.config.json]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from factory.config import load_config
from factory.content import claude_generate
from factory.picture_content import generate_picture_content
from factory.art import ComfyClient, square_workflow
from factory.audit import ClaudeVisionAuditor


def main() -> int:
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "books/dog-loss-kids.config.json"
    cfg = load_config(cfg_path)
    out = Path("out") / cfg.slug / "_smoke"
    out.mkdir(parents=True, exist_ok=True)

    print("[smoke] 1/3 generating story bible via claude…", flush=True)
    content = generate_picture_content(cfg, claude_generate)
    anchor, style = content["character_anchor"], content["art_style"]
    print(f"[smoke]     anchor: {anchor}", flush=True)
    print(f"[smoke]     style : {style}", flush=True)

    print("[smoke] 2/3 rendering ONE square reference image via ComfyUI…", flush=True)
    workflow = json.loads(
        (Path("comfyui") / "workflow.template.json").read_text(encoding="utf-8"))
    comfy = ComfyClient()
    img = comfy.generate(
        square_workflow(workflow), positive_node="6", sampler_node="3",
        prompt=f"{style}. Character reference sheet, full body, plain background. {anchor}",
        seed=12345, out_path=out / "reference.png")
    print(f"[smoke]     image written: {img}", flush=True)

    print("[smoke] 3/3 running the REAL claude vision auditor…", flush=True)
    auditor = ClaudeVisionAuditor()
    verdict = auditor.audit(img, anchor=anchor, reference_path=None,
                            scene="character reference sheet")
    print(f"[smoke]     VERDICT: {verdict}", flush=True)

    ok_shape = isinstance(verdict, dict) and "ok" in verdict and "issues" in verdict
    if ok_shape:
        print("[smoke] PASS — the claude -p vision round-trip works and returns a "
              "usable verdict. Safe to run a full build.", flush=True)
        return 0
    print("[smoke] FAIL — the auditor did not return a usable {ok, issues} verdict; "
          "the real vision adapter needs a fix before a full build.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

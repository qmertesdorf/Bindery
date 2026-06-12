"""Render local HTML files to PDF / screenshot via the gstack `browse` binary."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess"]


class BrowseError(RuntimeError):
    pass


def browse_binary() -> str:
    # Explicit override wins, then the gstack default install location, then PATH.
    env = os.environ.get("BROWSE_BIN")
    if env:
        return env
    candidates = [
        Path(os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse")),
        Path(os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse.exe")),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "browse"  # rely on PATH


def _default_runner(args: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(list(args), capture_output=True, text=True, timeout=180)


def _file_url(p: Path) -> str:
    return "file:///" + str(p.resolve()).replace("\\", "/").lstrip("/")


def _run(runner, args):
    r = runner(args)
    if r.returncode != 0:
        raise BrowseError(f"browse {args[1] if len(args) > 1 else ''} failed: {r.stderr[:500]}")
    return r


def html_to_pdf(html: Path, out_pdf: Path, *, width_in: float, height_in: float,
                margins_in: float = 0.0, runner: Runner | None = None,
                prefer_css_page_size: bool = False) -> Path:
    runner = runner or _default_runner
    b = browse_binary()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    args = [b, "pdf", str(out_pdf),
            "--width", f"{width_in}in", "--height", f"{height_in}in",
            "--margins", f"{margins_in}in", "--print-background"]
    # Full-bleed covers: make the PDF paper EXACTLY the CSS @page size. Without
    # this, browse's paper raster is ~2px wider than the rendered content, leaving
    # a hair-thin white line in the bleed at one trim edge.
    if prefer_css_page_size:
        args.append("--prefer-css-page-size")
    _run(runner, [b, "goto", _file_url(Path(html))])
    _run(runner, args)
    return out_pdf


def html_to_screenshot(html: Path, out_img: Path, *, width_px: int, height_px: int,
                       runner: Runner | None = None) -> Path:
    runner = runner or _default_runner
    b = browse_binary()
    out_img.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, [b, "viewport", f"{width_px}x{height_px}"])
    _run(runner, [b, "goto", _file_url(Path(html))])
    _run(runner, [b, "screenshot", str(out_img)])
    return out_img

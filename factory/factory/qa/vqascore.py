"""VQAScore caption-fidelity stage (research §WS1a).

A numeric image-text faithfulness gate: the probability a VQA model answers
"Yes" to *"Does this figure show {caption}?"*. VQAScore is SOTA on caption
fidelity across eight benchmarks and beats CLIPScore — which is bag-of-words and
unreliable on the relational prompts our captions use ("wrapping its tail round
the grass") — per arXiv 2404.01291 (ECCV 2024). We use it on the concept path
(captions are read aloud beside the picture) and on covers.

Injected exactly like judge_fn / ComfyClient so the art loop stays unit-testable
without a GPU. The real adapter lazily loads the open `t2v_metrics` package
(CLIP-FlanT5; needs a GPU) only on first call and caches it, so importing this
module — and running the test suite — never requires the model or a GPU.
"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

# The real model is heavy GPU (torch + a multi-GB VQA model) and must NOT live in
# factory/.venv (the lightweight test runner). It runs in an isolated venv via a
# persistent subprocess worker (vqa_worker.py); these point at that venv + model.
DEFAULT_VQA_PYTHON = Path.home() / ".book-gen-vqa" / "Scripts" / "python.exe"
DEFAULT_VQA_MODEL = "clip-flant5-xl"   # fits a 16GB card; xxl does not
_WORKER = Path(__file__).with_name("vqa_worker.py")
_DAEMON = None  # process-wide singleton so the model loads once per build


class VQAScoreError(RuntimeError):
    pass


class _VQADaemon:
    """Owns the long-lived worker process in the isolated venv and exchanges
    one JSON request/response line per score. Lazily started on first use."""

    def __init__(self, python=None, model=None):
        self.python = str(python or os.environ.get(
            "BOOK_GEN_VQA_PYTHON", DEFAULT_VQA_PYTHON))
        self.model = str(model or os.environ.get(
            "BOOK_GEN_VQA_MODEL", DEFAULT_VQA_MODEL))
        self.proc = None

    def _ensure(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        if not Path(self.python).exists():
            raise VQAScoreError(
                f"VQAScore venv python not found at {self.python}; create the "
                f"isolated venv (see factory/factory/qa/VQA_SETUP.md) or set "
                f"BOOK_GEN_VQA_PYTHON, or leave qa_vqa disabled to keep the "
                f"Claude-only path.")
        self.proc = subprocess.Popen(
            [self.python, "-u", str(_WORKER), "--model", self.model],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            encoding="utf-8", bufsize=1)
        # Block until the worker reports the model is loaded, skipping any library
        # noise that leaks onto stdout (download bars etc. should be on stderr).
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise VQAScoreError("VQAScore worker exited during startup")
            try:
                if json.loads(line.strip()).get("ready"):
                    return
            except json.JSONDecodeError:
                continue

    def score(self, image_path, caption: str) -> float:
        self._ensure()
        self.proc.stdin.write(
            json.dumps({"image": str(image_path), "caption": caption}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise VQAScoreError("VQAScore worker died mid-request")
        resp = json.loads(line.strip())
        if "error" in resp:
            raise VQAScoreError(f"VQAScore worker error: {resp['error']}")
        return float(resp["score"])


def _daemon_score(image_path: Path, caption: str) -> float:
    """Default adapter: P("Yes" | image, "Does this figure show {caption}?") via
    the isolated-venv worker. Returns a scalar in [0, 1]."""
    global _DAEMON
    if _DAEMON is None:
        _DAEMON = _VQADaemon()
    return _DAEMON.score(image_path, caption)


class VQAScorer:
    """Scores image<->caption faithfulness in [0, 1]. `score_fn` is injectable
    for tests; the default talks to the real model in the isolated GPU venv.
    `threshold` is the pass bar — tune empirically in config (the research gives
    no fixed number)."""

    def __init__(self, score_fn: Callable[[Path, str], float] | None = None,
                 threshold: float = 0.15):
        # 0.15 is a COARSE floor, not a fidelity ceiling: on real rendered pages
        # clip-flant5-xl scores correct matches anywhere from ~0.19 to ~0.97 but
        # gross mismatches (wrong subject) at ~0.05. A low floor catches the gross
        # case while best-of-N ranking and the holistic auditor handle fine
        # judgment — see VQA_SETUP.md for the calibration data.
        self.score_fn = score_fn or _daemon_score
        self.threshold = threshold

    def score(self, image_path, caption: str) -> float:
        return float(self.score_fn(Path(image_path), caption))

    def passes(self, image_path, caption: str) -> tuple[bool, float]:
        """Return (meets_threshold, score) so callers can both gate and report
        the number (used in the reject reason and for best-of-N selection)."""
        s = self.score(image_path, caption)
        return (s >= self.threshold, s)

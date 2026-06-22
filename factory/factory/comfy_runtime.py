"""Launch / health-check the local ComfyUI backend.

A long concept-art build (best-of-N × 20 spreads) can outlive a single ComfyUI
process: on this RTX 5080 (Blackwell) ComfyUI intermittently dies with a native
SIGILL at the VAE-decode stage — no Python traceback, the process just exits and
frees its VRAM. `ComfyClient` calls `make_restart_fn()`'s closure on a transport
death, which relaunches ComfyUI and blocks until it answers, then re-submits the
graph. Self-contained so it stays a no-op (returns None) on any machine without a
ComfyUI install — the test suite and other environments keep the prior behaviour.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

BASE = "http://127.0.0.1:8188"


def comfy_dir() -> Path:
    """ComfyUI install dir — $COMFYUI_DIR or ~/ComfyUI (this machine's default)."""
    return Path(os.environ.get("COMFYUI_DIR", str(Path.home() / "ComfyUI")))


def is_up(timeout: float = 3.0) -> bool:
    import requests
    try:
        requests.get(f"{BASE}/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


def _python(d: Path) -> Path:
    """Prefer ComfyUI's own venv interpreter; fall back to the current one."""
    for rel in ("venv/Scripts/python.exe", "venv/bin/python",
                ".venv/Scripts/python.exe", ".venv/bin/python"):
        p = d / rel
        if p.exists():
            return p
    return Path(sys.executable)


def launch(d: Optional[Path] = None) -> subprocess.Popen:
    """Spawn ComfyUI with the Blackwell perf flag, detached from this process."""
    d = Path(d) if d else comfy_dir()
    return subprocess.Popen(
        [str(_python(d)), "main.py", "--use-sage-attention"],
        cwd=str(d), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_up(*, boot_timeout: float = 180.0, poll: float = 3.0) -> None:
    """Block until ComfyUI answers /system_stats, launching it if it isn't already
    healthy. Idempotent: a transient blip where ComfyUI is still alive returns at
    once without spawning a duplicate."""
    if is_up():
        return
    launch()
    deadline = time.time() + boot_timeout
    while time.time() < deadline:
        time.sleep(poll)
        if is_up():
            return
    raise RuntimeError(f"ComfyUI did not come up within {boot_timeout:.0f}s")


def make_restart_fn() -> Optional[Callable[[], None]]:
    """A restart_fn for ComfyClient, or None if no ComfyUI install is found (so the
    test suite / non-dev machines keep the prior no-restart behaviour)."""
    if not (comfy_dir() / "main.py").exists():
        return None
    return lambda: ensure_up()

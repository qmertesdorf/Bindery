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


LAUNCH_LOCK = "_bookgen_launch.lock"


def _try_lock(lock: Path, stale_after: float) -> bool:
    """Atomically claim the launch lock. A lock older than `stale_after` belongs
    to a crashed launcher — remove it and claim. Returns False if someone else
    holds a fresh lock (they are booting ComfyUI right now)."""
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.unlink(missing_ok=True)   # stale — steal on next pass
                    continue
            except OSError:
                pass                                # vanished — retry claim
            return False
    return False


def _wait_health(deadline: float, poll: float) -> bool:
    while time.time() < deadline:
        time.sleep(poll)
        if is_up():
            return True
    return False


def ensure_up(*, boot_timeout: float = 180.0, poll: float = 3.0) -> None:
    """Block until ComfyUI answers /system_stats, launching it if it isn't already
    healthy. Safe under CONCURRENT callers (a build's restart_fn racing another
    ensure_up): a lockfile in comfy_dir guarantees at most one spawner — losers
    wait for the winner's boot instead of double-launching. Two ComfyUI instances
    split the GPU and every render times out while /system_stats still answers
    (live failure 2026-07-02), so a duplicate launch is never acceptable."""
    if is_up():
        return
    deadline = time.time() + boot_timeout
    lock = comfy_dir() / LAUNCH_LOCK
    if _try_lock(lock, stale_after=boot_timeout):
        try:
            if is_up():                 # winner double-checks: maybe it just booted
                return
            launch()
            if _wait_health(deadline, poll):
                return
        finally:
            lock.unlink(missing_ok=True)
    else:
        if _wait_health(deadline, poll):
            return
    raise RuntimeError(f"ComfyUI did not come up within {boot_timeout:.0f}s")


def make_restart_fn() -> Optional[Callable[[], None]]:
    """A restart_fn for ComfyClient, or None if no ComfyUI install is found (so the
    test suite / non-dev machines keep the prior no-restart behaviour)."""
    if not (comfy_dir() / "main.py").exists():
        return None
    return lambda: ensure_up()

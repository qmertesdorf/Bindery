"""ensure_up must be safe under concurrent callers: on 2026-07-02 two ComfyUI
instances (spawned the same second) split the 16GB card and every render timed
out while /system_stats still answered 200. The launch lockfile guarantees at
most one spawner; losers wait for the winner's boot instead of double-launching."""
import time
import pytest
from factory import comfy_runtime as cr


@pytest.fixture
def fake_comfy(monkeypatch, tmp_path):
    """Redirect comfy_dir to tmp and record launch() calls."""
    calls = {"launch": 0}
    monkeypatch.setattr(cr, "comfy_dir", lambda: tmp_path)
    monkeypatch.setattr(cr, "launch", lambda d=None: calls.__setitem__("launch", calls["launch"] + 1))
    return calls


def test_healthy_backend_never_launches(fake_comfy, monkeypatch):
    monkeypatch.setattr(cr, "is_up", lambda timeout=3.0: True)
    cr.ensure_up(boot_timeout=1.0, poll=0.01)
    assert fake_comfy["launch"] == 0


def test_down_backend_launches_and_clears_lock(fake_comfy, monkeypatch, tmp_path):
    health = iter([False, False, True, True])
    monkeypatch.setattr(cr, "is_up", lambda timeout=3.0: next(health, True))
    cr.ensure_up(boot_timeout=5.0, poll=0.01)
    assert fake_comfy["launch"] == 1
    assert not (tmp_path / cr.LAUNCH_LOCK).exists()   # lock released after boot


def test_fresh_lock_means_wait_not_second_launch(fake_comfy, monkeypatch, tmp_path):
    """A live lock = someone else is booting ComfyUI right now: do NOT spawn a
    duplicate (two instances wedge the GPU); wait for their boot to finish."""
    (tmp_path / cr.LAUNCH_LOCK).write_text("other")
    health = iter([False, False, True])
    monkeypatch.setattr(cr, "is_up", lambda timeout=3.0: next(health, True))
    cr.ensure_up(boot_timeout=5.0, poll=0.01)
    assert fake_comfy["launch"] == 0


def test_stale_lock_is_stolen(fake_comfy, monkeypatch, tmp_path):
    """A lock older than boot_timeout is a crashed launcher's leftover — steal it."""
    lock = tmp_path / cr.LAUNCH_LOCK
    lock.write_text("dead")
    old = time.time() - 9999
    import os
    os.utime(lock, (old, old))
    health = iter([False, False, False, True])   # entry, winner double-check, poll, up
    monkeypatch.setattr(cr, "is_up", lambda timeout=3.0: next(health, True))
    cr.ensure_up(boot_timeout=5.0, poll=0.01)
    assert fake_comfy["launch"] == 1
    assert not lock.exists()


def test_boot_timeout_raises_and_clears_lock(fake_comfy, monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "is_up", lambda timeout=3.0: False)
    with pytest.raises(RuntimeError):
        cr.ensure_up(boot_timeout=0.05, poll=0.01)
    assert not (tmp_path / cr.LAUNCH_LOCK).exists()

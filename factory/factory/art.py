"""Stage 3: generate cover art via the local ComfyUI HTTP API."""
from __future__ import annotations
import copy
import time
import urllib.parse
from pathlib import Path
from typing import Callable

BASE = "http://127.0.0.1:8188"


class ArtError(RuntimeError):
    pass


def inject_prompt(workflow: dict, *, positive_node: str, sampler_node: str,
                  prompt: str, seed: int) -> dict:
    wf = copy.deepcopy(workflow)
    wf[positive_node]["inputs"]["text"] = prompt
    wf[sampler_node]["inputs"]["seed"] = seed
    return wf


def _default_post(url, json):
    import requests
    r = requests.post(url, json=json, timeout=30)
    r.raise_for_status()
    return r.json()


def _default_get(url):
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    return r.json() if "application/json" in ct else r.content


class ComfyClient:
    def __init__(self, base: str = BASE,
                 http_post: Callable = _default_post,
                 http_get: Callable = _default_get,
                 poll_interval: float = 1.0, max_polls: int = 180):
        self.base = base
        self.http_post = http_post
        self.http_get = http_get
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def generate(self, workflow: dict, *, positive_node: str, sampler_node: str,
                 prompt: str, seed: int, out_path: Path) -> Path:
        wf = inject_prompt(workflow, positive_node=positive_node,
                           sampler_node=sampler_node, prompt=prompt, seed=seed)
        resp = self.http_post(f"{self.base}/prompt", json={"prompt": wf})
        pid = resp.get("prompt_id")
        if not pid:
            raise ArtError(f"ComfyUI did not return prompt_id: {resp}")
        hist = None
        for _ in range(self.max_polls):
            hist = self.http_get(f"{self.base}/history/{pid}")
            if isinstance(hist, dict) and pid in hist and hist[pid].get("outputs"):
                break
            time.sleep(self.poll_interval)
        else:
            raise ArtError("ComfyUI generation timed out")
        img = self._first_image(hist[pid]["outputs"])
        q = urllib.parse.urlencode(img)
        data = self.http_get(f"{self.base}/view?{q}")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return out_path

    @staticmethod
    def _first_image(outputs: dict) -> dict:
        for node in outputs.values():
            if node.get("images"):
                im = node["images"][0]
                return {"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                        "type": im.get("type", "output")}
        raise ArtError("no image in ComfyUI outputs")

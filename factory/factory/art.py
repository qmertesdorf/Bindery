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


def square_workflow(workflow: dict, *, base: int = 1024, final: int = 2048) -> dict:
    """Return a deep copy of the workflow producing a SQUARE image (the base graph
    is sized wide for the cover wrap). Rewrites dimensions by node class_type so it
    survives node-id changes: EmptyLatentImage -> base, LatentUpscale -> 2*base,
    ImageScale -> final. No new nodes or models — a parameter change only."""
    wf = copy.deepcopy(workflow)
    for node in wf.values():
        ct = node.get("class_type")
        inp = node.get("inputs", {})
        if ct == "EmptyLatentImage":
            inp["width"] = inp["height"] = base
        elif ct == "LatentUpscale":
            inp["width"] = inp["height"] = base * 2
        elif ct == "ImageScale":
            inp["width"] = inp["height"] = final
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
                 poll_interval: float = 1.0, max_polls: int = 600):
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
            if isinstance(hist, dict) and pid in hist:
                rec = hist[pid]
                if rec.get("status", {}).get("status_str") == "error":
                    raise ArtError(f"ComfyUI error: {rec.get('status', {}).get('messages')}")
                if rec.get("outputs"):
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


def _generate_audited(comfy, workflow, *, positive_node, sampler_node, prompt,
                      seed, out_path, auditor, anchor, reference_path, scene,
                      max_tries) -> Path:
    """Generate an image, audit it, and regenerate (fresh seed + corrective hints)
    until it passes or the try budget runs out — then fail the build loudly."""
    issues: list[str] = []
    for attempt in range(max_tries):
        p = prompt
        if issues:
            p = f"{prompt} Fix these problems from the last attempt: {'; '.join(issues)}"
        comfy.generate(workflow, positive_node=positive_node,
                       sampler_node=sampler_node, prompt=p,
                       seed=seed + attempt * 1009, out_path=out_path)
        verdict = auditor.audit(out_path, anchor=anchor,
                                reference_path=reference_path, scene=scene)
        if verdict.get("ok"):
            return Path(out_path)
        issues = verdict.get("issues", [])
    raise ArtError(
        f"could not produce a consistent illustration for {Path(out_path).name} "
        f"after {max_tries} tries; last issues: {issues}")


def generate_picture_art(cfg, content, out_dir, comfy, workflow, *,
                         positive_node: str, sampler_node: str, seed: int,
                         auditor, max_tries: int = 4) -> dict:
    """Stage 3 for picture books: reference sheet + one audited illustration per
    page (square) + a wide cover illustration. Returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sq = square_workflow(workflow)
    style, anchor = content["art_style"], content["character_anchor"]

    ref = _generate_audited(
        comfy, sq, positive_node=positive_node, sampler_node=sampler_node,
        prompt=f"{style}. Character reference sheet, full body, plain background. {anchor}",
        seed=seed, out_path=out_dir / "reference.png", auditor=auditor,
        anchor=anchor, reference_path=None, scene="character reference sheet",
        max_tries=max_tries)

    pages = []
    for i, page in enumerate(content["pages"], 1):
        out = out_dir / f"page_{i:02d}.png"
        pages.append(_generate_audited(
            comfy, sq, positive_node=positive_node, sampler_node=sampler_node,
            prompt=f"{style}. {anchor}. Scene: {page['scene']}",
            seed=seed + i, out_path=out, auditor=auditor, anchor=anchor,
            reference_path=ref, scene=page["scene"], max_tries=max_tries))

    # Wide cover illustration (uses the unmodified wrap-sized workflow).
    cover = comfy.generate(
        workflow, positive_node=positive_node, sampler_node=sampler_node,
        prompt=f"{style}. {anchor}. Front cover illustration: {content['pages'][0]['scene']}",
        seed=seed, out_path=out_dir / "art.png")
    return {"reference": ref, "pages": pages, "cover": Path(cover)}

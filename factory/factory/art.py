"""Stage 3: generate cover art via the local ComfyUI HTTP API."""
from __future__ import annotations
import copy
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Callable

BASE = "http://127.0.0.1:8188"


def _log(msg: str) -> None:
    """Progress line to stderr so a real build shows what the auditor is doing
    (which images regenerate and why) — the signal needed to tune strictness."""
    print(msg, file=sys.stderr, flush=True)


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

    def submit(self, workflow: dict, *, out_path: Path) -> Path:
        """POST an already-complete workflow graph, poll until it finishes, and
        download the first output image. Backend-agnostic (no prompt/seed
        injection) so Flux graphs — which bake prompt+seed into their own nodes —
        can reuse the same submit/poll/retrieve path and the same test fakes."""
        resp = self.http_post(f"{self.base}/prompt", json={"prompt": workflow})
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

    def generate(self, workflow: dict, *, positive_node: str, sampler_node: str,
                 prompt: str, seed: int, out_path: Path) -> Path:
        wf = inject_prompt(workflow, positive_node=positive_node,
                           sampler_node=sampler_node, prompt=prompt, seed=seed)
        return self.submit(wf, out_path=out_path)

    @staticmethod
    def _first_image(outputs: dict) -> dict:
        for node in outputs.values():
            if node.get("images"):
                im = node["images"][0]
                return {"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                        "type": im.get("type", "output")}
        raise ArtError("no image in ComfyUI outputs")


def _render_best_of_n(render, prompt, base_seed, out_path, *, n_candidates,
                      selector, caption) -> Path:
    """Render the page and leave the chosen image at out_path (research §WS1b).

    With n_candidates<=1 — or with no selector / no caption to rank on — this
    renders ONCE at base_seed, byte-for-byte today's behaviour. Otherwise it
    draws N candidates at distinct seeds, lets `selector` pick the best (highest
    VQAScore), copies the winner to out_path, and cleans up the rest. Best-of-N
    is caption-gated because the selector ranks by caption fidelity; a page with
    no caption has nothing to choose between, so we don't waste the extra draws."""
    out_path = Path(out_path)
    if n_candidates <= 1 or selector is None or not caption:
        render(prompt, base_seed, out_path)
        return out_path
    cands = []
    for k in range(n_candidates):
        cp = out_path.with_name(f"{out_path.stem}__cand{k}{out_path.suffix}")
        render(prompt, base_seed + k * 7919, cp)  # distinct prime stride per candidate
        cands.append(cp)
    chosen = Path(selector.select(cands, caption))
    if chosen != out_path:
        out_path.write_bytes(chosen.read_bytes())
    for cp in cands:
        if cp != out_path:
            cp.unlink(missing_ok=True)
    return out_path


def run_audited_render(render, prompt, *, out_path, auditor, anchor, scene,
                       reference_path=None, seed=0, max_tries=4,
                       audit_kind="character", caption=None,
                       n_candidates=1, selector=None, repair_fn=None) -> Path:
    """Render → audit → regenerate (fresh seed + corrective hints) until the
    auditor passes or the try budget runs out, then fail loudly. `render` is a
    callable (prompt, seed, out_path) -> None that writes the image. The seed is
    bumped by attempt*1009 each retry so a fresh sample is drawn, and the last
    attempt's issues are appended to the prompt as corrective guidance.

    Optional QA layers (research §WS1b/§WS2; off by default → unchanged behaviour):
    `n_candidates`+`selector` draw best-of-N per attempt; `repair_fn(image,
    defects, prompt=...)` does a localized inpaint repair and re-audit on a
    LOCALIZED reject (auditor verdict carries `defects`) before a fresh-seed reroll."""
    out_path = Path(out_path)
    name = out_path.name
    issues: list[str] = []
    for attempt in range(max_tries):
        p = prompt
        if issues:
            p = f"{prompt} Fix these problems from the last attempt: {'; '.join(issues)}"
        _render_best_of_n(render, p, seed + attempt * 1009, out_path,
                          n_candidates=n_candidates, selector=selector,
                          caption=caption)
        verdict = auditor.audit(out_path, anchor=anchor,
                                reference_path=reference_path, scene=scene,
                                kind=audit_kind, caption=caption)
        if verdict.get("ok"):
            _log(f"  [audit] {name}: OK"
                 + (f" on attempt {attempt + 1}/{max_tries}" if attempt else ""))
            return out_path
        issues = verdict.get("issues", [])
        # WS2: a LOCALIZED reject (detector boxes) gets a masked inpaint repair and
        # a re-audit BEFORE we spend a fresh-seed reroll on the whole page.
        if repair_fn is not None and verdict.get("defects"):
            _log(f"  [repair] {name}: localized defect(s) — inpainting before reroll")
            try:
                repair_fn(out_path, verdict["defects"], prompt=p)
            except Exception as e:  # repair is best-effort; fall back to a reroll
                _log(f"  [repair] {name}: repair failed ({e}); rerolling")
            else:
                rev = auditor.audit(out_path, anchor=anchor,
                                    reference_path=reference_path, scene=scene,
                                    kind=audit_kind, caption=caption)
                if rev.get("ok"):
                    _log(f"  [repair] {name}: OK after inpaint repair")
                    return out_path
                issues = rev.get("issues", issues)
        _log(f"  [audit] {name}: REJECT attempt {attempt + 1}/{max_tries} — "
             f"{'; '.join(issues) or 'no reason given'}"
             + ("; regenerating" if attempt + 1 < max_tries else ""))
    raise ArtError(
        f"could not produce a consistent illustration for {name} "
        f"after {max_tries} tries; last issues: {issues}")


def _generate_audited(comfy, workflow, *, positive_node, sampler_node, prompt,
                      seed, out_path, auditor, anchor, reference_path, scene,
                      max_tries) -> Path:
    """SDXL adapter: drive run_audited_render with a ComfyClient.generate render."""
    def render(p, s, op):
        comfy.generate(workflow, positive_node=positive_node,
                       sampler_node=sampler_node, prompt=p, seed=s, out_path=op)
    return run_audited_render(render, prompt, out_path=out_path, auditor=auditor,
                              anchor=anchor, scene=scene,
                              reference_path=reference_path, seed=seed,
                              max_tries=max_tries)


def generate_picture_art(cfg, content, out_dir, comfy, workflow, *,
                         positive_node: str, sampler_node: str, seed: int,
                         auditor, max_tries: int = 4) -> dict:
    """Stage 3 for picture books: reference sheet + one audited illustration per
    page (square) + a wide cover illustration. Returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sq = square_workflow(workflow)
    style, anchor = content["art_style"], content["character_anchor"]
    n_pages = len(content["pages"])

    _log(f"[art] generating character reference sheet (anchors {n_pages} pages)…")
    ref = _generate_audited(
        comfy, sq, positive_node=positive_node, sampler_node=sampler_node,
        prompt=f"{style}. Character reference sheet, full body, plain background. {anchor}",
        seed=seed, out_path=out_dir / "reference.png", auditor=auditor,
        anchor=anchor, reference_path=None, scene="character reference sheet",
        max_tries=max_tries)

    pages = []
    for i, page in enumerate(content["pages"], 1):
        _log(f"[art] page {i}/{n_pages}: {page['scene'][:70]}")
        out = out_dir / f"page_{i:02d}.png"
        pages.append(_generate_audited(
            comfy, sq, positive_node=positive_node, sampler_node=sampler_node,
            prompt=f"{style}. {anchor}. Scene: {page['scene']}",
            seed=seed + i, out_path=out, auditor=auditor, anchor=anchor,
            reference_path=ref, scene=page["scene"], max_tries=max_tries))

    # Wide cover illustration (uses the unmodified wrap-sized workflow).
    _log("[art] generating cover illustration…")
    cover = comfy.generate(
        workflow, positive_node=positive_node, sampler_node=sampler_node,
        prompt=f"{style}. {anchor}. Front cover illustration: {content['pages'][0]['scene']}",
        seed=seed, out_path=out_dir / "art.png")
    _log(f"[art] complete: reference + {n_pages} pages + cover")
    return {"reference": ref, "pages": pages, "cover": Path(cover)}

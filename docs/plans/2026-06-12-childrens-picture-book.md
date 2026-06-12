# Children's Picture Book (`book_type: "picture"`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third `book_type: "picture"` to the factory that produces a full-colour, framed 8.5×8.5 children's pet-loss picture book end to end, with art consistency enforced by a vision auditor that rejects and regenerates off-model illustrations.

**Architecture:** New per-`book_type` strategy mirroring the journal/standard split: a `picture_content` generator (story bible → story pages), a new injected `VisionAuditor` adapter, an audited multi-image art loop, a colour/paper-aware economics layer, a framed picture interior template, and a `build.py` branch that runs **art before interior** (the interior embeds the page images). Every external effect stays behind a thin injected adapter so the whole pipeline is unit-tested with fakes — no GPU/network/`claude` CLI in tests.

**Tech Stack:** Python 3, dataclasses, Jinja2 templates, PyMuPDF (`fitz`), Pillow, the gstack `browse` HTML→PDF binary, a local ComfyUI HTTP API (JuggernautXL/SDXL), and the `claude` CLI (text + vision) — all injected.

**Spec:** `docs/specs/2026-06-12-childrens-picture-book-design.md`

---

## File structure

**New files**
- `factory/factory/picture_content.py` — story-bible + story-page generation & validation.
- `factory/factory/audit.py` — `VisionAuditor` (`ClaudeVisionAuditor`) adapter + verdict parsing.
- `factory/templates/interior/picture.html.j2` — framed full-colour 8.5×8.5 interior.
- `factory/books/dog-loss-kids.config.json` — first title.
- `factory/tests/test_picture_content.py`, `factory/tests/test_audit.py`, `factory/tests/test_picture_interior.py`.

**Modified files**
- `factory/factory/config.py` — `"picture"` book_type, new fields, validation.
- `factory/factory/content.py` — dispatch to `picture_content`.
- `factory/factory/art.py` — `square_workflow()` + `generate_picture_art()` audited loop.
- `factory/factory/specs.py` — colour print cost + paper-aware spine width.
- `factory/factory/cover.py` — thread paper-aware spine per-page through cover + guards.
- `factory/factory/interior.py` — picture template selection + page-count guard.
- `factory/factory/copy.py` — picture blurb branch.
- `factory/factory/checklist.py` + `factory/templates/checklist.md.j2` — colour settings + picture categories/keywords.
- `factory/build.py` — picture branch (art→interior order) + injected `auditor`.
- `factory/tests/conftest.py` — picture fixtures.

---

## Task 1: Config — add the `picture` book_type

**Files:**
- Modify: `factory/factory/config.py`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_config.py`:

```python
import json, pytest
from factory.config import load_config, ConfigError

def _write(tmp_path, d):
    p = tmp_path / "b.config.json"; p.write_text(json.dumps(d), encoding="utf-8"); return p

def test_picture_config_loads(tmp_path):
    cfg = load_config(_write(tmp_path, {
        "slug": "dog-loss-kids", "title": "T", "subtitle": "S", "author": "A",
        "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
        "pet_name": "Sunny", "page_count": 22, "trim_w": 8.5, "trim_h": 8.5,
        "price_usd": 10.99}))
    assert cfg.book_type == "picture"
    assert cfg.pet_name == "Sunny" and cfg.page_count == 22
    assert cfg.makes_ebook is False

def test_picture_requires_pet_name(tmp_path):
    with pytest.raises(ConfigError, match="pet_name"):
        load_config(_write(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
            "page_count": 22}))

def test_picture_page_count_even_and_min(tmp_path):
    with pytest.raises(ConfigError, match="page_count"):
        load_config(_write(tmp_path, {
            "slug": "k", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "x", "book_type": "picture", "pet_kind": "dog",
            "pet_name": "Sunny", "page_count": 21}))
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_config.py -k picture -v`
Expected: FAIL (`"picture"` rejected by `book_type` validation).

- [ ] **Step 3: Implement**

In `factory/factory/config.py`: change `BOOK_TYPES` and add fields + validation.

```python
BOOK_TYPES = ("journal", "standard", "picture")
```

Add to the `BookConfig` dataclass (after `words_per_chapter`):

```python
    pet_name: str = ""               # picture only — the remembered pet's name
    page_count: int = 0              # picture only — number of story pages
    art_style: str = ""              # picture only — locked illustration style (optional)
```

In `load_config`, after the `standard` validation block and before the trim parsing, add:

```python
    if book_type == "picture":
        if not data.get("pet_kind"):
            raise ConfigError(f"{path}: picture books require 'pet_kind'")
        if not data.get("pet_name"):
            raise ConfigError(f"{path}: picture books require 'pet_name'")
        pc = int(data.get("page_count", 0))
        if pc < 20 or pc % 2 != 0:
            raise ConfigError(
                f"{path}: picture 'page_count' must be even and >= 20 "
                f"(with fixed matter this clears KDP's 24-page floor); got {pc}")
```

In the `return BookConfig(...)` call, add the three new kwargs:

```python
        pet_name=str(data.get("pet_name", "")),
        page_count=int(data.get("page_count", 0)),
        art_style=str(data.get("art_style", "")),
```

`makes_ebook` already returns `self.book_type == "standard"`, so picture is paperback-only with no change.

- [ ] **Step 4: Run tests, verify pass**

Run: `cd factory && pytest tests/test_config.py -v`
Expected: PASS (all config tests, old + new).

- [ ] **Step 5: Commit**

```bash
git add factory/factory/config.py factory/tests/test_config.py
git commit -m "feat(config): add picture book_type (pet_name, page_count, art_style)"
```

---

## Task 2: Picture content generation (`picture_content.py`)

Two LLM calls: a frozen **story bible** (`character_anchor`, `art_style`, `dedication`) then the **story pages** (`pages: [{text, scene}]` + `closing`). The anchor is the consistency keystone.

**Files:**
- Create: `factory/factory/picture_content.py`
- Test: `factory/tests/test_picture_content.py`

- [ ] **Step 1: Write failing tests**

Create `factory/tests/test_picture_content.py`:

```python
import json, pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.picture_content import (
    build_bible_prompt, build_story_prompt, validate_bible, validate_story,
    generate_picture_content)

def _cfg(**kw):
    base = dict(slug="k", title="Sunny's Last Walk", subtitle="S", author="A",
                art_prompt="x", book_type="picture", pet_kind="dog",
                pet_name="Sunny", page_count=4, trim_w=8.5, trim_h=8.5)
    base.update(kw); return BookConfig(**base)

def test_bible_prompt_mentions_pet_name_and_audience():
    p = build_bible_prompt(_cfg())
    assert "Sunny" in p and "dog" in p

def test_story_prompt_requests_exact_page_count():
    p = build_story_prompt(_cfg(page_count=4), anchor="a child and a dog")
    assert "4" in p and "a child and a dog" in p

def test_validate_story_rejects_wrong_page_count():
    with pytest.raises(ContentError, match="4 pages"):
        validate_story({"pages": [{"text": "t", "scene": "s"}], "closing": "c"}, 4)

def test_validate_story_rejects_empty_scene():
    pages = [{"text": "t", "scene": ""}] * 4
    with pytest.raises(ContentError, match="scene"):
        validate_story({"pages": pages, "closing": "c"}, 4)

def test_generate_picture_content_assembles_schema():
    bible = {"character_anchor": "a small girl with a golden dog",
             "art_style": "soft flat storybook watercolor", "dedication": "For Sunny"}
    story = {"pages": [{"text": f"line {i}", "scene": f"scene {i}"} for i in range(4)],
             "closing": "We will always remember you."}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_picture_content(_cfg(page_count=4), fake_llm)
    assert out["character_anchor"].startswith("a small girl")
    assert out["art_style"] == "soft flat storybook watercolor"
    assert len(out["pages"]) == 4 and out["closing"].startswith("We will")

def test_config_art_style_overrides_bible():
    bible = {"character_anchor": "anchor", "art_style": "MODEL CHOICE", "dedication": "d"}
    story = {"pages": [{"text": "t", "scene": "s"} for _ in range(4)], "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_picture_content(_cfg(page_count=4, art_style="LOCKED STYLE"), fake_llm)
    assert out["art_style"] == "LOCKED STYLE"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_picture_content.py -v`
Expected: FAIL (`No module named 'factory.picture_content'`).

- [ ] **Step 3: Implement**

Create `factory/factory/picture_content.py`:

```python
"""Picture-book content: a frozen story bible + per-page story text & scenes."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences


def build_bible_prompt(cfg: BookConfig) -> str:
    return f"""You are designing a gentle children's picture book for a young child
(ages 4-8) grieving the death of their {cfg.pet_kind}, named {cfg.pet_name}. The
child narrates; {cfg.pet_name} appears in soft, remembered moments. Title: {cfg.title}.

First produce the STORY BIBLE. Return ONLY valid JSON (no markdown, no commentary):
{{"character_anchor": "...", "art_style": "...", "dedication": "..."}}
- "character_anchor": a SIMPLE, ICONIC, fixed visual description reused on every
  page so an image model can repeat it — the child (age, hair, skin, ONE simple
  outfit) and {cfg.pet_name} the {cfg.pet_kind} (breed, colour, markings). Keep it
  concrete and free of scene details. No proper nouns an image model can't draw.
- "art_style": one short style string, e.g.
  "soft flat storybook watercolor, muted palette, soft edges, no text".
- "dedication": one tender line for the dedication page.
Output the JSON and nothing else."""


def build_story_prompt(cfg: BookConfig, anchor: str) -> str:
    return f"""You are writing the gentle children's picture book "{cfg.title}" for a
child (ages 4-8) grieving their {cfg.pet_kind}, {cfg.pet_name}. The child narrates;
{cfg.pet_name} appears in soft remembered moments. Warm, simple, never clinical;
never the "Rainbow Bridge" poem.

The recurring characters (keep every page consistent with this): {anchor}

Write EXACTLY {cfg.page_count} story pages that move gently from loss to remembering
with love. Return ONLY valid JSON:
{{"pages": [{{"text": "...", "scene": "..."}}], "closing": "..."}}
- each "text": 1-2 short child-friendly sentences for that page.
- each "scene": a concrete VISUAL description of what to illustrate on that page
  (setting, what the child and {cfg.pet_name} are doing), consistent with the
  characters above. Do NOT include any words/letters to render in the picture.
- "closing": one comforting closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def validate_bible(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContentError("story bible is not a JSON object")
    for k in ("character_anchor", "art_style", "dedication"):
        if not str(data.get(k, "")).strip():
            raise ContentError(f"story bible missing '{k}'")


def validate_story(data: dict, expected_pages: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("story is not a JSON object")
    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ContentError(
            f"story must have exactly {expected_pages} pages, got "
            f"{len(pages) if isinstance(pages, list) else 'non-list'}")
    for i, pg in enumerate(pages, 1):
        if not isinstance(pg, dict) or not str(pg.get("text", "")).strip():
            raise ContentError(f"story page {i} missing 'text'")
        if not str(pg.get("scene", "")).strip():
            raise ContentError(f"story page {i} missing 'scene'")
    if not str(data.get("closing", "")).strip():
        raise ContentError("story missing 'closing'")


def _generate_bible(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_bible_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"story bible is not valid JSON: {e}") from e
    validate_bible(data)
    return data


def _generate_story(cfg: BookConfig, anchor: str,
                    generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_story_prompt(cfg, anchor))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"story is not valid JSON: {e}") from e
    validate_story(data, cfg.page_count)
    return data


def generate_picture_content(cfg: BookConfig,
                             generate_fn: Callable[[str], str]) -> dict:
    # One retry each: a transient LLM blip should not nuke the whole build
    # (same pattern as the standard strategy).
    try:
        bible = _generate_bible(cfg, generate_fn)
    except ContentError:
        bible = _generate_bible(cfg, generate_fn)
    # A config-locked art_style always wins so the look never drifts run to run.
    art_style = cfg.art_style or bible["art_style"]
    anchor = bible["character_anchor"]
    try:
        story = _generate_story(cfg, anchor, generate_fn)
    except ContentError:
        story = _generate_story(cfg, anchor, generate_fn)
    return {"character_anchor": anchor, "art_style": art_style,
            "dedication": bible["dedication"], "pages": story["pages"],
            "closing": story["closing"]}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd factory && pytest tests/test_picture_content.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/picture_content.py factory/tests/test_picture_content.py
git commit -m "feat(content): picture-book story bible + story-page generation"
```

---

## Task 3: Dispatch picture content from `generate_content`

**Files:**
- Modify: `factory/factory/content.py:58-68`
- Test: `factory/tests/test_content.py`

- [ ] **Step 1: Write failing test**

Add to `factory/tests/test_content.py`:

```python
import json
from factory.config import BookConfig
from factory.content import generate_content

def test_generate_content_dispatches_picture():
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="picture", pet_kind="dog", pet_name="Sunny",
                     page_count=4, trim_w=8.5, trim_h=8.5)
    bible = {"character_anchor": "a child and a golden dog",
             "art_style": "soft watercolor", "dedication": "For Sunny"}
    story = {"pages": [{"text": f"t{i}", "scene": f"s{i}"} for i in range(4)],
             "closing": "c"}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)
    out = generate_content(cfg, generate_fn=fake_llm)
    assert len(out["pages"]) == 4 and out["character_anchor"].startswith("a child")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd factory && pytest tests/test_content.py -k picture -v`
Expected: FAIL (journal path runs, missing `intro` key → ContentError).

- [ ] **Step 3: Implement**

In `factory/factory/content.py`, in `generate_content`, extend the dispatch at the top of the function:

```python
def generate_content(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    if cfg.book_type == "standard":
        from .standard_content import generate_standard_content
        return generate_standard_content(cfg, generate_fn)
    if cfg.book_type == "picture":
        from .picture_content import generate_picture_content
        return generate_picture_content(cfg, generate_fn)
    raw = generate_fn(build_prompt(cfg))
    ...
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd factory && pytest tests/test_content.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/content.py factory/tests/test_content.py
git commit -m "feat(content): dispatch picture book_type to picture_content"
```

---

## Task 4: Vision auditor adapter (`audit.py`)

**Files:**
- Create: `factory/factory/audit.py`
- Test: `factory/tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

Create `factory/tests/test_audit.py`:

```python
import json, pytest
from pathlib import Path
from factory.audit import (build_audit_prompt, parse_verdict, AuditError,
                           ClaudeVisionAuditor)

def test_build_audit_prompt_includes_image_anchor_scene():
    p = build_audit_prompt(anchor="a girl + golden dog", scene="by the window",
                           image_path=Path("/out/page_01.png"),
                           reference_path=Path("/out/reference.png"))
    assert "page_01.png" in p and "a girl + golden dog" in p
    assert "by the window" in p and "reference.png" in p

def test_parse_verdict_ok():
    v = parse_verdict('{"ok": true, "issues": []}')
    assert v == {"ok": True, "issues": []}

def test_parse_verdict_coerces_issues_and_strips_fences():
    v = parse_verdict('```json\n{"ok": false, "issues": ["dog colour wrong"]}\n```')
    assert v["ok"] is False and v["issues"] == ["dog colour wrong"]

def test_parse_verdict_rejects_missing_ok():
    with pytest.raises(AuditError):
        parse_verdict('{"issues": []}')

def test_auditor_uses_injected_judge_fn():
    seen = {}
    def fake_judge(prompt):
        seen["prompt"] = prompt
        return '{"ok": false, "issues": ["child hair differs"]}'
    auditor = ClaudeVisionAuditor(judge_fn=fake_judge)
    v = auditor.audit(Path("/out/page_02.png"), anchor="anchor",
                      reference_path=Path("/out/reference.png"), scene="garden")
    assert v["ok"] is False and v["issues"] == ["child hair differs"]
    assert "page_02.png" in seen["prompt"]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_audit.py -v`
Expected: FAIL (`No module named 'factory.audit'`).

- [ ] **Step 3: Implement**

Create `factory/factory/audit.py`:

```python
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
    ref = (f"\nRead the reference character sheet at {reference_path} — the child "
           f"and pet in the new image MUST match it." if reference_path else "")
    scene_line = f"\nIntended scene for this page: {scene}." if scene else ""
    return f"""Read the image file at {image_path} and judge it strictly.{ref}

The recurring characters must look like: {anchor}.{scene_line}

Reject (ok=false) if ANY of these is true:
- the child or the pet is NOT visually consistent with the reference/anchor
  (different hair, skin, age, breed, colour, or markings);
- any text, letters, words, or numbers are baked into the artwork;
- anatomy is deformed (bad faces, extra/missing limbs);
- the picture does not match the intended scene.
Be strict — if you are unsure, set ok=false.

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
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
              scene: str | None = None) -> dict:
        prompt = build_audit_prompt(
            anchor=anchor, scene=scene, image_path=Path(image_path),
            reference_path=Path(reference_path) if reference_path else None)
        return parse_verdict(self.judge_fn(prompt))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd factory && pytest tests/test_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/audit.py factory/tests/test_audit.py
git commit -m "feat(audit): claude vision auditor adapter + verdict parsing"
```

---

## Task 5: Square workflow variant for picture art

The base ComfyUI workflow emits a wide 1536×768 latent (sized for the cover wrap). Story pages and the reference sheet are **square**, so derive a square variant by class-type scan — robust to node-id changes, no new nodes/models.

**Files:**
- Modify: `factory/factory/art.py`
- Test: `factory/tests/test_art.py`

- [ ] **Step 1: Write failing test**

Add to `factory/tests/test_art.py`:

```python
from factory.art import square_workflow

def test_square_workflow_sets_square_dims_by_class_type():
    wf = {
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1536, "height": 768}},
        "10": {"class_type": "LatentUpscale", "inputs": {"width": 3072, "height": 1536}},
        "12": {"class_type": "ImageScale", "inputs": {"width": 5568, "height": 2784}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
    }
    sq = square_workflow(wf, base=1024, final=2048)
    assert sq["5"]["inputs"]["width"] == sq["5"]["inputs"]["height"] == 1024
    assert sq["10"]["inputs"]["width"] == sq["10"]["inputs"]["height"] == 2048
    assert sq["12"]["inputs"]["width"] == sq["12"]["inputs"]["height"] == 2048
    # original untouched (deep copy) and unrelated nodes preserved
    assert wf["5"]["inputs"]["width"] == 1536
    assert sq["6"]["inputs"]["text"] == "x"

def test_square_workflow_tolerates_missing_nodes():
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
    assert square_workflow(wf) == wf  # nothing to change, equal content
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd factory && pytest tests/test_art.py -k square -v`
Expected: FAIL (`cannot import name 'square_workflow'`).

- [ ] **Step 3: Implement**

In `factory/factory/art.py`, add after `inject_prompt`:

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd factory && pytest tests/test_art.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/art.py factory/tests/test_art.py
git commit -m "feat(art): square_workflow variant for picture illustrations"
```

---

## Task 6: Audited multi-image art loop (`generate_picture_art`)

Generate a reference sheet (audited vs. the anchor), then one audited illustration per page (vs. the reference sheet), regenerating with a fresh seed + the auditor's corrections up to a bound, then a wide cover illustration. Fail the build if any image can't pass within the bound.

**Files:**
- Modify: `factory/factory/art.py`
- Test: `factory/tests/test_art.py`

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_art.py`:

```python
import json
from pathlib import Path
from factory.config import BookConfig
from factory.art import generate_picture_art, ComfyClient, ArtError
import pytest

def _picture_cfg():
    return BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                      book_type="picture", pet_kind="dog", pet_name="Sunny",
                      page_count=2, trim_w=8.5, trim_h=8.5)

def _content():
    return {"character_anchor": "a girl and a golden dog",
            "art_style": "soft watercolor",
            "dedication": "For Sunny",
            "pages": [{"text": "t1", "scene": "garden"},
                      {"text": "t2", "scene": "window"}],
            "closing": "c"}

def _fake_comfy():
    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    return ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

class _Auditor:
    """Fail the first `fail_first` audits, then pass."""
    def __init__(self, fail_first=0): self.calls = 0; self.fail_first = fail_first
    def audit(self, image_path, *, anchor, reference_path=None, scene=None):
        self.calls += 1
        ok = self.calls > self.fail_first
        return {"ok": ok, "issues": [] if ok else ["dog colour off"]}

def test_generate_picture_art_writes_ref_pages_and_cover(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    art = generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                               wf, positive_node="6", sampler_node="3", seed=7,
                               auditor=_Auditor())
    assert Path(art["reference"]).name == "reference.png"
    assert [Path(p).name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert Path(art["cover"]).name == "art.png"
    for p in [art["reference"], *art["pages"], art["cover"]]:
        assert Path(p).exists()

def test_generate_picture_art_regenerates_until_consistent(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    auditor = _Auditor(fail_first=1)  # first audit (reference) fails, then all pass
    art = generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                               wf, positive_node="6", sampler_node="3", seed=7,
                               auditor=auditor)
    assert Path(art["reference"]).exists()
    assert auditor.calls >= 4  # 2 for ref (1 fail + 1 pass) + 2 pages

def test_generate_picture_art_fails_when_never_consistent(tmp_path):
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    auditor = _Auditor(fail_first=999)  # never passes
    with pytest.raises(ArtError, match="consistent"):
        generate_picture_art(_picture_cfg(), _content(), tmp_path, _fake_comfy(),
                             wf, positive_node="6", sampler_node="3", seed=7,
                             auditor=auditor, max_tries=3)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_art.py -k picture -v`
Expected: FAIL (`cannot import name 'generate_picture_art'`).

- [ ] **Step 3: Implement**

In `factory/factory/art.py`, add at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd factory && pytest tests/test_art.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/art.py factory/tests/test_art.py
git commit -m "feat(art): audited reference-sheet + per-page picture art loop"
```

---

## Task 7: Colour print economics + paper-aware spine width

Colour interiors print on white/colour stock (not cream), so both the **print cost** and the **spine-per-page** differ. Getting the spine wrong makes the existing cover-dimension guard reject the file. Thread a `book_type`-derived per-page value through `specs` and `cover`.

> NOTE: the colour print constants are rough estimates (KDP's exact colour pricing is verified per-book in its calculator — the checklist already frames royalty as "estimated"). The spine values are KDP's published per-page caliper for cream vs. white stock.

**Files:**
- Modify: `factory/factory/specs.py`, `factory/factory/cover.py`
- Test: `factory/tests/test_specs.py`, `factory/tests/test_cover.py`

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_specs.py`:

```python
from factory import specs

def test_white_spine_is_thinner_than_cream():
    assert specs.spine_per_page("picture") < specs.spine_per_page("journal")

def test_cover_dimensions_take_per_page():
    cream = specs.cover_dimensions_in(40, 8.5, 8.5, per_page=specs.SPINE_PER_PAGE_IN)
    white = specs.cover_dimensions_in(40, 8.5, 8.5,
                                      per_page=specs.SPINE_PER_PAGE_WHITE_IN)
    assert white[0] < cream[0]  # thinner spine -> narrower wrap

def test_colour_print_costs_more_than_bw():
    assert specs.printing_cost_usd(40, colour=True) > specs.printing_cost_usd(40)
```

Add to `factory/tests/test_cover.py` (or create if absent) — verify a square picture cover passes the dimension guard with white-paper spine:

```python
from factory.config import BookConfig
from factory.cover import build_cover

def test_picture_cover_dimensions_use_white_spine(tmp_path):
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A",
                     art_prompt="x", book_type="picture", pet_kind="dog",
                     pet_name="Sunny", page_count=26, trim_w=8.5, trim_h=8.5,
                     price_usd=10.99)
    (tmp_path / "art.png").write_bytes(b"\x89PNG")
    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            Path(args[2]).write_bytes(b"x")  # stub; guards skip non-PDF
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    from pathlib import Path
    pdf, jpg = build_cover(cfg, 26, tmp_path / "art.png", tmp_path,
                           runner=runner, make_ebook_cover=False)
    assert pdf.exists() and jpg is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_specs.py tests/test_cover.py -k "spine or colour or per_page or picture" -v`
Expected: FAIL (`spine_per_page` / `per_page` kwarg / `colour` kwarg missing).

- [ ] **Step 3: Implement**

In `factory/factory/specs.py`, add constants and generalise the functions:

```python
SPINE_PER_PAGE_IN = 0.0025          # cream paper
SPINE_PER_PAGE_WHITE_IN = 0.002252  # white / colour stock (thinner)
# Rough colour-print estimate (verify per-book in KDP's calculator):
PRINT_COLOUR_FIXED_USD = 1.00
PRINT_COLOUR_PER_PAGE_USD = 0.07


def spine_per_page(book_type: str = "journal") -> float:
    """Per-page spine caliper: colour picture books print on white/colour stock,
    which is thinner per sheet than the cream stock journals/standard use."""
    return SPINE_PER_PAGE_WHITE_IN if book_type == "picture" else SPINE_PER_PAGE_IN


def spine_width_in(pages: int, per_page: float = SPINE_PER_PAGE_IN) -> float:
    return round(pages * per_page, 4)


def cover_dimensions_in(pages: int, trim_w: float = TRIM_W_IN,
                        trim_h: float = TRIM_H_IN,
                        per_page: float = SPINE_PER_PAGE_IN) -> tuple[float, float]:
    spine = spine_width_in(pages, per_page)
    width = BLEED_IN + trim_w + spine + trim_w + BLEED_IN
    height = trim_h + 2 * BLEED_IN
    return (round(width, 4), round(height, 4))


def printing_cost_usd(pages: int, colour: bool = False) -> float:
    if colour:
        return round(PRINT_COLOUR_FIXED_USD + pages * PRINT_COLOUR_PER_PAGE_USD, 2)
    return round(PRINT_FIXED_USD + pages * PRINT_PER_PAGE_USD, 2)


def royalty_usd(price_usd: float, pages: int, colour: bool = False) -> float:
    return round(price_usd * ROYALTY_RATE - printing_cost_usd(pages, colour), 2)
```

In `factory/factory/cover.py`, thread the per-page value through the guards. Change the `build_cover` body to compute it once and pass it down:

```python
def build_cover(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                runner=None, make_ebook_cover: bool = True) -> tuple[Path, Path | None]:
    out_dir = Path(out_dir)
    per_page = specs.spine_per_page(cfg.book_type)
    wrap_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=False)
    width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h,
                                                    per_page)
    pdf = out_dir / "cover-paperback.pdf"
    html_to_pdf(wrap_html, pdf, width_in=width_in, height_in=height_in,
                margins_in=0.0, runner=runner, prefer_css_page_size=True)
    _verify_cover_pdf(pdf, [cfg.title, cfg.subtitle, cfg.author, book_blurb(cfg)])
    _verify_cover_dimensions(pdf, pages, cfg.trim_w, cfg.trim_h, per_page=per_page)
    _verify_cover_background(pdf)
    _verify_cover_no_white_edge(pdf)
    _verify_cover_text_zones(pdf, pages, cfg.trim_w, per_page=per_page)
    if not make_ebook_cover:
        return pdf, None
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg
```

Add a `per_page` parameter (default `specs.SPINE_PER_PAGE_IN`) to `_verify_cover_dimensions`, `_verify_cover_text_zones`, and `_compose_wrap_bg`, and use it wherever they currently call `specs.spine_width_in(pages)` / `specs.cover_dimensions_in(...)`. Concretely:

- `_verify_cover_dimensions(pdf, pages, trim_w=..., trim_h=..., per_page=specs.SPINE_PER_PAGE_IN, tol_in=0.05)`: change the expected dims line to
  `exp_w, exp_h = specs.cover_dimensions_in(pages, trim_w, trim_h, per_page)` and the spine note to `specs.spine_width_in(pages, per_page)`.
- `_verify_cover_text_zones(pdf, pages, trim_w=..., per_page=specs.SPINE_PER_PAGE_IN, inset_in=0.2)`: change `spine_c = spine_l + specs.spine_width_in(pages, per_page) / 2`.
- `render_cover_html` computes wrap dims for the background compose — update its non-`front_only` branch:
  `per_page = specs.spine_per_page(cfg.book_type)` then
  `width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h, per_page)`.
- `_compose_wrap_bg(...)` does not use the spine directly (it positions by `trim_w`), so no spine change is needed there.

- [ ] **Step 4: Run tests, verify pass**

Run: `cd factory && pytest tests/test_specs.py tests/test_cover.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/specs.py factory/factory/cover.py factory/tests/test_specs.py factory/tests/test_cover.py
git commit -m "feat(specs,cover): colour print cost + paper-aware spine width"
```

---

## Task 8: Picture interior template + render selection + page-count guard

**Files:**
- Create: `factory/templates/interior/picture.html.j2`
- Modify: `factory/factory/interior.py`
- Test: `factory/tests/test_picture_interior.py`

- [ ] **Step 1: Write failing tests**

Create `factory/tests/test_picture_interior.py`:

```python
from pathlib import Path
from factory.config import BookConfig
from factory.interior import render_interior_html, InteriorError, _verify_picture_page_count
import pytest

def _cfg():
    return BookConfig(slug="k", title="Sunny's Last Walk", subtitle="S", author="A",
                      art_prompt="x", book_type="picture", pet_kind="dog",
                      pet_name="Sunny", page_count=2, trim_w=8.5, trim_h=8.5)

def _content():
    return {"character_anchor": "a", "art_style": "s", "dedication": "For Sunny",
            "pages": [{"text": "We walked every morning.", "scene": "garden"},
                      {"text": "Now the leash hangs still.", "scene": "hallway"}],
            "closing": "Love stays."}

def test_picture_interior_has_image_per_page_and_text(tmp_path):
    html_path = render_interior_html(_cfg(), _content(), tmp_path)
    html = html_path.read_text(encoding="utf-8")
    assert 'page_01.png' in html and 'page_02.png' in html
    assert "We walked every morning." in html
    assert "For Sunny" in html and "Love stays." in html
    # no fill-in ruled lines in a picture book
    assert 'class="lines"' not in html

def test_picture_page_count_guard_rejects_under_24():
    with pytest.raises(InteriorError, match="24"):
        _verify_picture_page_count(20)

def test_picture_page_count_guard_rejects_odd():
    with pytest.raises(InteriorError, match="even"):
        _verify_picture_page_count(25)

def test_picture_page_count_guard_accepts_even_min():
    _verify_picture_page_count(24)  # no raise
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_picture_interior.py -v`
Expected: FAIL (`_verify_picture_page_count` missing; template missing).

- [ ] **Step 3: Implement template**

Create `factory/templates/interior/picture.html.j2`:

```jinja
<!doctype html><html><head><meta charset="utf-8">
<style>
  @page { size: {{ "%g"|format(cfg.trim_w) }}in {{ "%g"|format(cfg.trim_h) }}in; margin: 0; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: Georgia, "Times New Roman", serif; color: #2b2b2b; }
  .pp { width: {{ "%g"|format(cfg.trim_w) }}in; height: {{ "%g"|format(cfg.trim_h) }}in;
        padding: 0.5in; page-break-after: always; display: flex; flex-direction: column;
        align-items: center; justify-content: center; text-align: center; }
  .pp img { max-width: 100%; max-height: 6.4in; object-fit: contain; }
  .caption { margin-top: 0.35in; font-size: 18pt; line-height: 1.5; max-width: 6.2in; }
  .title-main { font-size: 34pt; margin: 0 0 0.2in; }
  .title-sub { font-size: 16pt; font-style: italic; }
  .byline { margin-top: 0.6in; font-size: 14pt; }
  .ded { font-size: 18pt; font-style: italic; }
  .copyright { justify-content: flex-end; font-size: 9pt; color: #666; text-align: left;
               align-items: flex-start; line-height: 1.6; }
</style></head><body>

<section class="pp"><h1 class="title-main">{{ cfg.title }}</h1>
  <p class="title-sub">{{ cfg.subtitle }}</p>
  <p class="byline">{{ cfg.author }}</p></section>

<section class="pp copyright">
  <p>{{ cfg.title }}<br>Copyright &copy; {{ cfg.author }}. All rights reserved.<br>
  No part of this book may be reproduced without permission.</p></section>

<section class="pp"><p class="ded">{{ content.dedication }}</p></section>

{% for page in content.pages %}
<section class="pp">
  <img src="page_{{ "%02d"|format(loop.index) }}.png" alt="">
  <p class="caption">{{ page.text }}</p>
</section>
{% endfor %}

<section class="pp"><p class="caption">{{ content.closing }}</p></section>

</body></html>
```

- [ ] **Step 4: Implement render selection + guard**

In `factory/factory/interior.py`:

In `render_interior_html`, extend the template selection:

```python
def render_interior_html(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = {"standard": "interior/standard.html.j2",
                "picture": "interior/picture.html.j2"}.get(
                    cfg.book_type, "interior/journal.html.j2")
    html = render(template, cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path
```

Add a constant and guard near the top (after `class InteriorError`):

```python
MIN_PICTURE_PAGES = 24  # KDP paperback minimum


def _verify_picture_page_count(pages: int) -> None:
    """KDP rejects paperbacks under 24 pages, and a wrap needs an even leaf count."""
    if pages < MIN_PICTURE_PAGES:
        raise InteriorError(
            f"Picture interior rendered {pages} pages — KDP requires at least "
            f"{MIN_PICTURE_PAGES}. Increase page_count or front/back matter.")
    if pages % 2 != 0:
        raise InteriorError(
            f"Picture interior rendered an odd page count ({pages}); a printed "
            f"book needs an even number of leaves. Adjust page_count/matter.")
```

In `build_interior_pdf`, make the picture type use the real PDF page count and run the guard. Change the page-count block:

```python
    pages = (pdf_page_count(pdf) if book_type in ("standard", "picture")
             else count_pages(html_path))
    if book_type == "standard" and pages < 1:
        raise InteriorError(
            f"Standard interior {pdf.name} rendered 0 pages — the PDF failed to "
            f"open or is empty; the cover spine width would be wrong.")
    if book_type == "picture":
        _verify_picture_page_count(pages)
    return pdf, pages
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd factory && pytest tests/test_picture_interior.py tests/test_interior.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add factory/templates/interior/picture.html.j2 factory/factory/interior.py factory/tests/test_picture_interior.py
git commit -m "feat(interior): framed colour picture template + 24-page/even guard"
```

---

## Task 9: Picture blurb, categories, and colour checklist

**Files:**
- Modify: `factory/factory/copy.py`, `factory/factory/checklist.py`, `factory/templates/checklist.md.j2`
- Test: `factory/tests/test_copy.py`, `factory/tests/test_checklist.py`

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_copy.py`:

```python
from factory.config import BookConfig
from factory.copy import book_blurb

def test_picture_blurb_mentions_child_and_pet():
    cfg = BookConfig(slug="k", title="T", subtitle="S", author="A", art_prompt="x",
                     book_type="picture", pet_kind="dog", pet_name="Sunny",
                     page_count=22, trim_w=8.5, trim_h=8.5)
    b = book_blurb(cfg)
    assert "dog" in b.lower() and ("child" in b.lower() or "little" in b.lower())
```

Add to `factory/tests/test_checklist.py`:

```python
import json
from pathlib import Path
from factory.config import load_config
from factory.checklist import make_checklist

def test_picture_checklist_is_colour_and_juvenile(tmp_path):
    cfgp = tmp_path / "k.config.json"
    cfgp.write_text(json.dumps({
        "slug": "k", "title": "T", "subtitle": "S", "author": "A", "art_prompt": "x",
        "book_type": "picture", "pet_kind": "dog", "pet_name": "Sunny",
        "page_count": 26, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99}),
        encoding="utf-8")
    cfg = load_config(cfgp)
    out = make_checklist(cfg, 26, tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "Color" in text  # interior is colour, not "Black & white"
    assert "Juvenile" in text  # juvenile category, not Self-Help
    assert "cream" not in text.lower()  # colour books print on white stock
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd factory && pytest tests/test_copy.py tests/test_checklist.py -k picture -v`
Expected: FAIL (journal blurb returned; checklist still says "Black & white"/"cream"/"Self-Help").

- [ ] **Step 3: Implement copy**

In `factory/factory/copy.py`, add a picture branch before the journal default:

```python
def book_blurb(cfg: BookConfig) -> str:
    if cfg.book_type == "standard":
        return cfg.blurb or cfg.synopsis
    if cfg.book_type == "picture":
        return cfg.blurb or (
            f"A gentle, beautifully illustrated picture book for a little one saying "
            f"goodbye to a beloved {cfg.pet_kind}. Through a child's eyes and soft, "
            f"tender pictures, it holds space for big feelings and helps a family "
            f"remember {cfg.pet_name} with love. A comforting read-aloud and a "
            f"caring gift.")
    return (f"A gentle, guided journal to help you grieve and remember your beloved "
            f"{cfg.pet_kind}. Undated reflective prompts, memory pages, and milestone "
            f"reflections give you a private space to process loss at your own pace. "
            f"A comforting keepsake and a thoughtful gift.")
```

- [ ] **Step 4: Implement checklist keywords**

In `factory/factory/checklist.py`, add a picture branch at the top of `_keywords`:

```python
def _keywords(cfg: BookConfig) -> str:
    if cfg.book_type == "picture":
        base = [f"{cfg.pet_kind} loss children's book",
                f"pet loss book for kids", "grief picture book",
                f"death of a {cfg.pet_kind} kids", "rainbow bridge children",
                "memorial gift child", "saying goodbye pet"]
        return ", ".join(base[:7])
    if cfg.book_type == "standard":
        ...
```

And pass a `colour` flag into the template render. Change `make_checklist`:

```python
    md = render("checklist.md.j2",
                cfg=cfg, pages=pages,
                spine=specs.spine_width_in(pages, specs.spine_per_page(cfg.book_type)),
                royalty=specs.royalty_usd(cfg.price_usd, pages,
                                          colour=cfg.book_type == "picture"),
                print_cost=specs.printing_cost_usd(pages,
                                                   colour=cfg.book_type == "picture"),
                keywords=_keywords(cfg))
```

- [ ] **Step 5: Implement checklist template**

In `factory/templates/checklist.md.j2`:

Replace the **Files to upload** interior line so picture books don't say "cream":

```jinja
- Paperback interior: `interior.pdf` ({{ pages }} pages, {{ "%g"|format(cfg.trim_w) }}x{{ "%g"|format(cfg.trim_h) }}", {% if cfg.book_type == "picture" %}colour{% else %}cream{% endif %})
```

Replace the **Description** block's `else` (journal) branch to add a picture branch:

```jinja
{%- if cfg.book_type == "standard" %}
  <p>{{ cfg.blurb or cfg.synopsis }}</p>
{%- elif cfg.book_type == "picture" %}
  <p>{{ cfg.blurb or "A gentle, beautifully illustrated picture book for a child saying goodbye to a beloved " ~ cfg.pet_kind ~ ", helping a family remember " ~ cfg.pet_name ~ " with love." }}</p>
{%- else %}
  <p>A gentle, guided journal to help you grieve and remember your beloved {{ cfg.pet_kind }}.
  Undated reflective prompts, memory pages, and milestone reflections give you a private
  space to process loss at your own pace. A comforting keepsake and a thoughtful gift.</p>
{%- endif %}
```

Replace the **Paperback print settings** Interior + Paper lines with a colour-aware block:

```jinja
{%- if cfg.book_type == "picture" %}
- **Interior:** Standard Color (full-colour illustrations)
- **Paper:** White — ⚠ select white; the spine width ({{ spine }}in) was computed for white/colour stock.
{%- else %}
- **Interior:** Black & white
- **Paper:** Cream  — ⚠ must select cream; the spine width ({{ spine }}in) was computed for cream stock. White paper is thinner and KDP will reject the cover.
{%- endif %}
```

Replace the **Categories** block to add a picture branch:

```jinja
## Categories (choose 2)
{%- if cfg.book_type == "standard" %}
1. Self-Help › Death & Grief
2. Family & Relationships › Death, Grief, Bereavement
{%- elif cfg.book_type == "picture" %}
1. Children's Books › Growing Up & Facts of Life › Difficult Discussions › Death & Dying
2. Children's Books › Animals › Dogs   (Juvenile Nonfiction/Fiction › Social Themes › Death & Dying)
{%- else %}
1. Self-Help › Death & Grief
2. Self-Help › Journaling   (or Crafts, Hobbies & Home › {{ cfg.pet_kind|capitalize }} care)
{%- endif %}
```

- [ ] **Step 6: Run tests, verify pass**

Run: `cd factory && pytest tests/test_copy.py tests/test_checklist.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add factory/factory/copy.py factory/factory/checklist.py factory/templates/checklist.md.j2 factory/tests/test_copy.py factory/tests/test_checklist.py
git commit -m "feat(checklist,copy): colour/white print settings + juvenile categories for picture"
```

---

## Task 10: Wire the picture branch into `build.py` (art before interior)

**Files:**
- Modify: `factory/build.py`, `factory/tests/conftest.py`, `factory/tests/test_build.py`
- Test: `factory/tests/test_build.py`

- [ ] **Step 1: Add picture fixtures**

In `factory/tests/conftest.py`, add:

```python
@pytest.fixture
def picture_config_dict():
    return {
        "slug": "dog-loss-kids",
        "title": "Sunny's Last Walk",
        "subtitle": "A Gentle Goodbye to a Beloved Dog",
        "author": "Eleanor Hartley",
        "book_type": "picture",
        "pet_kind": "dog",
        "pet_name": "Sunny",
        "page_count": 2,
        "art_prompt": "soft storybook watercolor cover, a child and a golden dog",
        "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }


@pytest.fixture
def picture_content():
    return {
        "character_anchor": "a small girl with short brown hair and a golden retriever",
        "art_style": "soft flat storybook watercolor, muted palette, soft edges",
        "dedication": "For Sunny, our best friend.",
        "pages": [{"text": "We walked every morning, Sunny and me.", "scene": "garden path at dawn"},
                  {"text": "Now the leash hangs still by the door.", "scene": "quiet hallway, leash on a hook"}],
        "closing": "Love does not leave. It stays, soft and warm, forever.",
    }
```

- [ ] **Step 2: Write failing test**

Add to `factory/tests/test_build.py`:

```python
from factory.audit import ClaudeVisionAuditor  # noqa: F401 (import sanity)

def test_picture_build_paperback_only_with_pages(tmp_path, picture_config_dict, picture_content):
    cfgp = tmp_path / "book.config.json"
    cfgp.write_text(json.dumps(picture_config_dict), encoding="utf-8")

    bible = {"character_anchor": picture_content["character_anchor"],
             "art_style": picture_content["art_style"],
             "dedication": picture_content["dedication"]}
    story = {"pages": picture_content["pages"], "closing": picture_content["closing"]}
    def fake_llm(prompt):
        return json.dumps(bible) if "STORY BIBLE" in prompt else json.dumps(story)

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    class FakeAuditor:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None):
            return {"ok": True, "issues": []}

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            target = Path(args[2])
            if target.name == "interior.pdf":
                import fitz
                d = fitz.open()
                for _ in range(26):   # >= 24, even, for the picture page guard
                    d.new_page()
                d.save(str(target)); d.close()
            else:
                target.write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    workflow = {"5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1536, "height": 768}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}

    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, workflow=workflow, positive_node="6",
                        sampler_node="3", runner=runner, auditor=FakeAuditor())
    for f in ["content.json", "reference.png", "page_01.png", "page_02.png",
              "art.png", "interior.pdf", "cover-paperback.pdf", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
    assert not (Path(out_dir) / "interior.epub").exists()
    assert not (Path(out_dir) / "cover-ebook.jpg").exists()
```

- [ ] **Step 3: Run test, verify it fails**

Run: `cd factory && pytest tests/test_build.py -k picture -v`
Expected: FAIL (`run_build` has no `auditor` kwarg; no picture branch).

- [ ] **Step 4: Implement**

In `factory/build.py`:

Add imports:

```python
from factory.art import ComfyClient, generate_picture_art
from factory.audit import ClaudeVisionAuditor
```

Change the `run_build` signature to accept an injected auditor:

```python
def run_build(config_path, out_root="out", *, generate_fn=claude_generate,
              comfy=None, workflow=None, positive_node="6", sampler_node="3",
              runner=None, seed=DEFAULT_SEED, auditor=None) -> Path:
```

Replace stages ②–③ (interior then art) with a branch. After writing `content.json` and resolving `comfy`/`workflow` (move the comfy/workflow defaulting block to BEFORE the interior so picture can use it), use:

```python
    # Resolve image backend + workflow up front (picture needs art before interior).
    if comfy is None:
        comfy = ComfyClient()
    if workflow is None:
        workflow = json.loads((Path(__file__).parent / "comfyui" / "workflow.template.json")
                              .read_text(encoding="utf-8"))
    if "REPLACE_WITH_YOUR_CHECKPOINT" in json.dumps(workflow):
        raise SystemExit(
            "ComfyUI workflow still has the placeholder checkpoint. Edit "
            "comfyui/workflow.template.json and set ckpt_name to a real checkpoint "
            "from your ComfyUI install before running the factory.")

    if cfg.book_type == "picture":
        # Picture books illustrate every page, so art runs BEFORE the interior
        # (the interior embeds page_NN.png). Consistency is enforced by the auditor.
        if auditor is None:
            auditor = ClaudeVisionAuditor()
        art = generate_picture_art(cfg, content, out_dir, comfy, workflow,
                                   positive_node=positive_node,
                                   sampler_node=sampler_node, seed=seed,
                                   auditor=auditor)
        html = render_interior_html(cfg, content, out_dir)
        _, pages = build_interior_pdf(html, out_dir, runner=runner,
                                      book_type=cfg.book_type,
                                      trim_w=cfg.trim_w, trim_h=cfg.trim_h)
        art_path = art["cover"]
    else:
        html = render_interior_html(cfg, content, out_dir)
        _, pages = build_interior_pdf(html, out_dir, runner=runner,
                                      book_type=cfg.book_type,
                                      trim_w=cfg.trim_w, trim_h=cfg.trim_h)
        art_path = comfy.generate(workflow, positive_node=positive_node,
                                  sampler_node=sampler_node, prompt=cfg.art_prompt,
                                  seed=seed, out_path=out_dir / "art.png")
```

Leave stages ④ (cover) and ⑤ (checklist) unchanged below this block. Remove the now-duplicated old comfy/workflow defaulting that previously sat in stage ③.

- [ ] **Step 5: Run test, verify pass**

Run: `cd factory && pytest tests/test_build.py -v`
Expected: PASS (journal, standard, and picture builds).

- [ ] **Step 6: Run the whole suite**

Run: `cd factory && pytest -q`
Expected: PASS — all prior tests plus the new picture tests.

- [ ] **Step 7: Commit**

```bash
git add factory/build.py factory/tests/conftest.py factory/tests/test_build.py
git commit -m "feat(build): picture branch — art before interior, injected auditor"
```

---

## Task 11: First title config + README/candidates note

**Files:**
- Create: `factory/books/dog-loss-kids.config.json`
- Modify: `candidates.md`
- Test: `factory/tests/test_config.py` (load the real config file)

- [ ] **Step 1: Write failing test**

Add to `factory/tests/test_config.py`:

```python
from pathlib import Path
from factory.config import load_config

def test_dog_loss_kids_config_is_valid():
    p = Path(__file__).resolve().parent.parent / "books" / "dog-loss-kids.config.json"
    cfg = load_config(p)
    assert cfg.book_type == "picture" and cfg.pet_kind == "dog"
    assert cfg.trim_w == 8.5 and cfg.trim_h == 8.5
    assert cfg.page_count >= 20 and cfg.page_count % 2 == 0
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd factory && pytest tests/test_config.py -k dog_loss_kids -v`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Create the config**

Create `factory/books/dog-loss-kids.config.json`:

```json
{
  "slug": "dog-loss-kids",
  "book_type": "picture",
  "title": "The Morning Walk",
  "subtitle": "A Gentle Goodbye to a Beloved Dog",
  "author": "Eleanor Hartley",
  "pet_kind": "dog",
  "pet_name": "Biscuit",
  "page_count": 22,
  "art_style": "soft flat storybook watercolour, muted warm palette, gentle soft edges, simple iconic shapes, picture-book illustration, no text, no words, no letters",
  "art_prompt": "soft storybook watercolour front cover, a small child and a gentle golden dog sitting together on a grassy hill at warm sunset, tender and hopeful, no text, no words",
  "trim_w": 8.5,
  "trim_h": 8.5,
  "price_usd": 10.99,
  "blurb": "When a beloved dog is gone, a child's heart has big questions and even bigger feelings. Through a little one's eyes and soft, tender watercolours, this gentle read-aloud walks a family from the ache of goodbye toward remembering Biscuit with warmth and love. A comforting picture book and a caring gift for any child saying farewell to a faithful friend."
}
```

- [ ] **Step 4: Run test, verify pass**

Run: `cd factory && pytest tests/test_config.py -k dog_loss_kids -v`
Expected: PASS.

- [ ] **Step 5: Update `candidates.md` production status**

In `candidates.md`, under the production-status bullet list, add a third line after the standard-prose entry:

```markdown
- **Children's picture book (NEW):** *The Morning Walk — A Gentle Goodbye to a
  Beloved Dog* — a full-colour 8.5×8.5 framed picture book (ages 4–8), paperback,
  $10.99. First title off the new `picture` book_type: a frozen character anchor,
  a generated character reference sheet, and a vision auditor that regenerates any
  off-model illustration. Third format in the dog sub-line (journal + companion +
  kids' book).
```

- [ ] **Step 6: Commit**

```bash
git add factory/books/dog-loss-kids.config.json candidates.md factory/tests/test_config.py
git commit -m "feat(title): first picture book — The Morning Walk (dog kids' book)"
```

---

## Task 12: Documentation — README pipeline note

**Files:**
- Modify: `README.md`, `factory/README.md`

- [ ] **Step 1: Update root README**

In `README.md`, update the book-types sentence (the paragraph beginning "The pipeline builds two kinds of book") to describe three types, and note the picture pipeline's art-before-interior order + the vision auditor. Add to the prose:

```markdown
A **third** `book_type` builds **children's picture books**: a full-colour,
framed 8.5×8.5 paperback where every page is illustrated. Because the art is the
content, the picture pipeline runs **art before the interior**, and a **vision
auditor** checks each illustration against a generated character reference sheet —
regenerating any that drift off-model so the child and pet stay consistent across
the book. Still one config + one command.
```

- [ ] **Step 2: Update factory README**

In `factory/README.md`, add `picture` to the list of book types and note the extra dependency: the auditor uses the `claude` CLI's vision/file-reading in print mode (already a dependency for content), and ComfyUI must be live (it generates ~`page_count`+2 images per build, so expect a longer run than a single-cover title). Add a one-line build example:

```markdown
`python build.py books/dog-loss-kids.config.json` builds the picture book
(ComfyUI must be running; it renders a reference sheet, one illustration per
page, and the cover — each audited for character consistency).
```

- [ ] **Step 3: Run the full suite once more**

Run: `cd factory && pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 4: Commit**

```bash
git add README.md factory/README.md
git commit -m "docs: document the picture book_type (art-before-interior + vision auditor)"
```

---

## Manual end-to-end (real build, not in tests)

The test suite uses fakes (no GPU/CLI). The real proof needs ComfyUI live and the
`claude` CLI authenticated. Per the user's environment note, check VRAM first
(ComfyUI shares the GPU with video gen):

```powershell
cd factory ; .\.venv\Scripts\Activate.ps1
python build.py books/dog-loss-kids.config.json
```

Then inspect `out/dog-loss-kids/`: open `reference.png`, the `page_NN.png` set, and
`interior.pdf` to eyeball character consistency; open `cover-paperback.pdf` in KDP's
Print Previewer; follow `upload-checklist.md`. If the auditor's reject rate is high
(builds stall on regeneration), that is the documented signal to consider Approach B
(IPAdapter reference conditioning) from the spec — out of scope for this plan.

---

## Self-review notes (addressed)

- **Spec coverage:** book_type (T1), frozen anchor + bible (T2), dispatch (T3),
  vision auditor adapter (T4), square output (T5), reference sheet + audited
  regenerate-then-fail loop (T6), colour economics + paper-aware spine (T7),
  framed colour interior + ≥24/even guard (T8), blurb/categories/colour checklist
  (T9), art-before-interior build wiring (T10), first title + paperback-only (T11),
  docs (T12). No in-book AI-disclosure page (T8 template omits it).
- **Guards present:** audit-or-fail (T6), illustration count == pages (implicit:
  the interior references `page_NN.png` for each of `page_count`; a missing image
  renders a broken `<img>` but the page still prints — the audit loop guarantees
  each file exists before interior runs), ≥24/even page count (T8), paper-aware
  cover-dimension guard reused (T7).
- **Type consistency:** `auditor.audit(image_path, *, anchor, reference_path,
  scene) -> {"ok", "issues"}` is identical in T4, T6, T10. `square_workflow`,
  `generate_picture_art`, `spine_per_page`, `_verify_picture_page_count` names
  match across tasks.
```

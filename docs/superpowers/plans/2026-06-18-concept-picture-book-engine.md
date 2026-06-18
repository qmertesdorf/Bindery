# Concept (character-free) picture book engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `concept` book_type — a character-free, style-locked illustrated picture book that builds with no LoRA — wired end-to-end through config, content, Flux art, audit, interior, and build.

**Architecture:** A sibling of the existing `picture` type. Reuses the Flux graph (`flux_lora_workflow` with an empty LoRA stack), the audit/keep-best loop, the picture interior template, the overscan cover, and the checklist. Content is subject-driven (`{subject, text, scene}` per spread), not the grief/comfort character arc. Style cohesion comes from a locked `flux_style` + `flux_guidance` + sampler (no character identity to enforce).

**Tech Stack:** Python 3, pytest (run from `factory/` via `.venv/Scripts/python -m pytest`), Jinja2 interior, ComfyUI/Flux for art (faked in tests).

**Spec:** `docs/superpowers/specs/2026-06-18-concept-picture-book-design.md`

**Conventions:**
- All test commands run from the `factory/` directory: `cd factory` first (the persisted Bash cwd may drift — use the full `cd 'C:\Users\quint\git\book-gen\factory'` if unsure).
- Test runner: `.venv/Scripts/python -m pytest <args>`.
- After each task the FULL suite must stay green: `.venv/Scripts/python -m pytest -q`.

---

### Task 1: Config — `concept` book_type + validation

**Files:**
- Modify: `factory/factory/config.py`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `factory/tests/test_config.py` (follow the existing helper that writes a temp config; if the file uses a `write_cfg(tmp_path, data)` helper, reuse it — otherwise write the JSON with `tmp_path` and call `load_config`):

```python
def _concept_data(**over):
    data = {
        "slug": "tiny-creatures",
        "book_type": "concept",
        "art_engine": "flux",
        "title": "Tiny Creatures",
        "subtitle": "A First Look at Little Animals",
        "author": "Eleanor Hartley",
        "subject": "small animals and where they live",
        "flux_style": "soft storybook watercolour, warm natural palette, no text",
        "art_prompt": "a sunlit meadow full of small creatures, soft storybook watercolour, no text",
        "page_count": 22,
        "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }
    data.update(over)
    return data


def test_concept_config_loads(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data()), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.book_type == "concept"
    assert cfg.subject == "small animals and where they live"
    assert cfg.art_engine == "flux"
    assert cfg.makes_ebook is False


def test_concept_config_topics_parsed(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(topics=["a fox", "a snail"])), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.topics == ("a fox", "a snail")


def test_concept_requires_subject(tmp_path):
    p = tmp_path / "c.json"
    d = _concept_data(); d.pop("subject")
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ConfigError, match="subject"):
        load_config(p)


def test_concept_requires_flux_engine(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(art_engine="sdxl")), encoding="utf-8")
    with pytest.raises(ConfigError, match="flux"):
        load_config(p)


def test_concept_requires_flux_style(tmp_path):
    p = tmp_path / "c.json"
    d = _concept_data(); d.pop("flux_style")
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ConfigError, match="flux_style"):
        load_config(p)


def test_concept_page_count_floor(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(_concept_data(page_count=18)), encoding="utf-8")
    with pytest.raises(ConfigError, match="page_count"):
        load_config(p)
```

Ensure `json`, `pytest`, `load_config`, `ConfigError` are imported at the top of the test file (they are used by existing tests — reuse those imports).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -q`
Expected: FAIL — `concept` not in `BOOK_TYPES` (ConfigError "book_type must be one of …"), and `cfg.subject`/`cfg.topics` attributes missing.

- [ ] **Step 3: Implement config support**

In `factory/factory/config.py`:

Add `"concept"` to `BOOK_TYPES`:
```python
BOOK_TYPES = ("journal", "standard", "picture", "concept")
```

Add two fields to the `BookConfig` dataclass (place near the picture-only fields):
```python
    subject: str = ""                 # concept only — the book's subject
    topics: tuple = ()                # concept only — explicit per-spread subjects
```

Add a validation branch in `load_config` (after the `picture` branch, before the `trim_w` lines):
```python
    if book_type == "concept":
        if not data.get("subject"):
            raise ConfigError(f"{path}: concept books require 'subject'")
        if art_engine != "flux":
            raise ConfigError(
                f"{path}: concept books require art_engine 'flux', got {art_engine!r}")
        if not data.get("flux_style"):
            raise ConfigError(f"{path}: concept books require 'flux_style'")
        pc = int(data.get("page_count", 0))
        if pc < 20 or pc % 2 != 0:
            raise ConfigError(
                f"{path}: concept 'page_count' must be even and >= 20; got {pc}")
```

Pass the new fields to the `BookConfig(...)` constructor at the end of `load_config`:
```python
        subject=str(data.get("subject", "")),
        topics=tuple(str(t) for t in (data.get("topics", []) or [])),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -q`
Expected: PASS (all new tests green, existing config tests still green).

- [ ] **Step 5: Commit**

```bash
git add factory/factory/config.py factory/tests/test_config.py
git commit -m "feat(config): concept book_type (character-free, flux-only) with validation"
```

---

### Task 2: Audit — concept verdict mode + thread `audit_kind`

**Files:**
- Modify: `factory/factory/audit.py`
- Modify: `factory/factory/art.py` (`run_audited_render`)
- Modify (fakes): `factory/tests/test_art.py`, `factory/tests/test_build.py`, `factory/tests/test_flux_art.py`
- Test: `factory/tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

Add to `factory/tests/test_audit.py`:

```python
from factory.audit import build_concept_audit_prompt, ClaudeVisionAuditor


def test_concept_audit_prompt_is_character_free():
    prompt = build_concept_audit_prompt(
        anchor="a red fox in a meadow; no people, no text",
        scene="a fox sitting in tall grass at dawn",
        image_path=Path("/out/page_01.png"))
    assert "no people" in prompt.lower()
    assert "/out/page_01.png" in prompt
    # concept books must not carry the character-identity rules
    assert "outfit" not in prompt.lower()


def test_auditor_kind_selects_concept_prompt():
    captured = {}
    def judge(prompt):
        captured["prompt"] = prompt
        return '{"ok": true, "issues": []}'
    auditor = ClaudeVisionAuditor(judge_fn=judge)
    v = auditor.audit(Path("/out/page_01.png"), anchor="a red fox", scene="a fox",
                      kind="concept")
    assert v["ok"] is True
    assert "no people" in captured["prompt"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_audit.py -q`
Expected: FAIL — `build_concept_audit_prompt` does not exist; `audit()` has no `kind` param.

- [ ] **Step 3: Implement concept audit**

In `factory/factory/audit.py`, add the concept prompt builder (after `build_audit_prompt`):

```python
def build_concept_audit_prompt(*, anchor: str, scene: str | None,
                               image_path: Path) -> str:
    scene_line = f"\nThis page is meant to depict, roughly: {scene}." if scene else ""
    return f"""Read the image file at {image_path} and judge it for a character-free
children's picture book.

This page should show: {anchor}.{scene_line}

This is a soft, stylised storybook, so judge GENEROUSLY. Apply a two-tier bar.

REJECT (set ok=false) ONLY for a real defect that would break the book:
- the WRONG subject (a clearly different animal or thing than described above);
- ANY people or human figures appear (this book has no people);
- any text, letters, words, or numbers are rendered in the artwork;
- broken anatomy (malformed faces, extra or missing limbs/eyes);
- the art is clearly the wrong medium (photographic, cluttered collage, or
  otherwise not a soft storybook illustration).

ACCEPT (set ok=true) — do NOT reject — for natural variation:
- different pose, camera angle, framing, or composition;
- a different or simpler background, lighting, time of day, or season;
- extra incidental natural scenery (plants, sky, water) around the subject;
- stylistic differences that still read as the same soft storybook look.

When the subject is right and the art is clean, set ok=true even if such details
differ. Reserve issues for genuine defects.

Return ONLY JSON: {{"ok": true|false, "issues": ["short reason", ...]}}
Output the JSON and nothing else."""
```

Update `ClaudeVisionAuditor.audit` to select the prompt by `kind`:

```python
    def audit(self, image_path, *, anchor: str, reference_path=None,
              scene: str | None = None, kind: str = "character") -> dict:
        if kind == "concept":
            prompt = build_concept_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path))
        else:
            prompt = build_audit_prompt(
                anchor=anchor, scene=scene, image_path=Path(image_path),
                reference_path=Path(reference_path) if reference_path else None)
        return parse_verdict(self.judge_fn(prompt))
```

In `factory/factory/art.py`, thread `audit_kind` through `run_audited_render`:

```python
def run_audited_render(render, prompt, *, out_path, auditor, anchor, scene,
                       reference_path=None, seed=0, max_tries=4,
                       audit_kind="character") -> Path:
```

and change the audit call (the line near `verdict = auditor.audit(...)`):

```python
        verdict = auditor.audit(out_path, anchor=anchor,
                                reference_path=reference_path, scene=scene,
                                kind=audit_kind)
```

- [ ] **Step 4: Update the existing test fakes to accept `kind`**

The real auditor interface now passes `kind`. Update each fake's `audit` signature so it still matches. In `factory/tests/test_art.py` (≈line 84), `factory/tests/test_build.py` (≈lines 102 and 165), and `factory/tests/test_flux_art.py` (≈line 113), change:

```python
    def audit(self, image_path, *, anchor, reference_path=None, scene=None):
```
to:
```python
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character"):
```

(Leave each fake's body unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_audit.py tests/test_art.py tests/test_build.py tests/test_flux_art.py -q`
Expected: PASS (new audit tests green; the character-path tests still green because `audit_kind` defaults to `"character"`).

- [ ] **Step 6: Commit**

```bash
git add factory/factory/audit.py factory/factory/art.py factory/tests/test_audit.py factory/tests/test_art.py factory/tests/test_build.py factory/tests/test_flux_art.py
git commit -m "feat(audit): concept (character-free) verdict mode; thread audit_kind"
```

---

### Task 3: Content — `concept_content.py` + dispatch

**Files:**
- Create: `factory/factory/concept_content.py`
- Modify: `factory/factory/content.py` (`generate_content` dispatch)
- Test: `factory/tests/test_concept_content.py`

- [ ] **Step 1: Write the failing test**

Create `factory/tests/test_concept_content.py`:

```python
import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.concept_content import (
    generate_concept_content, validate_concept_story, build_concept_story_prompt)


def _cfg(**over):
    base = dict(slug="tiny", title="Tiny Creatures", subtitle="sub",
                author="Eleanor Hartley", art_prompt="meadow, no text",
                book_type="concept", art_engine="flux",
                subject="small animals", flux_style="soft watercolour, no text",
                page_count=4)
    base.update(over)
    return BookConfig(**base)


def _fake_llm(bible, story):
    calls = {"n": 0}
    def fn(prompt):
        calls["n"] += 1
        return bible if calls["n"] == 1 else story
    return fn


def test_generate_concept_content_shape():
    bible = json.dumps({"art_style": "soft watercolour", "dedication": "For the curious."})
    story = json.dumps({"pages": [
        {"subject": "a fox", "text": "A fox is red.", "scene": "a fox in tall grass"},
        {"subject": "a snail", "text": "A snail is slow.", "scene": "a snail on a leaf"},
        {"subject": "an owl", "text": "An owl hoots.", "scene": "an owl in an oak at dusk"},
        {"subject": "a frog", "text": "A frog hops.", "scene": "a frog on a lily pad"},
    ], "closing": "So many tiny friends!"})
    content = generate_concept_content(_cfg(), _fake_llm(bible, story))
    assert content["dedication"] == "For the curious."
    assert content["closing"] == "So many tiny friends!"
    assert len(content["pages"]) == 4
    assert content["pages"][0]["subject"] == "a fox"
    assert content["pages"][0]["text"] == "A fox is red."
    # no character anchor for a character-free book
    assert content["character_anchor"] == ""


def test_concept_story_validates_page_count():
    with pytest.raises(ContentError, match="exactly 4"):
        validate_concept_story({"pages": [], "closing": "x"}, 4)


def test_concept_story_requires_scene():
    bad = {"pages": [{"subject": "a fox", "text": "hi", "scene": ""}], "closing": "x"}
    with pytest.raises(ContentError, match="scene"):
        validate_concept_story(bad, 1)


def test_concept_story_prompt_includes_explicit_topics():
    prompt = build_concept_story_prompt(_cfg(topics=("a fox", "a snail")))
    assert "a fox" in prompt and "a snail" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_concept_content.py -q`
Expected: FAIL — `factory.concept_content` does not exist.

- [ ] **Step 3: Implement `concept_content.py`**

Create `factory/factory/concept_content.py`:

```python
"""Concept (character-free) picture-book content: a style bible + per-page
{subject, text, scene}. No recurring characters — every spread is independent,
held together only by a locked art style."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences


def build_concept_bible_prompt(cfg: BookConfig) -> str:
    return f"""You are designing a character-free children's picture book about \
{cfg.subject} for early readers (around age 5). Title: {cfg.title}. Each spread shows
a different subject; there are NO recurring characters and NO people anywhere.

Produce the STYLE BIBLE. Return ONLY valid JSON (no markdown, no commentary):
{{"art_style": "...", "dedication": "..."}}
- "art_style": one short, vivid illustration-style string reused on every page so
  the look stays consistent, e.g. "soft storybook watercolour, warm natural palette,
  gentle edges, no text".
- "dedication": one warm line for the dedication page.
Output the JSON and nothing else."""


def build_concept_story_prompt(cfg: BookConfig) -> str:
    if cfg.topics:
        topics = ("Use exactly these subjects, one per spread, IN THIS ORDER: "
                  + "; ".join(cfg.topics) + ".\n")
    else:
        topics = (f"Choose {cfg.page_count} varied, child-friendly subjects within "
                  f'"{cfg.subject}", one per spread.\n')
    return f"""You are writing the character-free children's picture book \
"{cfg.title}" about {cfg.subject}, for early readers (around age 5). Warm, simple,
concrete, never scary.
{topics}
Return ONLY valid JSON:
{{"pages": [{{"subject": "...", "text": "...", "scene": "..."}}], "closing": "..."}}
- "subject": the single subject of this spread (e.g. an animal name).
- "text": 1-2 short, simple sentences an early reader can read aloud — gentle and
  concrete, a light rhyme or one easy true fact about the subject.
- "scene": a RICH, concrete visual of the subject in its natural setting — what it
  looks like and where it is. CRITICAL: NO people, NO unrelated extra animals, and
  NO words/letters/numbers in the picture. One clear subject per page.
- "closing": one warm closing line for the final page.
Exactly {cfg.page_count} page objects. Output the JSON and nothing else."""


def validate_concept_bible(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContentError("concept bible is not a JSON object")
    for k in ("art_style", "dedication"):
        if not str(data.get(k, "")).strip():
            raise ContentError(f"concept bible missing '{k}'")


def validate_concept_story(data: dict, expected_pages: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("concept story is not a JSON object")
    pages = data.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ContentError(
            f"concept story must have exactly {expected_pages} pages, got "
            f"{len(pages) if isinstance(pages, list) else 'non-list'}")
    for i, pg in enumerate(pages, 1):
        if not isinstance(pg, dict):
            raise ContentError(f"concept page {i} is not an object")
        for k in ("subject", "text", "scene"):
            if not str(pg.get(k, "")).strip():
                raise ContentError(f"concept page {i} missing '{k}'")
    if not str(data.get("closing", "")).strip():
        raise ContentError("concept story missing 'closing'")


def _generate_concept_bible(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_concept_bible_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"concept bible is not valid JSON: {e}") from e
    validate_concept_bible(data)
    return data


def _generate_concept_story(cfg: BookConfig,
                            generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_concept_story_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"concept story is not valid JSON: {e}") from e
    validate_concept_story(data, cfg.page_count)
    return data


def generate_concept_content(cfg: BookConfig,
                             generate_fn: Callable[[str], str]) -> dict:
    # One retry each: a transient LLM blip should not nuke the whole build.
    try:
        bible = _generate_concept_bible(cfg, generate_fn)
    except ContentError:
        bible = _generate_concept_bible(cfg, generate_fn)
    art_style = cfg.art_style or bible["art_style"]
    try:
        story = _generate_concept_story(cfg, generate_fn)
    except ContentError:
        story = _generate_concept_story(cfg, generate_fn)
    return {"art_style": art_style, "character_anchor": "",
            "dedication": bible["dedication"], "pages": story["pages"],
            "closing": story["closing"]}
```

Wire the dispatch in `factory/factory/content.py` — inside `generate_content`, alongside the existing `standard`/`picture` branches:

```python
    if cfg.book_type == "concept":
        from .concept_content import generate_concept_content
        return generate_concept_content(cfg, generate_fn)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_concept_content.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/concept_content.py factory/factory/content.py factory/tests/test_concept_content.py
git commit -m "feat(content): concept (subject-driven) content generator + dispatch"
```

---

### Task 4: Art — `generate_concept_art` (empty-LoRA Flux + keep-best)

**Files:**
- Modify: `factory/factory/flux_art.py`
- Test: `factory/tests/test_concept_art.py`

- [ ] **Step 1: Write the failing test**

Create `factory/tests/test_concept_art.py`:

```python
from pathlib import Path
import pytest
from factory.config import BookConfig
from factory.flux_art import generate_concept_art, concept_page_prompt


def _cfg(**over):
    base = dict(slug="tiny", title="Tiny Creatures", subtitle="sub",
                author="Eleanor Hartley",
                art_prompt="a sunlit meadow, soft watercolour, no text",
                book_type="concept", art_engine="flux", subject="small animals",
                flux_style="soft storybook watercolour, no text", flux_guidance=2.4,
                page_count=2)
    base.update(over)
    return BookConfig(**base)


_CONTENT = {"art_style": "soft watercolour", "character_anchor": "",
            "dedication": "d",
            "pages": [{"subject": "a fox", "text": "A fox is red.",
                       "scene": "a fox in tall grass"},
                      {"subject": "a snail", "text": "A snail is slow.",
                       "scene": "a snail on a leaf"}],
            "closing": "bye"}


class _Comfy:
    """Records every submitted workflow and writes a stub PNG so the file exists."""
    def __init__(self):
        self.workflows = []
    def submit(self, workflow, *, out_path):
        self.workflows.append(workflow)
        Path(out_path).write_bytes(b"\x89PNG stub")


class _OKAuditor:
    def __init__(self):
        self.kinds = []
    def audit(self, image_path, *, anchor, reference_path=None, scene=None,
              kind="character"):
        self.kinds.append(kind)
        return {"ok": True, "issues": []}


def test_concept_page_prompt_excludes_people_and_text():
    p = concept_page_prompt({"subject": "a fox", "scene": "a fox in grass"},
                            style="soft watercolour")
    assert "soft watercolour" in p
    assert "a fox in grass" in p
    assert "no people" in p.lower()
    assert "no text" in p.lower()


def test_generate_concept_art_uses_empty_lora_stack_and_concept_audit(tmp_path):
    comfy, auditor = _Comfy(), _OKAuditor()
    art = generate_concept_art(_cfg(), _CONTENT, tmp_path, comfy,
                               seed=99, auditor=auditor)
    assert [p.name for p in art["pages"]] == ["page_01.png", "page_02.png"]
    assert art["cover"].name == "art.png"
    assert art["flagged"] == []
    # every page audited under the concept (character-free) bar
    assert set(auditor.kinds) == {"concept"}
    # empty LoRA stack => no LoraLoaderModelOnly nodes in any submitted graph
    for wf in comfy.workflows:
        assert not any(n.get("class_type") == "LoraLoaderModelOnly"
                       for n in wf.values())


def test_generate_concept_art_keeps_best_and_flags(tmp_path):
    comfy = _Comfy()

    class _NeverPasses:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character"):
            return {"ok": False, "issues": ["stub never passes"]}

    art = generate_concept_art(_cfg(page_count=1,), {
        "art_style": "x", "character_anchor": "", "dedication": "d",
        "pages": [{"subject": "a fox", "text": "t", "scene": "a fox"}],
        "closing": "c"}, tmp_path, comfy, seed=1, auditor=_NeverPasses(),
        max_tries=2)
    assert 1 in art["flagged"]
    assert art["pages"][0].name == "page_01.png"
    assert art["pages"][0].exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_concept_art.py -q`
Expected: FAIL — `generate_concept_art` / `concept_page_prompt` do not exist.

- [ ] **Step 3: Implement concept art**

In `factory/factory/flux_art.py`, add (after `generate_flux_art`):

```python
def concept_page_prompt(page: dict, *, style: str) -> str:
    """Prompt for one character-free spread: locked style + the page's scene, with
    hard 'no people / no text' steering. No LoRA triggers — identity is irrelevant."""
    return (f"{style}. {page['scene']} A single clear subject. No people, no "
            f"unrelated extra animals, no text. Richly detailed natural setting, "
            f"illustrated edge to edge.")


def generate_concept_art(cfg, content, out_dir, comfy, *, seed, auditor,
                         max_tries: int = 4) -> dict:
    """Illustrate every spread with a locked Flux style and an EMPTY LoRA stack
    (no character identity to carry), each audited under the concept bar and
    regenerated until it passes — keeping the best and flagging a stubborn page
    rather than failing the whole book. Returns {"pages", "cover", "flagged"}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    style = cfg.flux_style or content["art_style"]
    guidance = cfg.flux_guidance
    pages = content["pages"]
    n = len(pages)

    out_pages, flagged = [], []
    for i, page in enumerate(pages, 1):
        prompt = concept_page_prompt(page, style=style)
        subject = page.get("subject", "the subject")
        _log(f"[concept] page {i}/{n} ({subject}): {page['scene'][:60]}")

        def render(p, s, op):
            comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance),
                         out_path=op)

        op = out_dir / f"page_{i:02d}.png"
        anchor = (f"a {subject} in its natural setting, in a consistent soft "
                  f"storybook illustration style; no people and no text")
        try:
            out_pages.append(run_audited_render(
                render, prompt, out_path=op, auditor=auditor, anchor=anchor,
                scene=page["scene"], reference_path=None, seed=seed + i * 17,
                max_tries=max_tries, audit_kind="concept"))
        except ArtError:
            _log(f"[concept] page {i}: kept best after {max_tries} tries (REVIEW)")
            flagged.append(i)
            out_pages.append(op)

    _log("[concept] cover…")
    cover_prompt = f"{style}. {cfg.art_prompt}. No people, no text."

    def cover_render(p, s, op):
        comfy.submit(flux_lora_workflow(p, s, loras=[], guidance=guidance),
                     out_path=op)

    cover_path = out_dir / "art.png"
    cover_anchor = (f"a {cfg.subject} scene in a soft storybook illustration style; "
                    f"no people, no text")
    try:
        cover = run_audited_render(
            cover_render, cover_prompt, out_path=cover_path, auditor=auditor,
            anchor=cover_anchor, scene="front cover", reference_path=None,
            seed=seed + 42, max_tries=max_tries, audit_kind="concept")
    except ArtError:
        _log(f"[concept] cover: kept best after {max_tries} tries (REVIEW)")
        flagged.append("cover")
        cover = cover_path
    if flagged:
        _log(f"[concept] REVIEW these (audit not fully passed): {flagged}")
    _log(f"[concept] complete: {n} pages + cover")
    return {"pages": out_pages, "cover": Path(cover), "flagged": flagged}
```

Note: `flux_lora_workflow`, `run_audited_render`, `ArtError`, and `_log` are already imported/defined in `flux_art.py` (it imports `from factory.art import ArtError, run_audited_render, _log`). With `loras=[]` the workflow's LoRA loop adds no nodes and the sampler reads from `head="u"` (the UNET) — verified against the existing graph builder.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_concept_art.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/flux_art.py factory/tests/test_concept_art.py
git commit -m "feat(flux): generate_concept_art — empty-LoRA style-locked spreads"
```

---

### Task 5: Wire end-to-end — interior routing + build route

**Files:**
- Modify: `factory/factory/interior.py` (template map + page-count handling)
- Modify: `factory/build.py` (route `concept`)
- Test: `factory/tests/test_build.py`

- [ ] **Step 1: Write the failing test**

Add to `factory/tests/test_build.py` a concept end-to-end test. Reuse the file's existing fakes/fixtures patterns (a fake `runner` that writes a stub PDF + reports a page count, a fake content `generate_fn`, and a fake `comfy`). Model it on the existing picture/flux build test in this file:

```python
def test_run_build_concept_end_to_end(tmp_path):
    cfg_path = tmp_path / "tiny.config.json"
    cfg_path.write_text(json.dumps({
        "slug": "tiny", "book_type": "concept", "art_engine": "flux",
        "title": "Tiny Creatures", "subtitle": "sub", "author": "Eleanor Hartley",
        "subject": "small animals", "flux_style": "soft watercolour, no text",
        "art_prompt": "a meadow, soft watercolour, no text",
        "page_count": 20, "trim_w": 8.5, "trim_h": 8.5, "price_usd": 10.99,
    }), encoding="utf-8")

    pages = [{"subject": f"animal {i}", "text": f"line {i}",
              "scene": f"animal {i} in a meadow"} for i in range(20)]
    bible = json.dumps({"art_style": "soft watercolour", "dedication": "d"})
    story = json.dumps({"pages": pages, "closing": "bye"})
    calls = {"n": 0}
    def fake_llm(prompt):
        calls["n"] += 1
        return bible if calls["n"] == 1 else story

    class FakeComfy:
        def submit(self, workflow, *, out_path):
            Path(out_path).write_bytes(b"\x89PNG stub")
        def generate(self, *a, **k):
            raise AssertionError("concept must use the Flux submit path, not generate")

    class FakeAuditor:
        def audit(self, image_path, *, anchor, reference_path=None, scene=None,
                  kind="character"):
            return {"ok": True, "issues": []}

    # Reuse the module's existing fake PDF runner if present (e.g. `_fake_runner`);
    # otherwise a runner that writes a 26-page stub PDF. The interior page-count
    # guard for concept expects the picture floor (>= 24 physical pages).
    out = run_build(cfg_path, out_root=tmp_path / "out", generate_fn=fake_llm,
                    comfy=FakeComfy(), runner=_fake_runner, auditor=FakeAuditor())

    assert (out / "content.json").exists()
    assert (out / "page_01.png").exists()
    assert (out / "interior.pdf").exists()
    assert (out / "upload-checklist.md").exists()
    assert not (out / "book.epub").exists()  # paperback-only
```

If `test_build.py` has no reusable `_fake_runner`, copy the runner fake used by the existing picture-build test in the same file and name it `_fake_runner` (it must write the interior PDF to the path it is given and make `pdf_page_count` return a value ≥ 24; match whatever the existing picture test does).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_build.py::test_run_build_concept_end_to_end -q`
Expected: FAIL — `run_build` does not route `concept` (no art generated / wrong interior template / page-count guard).

- [ ] **Step 3: Implement interior routing**

In `factory/factory/interior.py`:

In `render_interior_html`, add `concept` to the template map so it reuses the picture template:
```python
    template_name = {"standard": "interior/picture.html.j2",
                     "picture": "interior/picture.html.j2",
                     "concept": "interior/picture.html.j2"}.get(
                        cfg.book_type, "interior/journal.html.j2")
```
(Match the exact existing dict literal in the file; the key point is adding `"concept": "interior/picture.html.j2"`.)

In `build_interior_pdf`, treat `concept` like `picture` for page counting and the KDP floor check:
```python
    pages = (pdf_page_count(pdf) if book_type in ("standard", "picture", "concept")
             else <existing journal branch>)
    ...
    if book_type in ("picture", "concept"):
        _verify_picture_page_count(pages)
```
(Edit the two existing conditionals — add `"concept"` to the `("standard","picture")` membership test and change `if book_type == "picture"` to `if book_type in ("picture", "concept")`.)

- [ ] **Step 4: Implement the build route**

In `factory/build.py`:

Add the import:
```python
from factory.flux_art import generate_flux_art, generate_concept_art
```

Generalize the Flux detection so `concept` skips the SDXL workflow-template load:
```python
    flux = cfg.book_type in ("picture", "concept") and cfg.art_engine == "flux"
```

Route art generation. Change the `if cfg.book_type == "picture":` block opener to cover concept and pick the concept art function:
```python
    if cfg.book_type in ("picture", "concept"):
        if auditor is None:
            auditor = ClaudeVisionAuditor()
        if cfg.book_type == "concept":
            art = generate_concept_art(cfg, content, out_dir, comfy,
                                       seed=seed, auditor=auditor)
        elif flux:
            art = generate_flux_art(cfg, content, out_dir, comfy,
                                    seed=seed, auditor=auditor)
        else:
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
        ...  # unchanged journal/standard branch
```

(`makes_ebook` is already `False` for `concept`, so the existing cover/EPUB/checklist tail needs no change — it builds the paperback wrap, skips the EPUB, and writes the checklist.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_build.py tests/test_interior.py -q`
Expected: PASS (new concept e2e test green; existing build/interior tests still green).

- [ ] **Step 6: Run the FULL suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: PASS — all tests green (≥ the prior 150 + the new tests).

- [ ] **Step 7: Commit**

```bash
git add factory/factory/interior.py factory/build.py factory/tests/test_build.py
git commit -m "feat(build): route concept books end-to-end (art + interior + bundle)"
```

---

## Self-Review

**Spec coverage:**
- New `book_type: "concept"` + validation → Task 1. ✓
- Subject-driven content `{subject,text,scene}` → Task 3. ✓
- Empty-LoRA style-locked Flux art + keep-best-flag → Task 4. ✓
- Concept audit mode (no people, right subject, clean style) → Task 2. ✓
- Interior/cover/checklist reuse + build route, no EPUB → Task 5. ✓
- Tests via `factory/.venv`, suite stays green → every task ends with a run; Task 5 runs the full suite. ✓
- Piece B (the actual title config + GPU build) is intentionally a separate cycle (out of this plan).

**Placeholder scan:** No TBD/TODO. The only "match the existing literal/fixture" notes (interior template dict, `test_build` runner fake) point at concrete existing code the engineer reads in-file; the required change is stated explicitly.

**Type consistency:** `generate_concept_content` returns `{art_style, character_anchor, dedication, pages, closing}` — `pages` items are `{subject,text,scene}`, consumed unchanged by `generate_concept_art` (reads `page["scene"]`, `page["subject"]`) and the picture interior template (reads `page.text`, `content.dedication`, `content.closing`). `audit_kind="concept"` (art.py) maps to `kind="concept"` (auditor) → `build_concept_audit_prompt`. `generate_concept_art` returns `{pages,cover,flagged}`, same shape `build.py` already consumes via `art["cover"]`. Consistent.

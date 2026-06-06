# Pet-Loss Grief Journal Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python one-command pipeline that turns a per-book config into a KDP-ready bundle (print interior PDF, EPUB, wraparound cover PDF, ebook cover JPG, upload checklist) for a pet-loss grief journal series.

**Architecture:** Five isolated stages wired by `build.py`: ① generate-content (`claude -p`), ② render-interior (HTML/CSS → PDF + EPUB), ③ generate-art (ComfyUI HTTP API), ④ render-cover (art + typographic text, auto-computed spine), ⑤ make-checklist (with pre-filled KDP AI disclosure). External effects (LLM call, browser PDF, ComfyUI) are behind thin adapters so the pure logic is unit-testable with fakes.

**Tech Stack:** Python 3.11+, Jinja2 (templating), EbookLib (EPUB), requests (ComfyUI API), pytest. Shells out to the installed `claude` CLI and the gstack `browse` binary. ComfyUI runs locally at `http://127.0.0.1:8188`.

---

## File Structure

```
factory/
  build.py                         # orchestrator CLI (the one command)
  pyproject.toml                   # deps + pytest config
  factory/
    __init__.py
    specs.py                       # KDP constants + spine/dimension/royalty math (pure)
    config.py                      # load + validate book.config.json -> BookConfig
    content.py                     # stage ①: schema, prompt builder, generate_content, claude adapter
    browsepdf.py                   # helper: html file -> pdf/screenshot via `browse`
    templating.py                  # Jinja2 environment + render helpers
    interior.py                    # stage ②: interior HTML -> PDF + page count + EPUB
    art.py                         # stage ③: ComfyUI client + generate_art
    cover.py                       # stage ④: cover HTML -> wraparound PDF + ebook cover JPG
    checklist.py                   # stage ⑤: upload-checklist.md + AI disclosure
  templates/
    interior/book.html.j2
    interior/interior.css
    cover/cover.html.j2
    cover/cover.css
    checklist.md.j2
  comfyui/workflow.template.json   # API-format workflow, checkpoint filled by user
  books/
    dog-loss.config.json
    cat-loss.config.json
    pet-loss.config.json
  tests/
    __init__.py
    conftest.py
    test_specs.py
    test_config.py
    test_content.py
    test_browsepdf.py
    test_interior.py
    test_art.py
    test_cover.py
    test_checklist.py
    test_build.py
  out/                             # generated bundles (gitignored)
  README.md
```

All paths below are relative to `C:\Users\quint\git\book-gen\factory\`. On Windows, run commands from that directory in PowerShell. Use a venv: `python -m venv .venv ; .\.venv\Scripts\Activate.ps1`.

---

### Task 0: Scaffold project and dependencies

**Files:**
- Create: `factory/pyproject.toml`
- Create: `factory/factory/__init__.py` (empty)
- Create: `factory/tests/__init__.py` (empty)
- Create: `factory/tests/conftest.py`
- Modify: `book-gen/.gitignore` (create if absent)

- [ ] **Step 1: Create `factory/pyproject.toml`**

```toml
[project]
name = "petloss-factory"
version = "0.1.0"
description = "KDP pet-loss grief journal production factory"
requires-python = ">=3.11"
dependencies = [
    "Jinja2>=3.1",
    "EbookLib>=0.18",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Create empty package files**

Create `factory/factory/__init__.py` and `factory/tests/__init__.py` as empty files.

- [ ] **Step 3: Create `factory/tests/conftest.py`** (shared fixtures)

```python
import json
from pathlib import Path
import pytest


@pytest.fixture
def sample_config_dict():
    return {
        "slug": "dog-loss",
        "title": "Paw Prints on My Heart",
        "subtitle": "A Guided Grief Journal for Coping with the Loss of a Beloved Dog",
        "author": "Quint Mertesdorf",
        "pet_kind": "dog",
        "prompt_count": 70,
        "art_prompt": "soft pastel watercolor of a dog at a rainbow bridge, gentle, tender, no text",
        "price_usd": 9.99,
    }


@pytest.fixture
def sample_config_file(tmp_path, sample_config_dict):
    p = tmp_path / "dog-loss.config.json"
    p.write_text(json.dumps(sample_config_dict), encoding="utf-8")
    return p


@pytest.fixture
def sample_content():
    return {
        "intro": "This journal is a gentle space to remember your companion.",
        "how_to_use": "Use these pages at your own pace. There is no right way to grieve.",
        "pet_profile_fields": ["Name", "Breed", "Birthday", "The day we met", "Favorite things"],
        "prompts": [f"Today I miss you because... (prompt {i})" for i in range(1, 71)],
        "milestones": ["The first week without you", "One month on", "Your birthday"],
        "section_microcopy": {"prompts": "Take your time with these.", "milestones": "Marking the hard days."},
        "letter_pages": ["A letter to you", "What I never got to say"],
    }
```

- [ ] **Step 4: Create/append `book-gen/.gitignore`**

```gitignore
factory/.venv/
factory/out/
factory/__pycache__/
**/__pycache__/
*.pyc
```

- [ ] **Step 5: Install and verify**

Run: `cd factory ; python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -e ".[dev]"`
Expected: installs Jinja2, EbookLib, requests, pytest with no errors.

- [ ] **Step 6: Commit**

```bash
git add factory/pyproject.toml factory/factory/__init__.py factory/tests/__init__.py factory/tests/conftest.py .gitignore
git commit -m "chore: scaffold petloss factory package"
```

---

### Task 1: KDP specs math (pure functions)

KDP formulas: cream paper spine = `pages * 0.0025"`. Cover (6x9, 0.125" bleed) full width = `0.125 + 6 + spine + 6 + 0.125`. Height = `9 + 0.25`. B&W printing cost (US, cream) = `$1.00 + pages * $0.012`. Royalty = `price * 0.60 - printing_cost`.

**Files:**
- Create: `factory/factory/specs.py`
- Test: `factory/tests/test_specs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_specs.py
import pytest
from factory import specs


def test_spine_width_cream():
    assert specs.spine_width_in(120) == pytest.approx(0.30)


def test_cover_dimensions():
    w, h = specs.cover_dimensions_in(120)
    assert w == pytest.approx(0.125 + 6 + 0.30 + 6 + 0.125)  # 12.55
    assert h == pytest.approx(9.25)


def test_printing_cost():
    assert specs.printing_cost_usd(120) == pytest.approx(2.44)


def test_royalty():
    assert specs.royalty_usd(9.99, 120) == pytest.approx(9.99 * 0.60 - 2.44, abs=1e-6)


def test_trim_constants():
    assert specs.TRIM_W_IN == 6
    assert specs.TRIM_H_IN == 9
    assert specs.BLEED_IN == 0.125
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_specs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.specs'`

- [ ] **Step 3: Write `factory/factory/specs.py`**

```python
"""KDP layout and economics math. Pure functions, no I/O."""

TRIM_W_IN = 6.0
TRIM_H_IN = 9.0
BLEED_IN = 0.125
SPINE_PER_PAGE_IN = 0.0025          # cream paper
ROYALTY_RATE = 0.60                 # 60% for >= $9.99 paperback
PRINT_FIXED_USD = 1.00              # US B&W fixed charge
PRINT_PER_PAGE_USD = 0.012          # US B&W per-page

# Interior margins (no-bleed interior). Inside (gutter) larger for binding.
MARGIN_INSIDE_IN = 0.5
MARGIN_OUTSIDE_IN = 0.375
MARGIN_TOPBOTTOM_IN = 0.5


def spine_width_in(pages: int) -> float:
    return round(pages * SPINE_PER_PAGE_IN, 4)


def cover_dimensions_in(pages: int) -> tuple[float, float]:
    spine = spine_width_in(pages)
    width = BLEED_IN + TRIM_W_IN + spine + TRIM_W_IN + BLEED_IN
    height = TRIM_H_IN + 2 * BLEED_IN
    return (round(width, 4), round(height, 4))


def printing_cost_usd(pages: int) -> float:
    return round(PRINT_FIXED_USD + pages * PRINT_PER_PAGE_USD, 2)


def royalty_usd(price_usd: float, pages: int) -> float:
    return round(price_usd * ROYALTY_RATE - printing_cost_usd(pages), 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_specs.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/specs.py factory/tests/test_specs.py
git commit -m "feat: KDP spine, cover dimension, and royalty math"
```

---

### Task 2: Book config loading and validation

**Files:**
- Create: `factory/factory/config.py`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json
import pytest
from factory.config import load_config, BookConfig, ConfigError


def test_load_valid(sample_config_file):
    cfg = load_config(sample_config_file)
    assert isinstance(cfg, BookConfig)
    assert cfg.slug == "dog-loss"
    assert cfg.pet_kind == "dog"
    assert cfg.prompt_count == 70
    assert cfg.price_usd == 9.99


def test_missing_required_field(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"slug": "x"}), encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(p)
    assert "title" in str(e.value)


def test_defaults_applied(tmp_path):
    p = tmp_path / "min.json"
    p.write_text(json.dumps({
        "slug": "cat-loss", "title": "T", "subtitle": "S", "author": "A",
        "pet_kind": "cat", "art_prompt": "watercolor cat",
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.prompt_count == 70      # default
    assert cfg.price_usd == 9.99       # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.config'`

- [ ] **Step 3: Write `factory/factory/config.py`**

```python
"""Load and validate a book.config.json into a BookConfig."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ["slug", "title", "subtitle", "author", "pet_kind", "art_prompt"]


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BookConfig:
    slug: str
    title: str
    subtitle: str
    author: str
    pet_kind: str
    art_prompt: str
    prompt_count: int = 70
    price_usd: float = 9.99


def load_config(path: str | Path) -> BookConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON: {e}") from e
    missing = [k for k in REQUIRED if k not in data or data[k] in (None, "")]
    if missing:
        raise ConfigError(f"{path}: missing required field(s): {', '.join(missing)}")
    return BookConfig(
        slug=data["slug"],
        title=data["title"],
        subtitle=data["subtitle"],
        author=data["author"],
        pet_kind=data["pet_kind"],
        art_prompt=data["art_prompt"],
        prompt_count=int(data.get("prompt_count", 70)),
        price_usd=float(data.get("price_usd", 9.99)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/config.py factory/tests/test_config.py
git commit -m "feat: book config loading and validation"
```

---

### Task 3: Content stage — schema, prompt builder, generate_content

The LLM call is injected as `generate_fn(prompt: str) -> str` so the logic is testable without `claude`. `generate_content` builds the prompt, calls `generate_fn`, parses JSON (stripping ``` fences), and validates the shape.

**Files:**
- Create: `factory/factory/content.py`
- Test: `factory/tests/test_content.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_content.py
import json
import pytest
from factory.config import BookConfig
from factory.content import build_prompt, generate_content, ContentError, validate_content


@pytest.fixture
def cfg():
    return BookConfig(slug="dog-loss", title="T", subtitle="S", author="A",
                      pet_kind="dog", art_prompt="x", prompt_count=5)


def test_build_prompt_mentions_pet_and_count(cfg):
    p = build_prompt(cfg)
    assert "dog" in p
    assert "5" in p
    assert "JSON" in p


def test_generate_content_parses_fenced_json(cfg, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    fake = lambda prompt: "```json\n" + json.dumps(sample_content) + "\n```"
    out = generate_content(cfg, generate_fn=fake)
    assert len(out["prompts"]) == 5
    assert out["intro"]


def test_generate_content_rejects_bad_json(cfg):
    with pytest.raises(ContentError):
        generate_content(cfg, generate_fn=lambda p: "not json at all")


def test_validate_rejects_missing_key(sample_content):
    del sample_content["prompts"]
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=70)


def test_validate_rejects_wrong_prompt_count(sample_content):
    with pytest.raises(ContentError):
        validate_content(sample_content, expected_prompts=999)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_content.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.content'`

- [ ] **Step 3: Write `factory/factory/content.py`**

```python
"""Stage 1: generate interior content via an injected LLM callable."""
from __future__ import annotations
import json
import re
import subprocess
from typing import Callable
from .config import BookConfig

REQUIRED_KEYS = ["intro", "how_to_use", "pet_profile_fields", "prompts",
                 "milestones", "section_microcopy", "letter_pages"]


class ContentError(ValueError):
    pass


def build_prompt(cfg: BookConfig) -> str:
    return f"""You are writing the interior content for a print grief journal for someone \
who has lost their {cfg.pet_kind}. The tone is warm, tender, and gentle. Never clinical.

Return ONLY valid JSON (no markdown, no commentary) with exactly these keys:
- "intro": 2-4 warm sentences welcoming the griever (string)
- "how_to_use": 2-3 sentences on using the journal at their own pace (string)
- "pet_profile_fields": list of 5-7 short fill-in labels about the {cfg.pet_kind} \
(e.g. "Name", "Breed", "The day we met")
- "prompts": exactly {cfg.prompt_count} distinct, undated reflective grief prompts \
(strings), e.g. "Today I miss you because...", "What I wish I had said...". Vary them.
- "milestones": 4-6 milestone reflection headings (e.g. "The first week without you")
- "section_microcopy": object with short supportive lines, keys "prompts" and "milestones"
- "letter_pages": 2-3 headings for letter-to-pet pages

Output the JSON object and nothing else."""


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    # fall back: first { to last }
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        return text[s:e + 1]
    return text


def validate_content(data: dict, expected_prompts: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("content is not a JSON object")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ContentError(f"content missing keys: {', '.join(missing)}")
    if not isinstance(data["prompts"], list) or len(data["prompts"]) != expected_prompts:
        raise ContentError(
            f"expected {expected_prompts} prompts, got "
            f"{len(data['prompts']) if isinstance(data['prompts'], list) else 'non-list'}")


def generate_content(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"LLM did not return valid JSON: {e}") from e
    validate_content(data, cfg.prompt_count)
    return data


def claude_generate(prompt: str) -> str:
    """Real adapter: shell out to the installed Claude Code CLI in print mode."""
    proc = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise ContentError(f"claude CLI failed (exit {proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_content.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/content.py factory/tests/test_content.py
git commit -m "feat: content stage with injectable LLM and JSON validation"
```

---

### Task 4: browse PDF/screenshot helper

Wraps the gstack `browse` binary. Resolves the binary path, runs `goto file://<abs>` then `pdf` (or `screenshot`). The runner is injected for testing.

**Files:**
- Create: `factory/factory/browsepdf.py`
- Test: `factory/tests/test_browsepdf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browsepdf.py
from pathlib import Path
from factory.browsepdf import html_to_pdf, html_to_screenshot, BrowseError
import pytest


def make_runner(record):
    def run(args):
        record.append(args)
        class R: returncode = 0; stdout = "ok"; stderr = ""
        return R()
    return run


def test_html_to_pdf_invokes_goto_then_pdf(tmp_path):
    html = tmp_path / "in.html"; html.write_text("<h1>hi</h1>", encoding="utf-8")
    out = tmp_path / "out.pdf"
    calls = []
    html_to_pdf(html, out, width_in=6, height_in=9, runner=make_runner(calls))
    assert any(a[1] == "goto" and a[2].startswith("file://") for a in calls)
    pdf_call = [a for a in calls if a[1] == "pdf"][0]
    assert "--width" in pdf_call and "6in" in pdf_call
    assert "9in" in pdf_call


def test_runner_failure_raises(tmp_path):
    html = tmp_path / "in.html"; html.write_text("x", encoding="utf-8")
    def bad(args):
        class R: returncode = 1; stdout = ""; stderr = "boom"
        return R()
    with pytest.raises(BrowseError):
        html_to_pdf(html, tmp_path / "o.pdf", width_in=6, height_in=9, runner=bad)


def test_screenshot_invokes_viewport_and_screenshot(tmp_path):
    html = tmp_path / "c.html"; html.write_text("x", encoding="utf-8")
    calls = []
    html_to_screenshot(html, tmp_path / "o.jpg", width_px=1600, height_px=2560,
                       runner=make_runner(calls))
    assert any(a[1] == "viewport" for a in calls)
    assert any(a[1] == "screenshot" for a in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_browsepdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.browsepdf'`

- [ ] **Step 3: Write `factory/factory/browsepdf.py`**

```python
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
                margins_in: float = 0.0, runner: Runner | None = None) -> Path:
    runner = runner or _default_runner
    b = browse_binary()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, [b, "goto", _file_url(Path(html))])
    _run(runner, [b, "pdf", str(out_pdf),
                  "--width", f"{width_in}in", "--height", f"{height_in}in",
                  "--margins", f"{margins_in}in", "--print-background"])
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_browsepdf.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/browsepdf.py factory/tests/test_browsepdf.py
git commit -m "feat: browse-based HTML to PDF/screenshot helper"
```

---

### Task 5: Templating + interior assets + interior HTML render

**Files:**
- Create: `factory/factory/templating.py`
- Create: `factory/templates/interior/interior.css`
- Create: `factory/templates/interior/book.html.j2`
- Test: `factory/tests/test_interior.py` (HTML part)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interior.py
from pathlib import Path
from factory.config import BookConfig
from factory.interior import render_interior_html


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", prompt_count=5)


def test_render_interior_html_contains_title_and_prompts(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "Paw Prints" in text
    assert "prompt 1" in text
    assert "page-break" in text or "break-after" in text  # paginated layout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_interior.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.interior'`

- [ ] **Step 3: Write `factory/factory/templating.py`**

```python
"""Shared Jinja2 environment."""
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )


def render(template_name: str, **ctx) -> str:
    return env().get_template(template_name).render(**ctx)
```

- [ ] **Step 4: Write `factory/templates/interior/interior.css`**

```css
@page { margin: 0; }
body { font-family: Georgia, "Times New Roman", serif; color: #2b2b2b; margin: 0; }
.page {
  width: 6in; height: 9in; box-sizing: border-box;
  padding: 0.5in 0.375in 0.5in 0.5in;   /* top right bottom left(gutter) */
  break-after: page; position: relative; overflow: hidden;
}
.page:last-child { break-after: auto; }
h1.book-title { font-size: 30pt; text-align: center; margin-top: 2in; }
.book-sub { text-align: center; font-style: italic; font-size: 13pt; color: #555; }
.byline { text-align: center; margin-top: 0.4in; font-variant: small-caps; }
.section-head { font-size: 20pt; text-align: center; margin-top: 1.5in; }
.microcopy { text-align: center; font-style: italic; color: #666; margin-top: 0.3in; }
.prompt { font-size: 14pt; margin: 0 0 0.25in; }
.lines { border-bottom: 1px solid #ccc; height: 0.45in; }
.profile-field { font-size: 13pt; margin-bottom: 0.35in; }
.profile-field .lead { font-weight: bold; }
.intro-body { font-size: 13pt; line-height: 1.6; margin-top: 1in; }
```

- [ ] **Step 5: Write `factory/templates/interior/book.html.j2`**

```jinja
<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="interior.css"></head><body>

<section class="page"><h1 class="book-title">{{ cfg.title }}</h1>
<p class="book-sub">{{ cfg.subtitle }}</p>
<p class="byline">{{ cfg.author }}</p></section>

<section class="page"><div class="intro-body"><p>{{ content.intro }}</p>
<p>{{ content.how_to_use }}</p></div></section>

<section class="page"><h2 class="section-head">About {{ cfg.pet_kind|capitalize }}</h2>
{% for f in content.pet_profile_fields %}
<div class="profile-field"><span class="lead">{{ f }}:</span><div class="lines"></div></div>
{% endfor %}</section>

<section class="page"><h2 class="section-head">Memories</h2>
<p class="microcopy">{{ content.section_microcopy.prompts }}</p></section>
{% for p in content.prompts %}
<section class="page"><p class="prompt">{{ p }}</p>
{% for _ in range(8) %}<div class="lines"></div>{% endfor %}</section>
{% endfor %}

<section class="page"><h2 class="section-head">Milestones</h2>
<p class="microcopy">{{ content.section_microcopy.milestones }}</p></section>
{% for m in content.milestones %}
<section class="page"><p class="prompt">{{ m }}</p>
{% for _ in range(8) %}<div class="lines"></div>{% endfor %}</section>
{% endfor %}

{% for l in content.letter_pages %}
<section class="page"><h2 class="section-head">{{ l }}</h2>
{% for _ in range(9) %}<div class="lines"></div>{% endfor %}</section>
{% endfor %}

</body></html>
```

- [ ] **Step 6: Write `factory/factory/interior.py` (HTML render only for now)**

```python
"""Stage 2: render interior to HTML (and later PDF + EPUB)."""
from __future__ import annotations
import shutil
from pathlib import Path
from .config import BookConfig
from .templating import render, TEMPLATES_DIR


def render_interior_html(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render("interior/book.html.j2", cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    # copy CSS next to the HTML so the relative <link> resolves
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_interior.py -v`
Expected: PASS (1 passed)

- [ ] **Step 8: Commit**

```bash
git add factory/factory/templating.py factory/factory/interior.py factory/templates/interior/
git add factory/tests/test_interior.py
git commit -m "feat: interior HTML templating"
```

---

### Task 6: Interior PDF + page count + EPUB

`page_count` = number of `<section class="page">` (deterministic from content; matches the printed PDF since each section is one fixed 6x9 page). EPUB built with EbookLib from the same content.

**Files:**
- Modify: `factory/factory/interior.py`
- Test: `factory/tests/test_interior.py` (append)

- [ ] **Step 1: Write the failing tests (append to tests/test_interior.py)**

```python
from factory.interior import count_pages, build_interior_pdf, build_epub


def test_count_pages(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    # title + intro + profile + memories-head + 5 prompts + milestones-head
    # + 3 milestones + 2 letters = 14
    assert count_pages(html_path) == 14


def test_build_interior_pdf_calls_browse(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    html_path = render_interior_html(cfg(), sample_content, out_dir=tmp_path)
    calls = []
    def runner(args):
        calls.append(args)
        (tmp_path / "interior.pdf").write_bytes(b"%PDF-1.4")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, pages = build_interior_pdf(html_path, tmp_path, runner=runner)
    assert Path(pdf).exists()
    assert pages == 14
    assert any(a[1] == "pdf" for a in calls)


def test_build_epub(tmp_path, sample_content):
    sample_content["prompts"] = sample_content["prompts"][:5]
    out = build_epub(cfg(), sample_content, tmp_path)
    assert Path(out).exists()
    assert Path(out).suffix == ".epub"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_interior.py -v`
Expected: FAIL with `ImportError: cannot import name 'count_pages'`

- [ ] **Step 3: Extend `factory/factory/interior.py`**

```python
import re
from .browsepdf import html_to_pdf
from . import specs
from ebooklib import epub


def count_pages(html_path: Path) -> int:
    text = Path(html_path).read_text(encoding="utf-8")
    return len(re.findall(r'<section class="page"', text))


def build_interior_pdf(html_path: Path, out_dir: Path, runner=None) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    pdf = out_dir / "interior.pdf"
    html_to_pdf(Path(html_path), pdf,
                width_in=specs.TRIM_W_IN, height_in=specs.TRIM_H_IN,
                margins_in=0.0, runner=runner)
    return pdf, count_pages(html_path)


def build_epub(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"petloss-{cfg.slug}")
    book.set_title(cfg.title)
    book.set_language("en")
    book.add_author(cfg.author)

    def chapter(title, body_html, fname):
        c = epub.EpubHtml(title=title, file_name=fname, lang="en")
        c.content = f"<h1>{title}</h1>{body_html}"
        book.add_item(c)
        return c

    intro = chapter("Welcome", f"<p>{content['intro']}</p><p>{content['how_to_use']}</p>", "intro.xhtml")
    prompts_html = "".join(f"<p>{p}</p><hr/>" for p in content["prompts"])
    prompts = chapter("Reflections", prompts_html, "prompts.xhtml")
    miles = chapter("Milestones", "".join(f"<p>{m}</p>" for m in content["milestones"]), "miles.xhtml")

    book.toc = (intro, prompts, miles)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", intro, prompts, miles]

    out = Path(out_dir) / "interior.epub"
    out.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out), book)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_interior.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/interior.py factory/tests/test_interior.py
git commit -m "feat: interior PDF render, page count, and EPUB build"
```

---

### Task 7: ComfyUI art client

POST workflow to `/prompt`, poll `/history/{id}`, download via `/view`. The HTTP layer is injected (`http_post`, `http_get`) for testing. The workflow JSON has its positive-prompt node text and seed substituted.

**Files:**
- Create: `factory/factory/art.py`
- Test: `factory/tests/test_art.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_art.py
import json
from pathlib import Path
from factory.art import inject_prompt, ComfyClient


def test_inject_prompt_sets_text_and_seed():
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER"}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    out = inject_prompt(wf, positive_node="6", sampler_node="3",
                        prompt="watercolor dog", seed=42)
    assert out["6"]["inputs"]["text"] == "watercolor dog"
    assert out["3"]["inputs"]["seed"] == 42


def test_comfy_generate_downloads_image(tmp_path):
    posts, gets = [], []
    def http_post(url, json):
        posts.append(url)
        return {"prompt_id": "abc"}
    def http_get(url):
        gets.append(url)
        if "/history/" in url:
            return {"abc": {"outputs": {"9": {"images": [
                {"filename": "img.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG\r\n"  # /view raw bytes
    wf = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
          "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}
    client = ComfyClient(http_post=http_post, http_get=http_get)
    out = client.generate(wf, positive_node="6", sampler_node="3",
                          prompt="dog", seed=1, out_path=tmp_path / "art.png")
    assert Path(out).exists()
    assert Path(out).read_bytes().startswith(b"\x89PNG")
    assert any("/prompt" in u for u in posts)
    assert any("/view" in u for u in gets)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_art.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.art'`

- [ ] **Step 3: Write `factory/factory/art.py`**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_art.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/factory/art.py factory/tests/test_art.py
git commit -m "feat: ComfyUI art generation client"
```

---

### Task 8: Cover render (wraparound PDF + ebook cover JPG)

Computes spine from page count (Task 1), renders cover HTML with art as background and text in the front panel, exports wraparound PDF and a front-only ebook JPG.

**Files:**
- Create: `factory/templates/cover/cover.css`
- Create: `factory/templates/cover/cover.html.j2`
- Create: `factory/factory/cover.py`
- Test: `factory/tests/test_cover.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cover.py
from pathlib import Path
from factory.config import BookConfig
from factory.cover import render_cover_html, build_cover


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x")


def test_render_cover_html_has_dimensions_and_title(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    html = render_cover_html(cfg(), pages=120, art_path=art, out_dir=tmp_path)
    text = Path(html).read_text(encoding="utf-8")
    assert "Paw Prints" in text
    assert "12.55in" in text   # full wraparound width for 120pp
    assert "9.25in" in text


def test_build_cover_makes_pdf_and_jpg(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    calls = []
    def runner(args):
        calls.append(args)
        # create whatever output file browse was told to write
        target = args[2] if args[1] in ("pdf", "screenshot") else None
        if target:
            Path(target).write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    pdf, jpg = build_cover(cfg(), pages=120, art_path=art, out_dir=tmp_path, runner=runner)
    assert Path(pdf).exists() and Path(pdf).suffix == ".pdf"
    assert Path(jpg).exists() and Path(jpg).suffix == ".jpg"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_cover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.cover'`

- [ ] **Step 3: Write `factory/templates/cover/cover.css`**

```css
@page { margin: 0; }
html, body { margin: 0; padding: 0; }
.wrap {
  position: relative; box-sizing: border-box;
  width: {{ width_in }}in; height: {{ height_in }}in;
  background-image: url("{{ art_file }}");
  background-size: cover; background-position: center;
  font-family: Georgia, serif; color: #fff;
}
.front {
  position: absolute; top: 0; height: 100%;
  right: {{ bleed }}in; width: {{ trim_w }}in;
  display: flex; flex-direction: column; align-items: center;
  justify-content: flex-start; text-align: center;
  padding-top: 1in;
  text-shadow: 0 2px 8px rgba(0,0,0,0.55);
}
.front h1 { font-size: 38pt; margin: 0 0.4in; }
.front .sub { font-size: 15pt; font-style: italic; margin: 0.3in 0.4in 0; }
.front .author { position: absolute; bottom: 0.8in; font-variant: small-caps; font-size: 14pt; }
```

(The CSS is rendered through Jinja too — see Step 5 where it is emitted with values substituted.)

- [ ] **Step 4: Write `factory/templates/cover/cover.html.j2`**

```jinja
<!doctype html><html><head><meta charset="utf-8">
<style>{{ css }}</style></head><body>
<div class="wrap">
  <div class="front">
    <h1>{{ cfg.title }}</h1>
    <p class="sub">{{ cfg.subtitle }}</p>
    <div class="author">{{ cfg.author }}</div>
  </div>
</div></body></html>
```

- [ ] **Step 5: Write `factory/factory/cover.py`**

```python
"""Stage 4: assemble wraparound cover PDF and ebook cover JPG."""
from __future__ import annotations
import shutil
from pathlib import Path
from jinja2 import Template
from .config import BookConfig
from .templating import render, TEMPLATES_DIR
from .browsepdf import html_to_pdf, html_to_screenshot
from . import specs

_CSS_TEMPLATE = (TEMPLATES_DIR / "cover" / "cover.css").read_text(encoding="utf-8") \
    if (TEMPLATES_DIR / "cover" / "cover.css").exists() else ""


def _css(width_in: float, height_in: float, art_file: str) -> str:
    return Template(_CSS_TEMPLATE).render(
        width_in=width_in, height_in=height_in, art_file=art_file,
        bleed=specs.BLEED_IN, trim_w=specs.TRIM_W_IN)


def render_cover_html(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                      front_only: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art_local = out_dir / Path(art_path).name
    if Path(art_path).resolve() != art_local.resolve():
        shutil.copy(art_path, art_local)
    if front_only:
        width_in = specs.TRIM_W_IN + 2 * specs.BLEED_IN
        height_in = specs.TRIM_H_IN + 2 * specs.BLEED_IN
        name = "cover_front.html"
    else:
        width_in, height_in = specs.cover_dimensions_in(pages)
        name = "cover_wrap.html"
    css = _css(width_in, height_in, art_local.name)
    html = render("cover/cover.html.j2", cfg=cfg, css=css,
                  width_in=width_in, height_in=height_in)
    html_path = out_dir / name
    html_path.write_text(html, encoding="utf-8")
    return html_path


def build_cover(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                runner=None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    # wraparound paperback PDF
    wrap_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=False)
    width_in, height_in = specs.cover_dimensions_in(pages)
    pdf = out_dir / "cover-paperback.pdf"
    html_to_pdf(wrap_html, pdf, width_in=width_in, height_in=height_in,
                margins_in=0.0, runner=runner)
    # ebook front cover JPG (1600x2560)
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    return pdf, jpg
```

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/test_cover.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add factory/templates/cover/ factory/factory/cover.py factory/tests/test_cover.py
git commit -m "feat: wraparound cover PDF and ebook cover render"
```

---

### Task 9: Upload checklist + AI disclosure

**Files:**
- Create: `factory/templates/checklist.md.j2`
- Create: `factory/factory/checklist.py`
- Test: `factory/tests/test_checklist.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checklist.py
from pathlib import Path
from factory.config import BookConfig
from factory.checklist import make_checklist


def cfg():
    return BookConfig(slug="dog-loss", title="Paw Prints", subtitle="Sub",
                      author="A", pet_kind="dog", art_prompt="x", price_usd=9.99)


def test_make_checklist_has_disclosure_and_royalty(tmp_path):
    out = make_checklist(cfg(), pages=120, out_dir=tmp_path)
    text = Path(out).read_text(encoding="utf-8")
    assert "AI" in text and "disclos" in text.lower()
    assert "Text: AI-generated" in text
    assert "Images: AI-generated" in text
    assert "$9.99" in text
    assert "Death & Grief" in text
    assert "3.55" in text  # royalty 9.99*0.6 - 2.44
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_checklist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory.checklist'`

- [ ] **Step 3: Write `factory/templates/checklist.md.j2`**

```jinja
# KDP Upload Checklist — {{ cfg.title }}

## Files to upload
- Paperback interior: `interior.pdf` ({{ pages }} pages, 6x9", cream)
- Paperback cover (wraparound): `cover-paperback.pdf` (spine {{ spine }}in)
- Ebook manuscript: `interior.epub`
- Ebook cover: `cover-ebook.jpg`

## Listing metadata
- **Title:** {{ cfg.title }}
- **Subtitle:** {{ cfg.subtitle }}
- **Author:** {{ cfg.author }}
- **Description:** (paste)
  <p>A gentle, guided journal to help you grieve and remember your beloved {{ cfg.pet_kind }}.
  Undated reflective prompts, memory pages, and milestone reflections give you a private
  space to process loss at your own pace. A comforting keepsake and a thoughtful gift.</p>
- **Price:** ${{ "%.2f"|format(cfg.price_usd) }} (paperback)
- **Estimated royalty:** ${{ "%.2f"|format(royalty) }}/sale (60% − ${{ "%.2f"|format(print_cost) }} print)

## Categories (choose 2)
1. Self-Help › Death & Grief
2. Self-Help › Journaling   (or Crafts, Hobbies & Home › {{ cfg.pet_kind|capitalize }} care)

## 7 backend keywords
{{ keywords }}

## AI Content Disclosure (KDP asks at publish — answer privately)
- **Text: AI-generated** (AI-assisted prompts/copy, human-reviewed)
- **Images: AI-generated** (cover art via local ComfyUI)
- Translations: None

> Disclosure is private to Amazon and is NOT shown to buyers. Required — do not skip.
```

- [ ] **Step 4: Write `factory/factory/checklist.py`**

```python
"""Stage 5: emit upload checklist with pre-filled AI disclosure."""
from __future__ import annotations
from pathlib import Path
from .config import BookConfig
from .templating import render
from . import specs


def _keywords(cfg: BookConfig) -> str:
    base = [f"{cfg.pet_kind} loss gift", f"{cfg.pet_kind} memorial journal",
            "pet loss grief journal", "pet bereavement", "rainbow bridge keepsake",
            "in memory of pet", f"loss of a {cfg.pet_kind}"]
    return ", ".join(base[:7])


def make_checklist(cfg: BookConfig, pages: int, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render("checklist.md.j2",
                cfg=cfg, pages=pages,
                spine=specs.spine_width_in(pages),
                royalty=specs.royalty_usd(cfg.price_usd, pages),
                print_cost=specs.printing_cost_usd(pages),
                keywords=_keywords(cfg))
    out = out_dir / "upload-checklist.md"
    out.write_text(md, encoding="utf-8")
    return out
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_checklist.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add factory/templates/checklist.md.j2 factory/factory/checklist.py factory/tests/test_checklist.py
git commit -m "feat: upload checklist with AI disclosure"
```

---

### Task 10: Orchestrator build.py

Wires all stages. External effects (`generate_fn`, ComfyUI client, `runner`) are injectable so an end-to-end test runs with fakes and asserts every output file exists.

**Files:**
- Create: `factory/build.py`
- Test: `factory/tests/test_build.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build.py
import json
from pathlib import Path
from factory.art import ComfyClient
from build import run_build


def test_end_to_end_with_fakes(tmp_path, sample_config_dict, sample_content):
    cfgp = tmp_path / "dog-loss.config.json"
    sample_config_dict["prompt_count"] = 5
    cfgp.write_text(json.dumps(sample_config_dict), encoding="utf-8")

    fake_llm = lambda prompt: json.dumps({**sample_content, "prompts": sample_content["prompts"][:5]})

    def http_post(url, json): return {"prompt_id": "p"}
    def http_get(url):
        if "/history/" in url:
            return {"p": {"outputs": {"9": {"images": [
                {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}
        return b"\x89PNG"
    comfy = ComfyClient(http_post=http_post, http_get=http_get, poll_interval=0)

    def runner(args):
        if args[1] in ("pdf", "screenshot"):
            Path(args[2]).write_bytes(b"x")
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()

    workflow = {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                "3": {"class_type": "KSampler", "inputs": {"seed": 0}}}

    out_dir = run_build(cfgp, out_root=tmp_path / "out", generate_fn=fake_llm,
                        comfy=comfy, workflow=workflow,
                        positive_node="6", sampler_node="3", runner=runner)
    for f in ["interior.pdf", "interior.epub", "cover-paperback.pdf",
              "cover-ebook.jpg", "upload-checklist.md"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build'`

- [ ] **Step 3: Write `factory/build.py`**

```python
"""One-command orchestrator for the pet-loss journal factory."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from factory.config import load_config
from factory.content import generate_content, claude_generate
from factory.interior import render_interior_html, build_interior_pdf, build_epub
from factory.art import ComfyClient
from factory.cover import build_cover
from factory.checklist import make_checklist

DEFAULT_SEED = 12345


def run_build(config_path, out_root="out", *, generate_fn=claude_generate,
              comfy=None, workflow=None, positive_node="6", sampler_node="3",
              runner=None, seed=DEFAULT_SEED) -> Path:
    cfg = load_config(config_path)
    out_dir = Path(out_root) / cfg.slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # ① content
    content = generate_content(cfg, generate_fn=generate_fn)
    (out_dir / "content.json").write_text(json.dumps(content, indent=2), encoding="utf-8")

    # ② interior
    html = render_interior_html(cfg, content, out_dir)
    _, pages = build_interior_pdf(html, out_dir, runner=runner)
    build_epub(cfg, content, out_dir)

    # ③ art
    if comfy is None:
        comfy = ComfyClient()
    if workflow is None:
        workflow = json.loads((Path(__file__).parent / "comfyui" / "workflow.template.json")
                              .read_text(encoding="utf-8"))
    art_path = comfy.generate(workflow, positive_node=positive_node, sampler_node=sampler_node,
                              prompt=cfg.art_prompt, seed=seed, out_path=out_dir / "art.png")

    # ④ cover
    build_cover(cfg, pages, art_path, out_dir, runner=runner)

    # ⑤ checklist
    make_checklist(cfg, pages, out_dir)
    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Build a KDP pet-loss journal bundle")
    ap.add_argument("config", help="path to book.config.json")
    ap.add_argument("--out", default="out", help="output root dir")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    out = run_build(args.config, out_root=args.out, seed=args.seed)
    print(f"Done. Bundle in: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_build.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests pass (specs, config, content, browsepdf, interior, art, cover, checklist, build).

- [ ] **Step 6: Commit**

```bash
git add factory/build.py factory/tests/test_build.py
git commit -m "feat: one-command build orchestrator"
```

---

### Task 11: Configs, ComfyUI workflow template, README

These are data/docs, not code-under-test. The ComfyUI workflow MUST be exported by the user from their running ComfyUI in **API format** (Settings → enable dev mode → "Save (API Format)") because node IDs/checkpoint names depend on their install. The template below is a minimal SD-style graph; the user replaces the checkpoint name and confirms node IDs `6` (positive CLIPTextEncode) and `3` (KSampler).

**Files:**
- Create: `factory/books/dog-loss.config.json`
- Create: `factory/books/cat-loss.config.json`
- Create: `factory/books/pet-loss.config.json`
- Create: `factory/comfyui/workflow.template.json`
- Create: `factory/README.md`

- [ ] **Step 1: Create `factory/books/dog-loss.config.json`**

```json
{
  "slug": "dog-loss",
  "title": "Paw Prints on My Heart",
  "subtitle": "A Guided Grief Journal for the Loss of a Beloved Dog",
  "author": "Quint Mertesdorf",
  "pet_kind": "dog",
  "prompt_count": 70,
  "art_prompt": "soft pastel watercolor of a dog resting at a rainbow bridge at dawn, tender, peaceful, gentle light, no text, no words",
  "price_usd": 9.99
}
```

- [ ] **Step 2: Create `factory/books/cat-loss.config.json`**

```json
{
  "slug": "cat-loss",
  "title": "Whiskers and Memories",
  "subtitle": "A Guided Grief Journal for the Loss of a Beloved Cat",
  "author": "Quint Mertesdorf",
  "pet_kind": "cat",
  "prompt_count": 70,
  "art_prompt": "soft pastel watercolor of a cat curled on a windowsill in warm soft light, tender, peaceful, gentle, no text, no words",
  "price_usd": 9.99
}
```

- [ ] **Step 3: Create `factory/books/pet-loss.config.json`**

```json
{
  "slug": "pet-loss",
  "title": "Forever in My Heart",
  "subtitle": "A Guided Grief Journal for the Loss of a Beloved Pet",
  "author": "Quint Mertesdorf",
  "pet_kind": "pet",
  "prompt_count": 70,
  "art_prompt": "soft pastel watercolor memorial scene with a single glowing candle and wildflowers, tender, peaceful, gentle, no text, no words",
  "price_usd": 9.99
}
```

- [ ] **Step 4: Create `factory/comfyui/workflow.template.json`**

Replace `"REPLACE_WITH_YOUR_CHECKPOINT.safetensors"` with a checkpoint from your ComfyUI (`D:\ComfyUI-models\checkpoints\...`). Verify node `6` is the positive prompt and `3` is the sampler; adjust `build.py --positive-node/--sampler-node` if different.

```json
{
  "3": {"class_type": "KSampler", "inputs": {
    "seed": 0, "steps": 25, "cfg": 6.5, "sampler_name": "euler", "scheduler": "normal",
    "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "REPLACE_WITH_YOUR_CHECKPOINT.safetensors"}},
  "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1536, "batch_size": 1}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER", "clip": ["4", 1]}},
  "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "text, words, letters, watermark, signature, blurry, deformed", "clip": ["4", 1]}},
  "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
  "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "petloss_cover", "images": ["8", 0]}}
}
```

- [ ] **Step 5: Create `factory/README.md`**

````markdown
# Pet-Loss Grief Journal Factory

One command turns a book config into a KDP-ready bundle.

## Setup (once)
```powershell
cd factory
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```
- Ensure the `claude` CLI is on PATH (content generation).
- Ensure the gstack `browse` binary exists (PDF render) — it does at
  `~/.claude/skills/gstack/browse/dist/browse`.
- Start ComfyUI (`run_comfyui.bat`) so `http://127.0.0.1:8188` is live.
- Edit `comfyui/workflow.template.json`: set your checkpoint name.

## Build a title
```powershell
python build.py books/dog-loss.config.json
```
Output lands in `out/dog-loss/`: `interior.pdf`, `interior.epub`,
`cover-paperback.pdf`, `cover-ebook.jpg`, `upload-checklist.md`.

## Add a new title to the series
Drop a new `books/<slug>.config.json` and run `build.py` on it. No template edits.

## Upload (manual — KDP has no API for individuals)
Open KDP, create paperback + ebook, upload the files, paste metadata from
`upload-checklist.md`, and answer the AI-content disclosure as listed. Run KDP's
print previewer before publishing.

## Run tests
```powershell
pytest -v
```
````

- [ ] **Step 6: Commit**

```bash
git add factory/books/ factory/comfyui/ factory/README.md
git commit -m "feat: book configs, ComfyUI workflow template, README"
```

---

### Task 12: Live smoke test (manual, real services)

Verifies the real pipeline end-to-end. Not an automated test — a documented manual run.

- [ ] **Step 1: Preconditions**

Confirm: venv active, `claude` responds (`claude -p "say hi"`), `browse` runs (`& $HOME\.claude\skills\gstack\browse\dist\browse status`), ComfyUI reachable (`curl http://127.0.0.1:8188/system_stats`), checkpoint name set in `workflow.template.json`.

- [ ] **Step 2: Run the real build**

Run: `python build.py books/dog-loss.config.json`
Expected: `out/dog-loss/` contains all five outputs; `content.json` has 70 prompts.

- [ ] **Step 3: Inspect outputs**

Open `interior.pdf` — pages are 6x9, lined prompt pages render, no clipped text. Open `cover-paperback.pdf` — art spans back+spine+front, title legible on the front panel. Open `cover-ebook.jpg` — 1600x2560 front cover. Read `upload-checklist.md` — disclosure + royalty present.

- [ ] **Step 4: KDP previewer dry run**

In KDP, start a paperback draft, upload `interior.pdf` + `cover-paperback.pdf`, and run the print previewer. Confirm no margin/bleed/spine errors. (Do not publish yet.)

- [ ] **Step 5: Record findings**

Note any layout fixes needed (margins, font size, spine) and feed them back as small follow-up tasks editing `interior.css` / `cover.css` / `specs.py`.

---

## Self-Review

**Spec coverage:**
- §3 paperback + ebook → Tasks 6 (PDF + EPUB), 8 (covers). ✓
- §3 interior HTML/CSS→PDF → Tasks 5–6. ✓
- §3 cover ComfyUI + typographic text + auto spine → Tasks 7–8, spine in Task 1. ✓
- §3 one-command generator → Task 10. ✓
- §3 content via `claude -p` → Task 3 (`claude_generate`). ✓
- §5 ⑤ checklist + AI disclosure → Task 9. ✓
- §6 repo layout → Task 0 + per-file tasks. ✓
- §8 economics → Task 1 (royalty/print cost), surfaced in Task 9. ✓
- §3 3-title series reuse → Task 11 configs, validated by "new config only" design. ✓
- §9 isolated/swappable stages → each stage is its own module with injected effects. ✓

**Placeholder scan:** No TBD/TODO in code steps; the only intentional placeholders are the user-supplied ComfyUI checkpoint name and the API-format workflow export, both flagged explicitly in Task 11 as external inputs the user must provide.

**Type consistency:** `BookConfig` fields consistent across config/content/interior/cover/checklist. `runner` signature `(args) -> CompletedProcess-like` consistent across browsepdf/interior/cover/build. `ComfyClient.generate(...)` signature matches its call in `build.run_build`. `count_pages`/`build_interior_pdf` names consistent between Task 6 and Task 10.

**Known approximation:** Spec §8 estimated royalty ~$3.69 (using a $2.30 print cost); the code uses KDP's actual formula (`$1.00 + pages*$0.012` = $2.44 at 120pp → royalty $3.55). The code is the source of truth; the checklist shows the precise figure.

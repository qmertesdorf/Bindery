# Standard Read-Through Books — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the journal factory to also produce standard read-through prose books (front matter + chapters) end to end, and ship a first such title — a pet-loss companion read — without disturbing the journal path.

**Architecture:** Per-`book_type` strategy (approach B). A dispatcher in `content.py` routes to a journal generator (single LLM call, unchanged) or a new standard generator (`standard_content.py`, two-pass: outline then one call per chapter). The interior selects its Jinja template by `book_type`; standard interiors take the real rendered PDF page count. EPUB renders the standard chapter schema. New build-time guards reject a wrong-length outline or an empty/refused chapter, joining the existing margin/cover guards.

**Tech Stack:** Python 3, dataclasses, Jinja2, PyMuPDF (`fitz`), ebooklib, pytest. External effects (LLM, browser PDF, ComfyUI) stay behind injected adapters so every test runs with fakes — no network/GPU.

---

## File Structure

**Modify:**
- `factory/factory/config.py` — make `pet_kind` optional; add `synopsis`, `chapter_count`, `words_per_chapter`, `blurb`; per-`book_type` validation.
- `factory/factory/content.py` — turn `generate_content` into a dispatcher; keep journal logic; export shared `_strip_fences`/`ContentError`.
- `factory/factory/interior.py` — template selection by `book_type`; `pdf_page_count`; standard page count; standard-schema EPUB.
- `factory/factory/copy.py` — `book_blurb` dispatches on `book_type`.
- `factory/factory/checklist.py` — `_keywords` + template generalized for standard.
- `factory/build.py` — pass `book_type` into `build_interior_pdf`.
- `factory/templates/checklist.md.j2` — branch description/categories on `book_type`.
- Existing uncommitted tests that assume the old shapes (`test_config.py`, `test_build.py`, `test_interior.py`, `test_checklist.py`).

**Create:**
- `factory/factory/standard_content.py` — outline + chapter prompts, two-pass generator, validators, guards.
- `factory/templates/interior/standard.html.j2` — prose chapter template.
- `factory/templates/interior/journal.html.j2` — renamed from `book.html.j2`.
- `factory/books/dog-loss-companion.config.json` — the first standard title.
- `factory/tests/test_standard_content.py` — unit tests for the standard generator + guards.

---

## Task 0: Commit the existing edition-gating scaffolding

The working tree already has the `book_type`/`makes_ebook` plumbing and its tests. Land it as a clean baseline before building on it.

**Files:**
- Modify: (already-edited working tree) `factory/factory/config.py`, `factory/build.py`, `factory/factory/cover.py`, `factory/templates/checklist.md.j2`, `factory/tests/test_config.py`, `factory/tests/test_build.py`, `factory/tests/test_checklist.py`, `factory/tests/test_cover.py`

- [ ] **Step 1: Run the existing suite to confirm the scaffolding is green**

Run: `cd factory && pytest -q`
Expected: PASS (the pre-edited tests for book_type/makes_ebook pass against the current code).

- [ ] **Step 2: Commit the scaffolding**

```bash
git add factory/factory/config.py factory/build.py factory/factory/cover.py \
  factory/templates/checklist.md.j2 factory/tests/test_config.py \
  factory/tests/test_build.py factory/tests/test_checklist.py factory/tests/test_cover.py
git commit -m "feat(config): book_type + paperback-only edition gating"
```

---

## Task 1: Config — optional pet_kind + standard fields + per-type validation

**Files:**
- Modify: `factory/factory/config.py`
- Modify: `factory/tests/test_config.py`
- Test: `factory/tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_config.py` (top already imports `json, pytest, load_config, ConfigError`):

```python
def _write(tmp_path, **over):
    base = {"slug": "x", "title": "T", "subtitle": "S", "author": "A",
            "art_prompt": "art"}
    base.update(over)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    return p


def test_journal_requires_pet_kind(tmp_path):
    # journal is the default; without pet_kind it must fail
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path))            # no pet_kind
    assert "pet_kind" in str(e.value)


def test_standard_requires_synopsis_and_chapters(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, book_type="standard"))  # no synopsis/chapter_count
    msg = str(e.value)
    assert "synopsis" in msg or "chapter_count" in msg


def test_standard_config_loads_fields(tmp_path):
    cfg = load_config(_write(tmp_path, book_type="standard",
                             synopsis="A gentle book.", chapter_count=8,
                             words_per_chapter=1500, blurb="Back cover."))
    assert cfg.book_type == "standard"
    assert cfg.synopsis == "A gentle book."
    assert cfg.chapter_count == 8
    assert cfg.words_per_chapter == 1500
    assert cfg.blurb == "Back cover."
    assert cfg.pet_kind == ""                    # optional for standard
    assert cfg.makes_ebook is True
```

Also UPDATE the existing uncommitted `test_standard_book_type_makes_ebook` so it now supplies the newly-required standard fields (otherwise it will fail validation):

```python
def test_standard_book_type_makes_ebook(tmp_path):
    p = tmp_path / "std.json"
    p.write_text(json.dumps({
        "slug": "memoir", "title": "T", "subtitle": "S", "author": "A",
        "art_prompt": "x", "book_type": "standard",
        "synopsis": "A gentle read.", "chapter_count": 8,
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.book_type == "standard"
    assert cfg.makes_ebook is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd factory && pytest tests/test_config.py -q`
Expected: FAIL — `pet_kind` still in base `REQUIRED` (journal test passes for wrong reason / standard tests error on unknown kwargs `synopsis`).

- [ ] **Step 3: Implement the config changes**

Replace the body of `factory/factory/config.py` from the `REQUIRED` line through the end of `load_config` with:

```python
REQUIRED = ["slug", "title", "subtitle", "author", "art_prompt"]
BOOK_TYPES = ("journal", "standard")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BookConfig:
    slug: str
    title: str
    subtitle: str
    author: str
    art_prompt: str
    pet_kind: str = ""                # journals only
    prompt_count: int = 70           # journals only
    price_usd: float = 9.99
    book_type: str = "journal"
    synopsis: str = ""               # standard only
    chapter_count: int = 0           # standard only
    words_per_chapter: int = 0       # standard only
    blurb: str = ""                  # standard back-cover/listing copy

    @property
    def makes_ebook(self) -> bool:
        """Whether this title gets a Kindle/EPUB edition.

        Journals are paperback-only — a fill-in journal is useless as a
        reflowable Kindle book (you can't write in it) — so only standard
        read-through books produce an EPUB + ebook cover.
        """
        return self.book_type == "standard"


def load_config(path: str | Path) -> BookConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON: {e}") from e
    missing = [k for k in REQUIRED if k not in data or data[k] in (None, "")]
    if missing:
        raise ConfigError(f"{path}: missing required field(s): {', '.join(missing)}")
    book_type = str(data.get("book_type", "journal"))
    if book_type not in BOOK_TYPES:
        raise ConfigError(
            f"{path}: book_type must be one of {BOOK_TYPES}, got {book_type!r}")
    if book_type == "journal" and not data.get("pet_kind"):
        raise ConfigError(f"{path}: journal books require 'pet_kind'")
    if book_type == "standard":
        miss = [k for k in ("synopsis", "chapter_count")
                if not data.get(k)]
        if miss:
            raise ConfigError(
                f"{path}: standard books require: {', '.join(miss)}")
    return BookConfig(
        slug=data["slug"],
        title=data["title"],
        subtitle=data["subtitle"],
        author=data["author"],
        art_prompt=data["art_prompt"],
        pet_kind=str(data.get("pet_kind", "")),
        prompt_count=int(data.get("prompt_count", 70)),
        price_usd=float(data.get("price_usd", 9.99)),
        book_type=book_type,
        synopsis=str(data.get("synopsis", "")),
        chapter_count=int(data.get("chapter_count", 0)),
        words_per_chapter=int(data.get("words_per_chapter", 0)),
        blurb=str(data.get("blurb", "")),
    )
```

- [ ] **Step 4: Run the config tests**

Run: `cd factory && pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite (some failures expected downstream)**

Run: `cd factory && pytest -q`
Expected: `test_config.py` green. Other modules still green (BookConfig is constructed by keyword everywhere). If any test constructs `BookConfig` positionally, fix it to keyword — but a grep shows all call sites use keywords.

- [ ] **Step 6: Commit**

```bash
git add factory/factory/config.py factory/tests/test_config.py
git commit -m "feat(config): optional pet_kind + standard book fields & validation"
```

---

## Task 2: Standard content generator (two-pass) + guards

**Files:**
- Create: `factory/factory/standard_content.py`
- Modify: `factory/factory/content.py` (export `_strip_fences`; make `generate_content` dispatch)
- Test: `factory/tests/test_standard_content.py`

- [ ] **Step 1: Write failing tests**

Create `factory/tests/test_standard_content.py`:

```python
import json
import pytest
from factory.config import BookConfig
from factory.content import ContentError
from factory.standard_content import (
    build_outline_prompt, build_chapter_prompt,
    validate_outline, validate_chapter, generate_standard_content,
)


def cfg(**over):
    base = dict(slug="comp", title="Gentle Goodbye", subtitle="Sub", author="A",
                art_prompt="x", book_type="standard", synopsis="Grieving a dog.",
                chapter_count=3, words_per_chapter=40)
    base.update(over)
    return BookConfig(**base)


def _para(n_words=30):
    return " ".join(["word"] * n_words)


def _fake(outline_chapters=3):
    """A prompt-aware fake LLM: outline call vs chapter call."""
    outline = {"preface": "A short preface.",
               "chapters": [{"title": f"Chapter {i}", "synopsis": "s"}
                            for i in range(1, outline_chapters + 1)]}

    def fn(prompt):
        if "OUTLINE" in prompt:
            return json.dumps(outline)
        return json.dumps({"paragraphs": [_para(), _para()]})
    return fn


def test_outline_prompt_mentions_synopsis_and_count():
    p = build_outline_prompt(cfg())
    assert "Grieving a dog." in p
    assert "3" in p
    assert "OUTLINE" in p          # marker the fake/tests key on


def test_chapter_prompt_includes_prior_titles():
    p = build_chapter_prompt(cfg(), {"title": "Two", "synopsis": "s"}, 2, ["One"])
    assert "Two" in p
    assert "One" in p              # continuity context


def test_generate_standard_two_pass_accumulates_chapters():
    out = generate_standard_content(cfg(chapter_count=3), generate_fn=_fake(3))
    assert out["preface"] == "A short preface."
    assert len(out["chapters"]) == 3
    assert out["chapters"][0]["title"] == "Chapter 1"
    assert out["chapters"][0]["paragraphs"]


def test_outline_wrong_length_is_rejected():
    # config asks for 3 chapters, outline returns 2 -> guard fires
    with pytest.raises(ContentError):
        generate_standard_content(cfg(chapter_count=3), generate_fn=_fake(2))


def test_validate_chapter_rejects_too_short():
    with pytest.raises(ContentError):
        validate_chapter({"paragraphs": ["too short"]}, min_words=20)


def test_validate_outline_rejects_missing_preface():
    with pytest.raises(ContentError):
        validate_outline({"chapters": [{"title": "a", "synopsis": "s"}]}, 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && pytest tests/test_standard_content.py -q`
Expected: FAIL with `ModuleNotFoundError: factory.standard_content`.

- [ ] **Step 3: Export the shared helper from `content.py`**

In `factory/factory/content.py`, the helpers `_strip_fences` and `ContentError` already exist. No change needed beyond importing them in the new module. (They are module-level and importable as-is.)

- [ ] **Step 4: Create `factory/factory/standard_content.py`**

```python
"""Standard (read-through) book content: two-pass outline + per-chapter prose."""
from __future__ import annotations
import json
from typing import Callable
from .config import BookConfig
from .content import ContentError, _strip_fences

MIN_CHAPTER_WORDS = 20   # floor that catches an empty / refused generation


def build_outline_prompt(cfg: BookConfig) -> str:
    return f"""You are an author planning a warm, comforting read-through book.
Title: {cfg.title}
Subtitle: {cfg.subtitle}
What the book is about: {cfg.synopsis}

Plan exactly {cfg.chapter_count} chapters that flow as a gentle, supportive read.

Return ONLY valid JSON (no markdown, no commentary) for this OUTLINE:
{{"preface": "2-4 warm sentences introducing the book",
  "chapters": [{{"title": "chapter title", "synopsis": "one sentence"}}]}}
with exactly {cfg.chapter_count} chapter objects. Output the JSON and nothing else."""


def build_chapter_prompt(cfg: BookConfig, chapter: dict, n: int,
                         prior_titles: list[str]) -> str:
    prior = "; ".join(prior_titles) if prior_titles else "(this is the first chapter)"
    return f"""You are writing one chapter of the book "{cfg.title}" ({cfg.subtitle}).
Premise: {cfg.synopsis}
This is chapter {n} of {cfg.chapter_count}: "{chapter['title']}" — {chapter.get('synopsis', '')}
Earlier chapters so far: {prior}

Write approximately {cfg.words_per_chapter} words of warm, gentle, tender prose.
Do NOT repeat the chapter title or add headings.

Return ONLY valid JSON: {{"paragraphs": ["paragraph 1", "paragraph 2"]}}
(3-8 paragraphs). Output the JSON and nothing else."""


def validate_outline(data: dict, expected_chapters: int) -> None:
    if not isinstance(data, dict):
        raise ContentError("outline is not a JSON object")
    if not data.get("preface"):
        raise ContentError("outline missing 'preface'")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != expected_chapters:
        raise ContentError(
            f"outline must have exactly {expected_chapters} chapters, got "
            f"{len(chapters) if isinstance(chapters, list) else 'non-list'}")
    for i, ch in enumerate(chapters, 1):
        if not isinstance(ch, dict) or not ch.get("title"):
            raise ContentError(f"outline chapter {i} missing 'title'")


def validate_chapter(data: dict, min_words: int = MIN_CHAPTER_WORDS) -> None:
    paras = data.get("paragraphs") if isinstance(data, dict) else None
    if not isinstance(paras, list) or not paras:
        raise ContentError("chapter has no paragraphs")
    words = sum(len(str(p).split()) for p in paras)
    if words < min_words:
        raise ContentError(
            f"chapter prose too short ({words} words < {min_words}); "
            f"the generation was likely truncated or refused")


def generate_standard_content(cfg: BookConfig,
                              generate_fn: Callable[[str], str]) -> dict:
    raw = generate_fn(build_outline_prompt(cfg))
    try:
        outline = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"outline is not valid JSON: {e}") from e
    validate_outline(outline, cfg.chapter_count)

    chapters, titles = [], []
    for i, ch in enumerate(outline["chapters"], 1):
        raw_c = generate_fn(build_chapter_prompt(cfg, ch, i, titles))
        try:
            body = json.loads(_strip_fences(raw_c))
        except json.JSONDecodeError as e:
            raise ContentError(f"chapter {i} is not valid JSON: {e}") from e
        validate_chapter(body)
        chapters.append({"title": ch["title"], "paragraphs": body["paragraphs"]})
        titles.append(ch["title"])

    return {"preface": outline["preface"], "chapters": chapters}
```

- [ ] **Step 5: Run the standard-content tests**

Run: `cd factory && pytest tests/test_standard_content.py -q`
Expected: PASS.

- [ ] **Step 6: Make `generate_content` dispatch on book_type**

In `factory/factory/content.py`, replace the `generate_content` function with:

```python
def generate_content(cfg: BookConfig, generate_fn: Callable[[str], str]) -> dict:
    if cfg.book_type == "standard":
        from .standard_content import generate_standard_content
        return generate_standard_content(cfg, generate_fn)
    raw = generate_fn(build_prompt(cfg))
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise ContentError(f"LLM did not return valid JSON: {e}") from e
    validate_content(data, cfg.prompt_count)
    return data
```

(The local import avoids a circular import at module load.)

- [ ] **Step 7: Run content + standard-content tests**

Run: `cd factory && pytest tests/test_content.py tests/test_standard_content.py -q`
Expected: PASS (journal path unchanged; standard path dispatched).

- [ ] **Step 8: Commit**

```bash
git add factory/factory/standard_content.py factory/factory/content.py factory/tests/test_standard_content.py
git commit -m "feat(content): two-pass standard book generator + outline/chapter guards"
```

---

## Task 3: Interior — rename journal template, add standard template, page count

**Files:**
- Rename: `factory/templates/interior/book.html.j2` → `factory/templates/interior/journal.html.j2`
- Create: `factory/templates/interior/standard.html.j2`
- Modify: `factory/factory/interior.py`
- Modify: `factory/build.py`
- Modify: `factory/tests/test_interior.py`
- Test: `factory/tests/test_interior.py`

- [ ] **Step 1: Rename the journal template**

```bash
git mv factory/templates/interior/book.html.j2 factory/templates/interior/journal.html.j2
```

- [ ] **Step 2: Create `factory/templates/interior/standard.html.j2`**

```jinja
<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="interior.css"></head><body>

<section class="page title-page"><h1 class="book-title">{{ cfg.title }}</h1>
<p class="book-sub">{{ cfg.subtitle }}</p>
<p class="byline">{{ cfg.author }}</p></section>

<section class="page preface"><div class="intro-body">
{% for para in content.preface.split('\n') if para.strip() %}<p>{{ para }}</p>{% endfor %}
</div></section>

{% for ch in content.chapters %}
<section class="chapter"><h2 class="chapter-head">{{ ch.title }}</h2>
{% for para in ch.paragraphs %}<p class="body-para">{{ para }}</p>{% endfor %}
</section>
{% endfor %}

</body></html>
```

- [ ] **Step 3: Add prose CSS so chapters paginate (no fill-in lines)**

Append to `factory/templates/interior/interior.css`:

```css
/* Standard read-through books: each chapter starts on a new page; prose flows. */
.chapter { break-before: page; page-break-before: always; }
.chapter-head { font-size: 18pt; margin: 0 0 0.4in 0; text-align: center; }
.body-para { font-size: 11pt; line-height: 1.5; margin: 0 0 0.18in 0;
             text-indent: 0.25in; text-align: justify; }
.title-page { text-align: center; }
```

- [ ] **Step 4: Write failing interior tests**

Add to `factory/tests/test_interior.py` (imports already cover `render_interior_html`, `build_interior_pdf`; add `pdf_page_count` to the import line `from factory.interior import (...)`):

```python
def std_cfg():
    return BookConfig(slug="comp", title="Gentle Goodbye", subtitle="Sub",
                      author="A", art_prompt="x", book_type="standard",
                      synopsis="Grieving a dog.", chapter_count=2,
                      words_per_chapter=40)


def std_content():
    return {"preface": "A short preface.",
            "chapters": [{"title": "First", "paragraphs": ["Para one.", "Para two."]},
                         {"title": "Second", "paragraphs": ["Para three."]}]}


def test_standard_interior_renders_chapters_no_fill_lines(tmp_path):
    html_path = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "Gentle Goodbye" in text
    assert "First" in text and "Para one." in text
    assert 'class="chapter"' in text
    assert 'class="lines"' not in text          # no journal fill-in ruled lines


def test_pdf_page_count(tmp_path):
    import fitz
    p = tmp_path / "doc.pdf"
    d = fitz.open()
    d.new_page(); d.new_page(); d.new_page()
    d.save(str(p)); d.close()
    assert pdf_page_count(p) == 3
    stub = tmp_path / "s.pdf"; stub.write_bytes(b"x")
    assert pdf_page_count(stub) == 0            # non-PDF stub -> 0, no crash
```

- [ ] **Step 5: Run to verify failure**

Run: `cd factory && pytest tests/test_interior.py -q`
Expected: FAIL — `render_interior_html` still hardcodes `interior/book.html.j2` (now renamed → TemplateNotFound) and `pdf_page_count` is undefined.

- [ ] **Step 6: Implement interior changes**

In `factory/factory/interior.py`, replace `render_interior_html` and add `pdf_page_count`, and update `build_interior_pdf`:

```python
def render_interior_html(cfg: BookConfig, content: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    template = ("interior/standard.html.j2" if cfg.book_type == "standard"
                else "interior/journal.html.j2")
    html = render(template, cfg=cfg, content=content)
    html_path = out_dir / "interior.html"
    html_path.write_text(html, encoding="utf-8")
    shutil.copy(TEMPLATES_DIR / "interior" / "interior.css", out_dir / "interior.css")
    return html_path


def pdf_page_count(pdf: Path) -> int:
    """Real rendered page count of a PDF (0 for a non-PDF stub)."""
    import fitz
    try:
        doc = fitz.open(str(pdf))
    except Exception:
        return 0
    return doc.page_count
```

Change `build_interior_pdf` to accept `book_type` and use the right counter:

```python
def build_interior_pdf(html_path: Path, out_dir: Path, runner=None,
                       book_type: str = "journal") -> tuple[Path, int]:
    out_dir = Path(out_dir)
    pdf = out_dir / "interior.pdf"
    html_to_pdf(Path(html_path), pdf,
                width_in=specs.TRIM_W_IN, height_in=specs.TRIM_H_IN,
                margins_in=0.0, runner=runner)
    _verify_interior_margins(pdf)
    pages = (pdf_page_count(pdf) if book_type == "standard"
             else count_pages(html_path))
    return pdf, pages
```

- [ ] **Step 7: Wire build.py to pass book_type**

In `factory/build.py`, change the interior call:

```python
    _, pages = build_interior_pdf(html, out_dir, runner=runner, book_type=cfg.book_type)
```

- [ ] **Step 8: Run interior tests + full suite**

Run: `cd factory && pytest tests/test_interior.py -q`
Expected: PASS (journal tests still count via HTML; new standard/pdf tests pass).

Run: `cd factory && pytest -q`
Expected: PASS except `test_build_epub` (rewritten in Task 4) and the standard end-to-end (Task 7) — fix those there.

- [ ] **Step 9: Commit**

```bash
git add factory/factory/interior.py factory/build.py \
  factory/templates/interior/journal.html.j2 factory/templates/interior/standard.html.j2 \
  factory/templates/interior/interior.css factory/tests/test_interior.py
git commit -m "feat(interior): standard prose template + real PDF page count"
```

---

## Task 4: EPUB renders the standard chapter schema

**Files:**
- Modify: `factory/factory/interior.py` (`build_epub`)
- Modify: `factory/tests/test_interior.py` (`test_build_epub`)
- Test: `factory/tests/test_interior.py`

- [ ] **Step 1: Rewrite the EPUB test for the standard schema**

Replace the existing `test_build_epub` in `factory/tests/test_interior.py` with:

```python
def test_build_epub_standard_chapters(tmp_path):
    out = build_epub(std_cfg(), std_content(), tmp_path)
    assert Path(out).exists() and Path(out).suffix == ".epub"
    # the chapters are present in the package
    import zipfile
    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith(".xhtml") for n in names)
```

(`std_cfg`/`std_content` were added in Task 3.)

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && pytest tests/test_interior.py::test_build_epub_standard_chapters -q`
Expected: FAIL — current `build_epub` reads journal keys (`content['intro']`, `content['prompts']`) which the standard content dict lacks → `KeyError`.

- [ ] **Step 3: Rewrite `build_epub` for the standard schema**

Replace `build_epub` in `factory/factory/interior.py` with:

```python
def build_epub(cfg: BookConfig, content: dict, out_dir: Path,
               cover_path: Path | None = None) -> Path:
    book = epub.EpubBook()
    book.set_identifier(f"book-{cfg.slug}")
    book.set_title(cfg.title)
    book.set_language("en")
    book.add_author(cfg.author)

    # Embed the finished, title-bearing ebook cover JPG (≈1 MB) rather than the
    # print-resolution PNG, keeping the EPUB light (KDP charges per-MB delivery
    # on the 70% royalty plan).
    if cover_path is not None and Path(cover_path).exists():
        cp = Path(cover_path)
        book.set_cover("cover" + cp.suffix, cp.read_bytes())

    def chapter(title, body_html, fname):
        c = epub.EpubHtml(title=title, file_name=fname, lang="en")
        c.content = f"<h1>{title}</h1>{body_html}"
        book.add_item(c)
        return c

    items = []
    if content.get("preface"):
        pre_html = "".join(f"<p>{p}</p>" for p in content["preface"].split("\n") if p.strip())
        items.append(chapter("Preface", pre_html, "preface.xhtml"))
    for i, ch in enumerate(content["chapters"], 1):
        body = "".join(f"<p>{p}</p>" for p in ch["paragraphs"])
        items.append(chapter(ch["title"], body, f"chap{i}.xhtml"))

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]

    out = Path(out_dir) / "interior.epub"
    out.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out), book)
    return out
```

- [ ] **Step 4: Run the EPUB test**

Run: `cd factory && pytest tests/test_interior.py::test_build_epub_standard_chapters -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/interior.py factory/tests/test_interior.py
git commit -m "feat(epub): render standard preface + chapter schema"
```

---

## Task 5: Back-cover blurb dispatches on book_type

**Files:**
- Modify: `factory/factory/copy.py`
- Test: `factory/tests/test_cover.py` (new test) — or `factory/tests/test_copy.py` (create if absent)

- [ ] **Step 1: Write failing test**

Create `factory/tests/test_copy.py`:

```python
from factory.config import BookConfig
from factory.copy import book_blurb


def journal_cfg():
    return BookConfig(slug="d", title="T", subtitle="S", author="A",
                      pet_kind="dog", art_prompt="x")


def standard_cfg(**over):
    base = dict(slug="c", title="T", subtitle="S", author="A", art_prompt="x",
                book_type="standard", synopsis="A gentle read about loss.",
                chapter_count=8)
    base.update(over)
    return BookConfig(**base)


def test_journal_blurb_mentions_pet():
    assert "dog" in book_blurb(journal_cfg())


def test_standard_blurb_uses_blurb_field():
    assert book_blurb(standard_cfg(blurb="Custom back cover.")) == "Custom back cover."


def test_standard_blurb_falls_back_to_synopsis():
    assert book_blurb(standard_cfg()) == "A gentle read about loss."
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && pytest tests/test_copy.py -q`
Expected: FAIL — standard branch not implemented (returns the pet sentence / references empty `pet_kind`).

- [ ] **Step 3: Implement dispatch in `factory/factory/copy.py`**

```python
"""Shared marketing copy derived from a BookConfig (back-cover blurb, etc.)."""
from __future__ import annotations
from .config import BookConfig


def book_blurb(cfg: BookConfig) -> str:
    """One-paragraph back-cover / listing blurb for a title."""
    if cfg.book_type == "standard":
        return cfg.blurb or cfg.synopsis
    return (f"A gentle, guided journal to help you grieve and remember your beloved "
            f"{cfg.pet_kind}. Undated reflective prompts, memory pages, and milestone "
            f"reflections give you a private space to process loss at your own pace. "
            f"A comforting keepsake and a thoughtful gift.")
```

- [ ] **Step 4: Run the test**

Run: `cd factory && pytest tests/test_copy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/copy.py factory/tests/test_copy.py
git commit -m "feat(copy): standard-book blurb from blurb/synopsis"
```

---

## Task 6: Checklist generalized for standard books

**Files:**
- Modify: `factory/factory/checklist.py` (`_keywords`)
- Modify: `factory/templates/checklist.md.j2`
- Modify: `factory/tests/test_checklist.py` (`std_cfg` gains synopsis)
- Test: `factory/tests/test_checklist.py`

- [ ] **Step 1: Write failing tests + fix the existing std_cfg**

In `factory/tests/test_checklist.py`, update `std_cfg` to a valid standard config and add assertions:

```python
def std_cfg():
    return BookConfig(slug="memoir", title="A Book", subtitle="Sub",
                      author="A", art_prompt="x", price_usd=9.99,
                      book_type="standard", synopsis="A gentle read about loss.",
                      chapter_count=8, blurb="A comforting companion read.")


def test_standard_checklist_no_pet_kind_crash(tmp_path):
    # standard books have empty pet_kind; keywords/description must not break
    text = Path(make_checklist(std_cfg(), pages=120, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "A comforting companion read." in text   # standard description = blurb
    assert "{{" not in text                          # template fully rendered
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && pytest tests/test_checklist.py -q`
Expected: FAIL — template hardcodes the pet-grief description + `cfg.pet_kind` in keywords/categories; standard `pet_kind=""` yields wrong/empty copy.

- [ ] **Step 3: Make `_keywords` book_type-aware**

In `factory/factory/checklist.py`, replace `_keywords`:

```python
def _keywords(cfg: BookConfig) -> str:
    if cfg.book_type == "standard":
        # Derive simple keyword seeds from the title; the publisher refines these
        # against live Amazon search before upload.
        base = [cfg.title.lower(), "comfort read", "grief support book",
                "pet loss book", "coping with loss", "memorial gift",
                "rainbow bridge"]
        return ", ".join(base[:7])
    base = [f"{cfg.pet_kind} loss gift", f"{cfg.pet_kind} memorial journal",
            "pet loss grief journal", "pet bereavement", "rainbow bridge keepsake",
            "in memory of pet", f"loss of a {cfg.pet_kind}"]
    return ", ".join(base[:7])
```

- [ ] **Step 4: Branch the template description + categories on book_type**

In `factory/templates/checklist.md.j2`, replace the `- **Description:**` block (lines ~15-18) with:

```jinja
- **Description:** (paste)
{%- if cfg.book_type == "standard" %}
  <p>{{ cfg.blurb or cfg.synopsis }}</p>
{%- else %}
  <p>A gentle, guided journal to help you grieve and remember your beloved {{ cfg.pet_kind }}.
  Undated reflective prompts, memory pages, and milestone reflections give you a private
  space to process loss at your own pace. A comforting keepsake and a thoughtful gift.</p>
{%- endif %}
```

And replace the `## Categories (choose 2)` block (lines ~31-33) with:

```jinja
## Categories (choose 2)
{%- if cfg.book_type == "standard" %}
1. Self-Help › Death & Grief
2. Family & Relationships › Death, Grief, Bereavement
{%- else %}
1. Self-Help › Death & Grief
2. Self-Help › Journaling   (or Crafts, Hobbies & Home › {{ cfg.pet_kind|capitalize }} care)
{%- endif %}
```

Also make the price line edition-aware so a standard book shows it covers both editions; replace the `- **Price:**` and `- **Estimated royalty:**` lines with:

```jinja
- **Price:** ${{ "%.2f"|format(cfg.price_usd) }}{% if cfg.makes_ebook %} (same list price for paperback and Kindle — $9.99 earns 70% ebook / 60% paperback){% else %} (paperback){% endif %}
- **Estimated royalty:** ${{ "%.2f"|format(royalty) }}/sale paperback (60% − ${{ "%.2f"|format(print_cost) }} print)
```

- [ ] **Step 5: Run checklist tests**

Run: `cd factory && pytest tests/test_checklist.py -q`
Expected: PASS (journal assertions still hold; standard description = blurb, no unrendered `{{`).

- [ ] **Step 6: Commit**

```bash
git add factory/factory/checklist.py factory/templates/checklist.md.j2 factory/tests/test_checklist.py
git commit -m "feat(checklist): standard-book description, categories, keywords"
```

---

## Task 7: End-to-end standard build with fakes

**Files:**
- Modify: `factory/tests/test_build.py` (prompt-aware fake for standard)
- Test: `factory/tests/test_build.py`

- [ ] **Step 1: Generalize `_build` to accept a custom fake LLM, then drive the two-pass standard build**

The shared `_build` helper hardcodes a journal `fake_llm`; a standard build now calls the LLM for an outline then once per chapter. Rather than duplicate the ComfyUI/browse plumbing (and risk drifting from `poll_interval=0`, the `"9"` history node, and the `b"x"` stub), give `_build` an optional `fake_llm` parameter and reuse everything else.

In `factory/tests/test_build.py`, change the `_build` signature and its LLM line:

```python
def _build(tmp_path, config_dict, content, fake_llm=None):
    """Run the full pipeline with fakes (no LLM / ComfyUI / browser)."""
    cfgp = tmp_path / "book.config.json"
    config_dict = {**config_dict, "prompt_count": 5}
    cfgp.write_text(json.dumps(config_dict), encoding="utf-8")

    if fake_llm is None:
        fake_llm = lambda prompt: json.dumps({**content, "prompts": content["prompts"][:5]})
```

(The rest of `_build` — `http_post`, `http_get`, `comfy = ComfyClient(..., poll_interval=0)`, `runner`, `workflow`, `run_build(...)` — stays exactly as it is.)

Then replace `test_standard_book_build_includes_ebook` with a version that passes a prompt-aware fake:

```python
def test_standard_book_build_includes_ebook(tmp_path, sample_config_dict):
    cfg_dict = {**sample_config_dict, "book_type": "standard",
                "synopsis": "A comforting read on grieving a dog.",
                "chapter_count": 3, "words_per_chapter": 40,
                "blurb": "A comforting companion read."}

    outline = {"preface": "A short preface.",
               "chapters": [{"title": f"Chapter {i}", "synopsis": "s"} for i in range(1, 4)]}

    def fake_llm(prompt):
        if "OUTLINE" in prompt:                       # outline pass
            return json.dumps(outline)
        return json.dumps({"paragraphs": [" ".join(["word"] * 30)] * 2})  # chapter pass

    out_dir = _build(tmp_path, cfg_dict, content=None, fake_llm=fake_llm)
    for f in ["interior.pdf", "cover-paperback.pdf", "upload-checklist.md",
              "interior.epub", "cover-ebook.jpg"]:
        assert (Path(out_dir) / f).exists(), f"missing {f}"
```

> The `"OUTLINE"` marker is the same one asserted in Task 2's `test_outline_prompt_mentions_synopsis_and_count` and emitted by `build_outline_prompt` — keep them in sync.

- [ ] **Step 2: Run the standard end-to-end test**

Run: `cd factory && pytest tests/test_build.py -q`
Expected: PASS — journal build stays paperback-only; standard build produces all five artifacts.

- [ ] **Step 3: Commit**

```bash
git add factory/tests/test_build.py
git commit -m "test(build): end-to-end standard book with two-pass fake LLM"
```

---

## Task 8: First standard title + full suite

**Files:**
- Create: `factory/books/dog-loss-companion.config.json`
- Test: full suite

- [ ] **Step 1: Create the title config**

`factory/books/dog-loss-companion.config.json`:

```json
{
  "slug": "dog-loss-companion",
  "book_type": "standard",
  "title": "Until We Meet at the Bridge",
  "subtitle": "A Gentle Companion for Grieving the Loss of Your Dog",
  "author": "Eleanor Hartley",
  "synopsis": "A warm, comforting read-through book for someone grieving the death of a beloved dog. It walks gently through the shock of loss, the ache of an empty home, guilt and the 'what ifs', honoring memories, and slowly carrying love forward — a tender companion to sit beside the reader, never clinical.",
  "chapter_count": 10,
  "words_per_chapter": 1600,
  "art_prompt": "soft pastel watercolor wide panoramic landscape at dawn, a dog sitting by a tranquil river gazing across a wide valley toward a distant rainbow bridge, soft rolling hills and misty forest stretching far into the distance on both sides, serene and expansive, tender, peaceful, gentle light, no text, no words",
  "price_usd": 9.99,
  "blurb": "When you lose a dog, you lose a daily companion, a witness to your life, a piece of home. This gentle book sits beside you through the hardest days — the silence, the guilt, the aching love with nowhere to go — and walks with you, page by page, toward remembering them with more warmth than pain. A comforting read and a thoughtful gift for anyone saying goodbye to a beloved dog."
}
```

- [ ] **Step 2: Validate the config loads**

Run: `cd factory && python -c "from factory.config import load_config; c=load_config('books/dog-loss-companion.config.json'); print(c.book_type, c.chapter_count, c.makes_ebook)"`
Expected: `standard 10 True`

- [ ] **Step 3: Run the entire suite**

Run: `cd factory && pytest -q`
Expected: PASS — all journal tests plus the new standard tests.

- [ ] **Step 4: Commit**

```bash
git add factory/books/dog-loss-companion.config.json
git commit -m "feat(title): first standard book — dog-loss companion read"
```

- [ ] **Step 5 (optional, manual — needs ComfyUI + browse + claude CLI):** Real end-to-end build

Run: `cd factory && python build.py books/dog-loss-companion.config.json`
Expected: `out/dog-loss-companion/` contains `interior.pdf`, `interior.epub`, `cover-paperback.pdf`, `cover-ebook.jpg`, `upload-checklist.md`. Open the PDF/EPUB and skim the prose for tone and the chapter pagination, then inspect the cover framing per `factory/README.md`.

---

## Task 9: Docs — README reflects standard books

**Files:**
- Modify: `factory/README.md`, `README.md`

- [ ] **Step 1: Update `factory/README.md`**

Add a short subsection after "Add a new title to the series":

```markdown
## Book types: journals vs standard read-through books
Set `"book_type"` in the config:
- `"journal"` (default) — fill-in grief journal; **paperback only** (you can't write in a Kindle book). Requires `pet_kind`.
- `"standard"` — read-through prose book (front matter + chapters); produces **paperback + Kindle**. Requires `synopsis` and `chapter_count` (plus optional `words_per_chapter`, `blurb`). Prose is generated two-pass: an outline, then one LLM call per chapter.
```

- [ ] **Step 2: Update the root `README.md` pipeline description**

In `README.md`, adjust the opening so it no longer implies journals-only — note the factory builds both fill-in journals (paperback) and standard read-through books (paperback + Kindle) from the same five-stage pipeline, switched by `book_type`.

- [ ] **Step 3: Commit**

```bash
git add README.md factory/README.md
git commit -m "docs: document journal vs standard book types"
```

---

## Self-Review notes (already applied)

- **Spec coverage:** config (Task 1), strategy/two-pass + guards (Task 2), interior template + PDF page count (Task 3), EPUB chapters (Task 4), blurb dispatch (Task 5), checklist (Task 6), first title + e2e (Tasks 7-8), docs (Task 9). All spec sections map to a task.
- **Pre-existing tests updated, not duplicated:** the uncommitted `test_standard_book_type_makes_ebook` (Task 1), `test_build_epub` (Task 4), `std_cfg` in `test_checklist` (Task 6), and `test_standard_book_build_includes_ebook` (Task 7) are explicitly rewritten because the new validation/schemas change their assumptions.
- **Type consistency:** content schema `{"preface", "chapters":[{"title","paragraphs"}]}` is used identically across `standard_content.py`, `standard.html.j2`, `build_epub`, and all fakes. `build_interior_pdf(..., book_type=...)` and `pdf_page_count` names are consistent across interior, build, and tests.
- **Known soft spot:** `MIN_CHAPTER_WORDS = 20` is a deliberately low floor (catches empties/refusals, not length shortfalls); tune upward once real generations are observed.
```

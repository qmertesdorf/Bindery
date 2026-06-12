# Substantial Companion Edition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the dog-loss standard book ("Until We Meet at the Bridge") from a thin 53-page 6×9 paperback into a substantial ~150-page 5.5×8.5 gift book ($14.99) with roomier typography, ~18 chapters, and genuine front/back matter — without padding and without disturbing the paperback-only journal path.

**Architecture:** Trim size becomes a per-book config field (`trim_w`/`trim_h`, default 6×9) threaded through `specs`, `interior`, and `cover` so journals stay 6×9 and standard books render at 5.5×8.5. The standard interior gets a roomier type spec (12pt / ~16pt leading / 0.6in margins). The standard content schema grows optional front/back matter (`epigraph`, `readings`, `closing_letter`) generated in one extra LLM "matter" pass; a static, human-vetted memorial page and resources block live in the template (never LLM-generated, to avoid hallucinated hotlines or copyrighted poems). Page count is hit by adding real content (more chapters + matter) and calibrated empirically by rendering and measuring words-per-page — not by guessing.

**Tech Stack:** Python 3, dataclasses, Jinja2, PyMuPDF (`fitz`), ebooklib, pytest. External effects (LLM, browser PDF, ComfyUI) stay behind injected adapters so every test runs with fakes.

---

## Decided specs (from research `wd3un4m2a`, 2026-06-12)

- **Trim:** 5.5 × 8.5 in (gift-leaning, KDP-standard; aspect 0.647 vs 6×9's 0.667 → cover barely shifts).
- **Page target:** ~150 printed pages (substantial tier, beside *Goodbye, Friend* 184pp; clears the 110pp KDP per-page threshold).
- **Typography:** 12pt serif body, ~16pt leading (line-height ~1.33), 0.6in margins — roomier than the journal's 11pt/0.5in.
- **Structure:** ~18 chapters (~1,500 words) across the fuller grief arc, plus front matter (epigraph + preface) and back matter (3–5 short original readings, one static memorial page, a vetted resources block, a closing letter).
- **Content target:** ~34–38k words of prose; final count calibrated against a real render (Task 8).
- **Price:** $14.99 (60% royalty; nets ~$6/sale at ~150pp).

### Content quality & rights guardrails (apply throughout)

- **Readings/closing letter** are LLM-generated *original* prose. Keep readings short (40–80 words) and few (3–5); they are the highest triteness risk — review by eye after the build.
- **Resources list & memorial page** are STATIC template text, never LLM-generated: a hallucinated support-hotline number is a real-world harm, and the "Rainbow Bridge" poem has contested copyright (Edna Clyne-Rekhy) — do **not** include it. The resources block carries a checklist note to human-verify before upload.
- The memorial page is ONE static dedication page ("In loving memory of …"), not fill-in journal ruled lines — this stays a read-through book, not a journal.

---

## File Structure

**Modify:**
- `factory/factory/config.py` — add `trim_w`/`trim_h` fields + validation.
- `factory/factory/specs.py` — `cover_dimensions_in(pages, trim_w, trim_h)` takes trim.
- `factory/factory/interior.py` — `build_interior_pdf` + `_verify_interior_margins` take trim.
- `factory/factory/cover.py` — thread trim through cover render + guards.
- `factory/build.py` — pass `cfg.trim_w`/`cfg.trim_h`.
- `factory/factory/standard_content.py` — generate + validate front/back matter.
- `factory/templates/interior/standard.html.j2` — render matter; 0.6in `@page` margin.
- `factory/templates/interior/interior.css` — standard 12pt/16pt-leading type.
- `factory/templates/interior/_matter.html.j2` (new partial) — static memorial + resources blocks.
- `factory/factory/checklist.py` / `factory/templates/checklist.md.j2` — trim from cfg; resources-verify note.
- `factory/books/dog-loss-companion.config.json` — trim, price, chapters, matter.
- Tests: `test_config.py`, `test_specs.py`, `test_interior.py`, `test_cover.py`, `test_standard_content.py`, `test_checklist.py`, `test_build.py`.

**Create:**
- `factory/templates/interior/_matter.html.j2` — static back-matter partial.

---

## Task 0: Confirm green baseline

- [ ] **Step 1: Run the suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (62 tests, the current committed state).

---

## Task 1: Trim becomes a per-book config field + specs parameterization

**Files:**
- Modify: `factory/factory/config.py`, `factory/factory/specs.py`
- Test: `factory/tests/test_config.py`, `factory/tests/test_specs.py`

- [ ] **Step 1: Write failing config tests**

Add to `factory/tests/test_config.py`:

```python
def test_trim_defaults_to_6x9(tmp_path):
    cfg = load_config(_write(tmp_path, pet_kind="dog"))
    assert cfg.trim_w == 6.0 and cfg.trim_h == 9.0


def test_trim_override_for_standard(tmp_path):
    cfg = load_config(_write(tmp_path, book_type="standard",
                             synopsis="A gentle read.", chapter_count=8,
                             trim_w=5.5, trim_h=8.5))
    assert cfg.trim_w == 5.5 and cfg.trim_h == 8.5


def test_trim_must_be_positive(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, pet_kind="dog", trim_w=0))
```

(`_write` already exists in this file and injects fields into the base config.)

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: FAIL — `BookConfig` has no `trim_w`.

- [ ] **Step 3: Add the fields + validation to `config.py`**

In `factory/factory/config.py`, add to the `BookConfig` dataclass (after `blurb`):

```python
    trim_w: float = 6.0              # paperback trim width (in)
    trim_h: float = 9.0              # paperback trim height (in)
```

In `load_config`, before the `return BookConfig(...)`, add validation:

```python
    trim_w = float(data.get("trim_w", 6.0))
    trim_h = float(data.get("trim_h", 9.0))
    if trim_w <= 0 or trim_h <= 0:
        raise ConfigError(f"{path}: trim_w/trim_h must be positive")
```

And add to the `BookConfig(...)` constructor call:

```python
        trim_w=trim_w,
        trim_h=trim_h,
```

- [ ] **Step 4: Run config tests**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing specs test**

Add to `factory/tests/test_specs.py`:

```python
def test_cover_dimensions_custom_trim():
    # 5.5x8.5 at 150pp: spine = 150*0.0025 = 0.375
    w, h = specs.cover_dimensions_in(150, trim_w=5.5, trim_h=8.5)
    assert w == pytest.approx(0.125 + 5.5 + 0.375 + 5.5 + 0.125)  # 11.625
    assert h == pytest.approx(8.5 + 0.25)                          # 8.75


def test_cover_dimensions_defaults_unchanged():
    # default trim still 6x9 for journals
    w, h = specs.cover_dimensions_in(120)
    assert w == pytest.approx(12.55) and h == pytest.approx(9.25)
```

- [ ] **Step 6: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_specs.py -q`
Expected: FAIL — `cover_dimensions_in()` takes no `trim_w`.

- [ ] **Step 7: Parameterize `cover_dimensions_in` in `specs.py`**

Replace `cover_dimensions_in` in `factory/factory/specs.py`:

```python
def cover_dimensions_in(pages: int, trim_w: float = TRIM_W_IN,
                        trim_h: float = TRIM_H_IN) -> tuple[float, float]:
    spine = spine_width_in(pages)
    width = BLEED_IN + trim_w + spine + trim_w + BLEED_IN
    height = trim_h + 2 * BLEED_IN
    return (round(width, 4), round(height, 4))
```

- [ ] **Step 8: Run specs tests + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_specs.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add factory/factory/config.py factory/factory/specs.py \
  factory/tests/test_config.py factory/tests/test_specs.py
git commit -m "feat(config): per-book trim size; specs cover math takes trim"
```

---

## Task 2: Thread trim through the interior (page size + margin guard)

**Files:**
- Modify: `factory/factory/interior.py`, `factory/build.py`
- Test: `factory/tests/test_interior.py`

- [ ] **Step 1: Write failing interior test**

Add to `factory/tests/test_interior.py` (the `std_cfg` helper gains a trim; update it and add a test):

```python
def std_cfg_5x8():
    return BookConfig(slug="comp", title="Gentle Goodbye", subtitle="Sub",
                      author="A", art_prompt="x", book_type="standard",
                      synopsis="Grieving a dog.", chapter_count=2,
                      words_per_chapter=40, trim_w=5.5, trim_h=8.5)


def test_standard_interior_renders_at_configured_trim(tmp_path):
    # the browse pdf call must request the book's trim, not a hardcoded 6x9
    html_path = render_interior_html(std_cfg_5x8(), std_content(), out_dir=tmp_path)
    calls = []
    def runner(args):
        calls.append(args)
        import fitz
        d = fitz.open(); d.new_page(width=5.5*72, height=8.5*72)
        d.save(str(tmp_path / "interior.pdf")); d.close()
        class R: returncode = 0; stdout = ""; stderr = ""
        return R()
    build_interior_pdf(html_path, tmp_path, runner=runner, book_type="standard",
                       trim_w=5.5, trim_h=8.5)
    pdf_call = next(a for a in calls if a[1] == "pdf")
    assert "5.5in" in pdf_call and "8.5in" in pdf_call
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py::test_standard_interior_renders_at_configured_trim -q`
Expected: FAIL — `build_interior_pdf()` has no `trim_w` param.

- [ ] **Step 3: Add trim params to `build_interior_pdf` and `_verify_interior_margins`**

In `factory/factory/interior.py`, change `_verify_interior_margins` to take trim:

```python
def _verify_interior_margins(pdf: Path, trim_w: float = specs.TRIM_W_IN,
                             trim_h: float = specs.TRIM_H_IN,
                             tol_in: float = 0.06) -> None:
```

and inside it replace the four bound lines:

```python
    x0s = specs.MARGIN_INSIDE_IN
    x1s = trim_w - specs.MARGIN_OUTSIDE_IN
    y0s = specs.MARGIN_TOPBOTTOM_IN
    y1s = trim_h - specs.MARGIN_TOPBOTTOM_IN
```

Change `build_interior_pdf` signature and body:

```python
def build_interior_pdf(html_path: Path, out_dir: Path, runner=None,
                       book_type: str = "journal",
                       trim_w: float = specs.TRIM_W_IN,
                       trim_h: float = specs.TRIM_H_IN) -> tuple[Path, int]:
    out_dir = Path(out_dir)
    pdf = out_dir / "interior.pdf"
    # Page margins come from CSS @page (browse renders without
    # --prefer-css-page-size); see standard.html.j2. The page SIZE comes from
    # these width/height args.
    html_to_pdf(Path(html_path), pdf,
                width_in=trim_w, height_in=trim_h,
                margins_in=0.0, runner=runner)
    _verify_interior_margins(pdf, trim_w, trim_h)
    pages = (pdf_page_count(pdf) if book_type == "standard"
             else count_pages(html_path))
    if book_type == "standard" and pages < 1:
        raise InteriorError(
            f"Standard interior {pdf.name} rendered 0 pages — the PDF failed to "
            f"open or is empty; the cover spine width would be wrong.")
    return pdf, pages
```

- [ ] **Step 4: Wire `build.py` to pass trim**

In `factory/build.py`, change the interior call:

```python
    _, pages = build_interior_pdf(html, out_dir, runner=runner,
                                  book_type=cfg.book_type,
                                  trim_w=cfg.trim_w, trim_h=cfg.trim_h)
```

- [ ] **Step 5: Run interior tests + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py -q`
Expected: PASS (existing journal/standard tests use the 6×9 defaults; new test asserts 5.5×8.5).

- [ ] **Step 6: Commit**

```bash
git add factory/factory/interior.py factory/build.py factory/tests/test_interior.py
git commit -m "feat(interior): render + margin-check at the book's configured trim"
```

---

## Task 3: Thread trim through the cover + its guards

**Files:**
- Modify: `factory/factory/cover.py`
- Test: `factory/tests/test_cover.py`

- [ ] **Step 1: Write failing cover test**

Add to `factory/tests/test_cover.py`:

```python
def std_cfg_5x8():
    return BookConfig(slug="comp", title="Gentle Goodbye", subtitle="Sub",
                      author="A", art_prompt="x", book_type="standard",
                      synopsis="s", chapter_count=8, trim_w=5.5, trim_h=8.5,
                      blurb="A gentle companion read.")


def test_cover_html_uses_configured_trim(tmp_path):
    art = tmp_path / "art.png"; art.write_bytes(b"\x89PNG")
    # 150pp at 5.5x8.5 -> width 11.625, height 8.75
    html = render_cover_html(std_cfg_5x8(), pages=150, art_path=art, out_dir=tmp_path)
    text = Path(html).read_text(encoding="utf-8")
    assert "11.625in" in text
    assert "8.75in" in text


def test_verify_cover_dimensions_custom_trim(tmp_path):
    pages = 150
    exp_w, exp_h = specs.cover_dimensions_in(pages, 5.5, 8.5)
    good = tmp_path / "good.pdf"
    _pdf_of_size(good, exp_w, exp_h)
    _verify_cover_dimensions(good, pages, trim_w=5.5, trim_h=8.5)  # passes
    # a 6x9-sized cover is WRONG for a 5.5x8.5 book -> failure
    wrong = tmp_path / "wrong.pdf"
    w6, h6 = specs.cover_dimensions_in(pages)  # 6x9
    _pdf_of_size(wrong, w6, h6)
    with pytest.raises(CoverError):
        _verify_cover_dimensions(wrong, pages, trim_w=5.5, trim_h=8.5)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_cover.py -q`
Expected: FAIL — `render_cover_html` emits 6×9 dims; `_verify_cover_dimensions` takes no trim.

- [ ] **Step 3: Thread trim through `cover.py`**

In `factory/factory/cover.py`, make the trim flow from `cfg` through the helpers. Change these functions:

`_compose_wrap_bg` — add `trim_w` param and use it for the scrim centres:

```python
def _compose_wrap_bg(art_path: Path, out_dir: Path, width_in: float, height_in: float,
                     trim_w: float = specs.TRIM_W_IN, dpi: int = 300,
                     subject_x: float = 0.5, front_x: float = 0.64) -> None:
```

and inside it replace the two `specs.TRIM_W_IN` uses:

```python
    front_cx = W - round((specs.BLEED_IN + trim_w / 2) * dpi)
    back_cx = round((specs.BLEED_IN + trim_w / 2) * dpi)
```

`_css` — add `trim_w` and pass it to the template:

```python
def _css(width_in: float, height_in: float, art_file: str, fill: bool = False,
         trim_w: float = specs.TRIM_W_IN) -> str:
    return Template(_CSS_TEMPLATE).render(
        width_in=width_in, height_in=height_in, art_file=art_file,
        bleed=specs.BLEED_IN, trim_w=trim_w, fill=fill)
```

`render_cover_html` — use `cfg.trim_w`/`cfg.trim_h`:

```python
def render_cover_html(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                      front_only: bool = False) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art_local = out_dir / Path(art_path).name
    if Path(art_path).resolve() != art_local.resolve():
        shutil.copy(art_path, art_local)
    if front_only:
        width_in = cfg.trim_w + 2 * specs.BLEED_IN
        height_in = cfg.trim_h + 2 * specs.BLEED_IN
        name = "cover_front.html"
    else:
        width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h)
        name = "cover_wrap.html"
        _compose_wrap_bg(art_local, out_dir, width_in, height_in, trim_w=cfg.trim_w)
    css = _css(width_in, height_in, art_local.name, fill=front_only, trim_w=cfg.trim_w)
    html = render("cover/cover.html.j2", cfg=cfg, css=css,
                  width_in=width_in, height_in=height_in,
                  front_only=front_only, blurb=book_blurb(cfg))
    html_path = out_dir / name
    html_path.write_text(html, encoding="utf-8")
    return html_path
```

`_verify_cover_dimensions` — add trim:

```python
def _verify_cover_dimensions(pdf: Path, pages: int, trim_w: float = specs.TRIM_W_IN,
                             trim_h: float = specs.TRIM_H_IN,
                             tol_in: float = 0.05) -> None:
```

and inside replace the expected-size line:

```python
    exp_w, exp_h = specs.cover_dimensions_in(pages, trim_w, trim_h)
```

`_verify_cover_text_zones` — add `trim_w` and use it for `tw`:

```python
def _verify_cover_text_zones(pdf: Path, pages: int, trim_w: float = specs.TRIM_W_IN,
                             inset_in: float = 0.2) -> None:
```

and inside replace the `tw` binding:

```python
    bleed, tw = specs.BLEED_IN, trim_w
```

`build_cover` — read `cfg.trim_w`/`cfg.trim_h` and pass to the verifies:

```python
def build_cover(cfg: BookConfig, pages: int, art_path: Path, out_dir: Path,
                runner=None, make_ebook_cover: bool = True) -> tuple[Path, Path | None]:
    out_dir = Path(out_dir)
    wrap_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=False)
    width_in, height_in = specs.cover_dimensions_in(pages, cfg.trim_w, cfg.trim_h)
    pdf = out_dir / "cover-paperback.pdf"
    html_to_pdf(wrap_html, pdf, width_in=width_in, height_in=height_in,
                margins_in=0.0, runner=runner)
    _verify_cover_pdf(pdf, [cfg.title, cfg.subtitle, cfg.author, book_blurb(cfg)])
    _verify_cover_dimensions(pdf, pages, cfg.trim_w, cfg.trim_h)
    _verify_cover_background(pdf)
    _verify_cover_text_zones(pdf, pages, cfg.trim_w)
    if not make_ebook_cover:
        return pdf, None
    front_html = render_cover_html(cfg, pages, art_path, out_dir, front_only=True)
    jpg = out_dir / "cover-ebook.jpg"
    html_to_screenshot(front_html, jpg, width_px=1600, height_px=2560, runner=runner)
    _recompress_jpg(jpg)
    return pdf, jpg
```

- [ ] **Step 4: Run cover tests + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_cover.py -q`
Expected: PASS (journal 6×9 tests unchanged via defaults; new 5.5×8.5 tests pass).

Run: `cd factory && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/cover.py factory/tests/test_cover.py
git commit -m "feat(cover): compose + guard the wrap at the book's configured trim"
```

---

## Task 4: Standard typography — 12pt, roomier leading + margins

**Files:**
- Modify: `factory/templates/interior/interior.css`, `factory/templates/interior/standard.html.j2`
- Test: `factory/tests/test_interior.py`

- [ ] **Step 1: Write failing test**

Add to `factory/tests/test_interior.py`:

```python
def test_standard_typography_is_roomy(tmp_path):
    html_path = render_interior_html(std_cfg(), std_content(), out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "@page { margin: 0.6in; }" in text   # roomier than journal 0.5in
    css = (Path(html_path).parent / "interior.css").read_text(encoding="utf-8")
    assert "font-size: 12pt" in css             # 12pt body for standard
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py::test_standard_typography_is_roomy -q`
Expected: FAIL — current `@page` is 0.5in and `.body-para` is 11pt.

- [ ] **Step 3: Bump the standard `@page` margin in `standard.html.j2`**

In `factory/templates/interior/standard.html.j2`, change the inline style:

```jinja
<style>@page { margin: 0.6in; }</style></head><body>
```

- [ ] **Step 4: Roomier prose CSS for standard in `interior.css`**

In `factory/templates/interior/interior.css`, replace the `.body-para` and `.chapter-head` rules:

```css
.chapter-head { font-size: 20pt; margin: 0 0 0.45in 0; text-align: center; }
.body-para { font-size: 12pt; line-height: 1.34; margin: 0 0 0.16in 0;
             text-indent: 0.28in; text-align: justify; }
```

(12pt × 1.34 ≈ 16pt leading; the larger head + looser leading + 0.6in margins all lower words/page, helping reach the page target without padding.)

- [ ] **Step 5: Run interior tests + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add factory/templates/interior/standard.html.j2 factory/templates/interior/interior.css \
  factory/tests/test_interior.py
git commit -m "feat(interior): roomier 12pt/0.6in type spec for standard comfort books"
```

---

## Task 5: Front/back-matter content schema + generator

**Files:**
- Modify: `factory/factory/standard_content.py`
- Test: `factory/tests/test_standard_content.py`

The standard content dict grows three optional keys: `epigraph` (short original lines for the front), `readings` (3–5 short comforting passages for the back), and `closing_letter` (a warm final letter). They are produced in ONE extra "matter" LLM call so the build cost stays bounded.

- [ ] **Step 1: Write failing tests**

Add to `factory/tests/test_standard_content.py`:

```python
from factory.standard_content import build_matter_prompt, validate_matter


def test_matter_prompt_mentions_title_and_marker():
    p = build_matter_prompt(cfg())
    assert "Gentle Goodbye" in p
    assert "MATTER" in p          # marker the fake/dispatch key on


def test_validate_matter_requires_keys():
    with pytest.raises(ContentError):
        validate_matter({"epigraph": "x"})          # missing readings/closing_letter
    validate_matter({"epigraph": "x", "readings": ["a", "b", "c"],
                     "closing_letter": "Dear friend, ..."})   # ok


def test_generate_includes_matter():
    def fn(prompt):
        if "OUTLINE" in prompt:
            return json.dumps({"preface": "p",
                               "chapters": [{"title": "C1", "synopsis": "s"}]})
        if "MATTER" in prompt:
            return json.dumps({"epigraph": "A few gentle lines.",
                               "readings": ["r one", "r two", "r three"],
                               "closing_letter": "Dear friend, be gentle."})
        return json.dumps({"paragraphs": [_para(), _para()]})
    out = generate_standard_content(cfg(chapter_count=1), generate_fn=fn)
    assert out["epigraph"].startswith("A few gentle")
    assert len(out["readings"]) == 3
    assert out["closing_letter"].startswith("Dear friend")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_standard_content.py -q`
Expected: FAIL — `build_matter_prompt`/`validate_matter` don't exist and the matter keys aren't produced.

- [ ] **Step 3: Implement matter prompt + validator + wiring**

In `factory/factory/standard_content.py`, add:

```python
def build_matter_prompt(cfg: BookConfig) -> str:
    return f"""You are writing the gentle front/back matter for the comfort book
"{cfg.title}" ({cfg.subtitle}).
Premise: {cfg.synopsis}

Write, as warm original prose (no quotes from other authors, no poems you did not
write, never the "Rainbow Bridge" poem):
- epigraph: 1-3 short tender lines for the opening page.
- readings: 4 short comforting passages (40-80 words each) to dip into on hard days.
- closing_letter: a warm 120-180 word farewell letter to the grieving reader.

Return ONLY valid JSON for this MATTER:
{{"epigraph": "...", "readings": ["...", "..."], "closing_letter": "..."}}
Output the JSON and nothing else."""


def validate_matter(data: dict) -> None:
    if not isinstance(data, dict):
        raise ContentError("matter is not a JSON object")
    if not str(data.get("epigraph", "")).strip():
        raise ContentError("matter missing 'epigraph'")
    readings = data.get("readings")
    if not isinstance(readings, list) or len(readings) < 3:
        raise ContentError("matter needs at least 3 readings")
    if not all(isinstance(r, str) and r.strip() for r in readings):
        raise ContentError("matter readings must be non-empty strings")
    if not str(data.get("closing_letter", "")).strip():
        raise ContentError("matter missing 'closing_letter'")
```

In `generate_standard_content`, after the chapter loop and before the `return`, add the matter pass and merge it:

```python
    raw_m = generate_fn(build_matter_prompt(cfg))
    try:
        matter = json.loads(_strip_fences(raw_m))
    except json.JSONDecodeError as e:
        raise ContentError(f"matter is not valid JSON: {e}") from e
    validate_matter(matter)

    return {"preface": outline["preface"], "chapters": chapters,
            "epigraph": matter["epigraph"], "readings": matter["readings"],
            "closing_letter": matter["closing_letter"]}
```

(Remove the old `return {"preface": ..., "chapters": chapters}` line it replaces.)

- [ ] **Step 4: Run standard-content tests + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_standard_content.py -q`
Expected: PASS.

> Note: `test_build.py`'s standard fake LLM must also answer the MATTER call — handled in Task 8 Step 3. Until then `test_build.py`'s standard test may fail; that is expected and fixed there.

- [ ] **Step 5: Commit**

```bash
git add factory/factory/standard_content.py factory/tests/test_standard_content.py
git commit -m "feat(content): generate original epigraph, readings, closing letter"
```

---

## Task 6: Render front/back matter in interior + EPUB; static memorial + resources

**Files:**
- Create: `factory/templates/interior/_matter.html.j2`
- Modify: `factory/templates/interior/standard.html.j2`, `factory/factory/interior.py`
- Test: `factory/tests/test_interior.py`

- [ ] **Step 1: Create the static back-matter partial**

`factory/templates/interior/_matter.html.j2` (static, human-vetted — NOT LLM):

```jinja
<section class="chapter memorial"><h2 class="chapter-head">In Loving Memory</h2>
<p class="body-para" style="text-align:center;text-indent:0">This book is kept in
loving memory of a cherished companion, and of the years of devotion they gave.</p>
</section>

<section class="chapter resources"><h2 class="chapter-head">Where to Turn for Support</h2>
<p class="body-para">Grieving a pet is real grief, and you do not have to carry it
alone. These services offer compassionate, pet-specific support:</p>
<p class="body-para">• ASPCA Pet Loss Support — aspca.org/pet-care/pet-loss<br>
• Lap of Love Pet Loss Support Groups — lapoflove.com/pet-loss-support<br>
• The Association for Pet Loss and Bereavement — aplb.org<br>
• Your veterinarian can often point you to a local pet-loss support group.</p>
<p class="body-para" style="font-style:italic">If you are struggling badly, please
reach out to a doctor or a mental-health professional — grief for a pet can be as
heavy as any other loss.</p>
</section>
```

> The resources are real organizations as of 2026-06-12; the checklist (Task 7) reminds the publisher to re-verify each URL before upload.

- [ ] **Step 2: Write failing interior test**

Add to `factory/tests/test_interior.py` — extend `std_content()` with matter and assert it renders:

```python
def std_content_full():
    return {"preface": "A short preface.", "epigraph": "Gentle opening lines.",
            "chapters": [{"title": "First", "paragraphs": ["Para one.", "Para two."]}],
            "readings": ["Reading one.", "Reading two.", "Reading three."],
            "closing_letter": "Dear friend, be gentle with yourself."}


def test_standard_interior_renders_front_and_back_matter(tmp_path):
    html_path = render_interior_html(std_cfg(), std_content_full(), out_dir=tmp_path)
    text = Path(html_path).read_text(encoding="utf-8")
    assert "Gentle opening lines." in text            # epigraph (front)
    assert "Reading one." in text                      # readings (back)
    assert "Dear friend" in text                       # closing letter (back)
    assert "In Loving Memory" in text                  # static memorial page
    assert "ASPCA Pet Loss Support" in text            # static resources
```

- [ ] **Step 3: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py::test_standard_interior_renders_front_and_back_matter -q`
Expected: FAIL — the standard template renders none of these yet.

- [ ] **Step 4: Render matter in `standard.html.j2`**

In `factory/templates/interior/standard.html.j2`, add an epigraph section after the title page and the back matter after the chapter loop:

```jinja
{% if content.epigraph %}<section class="epigraph"><div class="intro-body">
{% for line in content.epigraph.split('\n') if line.strip() %}<p>{{ line.strip() }}</p>{% endfor %}
</div></section>{% endif %}
```

(place it immediately after the `</section>` that closes `title-page`, before the `preface` section)

and after the `{% endfor %}` that closes the chapter loop, add:

```jinja
{% if content.readings %}
<section class="chapter readings-section"><h2 class="chapter-head">Words for the Hard Days</h2>
{% for r in content.readings %}<p class="body-para" style="text-indent:0;margin-bottom:0.28in">{{ r }}</p>{% endfor %}
</section>{% endif %}

{% include "interior/_matter.html.j2" %}

{% if content.closing_letter %}
<section class="chapter closing-letter"><h2 class="chapter-head">A Closing Letter</h2>
{% for para in content.closing_letter.split('\n') if para.strip() %}<p class="body-para">{{ para.strip() }}</p>{% endfor %}
</section>{% endif %}
```

- [ ] **Step 5: Render matter in the EPUB (`build_epub`)**

In `factory/factory/interior.py`, inside `build_epub`, after the preface block and before the chapter loop, add the epigraph; after the chapter loop add readings, then closing letter:

```python
    if content.get("epigraph"):
        epi = "".join(f"<p>{p}</p>" for p in content["epigraph"].split("\n") if p.strip())
        items.append(chapter("Epigraph", epi, "epigraph.xhtml"))
```

(insert the epigraph item BEFORE the preface item so order reads epigraph → preface → chapters; i.e. build the epigraph item first, then preface, then chapters)

After the `for i, ch ...` chapter loop:

```python
    if content.get("readings"):
        rd = "".join(f"<p>{r}</p>" for r in content["readings"])
        items.append(chapter("Words for the Hard Days", rd, "readings.xhtml"))
    if content.get("closing_letter"):
        cl = "".join(f"<p>{p}</p>" for p in content["closing_letter"].split("\n") if p.strip())
        items.append(chapter("A Closing Letter", cl, "closing.xhtml"))
```

- [ ] **Step 6: Write failing EPUB test + run**

Add to `factory/tests/test_interior.py`:

```python
def test_epub_includes_matter(tmp_path):
    out = build_epub(std_cfg(), std_content_full(), tmp_path)
    import zipfile
    names = zipfile.ZipFile(out).namelist()
    assert any(n.endswith("epigraph.xhtml") for n in names)
    assert any(n.endswith("readings.xhtml") for n in names)
    assert any(n.endswith("closing.xhtml") for n in names)
```

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_interior.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add factory/templates/interior/_matter.html.j2 factory/templates/interior/standard.html.j2 \
  factory/factory/interior.py factory/tests/test_interior.py
git commit -m "feat(interior): render epigraph, readings, memorial, resources, closing letter"
```

---

## Task 7: Checklist — trim from config + resources-verify note

**Files:**
- Modify: `factory/templates/checklist.md.j2`
- Test: `factory/tests/test_checklist.py`

- [ ] **Step 1: Write failing test**

In `factory/tests/test_checklist.py`, update `std_cfg` to a 5.5×8.5 / $14.99 standard config and assert trim + verify note:

```python
def std_cfg():
    return BookConfig(slug="memoir", title="A Book", subtitle="Sub",
                      author="A", art_prompt="x", price_usd=14.99,
                      book_type="standard", synopsis="A gentle read about loss.",
                      chapter_count=18, blurb="A comforting companion read.",
                      trim_w=5.5, trim_h=8.5)


def test_checklist_shows_configured_trim_and_resources_note(tmp_path):
    text = Path(make_checklist(std_cfg(), pages=150, out_dir=tmp_path)).read_text(encoding="utf-8")
    assert "5.5 x 8.5" in text
    assert "verify" in text.lower() and "resource" in text.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_checklist.py -q`
Expected: FAIL — template hardcodes `6 x 9 in` and has no resources-verify note.

- [ ] **Step 3: Update `checklist.md.j2`**

In `factory/templates/checklist.md.j2`, replace the hardcoded trim line(s). Change the `Trim size:` line to:

```jinja
- **Trim size:** {{ "%g"|format(cfg.trim_w) }} x {{ "%g"|format(cfg.trim_h) }} in
```

and replace the interior/cover file lines that say `6x9"` with `{{ "%g"|format(cfg.trim_w) }}x{{ "%g"|format(cfg.trim_h) }}"`.

Add, in the standard branch of the checklist (near the AI disclosure block), a verify note:

```jinja
{%- if cfg.book_type == "standard" %}
> ⚠ Before upload: re-verify every link in the book's "Where to Turn for Support"
> resources page is still live and correct. Do not ship a dead or wrong support link.
{%- endif %}
```

- [ ] **Step 4: Run checklist tests**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_checklist.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add factory/templates/checklist.md.j2 factory/tests/test_checklist.py
git commit -m "feat(checklist): trim from config + resources-link verify reminder"
```

---

## Task 8: Title config + end-to-end fake build + empirical calibration + real build

**Files:**
- Modify: `factory/books/dog-loss-companion.config.json`, `factory/tests/test_build.py`
- Test: `factory/tests/test_build.py`

- [ ] **Step 1: Update the title config**

In `factory/books/dog-loss-companion.config.json`, set the substantial-edition fields (chapter count is a first estimate; calibrated in Step 5):

```json
  "chapter_count": 18,
  "words_per_chapter": 1500,
  "price_usd": 14.99,
  "trim_w": 5.5,
  "trim_h": 8.5,
```

(leave `title`, `subtitle`, `author`, `synopsis`, `art_prompt`, `blurb`, `slug`, `book_type` as-is.)

- [ ] **Step 2: Validate the config loads**

Run: `cd factory && .venv/Scripts/python.exe -c "from factory.config import load_config; c=load_config('books/dog-loss-companion.config.json'); print(c.trim_w, c.trim_h, c.price_usd, c.chapter_count)"`
Expected: `5.5 8.5 14.99 18`

- [ ] **Step 3: Update the standard fake LLM in `test_build.py` to answer the MATTER call**

In `factory/tests/test_build.py`, in `test_standard_book_build_includes_ebook`'s `fake_llm`, add a MATTER branch (and keep OUTLINE + chapter branches):

```python
    def fake_llm(prompt):
        if "OUTLINE" in prompt:
            return json.dumps(outline)
        if "MATTER" in prompt:
            return json.dumps({"epigraph": "Gentle lines.",
                               "readings": ["r1", "r2", "r3"],
                               "closing_letter": "Dear friend, be gentle."})
        return json.dumps({"paragraphs": [" ".join(["word"] * 30)] * 2})
```

- [ ] **Step 4: Run the end-to-end fake build + full suite**

Run: `cd factory && .venv/Scripts/python.exe -m pytest tests/test_build.py -q`
Expected: PASS — standard build produces all five artifacts with matter and at 5.5×8.5.

Run: `cd factory && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (whole suite).

- [ ] **Step 5: Commit the config + test**

```bash
git add factory/books/dog-loss-companion.config.json factory/tests/test_build.py
git commit -m "feat(title): substantial 5.5x8.5 $14.99 edition + matter in e2e build"
```

- [ ] **Step 6 (manual — needs ComfyUI + browse + claude CLI): real build + calibrate to ~150pp**

Run: `cd factory && .venv/Scripts/python.exe build.py books/dog-loss-companion.config.json`

Then measure words-per-page and total pages:

```bash
cd factory && .venv/Scripts/python.exe -c "import json,fitz; d=json.load(open('out/dog-loss-companion/content.json',encoding='utf-8')); w=sum(len(p.split()) for c in d['chapters'] for p in c['paragraphs']); pg=fitz.open('out/dog-loss-companion/interior.pdf').page_count; print('chapters',len(d['chapters']),'words',w,'pages',pg,'wpp',round(w/pg))"
```

If `pages` is materially below ~150, raise `chapter_count` (and/or `words_per_chapter`) using the measured words-per-page: `needed_words ≈ (150 − front/back-matter pages) × wpp`, then re-run. Re-run until pages ∈ ~[145, 160]. Commit the final calibrated `chapter_count`/`words_per_chapter`:

```bash
git add factory/books/dog-loss-companion.config.json
git commit -m "chore(title): calibrate chapter count to ~150 printed pages"
```

- [ ] **Step 7 (manual): eyeball the result**

Open `out/dog-loss-companion/interior.pdf` and skim: chapter pagination, 12pt readability, the epigraph/readings/memorial/resources/closing-letter pages, and that the readings don't read as repetitive/trite (the one real quality risk). Inspect the cover framing per `factory/README.md`. Confirm the checklist shows 5.5×8.5 and $14.99.

---

## Task 9: Docs

**Files:**
- Modify: `factory/README.md`

- [ ] **Step 1: Document trim + matter for standard books**

In `factory/README.md`, under the book-types section, note that standard books support a per-book `trim_w`/`trim_h` (default 6×9; the dog-loss companion uses 5.5×8.5), a roomier 12pt type spec, and auto-generated front/back matter (epigraph, readings, closing letter) plus a static, human-verified memorial + resources page.

- [ ] **Step 2: Commit**

```bash
git add factory/README.md
git commit -m "docs: standard-book trim sizing + front/back matter"
```

---

## Self-Review notes (applied)

- **Spec coverage:** trim (Tasks 1–3), typography (Task 4), front/back matter generate (5) + render/epub (6), checklist trim/notes (7), title config + e2e + calibration (8), docs (9). Each decided spec maps to a task.
- **Journals untouched:** every trim param defaults to 6×9, so all journal tests pass unchanged; only the standard path opts into 5.5×8.5.
- **Type consistency:** `build_interior_pdf(..., trim_w, trim_h)`, `cover_dimensions_in(pages, trim_w, trim_h)`, `_verify_cover_dimensions(pdf, pages, trim_w, trim_h)`, `_verify_cover_text_zones(pdf, pages, trim_w)`, and the content keys `epigraph`/`readings`/`closing_letter` are used identically across generator, templates, `build_epub`, and all fakes.
- **Rights/accuracy guardrails:** resources + memorial are static template text (no hallucinated hotlines, no Rainbow Bridge poem); the checklist forces a pre-upload link re-verify.
- **Known soft spot:** LLM readings/closing letter can run trite — flagged for human review in Task 8 Step 7; page calibration (Task 8 Step 6) is empirical because words-per-page depends on the final 12pt/0.6in render.
```

# Standard read-through books — pipeline design

**Date:** 2026-06-12
**Status:** Approved (brainstorm) — pending implementation plan

## Goal

Extend the existing journal factory so it can also produce **standard
read-through prose books** (front matter + chapters), end to end, and ship a
first such title. The journal path must keep working unchanged.

Out of this round: research a genre that fits the pipeline, generalize the
content + interior stages, and build one standard title as the proof.

## Genre decision

Reasoned from the existing `research-findings.md` + `candidates.md` plus
pipeline-fit (one AI cover image, claude-generated text, flowing interior,
EPUB + paperback — no interior illustrations, output length bounded by the LLM).

Fit ranking:

| Genre family | Fit | Notes |
|---|---|---|
| Caregiver / life-transition emotional-support guides | **High** | Single cover, moderate prose, no load-bearing facts; same emotionally-motivated gift buyer as the pet-loss line |
| Hyper-local how-to | Medium | Higher AI-hallucination liability (factual accuracy) |
| Niche prose workbooks | Medium | Overlaps the existing journal product |
| Children's picture books | Low | Needs many illustrations — fights the single-art pipeline |
| Fiction | Low for a first title | Discoverability/stigma/saturation; 30k+ words can't come from one reliable pass |

**First standard title:** an emotional-support read-through *companion* to the
existing pet-loss journal (a gentle book on grieving and remembering a dog/cat).
It reuses the proven positioning (Eleanor Hartley pen name, rainbow-bridge art
style), cross-sells with the journals, dodges fiction's discoverability problem,
and its reflective content is not fact-load-bearing so hallucination is not a
liability. The genre generalizes to the rest of the caregiver family afterward.

## Architecture

Approach **B — strategy per `book_type`**: isolate journal vs standard content
logic behind a small interface, dispatched on `book_type`. Mirrors the existing
injected-adapter philosophy, keeps each shape independently unit-testable, and
makes a future third type a new strategy file rather than edits to old ones.

### 1. Config (`factory/factory/config.py`)

- Base required fields: `slug, title, subtitle, author, art_prompt`.
- `pet_kind` becomes required **only when `book_type == "journal"`**.
- New standard-only fields:
  - `synopsis` (str) — what the book is about; feeds the outline prompt.
  - `chapter_count` (int, e.g. 10).
  - `words_per_chapter` (int, e.g. 1600).
  - `blurb` (str, optional) — back-cover/listing text; falls back to `synopsis`.
- Validation dispatches on `book_type`: journal requires `pet_kind`; standard
  requires `synopsis` + `chapter_count`. Unknown `book_type` still rejected.
- **Pricing:** single `price_usd = 9.99` for v1 — the one value simultaneously
  valid for the 70% ebook band (≤ 9.99) and the 60% paperback rate (≥ 9.99).
  Per-edition pricing is a future knob, not built now.

### 2. Content strategy (`factory/factory/content.py`, + strategy module)

A per-type strategy exposing prompt-building + validation, dispatched by
`book_type`. The injected `generate_fn` is called once (journal) or N+1 times
(standard); test fakes branch on prompt text.

- **Journal strategy:** today's single-call prompt + existing keys. Unchanged
  behavior.
- **Standard strategy — two-pass:**
  - *Pass 1 — outline:* one call → JSON `{chapters: [{title, synopsis}]}`,
    length == `chapter_count`.
  - *Pass 2 — prose:* one call per chapter, given the outline + prior chapter
    titles for continuity → JSON `{paragraphs: [...]}`.
  - Accumulated content schema:
    ```json
    { "preface": "…",
      "chapters": [ {"title": "...", "paragraphs": ["…"]} ] }
    ```

### 3. Interior (`factory/factory/interior.py` + templates)

- `render_interior_html` selects template by `book_type`:
  - `templates/interior/journal.html.j2` (renamed from current `book.html.j2`).
  - `templates/interior/standard.html.j2` (new).
- `standard.html.j2`: title page → preface → one `<section class="chapter">`
  per chapter (`<h2>` + flowing `<p>` paragraphs). CSS: `page-break-before:
  always` per chapter, natural pagination, **no ruled fill-in lines**.
- **Page count:** add `pdf_page_count(pdf)` (fitz `doc.page_count`). Standard
  returns the real rendered count (flowing prose ≠ one-section-per-page);
  journal keeps its existing `count_pages()` section count untouched. The cover
  spine width consumes whichever count is returned.
- The existing `_verify_interior_margins` guard runs on standard automatically.

### 4. EPUB (`build_epub`)

Rewrite to render the standard schema (only ever called for `standard` /
`makes_ebook`): preface + one chapter per `chapters[]`, real TOC + spine.

### 5. Cover & copy

- `cover.py` is already generic (takes `make_ebook_cover`) — no structural
  change.
- `copy.book_blurb` dispatches on `book_type`: journal → today's sentence;
  standard → `cfg.blurb` (or derived from `synopsis`).

### 6. Checklist (`factory/factory/checklist.py` + template)

Generalize the journal-hardwired wording; keep the mandatory AI-content
disclosure and the conditional ebook section already started in the working
diff.

### 7. First title

`factory/books/dog-loss-companion.config.json` — `book_type: "standard"`,
Eleanor Hartley, rainbow-bridge art reused, ~10 chapters; a comforting
read-through companion to the existing `dog-loss` journal. Built end to end as
the proof.

## Testing + build-time guards

Consistent with the standing preference to fix **and guard** generated-output
defects at build time (joins the existing margin guard + cover-text guard).

- Unit tests: config (standard validation, optional `pet_kind`, per-type
  required fields), two-pass standard strategy (fakes + validation-failure
  cases), standard interior (chapters present, zero fill-in lines),
  `pdf_page_count`, EPUB chapters, blurb dispatch.
- New build-time guards:
  - Outline must have exactly `chapter_count` chapters.
  - Every chapter must contain non-empty prose above a minimum word floor
    (catches a truncated or refused generation).

## Out of scope (YAGNI)

- No fiction-specific schema yet (the generic chapter schema absorbs it later).
- No multi-image interiors.
- No live web research (genre chosen by reasoning from existing docs).
- No per-edition pricing.

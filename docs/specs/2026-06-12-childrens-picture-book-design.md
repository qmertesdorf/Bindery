# Children's picture books — pipeline design

**Date:** 2026-06-12
**Status:** Approved (brainstorm) — pending implementation plan

## Goal

Add a third `book_type: "picture"` to the factory so it can produce an
**illustrated children's picture book** end to end, and ship a first such title:
a gentle pet-loss book for a grieving child, extending the dog sub-line (joining
the *Paw Prints on My Heart* journal and the *Until We Meet at the Bridge*
companion — three formats for the same dog-owner, shared keywords and cover
style). The journal and standard paths must keep working unchanged.

The defining difference from every prior title: a picture book needs **many
illustrations (one per page), kept visually consistent**, not one cover image.
That consistency problem is the heart of this design.

## Creative decisions (from brainstorm)

- **Narrative shape:** *child narrator, pet in memory* — the story centers the
  child's feelings; the dog appears in soft, "remembered" vignettes. The child
  recurs; the dog recurs but soft-focus, easing exact-match pressure.
- **Pet / positioning:** a **dog**, extending the strongest existing sub-line.
- **Audience:** read-aloud / early reader, ages ~4–8. 1–2 short sentences/page.
- **Author:** Eleanor Hartley (line pen name).
- **Editions:** **paperback only** (a fixed-layout picture EPUB isn't worth it;
  consistent with journals). `makes_ebook = False`.

## The crux: art consistency

**Approach A — prompt-anchored + fixed seed**, hardened by a **vision auditor
that rejects and regenerates** any off-model illustration. Chosen over IPAdapter
(B) and a character LoRA (C) because it needs **zero new ComfyUI infrastructure**
(the workflow stays the single JuggernautXL/SDXL text→image graph; stage ③ just
becomes a loop over the existing `ComfyClient`), respects the GPU shared with the
user's video gen, and matches the soft-focus narrative pick. B is a documented
future upgrade if the auditor's reject rate proves too high.

The two mechanisms that make A work:

1. **A frozen character + style anchor.** Generated *once* into `content.json`
   and never re-invented: a deliberately *simple, iconic* visual description of
   the child (age, hair, skin, one simple outfit) and the dog (name, breed,
   colour, markings), plus one locked art-style string ("soft flat storybook
   watercolor, muted palette, soft edges"). This exact anchor is prepended to
   **every** page's art prompt and is the auditor's yardstick. Simple, flat
   character design is far easier for SDXL to repeat than a detailed one.

2. **A character reference sheet + vision audit-and-regenerate loop.** Before the
   story pages, one **reference-sheet image** of the child + dog is generated
   from the anchor and approved (audited against the anchor; regenerated until it
   passes). Every story-page illustration is then audited **against that
   reference sheet** for character consistency. The reference sheet also seeds
   the cover illustration.

## Architecture

New strategy per `book_type`, mirroring the journal/standard split: a
`picture` content strategy + a picture interior template + an audited art loop +
one new injected adapter (`VisionAuditor`). Each unit independently unit-testable
with fakes; no GPU/network in tests.

### 1. Config (`factory/factory/config.py`)

- `book_type` gains `"picture"`.
- New picture-only fields:
  - `pet_kind` — required (reused; "dog" here).
  - `pet_name` (str) — the remembered dog's name, woven into story + anchor.
  - `page_count` (int) — target story pages (default ~18–22 so that, with the
    fixed front/back matter below, the interior naturally clears the KDP 24-page
    floor without padding blanks; see page-count guard).
  - `art_style` (str, optional) — the locked style string; sensible default if
    omitted.
- Validation dispatches on `book_type`: picture requires `pet_kind` + `pet_name`.
  Journal/standard validation unchanged. Unknown `book_type` still rejected.
- **Trim:** `trim_w = trim_h = 8.5` (square) set in the title config; the
  existing per-book trim plumbing carries it through.
- **Pricing:** `price_usd = 10.99` (colour interior prints cost more than B&W).
- `makes_ebook` stays `False` for picture (only `standard` is True).

### 2. Content strategy (`factory/factory/picture_content.py`, new)

Dispatched by `book_type`, exposing prompt-building + validation like the
standard strategy. Two phases via the injected `generate_fn`:

- **Phase 1 — story bible (one call):** JSON
  `{character_anchor, art_style, dedication}` — the frozen anchor (child + dog
  visual description) and dedication. If `art_style` is set in config it wins.
- **Phase 2 — story pages (one call):** JSON
  `{pages: [{text, scene}]}`, exactly `page_count` entries, each `text` 1–2
  child-friendly sentences (ages 4–8) and `scene` a concrete visual description
  of what that page depicts (the auditor and art prompt consume `scene`).
- Accumulated `content.json` schema:
  ```json
  { "character_anchor": "…", "art_style": "…", "dedication": "…",
    "pages": [ {"text": "…", "scene": "…"} ],
    "closing": "…" }
  ```
- Validation guards: exactly `page_count` pages; every `text` and `scene`
  non-empty; anchor + art_style non-empty. A hard-failed call gets one retry
  (same pattern as the standard strategy), else the build fails.

### 3. Art stage — reference sheet + audited regenerate loop

New injected adapter **`VisionAuditor`** (`factory/factory/audit.py`):

```
audit(image_path, *, anchor, reference_path=None, scene=None) -> Verdict
Verdict = {ok: bool, issues: [str]}
```

Real impl calls `claude` with vision (the image(s) + anchor + scene); the test
fake returns scripted verdicts to exercise the regenerate-then-fail path. Kept
thin and injected exactly like `generate_fn` and `ComfyClient`.

**Square output:** the existing workflow emits a *wide* 1536×768 latent (sized
for the cover wrap). The reference sheet and story pages are **square**, so the
prompt injector is extended to also set the output dimensions per call (square
for the ref sheet + pages; the wide setting is kept for the cover-art image).
This is a parameter change to the existing graph — no new nodes or models.

Flow in stage ③ (`factory/factory/art.py`, extended for picture):

1. **Reference sheet:** generate one image from `art_style + character_anchor`
   (a clean character turnaround/portrait of child + dog). Audit against the
   anchor; regenerate (new seed) until `ok` or the retry bound, then it becomes
   `reference.png`.
2. **Per page:** `final_prompt = art_style + character_anchor + scene`, square
   image, base seed + page index. Audit **against `reference.png`** (plus anchor
   + scene). On `!ok`: regenerate with a new seed and the auditor's `issues`
   appended as corrective hints — **bounded to ≈4 tries**. If still failing →
   **fail the build loudly** (don't ship inconsistent art). Save `page_NN.png`.
3. **Cover illustration:** one more image from the anchor for the front cover
   (kept distinct from the dog journal/companion covers).

Auditor reject criteria: wrong/inconsistent child or dog vs. the reference; any
text/letters baked into the image; deformed anatomy; image doesn't match
`scene`.

### 4. Interior (`templates/interior/picture.html.j2`, new)

- Full-**colour**, **8.5×8.5 square**, one page per story page.
- **Framed soft-edge illustration** (art fades to white) with the page `text` in
  a band below — *not* full-bleed. This suits the gentle aesthetic and avoids
  KDP's full-bleed interior setup for v1. (Full-bleed is a future option.)
- `render_interior_html` selects `picture.html.j2` by `book_type`; the template
  references the `page_NN.png` files produced by stage ③.
- Front/back matter: half-title, copyright page, dedication page,
  the story pages, a closing page (`closing`). No in-book AI-disclosure page —
  KDP's AI disclosure is a private upload-form field, not printed in the book. With ~18–22 story pages this lands
  naturally at **≥ 24 pages**; one trailing blank is added only if needed to make
  the count **even**.

### 5. Build order (`build.py`)

Picture books **reverse** the journal/standard order: **art runs before
interior** (the interior embeds the illustration files). `run_build` branches on
`book_type`: `picture` → content → art (ref sheet + pages + cover) → interior →
cover wrap → checklist. The cover-spine page count comes from the rendered
picture interior (`pdf_page_count`).

### 6. Cover & checklist (reuse)

- `cover.py` reused as-is: the cover illustration + the existing **typographic
  title overlay** (real text over art, never diffused) → square paperback wrap,
  spine from page count. Paperback only.
- `copy.book_blurb` gains a `picture` branch (kid-book back-cover line, or
  `cfg.blurb`).
- `checklist.py` reused; flags **colour interior** + **8.5×8.5** + paperback-only.
  The KDP **upload-form** AI disclosure (private, never printed) is already
  emitted by the checklist — unchanged.

### 7. First title

`factory/books/dog-loss-kids.config.json` — `book_type: "picture"`, dog,
`pet_name` set, Eleanor Hartley, 8.5×8.5, $10.99, ~16–18 pages. Final title
chosen at config time. Built end to end (ComfyUI live) as the proof.

## Testing + build-time guards

Consistent with the standing preference to fix **and guard** generated-output
defects at build time (joins the margin guard, cover-text guard, chapter-length
guard).

- Unit tests (fakes only, no GPU/network): config (picture validation, required
  `pet_kind`+`pet_name`, square trim), picture content strategy (page count,
  anchor present, validation-failure + retry cases), the **audit regenerate
  loop** (fake auditor scripted to fail N times then pass → asserts regeneration;
  fail past the bound → asserts the build fails), picture interior (one framed
  image+text per page, references the right files, no fill-in lines), blurb
  dispatch.
- New build-time guards:
  - Illustration count == `page_count` (every page got an image).
  - Every illustration file non-empty and square (right aspect ratio).
  - **Audit consistency must pass within the retry bound or the build fails.**
  - Interior page count **≥ 24 and even**.
  - Reference sheet must pass audit before any page is generated.

## Out of scope (YAGNI)

- Full-bleed interiors (framed v1; bleed setup deferred).
- IPAdapter / LoRA character conditioning (Approach A first; B documented as the
  upgrade path).
- Picture-book EPUB / Kindle (paperback only).
- Hardcover edition.
- Two-page spread layouts (one illustration per single page in v1).

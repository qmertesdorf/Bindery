# Pet-Loss Grief Journal Factory — Design Spec

**Date:** 2026-06-05
**Status:** Approved design, pre-implementation

## 1. Purpose

Build a repeatable production pipeline that turns a per-book config into a
**publish-ready Amazon KDP bundle** (print interior PDF, ebook EPUB, wraparound
cover PDF, ebook cover, and an upload checklist with AI disclosure) for a
**pet-loss grief guided journal** series.

The pet-loss journal is the **proof-of-concept** for a more general ambition: a
reusable book-production factory whose hardest and most interesting component is
the **content engine** (stage ①). Journals are the deliberately easy first case —
their content is a set of independent prompts with no narrative continuity — which
lets us prove the render → cover → publish scaffolding before pointing the content
engine at harder genres later (see §9).

## 2. Validation basis (why this niche)

Live Amazon validation (2026-06-05, see `../../candidates.md` and project memory):
- **Pet loss grief journal**: ~3,000 results; category leader ~312 reviews, rest of
  page 1 under 100 (99/34/10/6); prices **$7.89–$34.99** (premium tolerated).
- Passes the Goldilocks test: real demand + beatable page-1 competition.
- Highest price tolerance of the three validated niches; evergreen, gift-driven,
  emotionally motivated buyers.

## 3. Scope decisions (locked)

| Decision | Choice |
|---|---|
| Formats | Paperback (hero) **+** ebook companion |
| Interior engine | Templated **HTML/CSS → PDF** via `browse pdf` |
| Cover | **ComfyUI art + HTML/CSS typographic text**, wraparound assembled in template |
| Automation | **One-command generator**: `python build.py <config>` |
| Trim / length / price | **6×9", ~120 pages, $9.99** launch target |
| Content generation | Shell out to installed **`claude` CLI** (`claude -p`) — no separate API key |
| Orchestrator language | **Python** (already present via ComfyUI; familiar across user's projects) |
| Series | 3 titles reusing all templates: **dog / cat / general pet** |

### Explicit non-goals (YAGNI)
- No KDP publishing API automation — **none exists for individual authors**; final
  upload is manual through the KDP web dashboard by design.
- No GUI.
- No multi-niche / multi-genre abstraction *built now*. The architecture keeps
  stages isolated so a future content engine can plug in, but we do not build that
  generality speculatively (see §9).

## 4. Architecture

A content-driven pipeline. One input config flows through five isolated stages;
out comes a publish-ready bundle. A new title = new config + one command. Templates
and the ComfyUI workflow are shared across the series.

```
book.config.json  ─▶ ① generate-content ─▶ content.json
                                              │
            ┌─────────────────────────────────┤
            ▼                                  ▼
   ② render-interior                   ③ generate-art (ComfyUI)
   (HTML→PDF + EPUB)                          │
            │                                  ▼
            │  page count ───────────▶ ④ render-cover (art+text→wraparound PDF)
            ▼                                  │
        interior.pdf / .epub            cover-paperback.pdf
                          └────────┬───────────┘ cover-ebook.jpg
                                   ▼
                        ⑤ make-checklist → upload-checklist.md (+ AI disclosure)
```

Orchestrator `build.py` runs ①→⑤ in sequence — the **one command**:
`python build.py books/dog-loss.config.json`

Each stage is an independent module with a clear contract (input file → output
file), runnable in isolation for debugging.

## 5. Stage contracts

### ① generate-content
- **In:** `book.config.json` (title, subtitle, theme e.g. `dog`/`cat`/`pet`, page
  target, art-prompt seeds, structure knobs).
- **Does:** shells out to `claude -p` with a structured prompt + the config.
- **Out:** `content.json` — intro/how-to-use copy; an "About [pet]" fill-in profile
  (name, breed, birthday, the day we met, favorite things); ~70 undated grief
  prompts ("Today I miss…", "What I wish I'd said…", "A memory that made me smile…");
  milestone reflections (first week / first month / birthday / special dates);
  short supportive microcopy between sections; "Letter to [pet]" pages.
- **Why this is the easy case:** prompts are independent — no continuity, plot, or
  character state to maintain. A single LLM call suffices.

### ② render-interior
- **In:** `content.json` + `templates/interior/`.
- **Does:** renders HTML, exports with `browse pdf` at KDP print specs — 6×9" trim,
  0.125" bleed, gutter/outer margins ≥0.375", embedded fonts, page numbers. Lined
  writing areas and section dividers are pure CSS. Re-exports a reflowable **EPUB**
  for the ebook from the same content.
- **Out:** `interior.pdf` (print), `interior.epub` (ebook), and final **page count**.

### ③ generate-art
- **In:** art-prompt seeds from config + `comfyui/workflow.json`.
- **Does:** calls **ComfyUI HTTP API at `localhost:8188`** (user's `run_comfyui.bat`
  instance) to generate soft watercolor pet imagery (rainbow bridge, paw prints,
  gentle pastels).
- **Out:** cover art PNG(s).

### ④ render-cover
- **In:** cover art + `templates/cover/` + page count from ②.
- **Does:** places **title/subtitle/author as real typographic text** over the art;
  assembles the full wraparound (back + spine + front). **Spine width auto-computed**:
  `pages × 0.0025" + bleed`. No diffused lettering = no garbled titles.
- **Out:** `cover-paperback.pdf` (wraparound), `cover-ebook.jpg` (front only,
  ~1600×2560).

### ⑤ make-checklist
- **In:** config + computed specs.
- **Does:** emits the KDP listing + the mandatory AI disclosure answers.
- **Out:** `upload-checklist.md` — keyword-rich title/subtitle; paste-ready
  description (HTML); 7 backend keywords; 2 categories (Self-Help › Death & Grief
  primary); suggested price ($9.99); royalty note (~$3.69/sale at 120pp, 60%, ~$2.30
  print cost); and **AI-disclosure answers pre-filled** (text: AI-generated; images:
  AI-generated). User pastes into KDP and ticks the boxes — the one manual step.

## 6. Repo layout

```
book-gen/factory/
  build.py                 # orchestrator (one command)
  stages/                  # content, interior, art, cover, checklist modules
  templates/interior/      # HTML/CSS, shared across series
  templates/cover/
  comfyui/workflow.json    # saved pet-art workflow
  books/
    dog-loss.config.json   # title #1
    cat-loss.config.json   # title #2 (new config only)
    pet-loss.config.json   # title #3
  out/<slug>/              # generated interior.pdf, .epub, cover PDFs, checklist
```

## 7. Stack & dependencies

- **Python** orchestrator (system Python, already present via ComfyUI).
- Shells out to: the **`browse`** binary (PDF/EPUB render, already installed via
  gstack/bun), the **`claude`** CLI (content generation), and **ComfyUI's HTTP API**.
- Python libs: `requests` (ComfyUI API) and stdlib `subprocess`/`json`. EPUB
  assembly: a light dependency (e.g. `ebooklib`) or hand-rolled zip — decided at
  plan time.
- No new heavy dependencies.

## 8. Compliance & economics

- **AI disclosure (mandatory):** KDP requires private disclosure of AI-generated
  text and images at publish time. Stage ⑤ pre-fills these answers. Disclosure is
  private to Amazon, not shown to buyers.
- **Velocity:** ≤3 new titles/day cap is irrelevant at our 3-title series pace.
- **Royalty math (launch target):** 6×9", ~120pp B&W paperback, print cost ~$2.30;
  at $9.99 × 60% − $2.30 ≈ **$3.69/sale**. Ebook companion priced low ($2.99–$4.99)
  mainly for discoverability.

## 9. Future extension: the content engine (the strategic interest)

The content engine (stage ①) is the component of greatest long-term interest. The
pet-loss journal exercises it in **easy mode** (independent prompts). The render
(②), art+cover (③–④), and publish (⑤) stages are **genre-agnostic** and reusable
as-is.

Extending to other genres = writing a **new stage-① content engine** and reusing
②–⑤ unchanged. The difficulty scales sharply with content type:
- **Journals / activity / low-content:** independent units, single-call generation. (Now.)
- **Structured nonfiction / workbooks:** outline-driven, moderate continuity.
- **Fiction / mystery:** 50k–80k words of internally-consistent narrative — requires
  a multi-pass pipeline (outline → chapter beats → draft → continuity/consistency
  pass → human line-edit), not a single call. Also the highest KDP spam-saturation
  and quality-review risk; verified research flags AI fiction as a poor near-term
  bet. Treated as a **later, separate project**, not this build.

**Design implication honored now:** keep stages isolated and the content stage a
clean swappable module so a future content engine plugs in without touching ②–⑤.
We do **not** build that generality speculatively in this iteration.

## 10. Success criteria

- `python build.py books/dog-loss.config.json` produces, unattended: a KDP-valid
  print `interior.pdf`, an `interior.epub`, a wraparound `cover-paperback.pdf` with
  correct spine width, a `cover-ebook.jpg`, and a complete `upload-checklist.md`.
- Output passes KDP's print previewer without margin/bleed errors.
- A second title (`cat-loss`) is produced by adding only a new config — zero template
  edits.

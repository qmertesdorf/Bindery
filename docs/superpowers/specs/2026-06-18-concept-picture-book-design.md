# Generic character-free picture book (`concept` type) — Design

**Date:** 2026-06-18
**Status:** Approved (brainstorming → spec)
**Branch:** `feat/concept-picture-book`

## Goal

Two deliverables:

1. **A reusable template** — a new character-free illustrated-book "kind" the
   factory can build *without* LoRA training. Content is driven by a *subject*,
   not the grief/comfort narrative arc. Each spread is an independent
   illustration; the only consistency bar is **art style**, not character
   identity. This sidesteps the LoRA-consistency problem that stalled the Mango
   book.
2. **First title** — an *Animals & Nature* book, age ~5 early-reader, built
   through that template as the proving run.

## Why a new `book_type`, not an extension of `picture`

The existing `"picture"` type is hard-wired to recurring characters:

- `config.py` requires `pet_kind`, `pet_name`, `theme ∈ {grief,comfort}`, and
  (for Flux) exactly one hero LoRA.
- `picture_content.py` only knows grief/comfort story prompts.
- `flux_art.py`'s `page_plan` builds every prompt from LoRA triggers + a `cast`.

Overloading that would risk the working *Morning Walk* / *Mango* paths. So we
add a sibling type: **`book_type: "concept"`** — a character-free, style-locked
illustrated book. (Name chosen over `nature`/`showcase`/`illustrated` because it
generalizes to future counting/colors/ABC books, not just nature.)

## Style consistency: prompt-lock (Approach A)

No character LoRA. Cohesion comes from a **locked style**: a fixed Flux
checkpoint + one reusable `flux_style` suffix on every page + locked
`flux_guidance` + locked sampler settings. Only the per-page subject/scene
varies. Natural drift between very different subjects (a whale vs a ladybug)
reads as variety, not a defect. IPAdapter style-anchoring is a known fallback if
a proof run drifts too much, but is **out of scope** for v1.

## Components

### 1. Config (`factory/factory/config.py`)
- Add `"concept"` to `BOOK_TYPES`.
- New validation branch for `concept` requires:
  - `subject` (e.g. `"animals and nature"`)
  - `flux_style`
  - `art_engine == "flux"`
  - `page_count` even and ≥ 20 (same KDP-floor rule as `picture`)
- New optional field `topics`: explicit list of per-spread subjects (animals).
  If omitted, the content LLM picks them.
- *Not* required/used for `concept`: `pet_kind`, `pet_name`, `theme`,
  `characters`.
- Reuses existing fields: `flux_style`, `flux_guidance`, `trim_w/h`,
  `price_usd`, `art_prompt`, `blurb`, `title/subtitle/author`.
- `makes_ebook` stays `False` (paperback-only house rule).

### 2. Content (`factory/factory/concept_content.py`, new)
- `generate_concept_content(cfg, generate_fn)` mirrors the bible+story+retry
  structure of `picture_content.py`.
- Produces a small bible (`art_style`, `dedication`) plus a `pages` list where
  each page is **`{subject, text, scene}`** — no `cast`, no `mood`.
  - `text`: 1–2 simple early-reader (age ~5) lines — gentle, concrete, a light
    rhyme or an easy nature fact.
  - `scene`: a rich, concrete habitat visual — **no people, no text/letters**.
  - `subject`: the animal/spread subject (used for audit + ordering); seeded
    from `cfg.topics` when provided.
- `validate_concept_story` enforces exactly `page_count` pages, each with
  non-empty `subject`/`text`/`scene`. Config-locked `art_style` wins over the
  bible's, same as `picture_content`.
- Wire into `content.generate_content` dispatch alongside `standard`/`picture`.

### 3. Art (`factory/factory/flux_art.py`)
- Add `generate_concept_art(cfg, content, out_dir, comfy, *, seed, auditor,
  max_tries=4)`.
- Reuses `flux_lora_workflow` with an **empty LoRA stack** (`loras=[]` — the
  graph already degrades cleanly to just the UNET `head="u"`).
- Per page: `prompt = f"{flux_style}. {scene} No people, no text."`; locked
  `flux_guidance`; per-page seed offset as today (`seed + i*17`).
- Keeps the **keep-best-and-flag** behavior (returns `flagged`).
- Audits each page against a *subject* anchor (see §4), not a character anchor.
- Cover from `cfg.art_prompt` (a representative nature scene), no characters.
- Returns `{"pages": [...], "cover": Path, "flagged": [...]}`, same shape as
  `generate_flux_art`.

### 4. Audit (`factory/factory/audit.py`)
- Add a **concept audit mode** (a `mode`/`kind` param or a
  `build_concept_audit_prompt`): judge *correct subject* (the right animal),
  clean and consistent storybook style, **no people**, no text/letters/numbers,
  no broken anatomy. Drop the character-identity / outfit / mood-contradiction
  rules (no character to check). Keep the generous two-tier ACCEPT/REJECT bar.
- `ClaudeVisionAuditor.audit` gains a way to select the concept prompt;
  `generate_concept_art` passes a subject string as the `anchor`.

### 5. Interior / Cover / Checklist / build.py
- Reuse the picture interior template (`templates/interior/picture.html.j2`) —
  same shape (image + 1–2 lines per spread). Verify no pet/dedication wording
  breaks for `concept`; adjust the template minimally if it does.
- Reuse the (now-committed) overscan-crop cover and the checklist as-is.
- `build.py`: add a `concept` route mirroring the `picture` branch — art before
  interior, Flux graph, no EPUB. Generalize the `flux` detection so `concept`
  (always Flux) takes the Flux-graph path.

## Build sequencing (decomposition)

- **Piece A — the engine.** Config + content + art + audit + build routing +
  tests. Pure-Python, unit-testable with fakes (`generate_fn`, `ComfyClient`,
  `auditor`), **no GPU**. Lands first.
- **Piece B — the first title.** The book config
  (`factory/books/<slug>.config.json`) + a real ComfyUI build. Needs the GPU
  (VRAM-check first — shared with the user's video gen).

## Testing

Follows the existing fake-injection pattern; run via `factory/.venv` from
`factory/`. New tests:

- concept config validation (required fields; rejects character/pet/theme reqs)
- concept content schema (bible + page list, exactly `page_count`,
  subject/text/scene present, config style wins)
- concept art: empty-LoRA prompt assembly + keep-best-and-flag path
- concept audit: verdict parsing for the no-character prompt

Target: full suite stays green (currently 150 passed).

## Defaults & decisions

- House style: 8.5×8.5 paperback, ~$10.99, paperback-only, author
  *Eleanor Hartley* (adjustable for a non-grief pen name during Piece B).
- Engine improvements from the Mango pause already committed
  (`2f75f0e`) so this work starts clean.

## Out of scope (v1)

- IPAdapter style anchoring (fallback only).
- SDXL path for `concept` (Flux-only).
- Kindle/EPUB edition (paperback-only).
- Multi-character or counting/ABC content (the schema generalizes, but only the
  nature subject is built here).

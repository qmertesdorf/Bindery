# *Where Does Mango Go?* — Design Spec

**Date:** 2026-06-14
**Status:** Approved direction (proceeding to implementation plan)

## Goal

Produce a second Flux/LoRA children's picture book — *Where Does Mango Go?* — a **comforting "where do pets go" story** about a little blonde girl (Posy) and her cat (Mango). To do this, generalize the picture pipeline two ways: (1) make content generation **theme-driven** (it currently hardwires the grief arc), and (2) replace the time-based `moment` page field with an honest **cast** field that directly drives which character LoRAs render — including a new "pet alone" cast for the peaceful-place pages.

The shipped dog book (*The Morning Walk*) must remain functionally identical after these changes.

## Scope & decomposition

This effort has two pieces; only the first is software and is what this spec + the resulting plan cover.

- **A — Pipeline engine change + book config (THIS SPEC, fakes-tested, no GPU).** The `theme` field, the `cast` page model, theme-aware content generation, `flux_art` cast routing, and the `books/where-does-mango-go.config.json` wiring.
- **B — Character LoRA assets (prerequisite runbook, GPU-gated).** Train a `posy` (girl) LoRA and a `mango` (cat) LoRA via the established Biscuit procedure. This is a known manual process, not new code; it runs when the GPU/VRAM is free (the GPU is shared with the user's video gen — check VRAM first). Documented as a checklist in this spec (see "Character assets runbook"). The book only *builds* once these `.safetensors` exist.

The book ships when both A and B land. A is independently testable and mergeable without B (the build is fakes-tested; a real GPU build waits on B).

## The book (surface)

- **Title:** *Where Does Mango Go?*
- **Subtitle:** *A Gentle Story About Where Beloved Pets Go*
- **Author:** Eleanor Hartley
- **Premise/theme:** comfort. Answers a young child's question "where did my cat go?" after Mango dies, with a secular, reassuring blend: gentle visions of Mango at peace in a luminous natural place (sunlit meadows, soft stars, warm light), and a close on **"he stays in your heart."** Never the "Rainbow Bridge" poem; no religious afterlife claim.
- **Format:** 8.5×8.5 in, paperback-only, Standard Color, No Bleed, **$10.99** (matches *The Morning Walk*).
- **Characters (locked design — feeds both the LoRA training and the config anchor):**
  - **Posy** — a round-faced little blonde girl about five, fair skin, shoulder-length wavy honey-blonde hair with a small side braid; one fixed outfit: a soft sky-blue pinafore dress over a cream long-sleeved top, with little red shoes. Trigger (proposed): `p0sygirl girl`.
  - **Mango** — a small soft ginger/orange tabby cat with a cream chest and paws, gentle amber-green eyes, a fluffy tail, and a little pink nose. Trigger (proposed): `mang0cat cat`.
  - (Triggers/strengths are finalized during LoRA training; the config's `character_anchor` must match the trained appearance.)

## Architecture

### 1. Theme field (`config.py`)
Add a picture-only `theme` field to `BookConfig` (enum, default `"grief"`): `theme ∈ {"grief", "comfort"}`. Validated in `load_config` for picture books (reject unknown values — consistent with the existing build-time guards). `theme` selects the content-generation framing. Adding a future theme = one new prompt template + one enum value.

### 2. Cast-based page model (replaces `moment`)
A page's `moment` (`memory|present`) is a *time* label standing in for *who is in frame*. Replace it with a **`cast`** field that directly models frame occupancy and drives LoRA selection:

| `cast` | Illustration shows | LoRAs rendered | Audit anchor |
|---|---|---|---|
| `child` | the child alone (no pet, no other people) | hero only | child-only (anchor text before the pet name) |
| `child_and_pet` | the child **and** the pet together | hero + companion | full anchor |
| `pet` | the pet **alone** in a setting (no child, no people) | companion only | pet-only (anchor text from the pet name onward) |

- The new `pet` cast is the capability Approach 2 adds: the peaceful-"beyond" pages where Mango is at peace, no child present.
- **Both themes emit `cast`.** The grief generator maps its existing arc onto it: happy memories → `child_and_pet`, loss/missing → `child` (it never emits `pet`). So *The Morning Walk* renders identically, with cleaner labels.
- Validation: `cast ∈ {child, child_and_pet, pet}` (replaces the `moment ∈ {memory, present}` check).

### 3. Theme-aware content generation (`picture_content.py`)
`build_bible_prompt` and `build_story_prompt` become theme-parameterized:
- **grief** (default): today's framing and arc, unchanged in behavior — but emitting `cast` instead of `moment`.
- **comfort**: a new framing. Bible still yields `character_anchor`/`art_style`/`dedication`. Story arc: the child misses the pet (`child`) → wonders where they went → gentle visions of the pet at peace in a luminous natural place (`pet`, and `child_and_pet` for "with him in that place") → reassurance the pet is happy and safe → closes on "he stays in your heart" (`child`, warm). Same hard image constraints carry over (only the child, the child-with-pet, or the pet may appear; never other people; no words in the picture).

The `generate_picture_content` orchestration (bible → lock config overrides → story → assemble) is unchanged except for passing `theme` through to the prompt builders and validating `cast`.

### 4. `flux_art.py` cast routing
- `page_plan(page, *, hero, companion, style, outfit)` routes on `page["cast"]`:
  - `child` → hero LoRA only; prompt "{hero.trigger} {outfit}, alone, no other people, no animals"; child expression from mood (existing `_expression`/`GRIEF` logic).
  - `child_and_pet` → hero + companion; "{hero.trigger} {outfit}, together with {companion.trigger}"; "Only the child and the pet, no other people."
  - `pet` → companion LoRA only; a **new child-free prompt branch**: "{companion.trigger}, peaceful and content, in {scene}. No people, no other animals. Soft luminous light." (no child-expression clause).
- `generate_flux_art` computes both `hero_anchor` (text before the pet name, for `child` audits) and a new `pet_anchor` (the pet name onward, for `pet` audits); selects the audit anchor by cast (`child`→hero_anchor, `child_and_pet`→full anchor, `pet`→pet_anchor). Page seeds and the audit-retry loop are unchanged.
- Cover: `child_and_pet` cast (Posy + Mango together in the luminous place), warm and hopeful, audited against the full anchor — reuses the existing cover path.

### 5. Build + tests
- `build.py`: no routing change needed (the `art_engine == "flux"` route already added). The cast model is internal to `flux_art`/`picture_content`.
- Update every test/fixture that references `moment` to `cast`: `conftest.py` (`picture_content` fixture), `test_picture_content.py`, `test_flux_art.py`, `test_build.py`. This is the deliberate "heavier" cost of the clean model. Add new coverage for: the `pet` cast in `page_plan`, the `pet_anchor` audit selection in `generate_flux_art`, theme selection in `picture_content`, and a comfort-book build route.

## Character assets runbook (piece B — prerequisite, GPU)

Not part of the code spec; documented so the plan can reference it. Follows the validated Biscuit procedure (see the `picture-book-ipadapter` memory and the `_build_faceset.py`/`_build_dogset.py`/`_train_lora.py` scratch scripts + the isolated kohya venv at `~/.book-gen-train`):
1. Lock Posy's and Mango's appearance (above) into a small bootstrap prompt set.
2. Bootstrap a training set per character (IPAdapter/Flux), curate.
3. Train `posy` (girl, face-dominant) and `mango` (cat) LoRAs; pick keepers by visual audit.
4. Place the `.safetensors` in `ComfyUI/models/loras/` and record their filenames + triggers + strengths in the book config's `characters` array.
5. Verify VRAM is free before training (GPU shared with video gen).

## The book config (`books/where-does-mango-go.config.json`)

A `book_type: "picture"`, `art_engine: "flux"`, `theme: "comfort"` config carrying: Posy as the `hero` character, Mango as the `companion`, the locked `flux_style` (the validated watercolour string), `outfit` (Posy's sky-blue pinafore over a cream top), the `character_anchor` describing both, a comfort cover `art_prompt` (Posy and Mango together on a sunlit hill / among soft stars), `page_count` (≥20, even — likely 22), and the listing metadata (subtitle, blurb, price 10.99, trim 8.5×8.5). LoRA filenames are filled in after training (piece B).

## Testing approach

Mirror the proven pattern throughout: injected fake `ComfyClient` (`http_post`/`http_get`) + fake auditor, no GPU, no real LLM (fake `generate_fn`). Every engine change lands test-first. The full suite (currently 139) must stay green; the `moment`→`cast` rename updates existing picture tests rather than adding parallel ones.

## Non-goals / YAGNI

- No GPU work in the code spec; LoRA training is a separate runbook.
- No third art engine, no new book_type — `theme` is a sub-field of the existing picture type.
- No freeform "premise" text input — `theme` is a small guarded enum; generalize only when a third theme actually appears.
- No backfill of the dog book's already-shipped PDFs; it stays buildable and renders equivalently under `cast`.

## Risks

- **Rename blast radius:** `moment`→`cast` touches content generation, flux_art, and four test files. Mitigated by it being mechanical and fully test-guarded, and by keeping the grief arc's behavior identical.
- **Comfort-arc art quality** (the `pet`-alone luminous-place pages) is only verifiable on a real GPU build — flagged for visual confirmation when piece B lands, same as any Flux art.
- **Anchor splitting for `pet_anchor`** depends on the pet name appearing cleanly in the anchor; the existing `pet in anchor` guard + maxsplit handling carries over.

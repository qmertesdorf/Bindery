# Auto-subject-fallback for interchangeable concept pages

**Date:** 2026-06-28
**Status:** approved, ready to implement

## Problem

In the concept line a page's subject is interchangeable — the book is "ocean
animals," not "this specific animal." Some subjects are Flux-hard: the manatee's
single paddle tail rendered notched/two-lobed across ~24 gated attempts and never
passed the auditor. Today the pipeline then "keeps best + flags," shipping a
defect. We've fixed this before by hand (manta→swordfish, seahorse→angelfish); this
automates that judgement.

## Behavior

For a book that opts in (`subject_fallback: true`), when a page exhausts its
render→audit attempts (`max_tries`) without passing:

1. Ask the LLM for a **replacement subject** — on-theme (from the book's `subject`),
   simple and clean to illustrate, NOT already used in the book, with explicit
   best-judgment guidance to avoid Flux-hard body plans (flat rays/skates, eels,
   long odd-tailed mammals) and prefer simple, rounded, friendly animals.
2. **Regenerate that page's content** for the new subject: a fresh `scene` and a
   fresh rhyming `text` couplet, reusing the existing concept content generation so
   it matches the book's voice and readability ceiling.
3. **Re-run the render→audit loop** for the new subject.
4. If still failing, **fall back again** (next subject), up to `max_fallbacks`.
5. On success, **persist** the new `{subject, scene, text}` to `content.json` (so
   the interior PDF caption matches the picture) and the page image.
6. If the cap is hit, keep best + flag (today's behavior).

Default off → existing builds are byte-for-byte unchanged.

## Components

### Config (`factory/factory/config.py`)
- `subject_fallback: bool = False` — opt-in (on for the concept line).
- `max_fallbacks: int = 3` — cap on subject swaps per page.
- Parsed in `from_dict` like the existing `qa_*` flags.

### Replacement-subject generator
An injectable callable (mirrors `auditor` / `generate_fn`); real impl shells
`claude -p`. Signature roughly:
`suggest_subject(theme: str, used: list[str], failed: str) -> str`.
Prompt instructs: one short subject phrase, on `theme`, simple/clean to illustrate
in a soft kawaii storybook, a single clear animal with a simple rounded body,
explicitly NOT any of `used` and not `failed`, avoid flat/odd body plans. A dedupe
retry loop (capped) re-asks if it returns something already used.

### Single-page content regenerator
Reuse the existing concept content path to produce `{subject, scene, text}` for ONE
new subject, consistent with the book (rhyming couplet, scene with anatomy cues,
under `max_reading_grade`). Investigate `content.py` / `copy.py` during
implementation to reuse the per-page prompt rather than duplicating it.

### Art-loop integration (`factory/factory/flux_art.py::generate_concept_art`)
Wrap the current per-page render→audit attempt loop in a fallback loop. On
exhaustion + `subject_fallback` + budget remaining: get a replacement subject,
regenerate content, mutate `content["pages"][i]` in place, retry. Track used
subjects (all book subjects + ones already tried for this page) to avoid dupes.

### content.json persistence (`factory/factory/build.py`)
After concept art, re-write `content.json` from the (possibly mutated) `content`
dict so swaps reach the interior PDF caption rendering.

## Testing (TDD)

- Fake auditor rejects subject A, accepts B; fake `suggest_subject` returns B →
  page falls back to B, passes, final `content["pages"][i]` is B's subject/scene/
  text; the persisted caption is B's.
- `subject_fallback` off → unchanged (keep best + flag, no LLM calls).
- `max_fallbacks` respected (stops after N swaps, keeps best + flags).
- No duplicate subject chosen (dedupe re-ask honored).
- Regenerated caption still passes the readability gate (or is regenerated/flagged).

## Edge cases

- LLM returns an already-used subject → re-ask, capped; if still dup, give up that
  fallback slot.
- If page 1 (the style anchor) swaps, the new page 1 becomes the anchor — acceptable.
- Persistent readability failure on a regenerated caption → flag rather than loop
  forever.

## Out of scope

- A curated config subject pool (chose LLM-generated, best-judgment).
- Fixing the VQAScore worker startup crash (separate issue).
- The deterministic exact-count guard (separate backlog item).

## First use

Run on Deep Blue World: the feature auto-swaps the stubborn manatee (page 19) to a
clean subject, regenerates its couplet + scene, re-rolls under the auditor, then
rebuild the interior + cover PDFs and verify.

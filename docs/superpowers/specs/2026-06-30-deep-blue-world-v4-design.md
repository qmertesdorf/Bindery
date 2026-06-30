# Deep Blue World v4 — design

**Date:** 2026-06-30
**Status:** approved (user signed off in brainstorming; build authorized to run overnight)
**Predecessors:** v2 (current ship version), v3 (abandoned — regressed)

## Goal

Produce a fresh, **reproducible**, codified re-render of *Deep Blue World* that comes out
**better than v2** — by using the taste-selected best-of-N that neutralizes v3's gloss-drift
failure — **without changing the approved story or art direction**.

v2 is clean and user-approved but was never reproducible (its hand-tuned `content.json` is
gitignored; a from-scratch rebuild would regenerate scenes and drift). v3 tried to "use all our
improvements" at full best-of-N quality and **regressed**: it recast land/ice/surface animals
underwater (→ chubby pale blobs) and its VQAScore best-of-N selector chased the boldest,
glossiest render (→ style drift away from the soft watercolour anchor). The auditor passed the
off-style pages because it optimized *checkable* defects, not taste.

v4 keeps everything v2 got right and changes only the two things that make a fresh build both
**safe** and **better**: it inherits v2's exact text, and it uses the new Claude **taste**
selector (anchored on a known-good v2 page) instead of VQAScore.

## What stays identical to v2 (no art-direction change)

- **Story text** — scenes, rhyming captions, subject list. Inherited verbatim by reusing v2's
  `content.json` (the engine reuses an existing `out/<slug>/content.json` if present:
  `build.py:42-47`). No regeneration → no copy/subject drift.
- **Topics / `flux_style` / cover `art_prompt` / blurb** — copied verbatim into the v4 config.
- **Hardened auditor** — 3-pass majority vote, describe-first, deterministic count guard, corner
  crops, RealESRGAN upscaler. All pure-quality, no art-direction effect; all kept on.

## What changes (the "better" + "reproducible" levers)

### 1. Taste-selected best-of-N (the quality lift)
- `qa_candidates: 3` — render 3 candidates per page.
- `qa_select: "claude"` — the `ClaudeBestOfNSelector` (factory/factory/qa/selection.py) picks the
  **literal best** by a Claude-vision art-director rubric: a hard print-safe full-bleed gate
  first, then correct true-species subject, then **soft watercolour house style (explicitly
  down-weighting glossy / hard-outlined / high-contrast / CGI renders)**, then clean, then appeal.
  This is the exact antidote to v3's failure — v3 regressed *because* VQAScore best-of-N rewarded
  gloss; this selector fights it.
- `qa_select_anchor: "out/deep-blue-world-v2/page_01.png"` — every page is judged for house-style
  cohesion against **v2's proven pixels** (the soft-matte whale), not against v4's own
  freshly-rendered page_01 (which could itself drift). Path is relative to the build cwd
  (`factory/`).
- `qa_vqa: false` — the Claude selector needs no VQAScore worker (which crashes on startup on this
  box), so best-of-N is usable here for the first time. No VRAM contention either: Flux (~12 GB)
  renders, then `claude -p` taste-picks (no GPU).

### 2. Lock v2's subjects (no swapping)
- `subject_fallback: false` — v2 had it on; for v4 we want v2's *exact* subjects, so a stubborn
  page keeps-best and **flags for review** rather than swapping the animal. Folds in v3's
  "no-swap" lesson.
- `qa_max_tries: 8` — bigger reroll budget (default 4) so a stubborn page converges instead of
  shipping a weak keep-best. Also a v3 lesson.

### 3. Reproducibility ("the lock in")
- v2's `content.json` is persisted as a **git-tracked seed** at
  `factory/books/deep-blue-world-v4.content.json` (the `out/` dir is gitignored, so the seed lives
  next to the config).
- Build procedure copies the seed to `out/deep-blue-world-v4/content.json` before the first build
  → engine reuses it → text inherited exactly.
- **Both** the config and the content seed are committed. v4 is then deterministically
  rebuildable — the thing v2 never was.

## Config (`factory/books/deep-blue-world-v4.config.json`)

Cloned from v2 with these deltas:

| Field | v2 | v4 | Why |
|---|---|---|---|
| `slug` | `deep-blue-world-v2` | `deep-blue-world-v4` | new out dir; v2 untouched |
| `qa_candidates` | 1 | 3 | best-of-N quality lift |
| `qa_select` | (default) | `claude` | taste pick, no VQA worker |
| `qa_select_anchor` | "" | `out/deep-blue-world-v2/page_01.png` | cohesion vs proven v2 pixels |
| `subject_fallback` | true | false | lock v2's exact subjects |
| `qa_max_tries` | 4 (default) | 8 | bigger reroll budget |

Everything else (topics, flux_style, art_prompt, blurb, `qa_vqa:false`, `qa_audit_passes:3`,
`qa_audit_aggregate:"majority"`, `qa_describe_first:true`, `qa_count_guard:true`,
`qa_corner_crops:true`, `upscale_model:"RealESRGAN_x4plus.pth"`, trim, price) = identical to v2.

## Build procedure (GPU-gated)

1. `cp books/deep-blue-world-v4.content.json out/deep-blue-world-v4/content.json` (done at setup).
2. Ensure ComfyUI is up: `~/ComfyUI` venv `main.py --use-sage-attention` (Blackwell flags).
3. Check `nvidia-smi` — need a free GPU (≥~12 GB).
4. From `factory/`: `./.venv/Scripts/python.exe build.py books/deep-blue-world-v4.config.json
   --out out --seed <s>`.
5. Build is per-page resumable (reuses any `page_NN.png`); self-heals ComfyUI crashes.

## The hard safeguard (the v3 lesson)

**v2 stays the ship version until v4 is eyeballed page-by-page and confirmed ≥ v2.** A green build
is NOT sufficient — v3 passed its auditor while regressing, and best-of-N + the taste-selector are
**unvalidated live** (v4 is their first real run). The mandatory gate is a human/vision compare of
all 20 v4 spreads + cover against v2. If v4 does not clearly beat v2, v2 ships and v4's render is
discarded (the config + selector learnings are still kept). Fallback if the taste-selector
underperforms: `qa_candidates:1` (= v2), not a redesign.

## Scope boundaries (YAGNI)

- **No engine code changes** — every lever already exists in the engine.
- No per-page candidate counts; no underwater recasts; no VQA; no new auditor passes.
- Cover renders separately with its existing hardened front-art audit (not part of best-of-N).

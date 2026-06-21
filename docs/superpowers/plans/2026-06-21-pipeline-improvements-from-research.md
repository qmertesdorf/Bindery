# Factory Pipeline Improvements — from Verified Deep Research (2026-06-21)

Implementation plan mapping the **verified** overnight research
(`docs/research/2026-06-21-verified-*.md`) onto concrete changes in the `factory` pipeline.
All claims here are 3-vote-verified unless noted; refuted claims are called out so we don't
build on them.

## Current pipeline (as built)
- **`audit.py`** — `ClaudeVisionAuditor`: one holistic `claude -p` vision judgment per image
  (character / concept / cover prompt variants). Verdict `{ok, issues}`. Concept prompt already
  does prose anatomy-counting, caption-fidelity, and style-cohesion vs a reference.
- **`art.py`** — `run_audited_render`: single-candidate **render → audit → reroll** (fresh seed
  `+attempt*1009` + corrective issue hints), `max_tries=4`, then fail/flag. `ComfyClient` injectable.
- **`flux_art.py`** — FLUX.1 (`flux1-dev-fp8`), stacked **model-only LoRAs**, upscale = naive
  **`ImageScale` lanczos → 2560px**. Concept path anchors every page/cover to the first passing
  page (`style_ref`) and flags-best-on-fail instead of dying.
- **`interior.py` / `cover.py` / `specs.py`** — KDP PDF geometry (verify against §WS4 table).
- **`copy.py` / `paste_console.py` / `checklist.py`** — listing copy + KDP paste console + checklist.

Design principle to preserve (user): **fix defects AND guard them at build time**
([[catch-defects-with-guards]]); keep the "flag best & continue" behavior so one stubborn page
never kills a book.

---

## Implementation status (branch `feature/qa-ensemble-phase1`)
Phase 1 **scaffolding is built, unit-tested, and default-OFF** (221 tests pass; Claude-only path
byte-for-byte unchanged). WS1a (VQAScore) is now **wired to a real model and validated**; HADM and
the Flux-Fill repair still need weights/provisioning.
- **WS1a VQAScore** — ✅ DONE & VALIDATED. `factory/factory/qa/vqascore.py` + `vqa_worker.py` run
  `clip-flant5-xl` in an isolated GPU venv (`~/.book-gen-vqa`, see `qa/VQA_SETUP.md`) via a
  subprocess daemon (factory/.venv stays torch-free). 5/5 real pages discriminate right vs wrong
  captions (right 6–15× wrong). Calibrated `qa_vqa_threshold` to a **coarse floor of 0.15** (correct
  matches score ~0.19–0.97, gross mismatches ~0.05). ☐ Re-tune vs full rhyming captions in a live run.
- **WS1b Best-of-N** — ✅ DONE & VALIDATED LIVE. `qa/selection.py` + `art._render_best_of_n`,
  wired into the concept path (caption-gated). Demo: 3 real ComfyUI candidates of one scene scored
  0.531/0.478/0.257 and the selector correctly kept the top one. Set `qa_candidates` (3–9) per book.
  VRAM note: flux (~12GB) + VQA (~6GB) contend on a 16GB card; ComfyUI's smart offload handles it,
  but a real build should render candidates then `/free` before scoring (see `_vqa_bestof_demo.py`).
- **WS1c HADM anatomy** — `qa/hadm.py`. Injectable `AnatomyDetector` + `Defect` boxes. ☐ TODO:
  HADM is a detectron2 project (not pip); `_load_model` raises until the HADM-L/HADM-G weights are
  provisioned and wired.
- **WS1d Ensemble** — `qa/ensemble.py` `EnsembleAuditor` (drop-in for `ClaudeVisionAuditor`),
  assembled by `build_ensemble_auditor(cfg)` from config flags. DONE.
- **WS2 repair** — `factory/factory/repair.py` (`InpaintRepairer`, Flux-Fill graph, mask-from-boxes)
  wired into `generate_concept_art` behind `qa_repair`. ☐ TODO: provision `flux1-fill-dev` in
  ComfyUI; one real localized-defect run to verify the inpaint blends.
- **Config** — `qa_vqa / qa_vqa_threshold / qa_anatomy / qa_anatomy_min_score / qa_candidates /
  qa_repair` on `BookConfig` (all default off).
- **Not started:** WS1e (TIFA decomposition, Phase 2), WS3/WS4 (print fidelity), WS5 (FLUX.2),
  WS6/WS7.

---

## WS1 — Layered QA ensemble in the auditor *(highest impact)*
**Why:** verified — *no single metric is a complete judge* (arXiv 2412.13989, 3-0); specialized
detectors beat general VLMs on anatomy (GPT-4o/LLaVA score ~chance AUC), and VQA-based metrics
beat CLIPScore for caption fidelity. Our auditor is currently one holistic VLM call.

- **1a. VQAScore caption-fidelity stage.** Add a numeric faithfulness gate using **VQAScore**
  (P("Yes") to *"Does this figure show {caption}?"*), shipped as the open `t2v_metrics` package
  (`github.com/linzhiqiu/t2v_metrics`). SOTA across 8 benchmarks; beats CLIPScore/TIFA/PickScore/
  ImageReward/HPSv2 (arXiv 2404.01291, ECCV 2024, 3-0). Use on the **concept** path (captions are
  read aloud) and covers. *Keep CLIPScore only as a cheap pre-filter — it's bag-of-words and
  unreliable on relational prompts (3-0).*
- **1b. Best-of-N selection.** In `run_audited_render`, generate **3–9 candidates** per page and
  pick the highest VQAScore before the holistic audit. Verified to lift human ratings ~0.2–0.3 on
  a 5-pt scale, 2–3× better than PickScore/DSG selection (GenAI-Bench, 3-0). Bounds reroll cost
  and raises floor quality. Make N configurable (default 3; 1 = current behavior).
- **1c. HADM anatomy-defect detector.** Add a specialized stage for extra/missing/malformed
  limbs, hands, eyes, faces: **HADM** (ViTDet + EVA-02 + Cascade-RCNN; **HADM-L** local malformed
  parts, **HADM-G** global missing/extra) — public code/dataset `github.com/wangkaihong/HADM`,
  arXiv 2411.13842 (3-0), **generalizes to FLUX.1-dev**. This is the strongest upgrade to today's
  prose "count the eyes/legs" check, and its bounding boxes feed the repair pass (§WS2).
- **1d. Keep Claude vision as the holistic/style/caption-mismatch member**, not the sole judge.
  Anchor with a reference exemplar (already done on concept path via `style_ref`). Caveat
  (verified, 3-0): GPT-4o-as-judge has self-preference bias; fine-tuned MLLM judges (IntJudge)
  beat it. We're not on GPT-4o; the ensemble + reference anchoring is our mitigation — don't
  promote any single VLM to sole authority.
- **1e. (Phase 2) TIFA-style decomposition** for interpretability: auto-generate per-fact
  question probes (object/**count**/color/spatial/action) from the caption (arXiv 2303.11897,
  3-0). Failing categories become **targeted reroll hints** (we already append `issues` to the
  reroll prompt) and explain *why* a page was rejected.

**Where:** new `factory/factory/qa/` (vqascore.py, hadm.py) behind injectable interfaces mirroring
`ClaudeVisionAuditor`; `ClaudeVisionAuditor.audit` becomes one member of an `EnsembleAuditor`.
**Guard/tests:** keep the injectable-fake pattern; unit-test the ensemble's combine logic and
each stage with fakes (mirror `test_audit.py`). Per-stage confidence thresholds in `config.py`.
**Effort:** M–L. **Risk:** new model deps (GPU/VRAM, t5/CLIP-FlanT5 for VQAScore; HADM weights) —
gate behind config so the Claude-only path still works.

## WS2 — Repair-before-reroll (detect → mask → localized inpaint)
**Why:** verified (3-0) — automated detect→mask→localized-inpaint repairs anatomy/face/hand
defects without rerolling the whole page. Today a single bad hand burns a full fresh-seed reroll.

- On a **localized** reject (HADM/detector bbox, or face/hand), inpaint **only** the masked region
  and re-audit **before** spending a fresh-seed reroll. Tooling (all verified, 3-0):
  ComfyUI **Impact-Pack** `FaceDetailer` / BBOX·SEGM·SAM detectors → `Detailer(SEGS)` /
  `MaskDetailer` (`github.com/ltdrdata/ComfyUI-Impact-Pack`); per-body-part **vslinx** workflow;
  or **SAM (SegmentAnythingUltra V2) + Flux Fill dev (`flux1-fill-dev`) + DifferentialDiffusion**
  for hands (arXiv 2306.00950).
- **Where:** new `factory/factory/repair.py` (ComfyUI graph builder for the fill/detailer pass);
  hook into `run_audited_render` as an optional `repair_fn(image, mask)->image` tried on localized
  rejects before reroll. **Effort:** M. **Risk:** needs `flux1-fill-dev` + detector models in
  ComfyUI; keep optional/config-gated. Pairs directly with WS1c (its masks drive this).

## WS3 — Real print-quality upscaler (replace naive lanczos)
**Why:** `flux_lora_workflow`'s `up` node is a plain **lanczos `ImageScale` to 2560px** — fine for
size, weak for print sharpness. **Refuted/avoid:** **SUPIR is non-commercial** (license verified,
3-0) — must NOT be used for paid KDP paperbacks.

- Swap the lanczos resize for a **commercially-licensed** ESRGAN/diffusion upscaler via ComfyUI
  `UpscaleModelLoader` (e.g. 4x-UltraSharp / Nomos-family ESRGAN models — verify each license).
- **Target 300 DPI at trim+bleed.** For 8.5"×8.5" + 0.125" bleed → 8.625"² → **≥2588px**; current
  2560px ≈ 297 DPI at trim (no bleed) — slightly under once bleed is included. Set the upscale
  target from the actual trim+bleed, not a hardcoded 2560.
- **Where:** `flux_art.py:flux_lora_workflow` (`up`/`upscale`), `specs.py` (DPI/trim constants).
  **Guard:** assert final px ≥ ceil(300 × (trim+bleed)). **Effort:** S–M. CMYK note: KDP accepts
  RGB and converts; soft-proof covers to a CMYK profile (research didn't surface a hard CMYK
  requirement — leave RGB, verify visually).

## WS4 — KDP print geometry as code (audit against verified table)
**Why:** verified verbatim against KDP help pages (3-0). Encode once, don't re-measure per book.
Audit current `interior.py`/`cover.py`/`specs.py` against this table:
- **Interior bleed** 0.125" on top/bottom/outside → width +0.125", height +0.25" (KDP GVBQ3CMEQW3W2VL6).
- **Gutter by page count:** 0.375" (24–150pp), 0.5" (151–300), 0.625" (301–500), 0.75" (501–700),
  0.875" (701–828).
- **Outside margin** ≥0.25" without bleed, **≥0.375" with bleed**.
- **Cover:** single back-spine-front PDF, **≥300 DPI**, ≤40MB recommended (>650MB fails); bleed
  0.125" on top/bottom/outside (not spine) (KDP G201953020).
- **Spine width = page_count × stock multiplier:** white B&W 0.002252", cream B&W 0.0025",
  Premium Color 0.002347", Standard Color 0.002252".
**Where:** `specs.py` constants + `interior.py`/`cover.py`. **Guard:** unit tests asserting
computed gutter/margins/spine match this table for sample page counts. **Effort:** S (if mostly
present) – M (if not). **Action:** first verify what's already implemented, then close gaps.

## WS5 — Evaluate FLUX.2-dev *(R&D, parallel path — do not rip out FLUX.1)*
**Why:** verified (3-0) — **FLUX.2-dev** gives training-free character/object/style consistency
from reference images (multi-reference editing) and **much better in-image typography** than
FLUX.1 (covers/titles). But identity **drifts over long sequences**, so a trained LoRA stays the
safety net for recurring characters.
- **Critical constraint (3-0):** FLUX.1 LoRAs are **incompatible** with FLUX.2 (12B vs **32B** →
  shape mismatch); LoRAs must be **retrained** on `black-forest-labs/FLUX.2-dev`. 32B needs **≥24GB
  VRAM** (check before building — shares GPU with the user's video gen, [[comfyui-build-environment]]).
- **Do NOT hardcode FLUX.2 recipe numbers** — many specific step/LR/reference-count claims were
  **refuted** (e.g. "4 reference images", "95% identity", various step counts). Tune empirically.
- **Where:** add a config-flagged FLUX.2 graph alongside `flux_lora_workflow`; trial first on the
  **concept line** (no recurring character → multi-reference consistency is the win) and on
  **cover typography**. **Effort:** L. Keep the working FLUX.1 path as default.
- LoRA hygiene (verified, 3-0): **15–30 sharp, well-captioned images**; quality ≫ quantity.

## WS6 — Text & metadata guards *(lower effort, real value)*
- **6a. Readability guard** on generated kids' text: use **few-shot** leveling (1/3/5 examples)
  but **do not trust LLM grade/Lexile targeting** — verified unreliable (best model ~22% within
  ±50 Lexile, 3-0). Add an external Flesch-Kincaid/readability check + keep human/top-model review
  for facts & length. **Where:** `picture_content.py`/`concept_content.py`/`content.py`.
- **6b. Rufus-era listing copy.** Amazon's shopping assistant (Rufus → "Alexa for Shopping",
  May 2026) is a **semantic LLM/RAG layer** (verified, 3-0) — write metadata/A+ for natural-language
  intent, not keyword stuffing. **Where:** `copy.py`, `paste_console.py`.
- **6c. AI disclosure + provenance.** Ensure the checklist/paste console reminds to tick the
  **AI-generated images** disclosure — required, and images count **even if hand-edited** (3-0).
  Keep a per-book provenance log (prompts/seeds/selection): the human selection/arrangement +
  human text **is** copyrightable even with AI images; AI parts must be disclaimed at registration
  (USCO, 3-0). (KDP disclosure ≠ USCO registration — two regimes, don't conflate.) **Where:**
  `checklist.py`, `paste_console.py`.

## WS7 — Strategy/niche decisions (not code)
- **Concept/nature line is validated** — children's **nonfiction grew 3.6% in 2025** (Circana,
  3-0), STEM/nature a named growth pocket; character-free concept books fit it. Keep going
  ([[concept-picture-book-resume]]).
- **Picture books = very high demand AND competition** (incl. trad publishers); professional-
  quality illustration is the #1 differentiator (3-0) — our audited, cohesive pipeline is the moat.
- **Pet-loss / grief journals — caution:** the "grief journals are low-competition at $11.99–14.99"
  claim was **REFUTED 0-3**. Do NOT assume low competition or a premium band; validate any journal
  niche with a real keyword tool first. Low-content price band **$6.99–9.99**, royalty ~$2 but
  **page-count dependent** (3-0). Profession/identity micro-niching beats generic (3-0, medium).
- **KDP does NOT ban AI** (3-0); just disclose. "AI is penalized in kids' books" was **refuted/
  unproven** beyond the general need for polished output.

---

## Suggested phasing
1. **Phase 1 (quality core):** WS1 (a→c) + WS2 — the auditor ensemble + repair loop. Biggest
   quality lift; directly extends today's reject-and-reroll.
2. **Phase 2 (print fidelity):** WS3 + WS4 — real upscaler + verified geometry. Protects the
   physical product.
3. **Phase 3 (model R&D):** WS5 — FLUX.2 trial on the concept line + cover text, FLUX.1 stays default.
4. **Ongoing:** WS6 guards + WS7 decisions.

## Cross-cutting test/guard note
Every new stage follows the existing injectable-fake pattern (`generate_fn`/`ComfyClient`/
`judge_fn`) so the art loop stays unit-testable without a GPU. Add per-stage thresholds to
`config.py`; add tests mirroring `test_audit.py`/`test_art.py`/`test_flux_art.py`.

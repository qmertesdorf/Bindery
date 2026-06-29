# Zero-GPU Pipeline Hardening (2026-06-28)

Batch of pipeline-quality fixes surfaced by the 2026-06-28 four-stage audit
(content / art / QA / packaging). Scope is deliberately limited to changes that
need **no GPU render to validate** — every one is unit-testable through the
existing injectable-fake pattern (`generate_fn` / `ComfyClient` / `judge_fn`).
The GPU-blocked items (live re-render, threshold re-tune, HADM, Flux-Fill,
FLUX.2) stay queued in `2026-06-21-pipeline-improvements-from-research.md`.

Design principle preserved: **fix the defect AND guard it at build time**
([[catch-defects-with-guards]]); keep "flag best & continue" so one stubborn
page never kills a book; every new stage stays default-safe.

## Why these, why now
The audit's three headline findings are all build-but-unused or structurally
inert capability — high leverage, low risk:

1. **Covers have the weakest QA path** — `art.py` renders the concept cover via
   raw `comfy.generate` with no auditor and no best-of-N, while every interior
   page gets both. The first image a shopper sees is the least-checked one.
2. **Flux "negative" prompts are inert** — `flux_art.py` appends
   `"no text / no extra animals"` into the *positive* CLIP encode under CFG=1,
   which Flux cannot act on (and may reinforce). Counts are likewise never
   injected at generation time, so the count guard only ever rejects after the
   fact and burns reroll budget.
3. **Committed guards are off / unproven** — `qa_corner_crops` is fully built,
   GPU-free, and enabled nowhere; `qa_audit_aggregate="majority"` votes down the
   rare-but-correct catches the count guard exists for.

## Audit correction (verified while implementing)
The "covers are unaudited" finding holds **only for the legacy SDXL path**
(`art.py:286`, `generate_picture_art`) — the live **Flux concept** cover
(`flux_art.py:434`) and the Flux **picture** cover (`:536`) both already run
through `run_audited_render`. Best-of-N doesn't apply to covers (it is
caption-gated; covers have no caption). So the cover-QA gap is narrower than the
audit first stated and is confined to the SDXL path we don't ship.

## Work items (priority order)

### ✅ DONE — Count injection at generation time
- `flux_art._count_directive` reuses the count guard's own `extract_count_claims`
  so the prompt and the guard parse the SAME claims and can never disagree;
  appends "Show exactly N <part>" to the concept page prompt. Turns the count
  guard into a backstop instead of the only defense. Tests in `test_concept_art.py`.

### ✅ DONE — Enable `qa_corner_crops` on the live config
- `deep-blue-world-v2.config.json` now sets `qa_corner_crops: true` (built,
  GPU-free guard, targets stray-text/blank-margin; only fires on a fresh render).

### DEFERRED to the GPU queue — Real Flux negative conditioning
- The `no-text / no-extra-subject` language sits in the **positive** CLIP encode
  under FluxGuidance/BasicGuider (single conditioning), which Flux can't act on
  and may reinforce. A real fix (CFGGuider + negative branch, or moving the "no
  marks" text out of positive) **changes the render graph and cannot be validated
  without a GPU A/B** — so it stays queued with the live re-render, not unit-faked.

### ✅ DONE — Deterministic couplet contract guard
- `concept_content.couplet_issues(text)`: exactly 2 non-empty lines + lines must
  not end on the identical word (a fake rhyme). Conservative — no phonetic
  matching, so zero false rejects on real couplets. Wired into
  `validate_concept_story` (hard, with the existing retry) and
  `regenerate_concept_page` (keep-best, exactly like the readability gate).
  Updated the content/build test fixtures that used single-line prose stand-ins.

### FOLLOW-UP — Reconcile / soften the guards
- Corner guard has no leniency (`any-corner-fail`, one probe each) — a re-probe-on-
  fail confirmation would cut stochastic false-positive rerolls, but it changes the
  4-probe contract test and its benefit needs real stochastic output to confirm,
  so it waits for the live re-render.
- Holistic aggregation stays `majority` (deliberate per the count-guard commit);
  the deterministic count/corner guards already bypass the vote.

### P1 — Pin the LLM call (reproducibility)
- `claude_generate` pins model + temperature + max-tokens (creative vs JSON
  tasks differ). Required for the reproducibility goal; removes silent
  truncation risk.
- Structured-output retry: feed the parse/validation error back into the retry
  prompt instead of re-rolling the identical prompt.

### P1 — Deterministic text guards
- Couplet contract guard: exactly 2 lines + AABB rhyme check, mirroring the
  readability guard. A failing couplet triggers regenerate (already wired) — the
  guard just makes the contract enforced, not asserted.
- (Stretch) fact-check the "one easy true thing" claim per subject.

### ✅ DONE — Reroll-hint positive shaping
- `art._shape_reroll_hint`: the count guard's negative report
  ("wrong arms count: … says 8, image shows 6") is rewritten to a POSITIVE
  directive ("draw exactly 8 arms") before it is fed back into the diffusion
  prompt, so the wrong number isn't reinjected into a bag-of-words prompt.
  Unrecognised issues pass through. Tests in `test_art.py`.

### ✅ DONE — Error-feedback retry for content generation (all paths)
- `content.generate_json(generate_fn, build_prompt, parse_validate)`: on a
  parse/validation failure it retries while FEEDING the rejection reason back into
  the prompt (the old retries re-rolled the identical prompt blind, so a systematic
  contract miss failed twice). **Concept** bible+story, **picture** bible+story, and
  **standard** outline/chapter/matter all route through it now — the standard
  *outline* also gained a feedback-retry it previously lacked, and the chapter
  length-expand retry is preserved on top. Tests in `test_content.py`,
  `test_concept_content.py`, `test_picture_content.py`, `test_standard_content.py`.

### ✅ DONE — Pin the content-generation model
- `content.CONTENT_MODEL` (env-overridable `BOOKGEN_CONTENT_MODEL`, default
  `claude-opus-4-8`) is passed as `claude -p --model <pinned>`; validated to a
  safe `[A-Za-z0-9._-]` token so the no-shell-injection property holds. Builds are
  now reproducible instead of inheriting the box's default model. (Temperature /
  max-tokens are NOT exposed by the CLI, so they remain out of scope.)

### DEFERRED — count-guard regex widening; LLM-differentiated listing copy
- Regex widening ("five-armed" / "a pair of" / `NOT`-shape): LOW marginal value —
  the live configs already write the clean "exactly N <part>" form, and widening
  risks the false-rejects the count guard is explicitly built to never produce.
- `copy.py` is already templated-per-subject (WS6b), not raw boilerplate; true
  LLM-differentiated copy is higher effort/risk and lower leverage with only a
  couple of concept titles — revisit when the catalog grows.

## Test / run note
Run the suite via the factory venv from `factory/`
([[factory-test-invocation]]): `factory/.venv/Scripts/python -m pytest`.
Every item ships with a test mirroring `test_art.py` / `test_audit.py` /
`test_flux_art.py` / `test_count_guard.py`. Default behavior stays byte-for-byte
unchanged except where a config flag is explicitly flipped.

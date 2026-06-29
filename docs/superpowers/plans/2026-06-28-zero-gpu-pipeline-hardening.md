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

### NEXT (this batch) — Deterministic couplet contract guard
- `couplet_issues(text)`: exactly 2 non-empty lines + lines must not end on the
  identical word (a fake rhyme). Conservative — no phonetic matching, so zero
  false rejects on real couplets. Wire into `validate_concept_story` (hard, with
  the existing retry) and `regenerate_concept_page` (keep-best like readability).
  Requires updating the existing tests that use single-line prose stand-ins.

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

### P2 — Reroll-hint shaping + copy differentiation
- Rephrase count/shape reject hints into positive directives
  ("draw exactly five arms") before appending to the reroll prompt.
- Widen the count-guard regex to catch "five-armed" / "a pair of" / `NOT`-shape
  claims (manatee/shark cases).
- Differentiate generated listing copy so catalog titles aren't near-duplicates.

## Test / run note
Run the suite via the factory venv from `factory/`
([[factory-test-invocation]]): `factory/.venv/Scripts/python -m pytest`.
Every item ships with a test mirroring `test_art.py` / `test_audit.py` /
`test_flux_art.py` / `test_count_guard.py`. Default behavior stays byte-for-byte
unchanged except where a config flag is explicitly flipped.

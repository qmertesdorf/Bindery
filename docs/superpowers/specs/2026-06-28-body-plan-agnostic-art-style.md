# Body-plan-agnostic art style (Deep Blue World)

**Date:** 2026-06-28
**Status:** approved, ready to implement

## Problem

Deep Blue World ships anatomy defects that the upgraded vision auditor correctly
rejects but the generator cannot fix: a 6-arm starfish (should be a flat 5-point
star) and a manatee with a forked/two-lobed tail (should be one rounded paddle).
Re-rolling under the current config never produces a correct render.

**Root cause is generation, not audit.** The book's `flux_style` bakes body shape
into the style prompt:

> "...of **an adorable cute animal with a big round head, a soft chubby rounded
> body** and a gentle happy face..."

`flux_art.concept_page_prompt(page, style=cfg.flux_style)` prepends this to *every*
page, and "big round head / chubby rounded body" overpowers the (correct) per-page
scene text ("a flat five-pointed star... not six"). It forces a round blob for the
star and a cute fish-fluke for the manatee. There is no per-page style override.

The approved first concept title (wild-little-world) does NOT have this problem —
its `flux_style` describes only medium/finish/palette/mood, never body shape.

## Principle (the general rule)

A book's `flux_style` governs **rendering** — medium, palette, softness, the
cuteness of eyes/face — and **never dictates body shape**. Each page's scene text
owns the anatomy. Cuteness comes from soft rendering + friendly face, not from
forcing every animal into the same round ball.

## Fix

Rewrite `factory/books/deep-blue-world.config.json` `flux_style`. Remove the
body-shape clause; keep every cuteness + cohesion cue; add a general species-shape
directive with **no animal named**:

> "Soft hand-painted watercolour storybook illustration in an adorable, sweet
> kawaii style — large friendly sparkly eyes, a gentle happy face, soft edges and
> tender huggable charm — with every animal drawn in its OWN correct natural body
> shape and true proportions for its real species (flat animals stay flat, long
> animals stay long, never forced into a uniform round chubby ball). Loose
> simplified naive childlike style, cool ocean palette of blues aquas and teal with
> sunlit water, gentle visible brushwork, soft edges, painterly flat shapes, bright
> friendly, children's picture book art, not photorealistic, not a photograph, no
> text"

Medium/palette/finish are unchanged, so the 18 reused pages stay cohesive; only the
re-rolled pages gain species-correct body shapes.

### No new guard

The general output-level guard already exists: the ensemble vision auditor catches
wrong anatomy regardless of cause (proven — it rejects 6-arm stars and forked
tails). The style fix removes the *cause*; the auditor stays the *safety net*. A
prompt-phrase lint would be brittle — YAGNI.

## Execution

1. Update the config `flux_style` string.
2. Delete `out/deep-blue-world/page_19.png` + `page_20.png`; re-roll with the
   3-pass ensemble (`qa_audit_passes:3`), VQA off (its worker is broken — separate
   issue) via a throwaway VQA-off config. Keep best; flag if still failing.
3. Verify anatomy: programmatic starfish arm-count = 5, manatee single paddle tail;
   confirm cohesion held vs the page_01 anchor.
4. Re-audit the other 18 pages under the corrected expectations; report any anatomy
   concern for the user's call (do not auto-re-roll them).
5. Rebuild `interior.pdf` + `cover-paperback.pdf` (reuse path, no GPU/VQA).

## Risk

The kawaii style genuinely struggles with flat stars; even corrected, the starfish
may need several attempts or still resist. If it does, surface it — do not ship
another 6-arm star.

## Out of scope

- Per-page `style` override field (not needed once the global style is correct).
- Fixing the VQAScore worker startup crash (separate issue).
- Deterministic count guard (separate backlog item).

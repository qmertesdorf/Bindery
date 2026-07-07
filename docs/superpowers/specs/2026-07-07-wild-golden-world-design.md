# Wild Golden World — A First Look at Savanna Animals (design)

**Date:** 2026-07-07 · **Status:** approved by standing delegation ("you decide what it's about based on best fit"); built autonomously.

## What

4th title in the character-free concept picture-book line: **Wild Golden World — A First Look at Savanna Animals**. Hannah Whitfield / Grace Sullivan, 8.5×8.5 paperback-only, $10.99, 20 spreads, ages ~5, `book_type: concept`, Flux, no LoRA, kawaii-cute + true-species-body style.

## Why savanna (best fit)

- **Zero overlap** with the existing shelf: Wild Little World (general), Deep Blue World (ocean), Wild Green World (forest).
- **Distinct series palette**: warm golds/ochres next to green and blue spines.
- **Safest animal classes**: 17 mammals + 3 birds + 1 tortoise (turtle-class rendered clean before); no crustaceans, no insects, per the safe-vs-risky-animals rules.
- **Highest kid appeal**: lion, elephant, giraffe, zebra are the most iconic first-animals there are.

Rejected alternatives: polar ("Wild White World") — overlaps Deep Blue World's penguin/walrus/orca/narwhal pages; nocturnal ("Wild Night World") — reuses fox/owl/badger and fights the soft warm-light house palette.

## How

Config `factory/books/wild-golden-world.config.json`, cloned from the proven `wild-green-world` config (same QA stack: 3 candidates, Claude taste-select, 3-pass majority audit, describe-first, count guard, corner crops, subject_fallback ON/3) with:

- savanna `flux_style` palette (golds, ochres, dusty sage, honey light) + "tall animals stay tall" added to the body-shape clause (giraffe/ostrich/secretary bird);
- v6's anti-glitter negative terms appended;
- 20 topics written per the no-comparison rule (name what a feature IS — "a fan of stiff golden feathers", never "like a crown");
- cover hero: ONE joyful lion cub, big/centred, per the proven single-hero cover template.

Anatomy watch-list for the eyeball pass: giraffe neck/leg count, elephant trunk (exactly one), horn pairs (gazelle/buffalo/wildebeest), rhino single horn, ostrich/flamingo/secretary-bird legs, tortoise shell.

## Build & acceptance

From `factory/`: `./.venv/Scripts/python.exe build.py books/wild-golden-world.config.json --out out --seed <s>`. Green build ≠ approval: zoom-audit faces/tails/limb counts on every page + cover before calling it ship-ready (`_audit_bundle.py` re-audit + manual eyeball, per the deep-blue-world lessons).

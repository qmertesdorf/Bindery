# book-gen

A one-command pipeline that turns a small JSON config into a **publish-ready Amazon KDP
bundle** — print interior PDF, EPUB, wraparound cover PDF, ebook cover, and an
upload checklist with the mandatory AI-content disclosure pre-filled.

The pipeline builds two kinds of book from the same five stages, switched by a `book_type`
field in the config: **fill-in journals** (paperback only — the proof-of-concept series is a
set of pet-loss grief journals, chosen by upfront market research below) and **standard
read-through prose books** (paperback + Kindle — e.g. a pet-loss companion read). The
interesting part is the architecture: five isolated stages, with every external effect (the
LLM, the PDF renderer, the image model) behind a thin injected adapter so the pure logic is
unit-tested with fakes — `57 passing tests`, no network or GPU required to run them.

## The pipeline

```
book.config.json ─▶ ① content (claude -p) ─▶ content.json
                                                │
              ┌──────────────────────────────────┤
              ▼                                   ▼
     ② interior                          ③ art (ComfyUI)
     (HTML/CSS → PDF + EPUB)                      │
              │                                   ▼
              │  page count ───────────▶ ④ cover (art + typographic text → wraparound PDF)
              ▼                                   │
       interior.pdf / .epub              cover-paperback.pdf / cover-ebook.jpg
                          └───────────┬────────────┘
                                      ▼
                          ⑤ checklist → upload-checklist.md (+ AI disclosure)
```

`python build.py books/dog-loss.config.json` runs ①→⑤ unattended. A new title is a new
config file and one command — templates and the ComfyUI workflow are shared across the series.
Journals render fill-in pages and ship paperback-only; standard books generate prose
chapters (an outline, then one LLM pass per chapter) and ship paperback + Kindle.

Spine width is auto-computed from the rendered page count, and the title/author are placed
as **real typographic text** over the art (not diffused into the image), so covers never
come out with garbled lettering.

## Run it

The working code lives in [`factory/`](factory/). See
**[factory/README.md](factory/README.md)** for setup, the three external dependencies
(the `claude` CLI, a headless-Chromium `browse` renderer, and ComfyUI), and how to build a
title.

```powershell
cd factory
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -v          # 26 tests, no external services needed
```

## Research behind the niche

Before writing code, the niche was validated against live Amazon data and KDP policy.

- [`research-findings.md`](research-findings.md) — adversarially-verified facts on KDP
  policy, royalty economics, the earnings reality (most sellers earn very little), and
  enforcement risks. Includes what was **refuted**, so those numbers aren't trusted.
- [`candidates.md`](candidates.md) — 10 concrete candidates plus the demand-validation gate
  run before committing to one.
- [`docs/specs/`](docs/specs/) — the design spec the build was implemented from.

**One-paragraph takeaway:** AI books are allowed on KDP but require a private "AI-generated"
disclosure to Amazon (not shown to buyers). Per-sale margins are fine (up to 70% on ebooks
at $2.99–$9.99), but the *typical* seller earns little. The real levers are catalog size,
ad spend, and niching down — not passive riches. Treated as a slow-build side business; the
pet-loss grief journal passed the demand-vs-beatable-competition test.

## License

MIT — see [LICENSE](LICENSE).

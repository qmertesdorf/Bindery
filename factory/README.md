# Pet-Loss Grief Journal Factory

One command turns a book config into a KDP-ready bundle.

## External dependencies
The factory orchestrates three external tools (it does not bundle them):

1. **Claude Code CLI** (`claude`) — generates the journal copy. Stage ① shells out to
   `claude -p`, so the CLI must be installed and on your `PATH`. See
   https://docs.claude.com/en/docs/claude-code. No separate API key is needed.
2. **A headless-Chromium PDF renderer** (`browse`) — renders the HTML/CSS interior and
   cover to print-spec PDF. Any CLI exposing `goto <url>`, `pdf`, `viewport`, and
   `screenshot` subcommands works (see `factory/browsepdf.py` for the exact calls). This
   project was built against the gstack `browse` binary. Point the factory at yours with
   the `BROWSE_BIN` env var, or put `browse` on your `PATH`.
3. **ComfyUI** — generates the cover art locally via its HTTP API. Start your ComfyUI
   instance (e.g. `run_comfyui.bat`) so `http://127.0.0.1:8188` is live.

## Setup (once)
```powershell
cd factory
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```
- Confirm the `claude` CLI and `browse` binary resolve (see above).
- Start ComfyUI so `http://127.0.0.1:8188` is reachable.
- Edit `comfyui/workflow.template.json`: set your checkpoint name.

## Build a title
```powershell
python build.py books/dog-loss.config.json
```
Output lands in `out/dog-loss/`: `interior.pdf`, `interior.epub`,
`cover-paperback.pdf`, `cover-ebook.jpg`, `upload-checklist.md`.

## Add a new title to the series
Drop a new `books/<slug>.config.json` and run `build.py` on it. No template edits.

## Upload (manual — KDP has no API for individuals)
Open KDP, create paperback + ebook, upload the files, paste metadata from
`upload-checklist.md`, and answer the AI-content disclosure as listed. Run KDP's
print previewer before publishing.

## Before your first run (common gotchas)
- **Set a real checkpoint.** Replace `REPLACE_WITH_YOUR_CHECKPOINT.safetensors` in
  `comfyui/workflow.template.json`. The build fails fast with a clear message if you don't.
- **ComfyUI must be running** at `http://127.0.0.1:8188` (start `run_comfyui.bat`).
- **Browse daemon conflict.** If you have used `/browse` from a Claude Code session whose
  folder is inside this repo, a "headed" browser daemon may be cached. If PDF steps error
  with `proxy/headed mismatch`, run `browse disconnect` from the repo root first.
- **Inspect the paperback cover.** Cover art is generated portrait (1024x1536), which fits
  the ebook front cover well but is center-cropped on the wider paperback wraparound. Open
  `cover-paperback.pdf` and check the framing before uploading; adjust the art prompt or the
  `EmptyLatentImage` size in the workflow if the crop loses important detail.

## Run tests
```powershell
pytest -v
```

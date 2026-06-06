# Pet-Loss Grief Journal Factory

One command turns a book config into a KDP-ready bundle.

## Setup (once)
```powershell
cd factory
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```
- Ensure the `claude` CLI is on PATH (content generation).
- Ensure the gstack `browse` binary exists (PDF render) — it does at
  `~/.claude/skills/gstack/browse/dist/browse`.
- Start ComfyUI (`run_comfyui.bat`) so `http://127.0.0.1:8188` is live.
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

## Run tests
```powershell
pytest -v
```

## After all files are written:
1. Validate the JSON files parse and load: run
   `cd C:\Users\quint\git\book-gen\factory ; .\.venv\Scripts\python.exe -c "from factory.config import load_config; [print(load_config('books/'+s+'.config.json').title) for s in ['dog-loss','cat-loss','pet-loss']]"`
   Expected: prints the three titles with no error (proves configs are valid against the real loader).
   Also confirm workflow.template.json parses: `.\.venv\Scripts\python.exe -c "import json; json.load(open('comfyui/workflow.template.json')); print('workflow ok')"`
2. Commit:
   ```
   cd C:\Users\quint\git\book-gen
   git add factory/books/ factory/comfyui/ factory/README.md
   git commit -m "feat: book configs, ComfyUI workflow template, README"
   ```

## Rules
- Use Write tool for all 5 files. Transcribe EXACTLY.
- The README contains markdown with code fences — write it as a normal .md file (the fences are literal content).
- Run the validation commands and report their output. If a config fails to load, STOP and report BLOCKED.

## Report back
Status, the validation command outputs (three titles + "workflow ok"), commit SHA and prior SHA, concerns. Concise.

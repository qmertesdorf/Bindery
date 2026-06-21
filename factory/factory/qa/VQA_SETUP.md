# Isolated VQAScore venv (`~/.book-gen-vqa`)

The WS1a VQAScore caption-fidelity gate runs its model in a **separate venv** so the
heavy GPU stack (torch + a ~6 GB VQA model) never lands in `factory/.venv` (the
lightweight test runner). `vqascore.py` lazily spawns a persistent worker
(`vqa_worker.py`) in this venv and talks to it over a line-JSON stdin/stdout
protocol, so the model loads once per build.

## One-time install (Windows, RTX 5080 / CUDA 12.8)

```bash
py -3.12 -m venv ~/.book-gen-vqa
VQ=~/.book-gen-vqa/Scripts/python.exe
"$VQ" -m pip install --upgrade "setuptools<81" wheel
# GPU torch for Blackwell (sm_120):
"$VQ" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
# t2v_metrics: UTF-8 + no build isolation, else image-reward's setup.py bombs on Windows
# (pkg_resources missing under isolation; charmap decode of its README):
PYTHONUTF8=1 "$VQ" -m pip install t2v_metrics --no-build-isolation
"$VQ" -m pip install clip-anytorch            # provides `import clip` (needed by bundled scorers)
# t2v_metrics' top-level import drags in ImageReward/HPSv2 -> diffusers/datasets/accelerate.
# Pin the late-2023 stack that matches its pinned transformers==4.36.1, or imports clash:
"$VQ" -m pip install "huggingface_hub==0.20.3" "datasets==2.16.1" \
                     "accelerate==0.25.0" "diffusers==0.25.1"
```

Verify: `"$VQ" -c "import t2v_metrics; print('OK')"`

## Runtime
- **Model:** `clip-flant5-xl` (`vqascore.DEFAULT_VQA_MODEL`) — ~6 GB, fits a 16 GB card;
  `clip-flant5-xxl` (the t2v_metrics default) does **not**.
- **Overrides:** `BOOK_GEN_VQA_PYTHON` (venv python path), `BOOK_GEN_VQA_MODEL` (model id).
- First score downloads the model (~6 GB) to the HF cache, then it loads once per build.
- Enable per book with `qa_vqa: true` (+ tune `qa_vqa_threshold`) and `qa_candidates` for best-of-N.

## Calibration (clip-flant5-xl, real rendered pages, 2026-06-21)
Right vs wrong caption, scored through the daemon (`_vqa_validate.py`):

| page | right | wrong |
|------|-------|-------|
| wlw fox      | 0.422 | 0.054 |
| wlw owl      | 0.974 | 0.063 |
| wlw deer     | 0.802 | 0.068 |
| dbw whale    | 0.194 | 0.049 |
| dbw dolphins | 0.472 | 0.067 |

Discrimination is strong (right is 6–15× wrong), but **absolute** correct-match scores
range ~0.19–0.97 while gross mismatches sit ~0.05. So the gate is a **coarse floor**
(`qa_vqa_threshold` default **0.15**) that catches wrong-subject pages; fine caption
judgment stays with best-of-N ranking + the holistic Claude auditor. Re-tune against full
rhyming captions (more figurative than these paraphrases) before raising it.
